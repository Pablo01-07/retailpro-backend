from datetime import datetime, date, timedelta
from unittest.mock import patch
import pandas as pd
from app.models.modelo_version import ModeloVersion
from app.models.auditoria import Auditoria
from app.services.ml_service import MLForecastService


def test_calcular_mape_14d_conocido():
    filas = []
    for d in range(14):
        filas.append({"id_producto": 101, "y_real": 10.0, "y_pred": 11.0})
        filas.append({"id_producto": 102, "y_real": 20.0, "y_pred": 18.0})
        filas.append({"id_producto": 103, "y_real": 0.0, "y_pred": 5.0})

    df = pd.DataFrame(filas)
    resultado = MLForecastService.mape_14d(df)
    resultado_alias = MLForecastService.calcular_mape_14d(df)

    assert resultado == 10.0
    assert resultado_alias == 10.0


def test_calcular_mape_14d_casos_borde():
    assert MLForecastService.mape_14d(pd.DataFrame()) == 0.0
    df_zeros = pd.DataFrame([{"id_producto": 1, "y_real": 0.0, "y_pred": 10.0}])
    assert MLForecastService.mape_14d(df_zeros) == 0.0


def test_get_ficha_modelo_activo_evalua_mape_14d(client, db_session, admin_token):
    mv = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=2.5,
        mape=16.5,
        rmse=3.5,
        mape_14d=12.4,
        estado="ACTIVA"
    )
    db_session.add(mv)
    db_session.commit()

    resp = client.get("/api/v1/modelos/activa", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mape_14d"] == 12.4
    assert data["mape"] == 16.5
    assert data["cumple_meta"] is True


def test_get_ficha_modelo_activo_fallback_mape_diario(client, db_session, admin_token):
    mv = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=2.5,
        mape=16.5,
        rmse=3.5,
        mape_14d=None,
        estado="ACTIVA"
    )
    db_session.add(mv)
    db_session.commit()

    resp = client.get("/api/v1/modelos/activa", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mape_14d"] is None
    assert data["mape"] == 16.5
    assert data["cumple_meta"] is False


def test_monitoreo_e_historial_incluyen_mape_14d(client, db_session, admin_token):
    mv_prod = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="produccion",
        mae=2.5,
        mape=15.0,
        rmse=3.5,
        mape_14d=11.5,
        estado="ACTIVA"
    )
    mv_backtest = ModeloVersion(
        version="v0.backtest.01",
        fecha_entrenamiento=datetime(2025, 1, 1),
        motivo_entrenamiento="backtest",
        mae=2.2,
        mape=16.0,
        rmse=3.1,
        mape_14d=13.2,
        estado="DESCARTADA"
    )
    db_session.add_all([mv_prod, mv_backtest])
    db_session.commit()

    resp_mon = client.get("/api/v1/modelos/monitoreo", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_mon.status_code == 200
    data_mon = resp_mon.json()
    assert len(data_mon["serie_mensual"]) == 1
    assert data_mon["serie_mensual"][0]["mape_14d"] == 13.2
    assert data_mon["serie_mensual"][0]["estado_alerta"] == "NORMAL"
    assert data_mon["alerta_degradacion"] is False

    resp_hist = client.get("/api/v1/modelos/historial", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_hist.status_code == 200
    data_hist = resp_hist.json()
    assert len(data_hist) == 1
    assert data_hist[0]["mape_14d"] == 11.5


def test_reevaluar_modelo_activo_permisos(client, db_session, analyst_token):
    resp = client.post("/api/v1/modelos/activa/reevaluar", headers={"Authorization": f"Bearer {analyst_token}"})
    assert resp.status_code == 403


def test_reevaluar_modelo_activo_sin_modelo(client, db_session, admin_token):
    resp = client.post("/api/v1/modelos/activa/reevaluar", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 404


def test_reevaluar_modelo_activo_exitoso(client, db_session, admin_token):
    mv_prod = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="produccion",
        mae=3.0,
        mape=17.0,
        rmse=4.0,
        mape_14d=None,
        estado="ACTIVA"
    )
    db_session.add(mv_prod)
    db_session.commit()

    fake_backtest_results = [
        {"corte_idx": i, "corte_fecha": f"2025-{i:02d}-01", "periodo": f"2025-{i:02d}", "mae": 2.0, "rmse": 3.0, "mape": 16.0, "wape": 12.0, "mape_14d": 11.0, "duracion_s": 0.5}
        for i in range(1, 13)
    ]
    fake_grid = pd.DataFrame([{"fecha": date(2025, 1, 1)}])

    with patch.object(MLForecastService, "load_clean_sales_grid", return_value=(fake_grid, {1: {"categoria": "Abarrotes"}}, {}, {})), \
         patch.object(MLForecastService, "run_walk_forward_backtest", return_value=(fake_backtest_results, {}, {}, {}, 94.72)):
        resp = client.post("/api/v1/modelos/activa/reevaluar", headers={"Authorization": f"Bearer {admin_token}"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["id_modelo"] == mv_prod.id_modelo
    assert data["version"] == "v1.0.0"
    assert data["mape_14d"] == 11.0
    assert data["mape"] == 16.0
    assert data["cortes_evaluados"] == 12

    db_session.refresh(mv_prod)
    assert float(mv_prod.mape_14d) == 11.0
    assert float(mv_prod.mape) == 16.0

    audit = db_session.query(Auditoria).filter(Auditoria.accion == "Reevaluación de métricas del modelo").first()
    assert audit is not None
    assert audit.modulo_afectado == "modelos"
    assert audit.detalle["mape_14d"] == 11.0
