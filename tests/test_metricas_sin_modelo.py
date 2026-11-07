import os
import csv
import pytest
from app.services.dashboard_service import DashboardService
from app.services.reporting_service import ReportingService
from app.models.modelo_version import ModeloVersion
from app.core.security import create_access_token


def test_dashboard_y_reportes_sin_modelo_activo(client, db_session):
    modelos_activos = db_session.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").all()
    assert len(modelos_activos) == 0

    resumen = DashboardService.get_dashboard_resumen(db_session)
    kpi_mape = next((k for k in resumen.kpis if "MAPE" in k.nombre), None)
    assert kpi_mape is not None
    assert kpi_mape.valor == "—"
    assert kpi_mape.valor_numerico is None
    assert kpi_mape.estado == "NEUTRO"

    admin_token = create_access_token(subject=1, role="administrador")
    resp = client.get("/api/v1/dashboard", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    kpi_mape_api = next((k for k in data["kpis"] if "MAPE" in k["nombre"]), None)
    assert kpi_mape_api is not None
    assert kpi_mape_api["valor"] == "—"
    assert kpi_mape_api["valor_numerico"] is None

    wape = ReportingService.calcular_wape_fuera_muestra(db_session)
    assert wape is None

    export_resp = ReportingService.exportar_indicadores(
        db=db_session,
        formato="csv",
        user_id=1
    )
    assert export_resp is not None
    filepath = os.path.join(ReportingService.ensure_storage_dir(), export_resp.nombre_archivo)
    assert os.path.exists(filepath)

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        filas = list(reader)

    indicadores_dict = {row[0]: row[1] for row in filas[1:]}

    assert indicadores_dict.get("MAPE Fuera de Muestra (XGBoost)") == "—"
    assert indicadores_dict.get("WAPE Fuera de Muestra") == "—"
    assert indicadores_dict.get("RMSE Fuera de Muestra") == "—"
    assert indicadores_dict.get("MAE Fuera de Muestra") == "—"


def test_modelos_monitoreo_devuelve_cobertura_94_72(client, db_session):
    admin_token = create_access_token(subject=1, role="administrador")

    resp_vacio = client.get("/api/v1/modelos/monitoreo", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_vacio.status_code == 200
    data_vacio = resp_vacio.json()
    assert data_vacio.get("cobertura_intervalo_95") is None
    assert data_vacio.get("cobertura_fuera_muestra") is None

    from datetime import datetime, timedelta
    corte_bt1 = ModeloVersion(
        version="v0.backtest.01",
        fecha_entrenamiento=datetime.utcnow() - timedelta(days=60),
        motivo_entrenamiento="backtest",
        mae=7.22,
        mape=19.23,
        rmse=10.98,
        estado="DESCARTADA"
    )
    corte_bt2 = ModeloVersion(
        version="v0.backtest.02",
        fecha_entrenamiento=datetime.utcnow() - timedelta(days=30),
        motivo_entrenamiento="backtest",
        mae=7.22,
        mape=19.23,
        rmse=10.98,
        estado="DESCARTADA"
    )
    db_session.add_all([corte_bt1, corte_bt2])
    db_session.commit()

    resp = client.get("/api/v1/modelos/monitoreo", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("cobertura_intervalo_95") == 94.72
    assert data.get("cobertura_fuera_muestra") == 94.72


def test_umbral_mape_max_cambia_cumple_meta_y_reporte(client, db_session):
    from datetime import datetime, timedelta

    modelo_activo = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow() - timedelta(days=5),
        motivo_entrenamiento="produccion",
        mae=7.2206,
        mape=19.23,
        rmse=10.9802,
        estado="ACTIVA"
    )
    db_session.add(modelo_activo)
    db_session.commit()

    admin_token = create_access_token(subject=1, role="administrador")

    resp_activa_15 = client.get("/api/v1/modelos/activa", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_activa_15.status_code == 200
    data_15 = resp_activa_15.json()
    assert data_15["mape"] == 19.23
    assert data_15["umbral_mape_max"] == 15.0
    assert data_15["cumple_meta"] is False, "Con MAPE 19.23 y umbral 15.0 no debe cumplir la meta"

    rep_15 = ReportingService.exportar_indicadores(db_session, formato="csv", user_id=1)
    path_15 = os.path.join(ReportingService.ensure_storage_dir(), rep_15.nombre_archivo)
    with open(path_15, "r", encoding="utf-8-sig") as f:
        filas_15 = list(csv.reader(f))

    mape_row_15 = next(r for r in filas_15 if "MAPE" in r[0])
    assert mape_row_15[2] == "<= 15.00%", "La meta del reporte debe ser dinámica desde umbral_configuracion"
    assert mape_row_15[3] == "NO CUMPLE", "El estado del reporte debe coincidir con cumple_meta=False"

    put_resp = client.put(
        "/api/v1/umbrales",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"mape_max": 25.0}
    )
    assert put_resp.status_code == 200

    resp_activa_25 = client.get("/api/v1/modelos/activa", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_activa_25.status_code == 200
    data_25 = resp_activa_25.json()
    assert data_25["umbral_mape_max"] == 25.0
    assert data_25["cumple_meta"] is True, "Con MAPE 19.23 y umbral 25.0 debe cumplir la meta"

    rep_25 = ReportingService.exportar_indicadores(db_session, formato="csv", user_id=1)
    path_25 = os.path.join(ReportingService.ensure_storage_dir(), rep_25.nombre_archivo)
    with open(path_25, "r", encoding="utf-8-sig") as f:
        filas_25 = list(csv.reader(f))

    mape_row_25 = next(r for r in filas_25 if "MAPE" in r[0])
    assert mape_row_25[2] == "<= 25.00%", "La meta del reporte debe reflejar el nuevo umbral 25.00%"
    assert mape_row_25[3] == "CUMPLE", "El reporte debe cambiar a CUMPLE junto con cumple_meta de /modelos/activa"
