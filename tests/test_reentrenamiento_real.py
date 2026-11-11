import os
import json
import pytest
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from decimal import Decimal
from unittest.mock import patch, MagicMock
import pandas as pd

from app.models.modelo_version import ModeloVersion
from app.models.umbral_configuracion import UmbralConfiguracion
from app.models.carga_datos import CargaDatos
from app.models.auditoria import Auditoria
from app.models.venta_historica import VentaHistorica
from app.models.producto import Producto
from app.services.ml_service import MLForecastService
from app.services.etl_service import verificar_reentrenamiento_por_acumulacion, get_storage_carga_dir
from app.services.scheduler import construir_trigger_proceso, get_procesos_config
from app.core.config import settings


@pytest.fixture(autouse=True)
def preserve_active_model_artifacts():
    model_dir = os.path.join(settings.STORAGE_DIR, "modelos")
    active_path = os.path.join(model_dir, "modelo_activo.json")
    calib_path = os.path.join(model_dir, "calibracion_activa.json")
    metricas_path = os.path.join(model_dir, "metricas_modelo.json")

    backup = {}
    for p in [active_path, calib_path, metricas_path]:
        if os.path.exists(p):
            with open(p, "rb") as f:
                backup[p] = f.read()

    yield

    for p, b in backup.items():
        with open(p, "wb") as f:
            f.write(b)

    for fname in os.listdir(model_dir):
        if fname.startswith("modelo_") and fname != "modelo_activo.json":
            try:
                os.remove(os.path.join(model_dir, fname))
            except Exception:
                pass
        elif fname.startswith("evaluacion_modelo_"):
            try:
                os.remove(os.path.join(model_dir, fname))
            except Exception:
                pass


def test_modelo_version_columna_observacion(db_session):
    mv = ModeloVersion(
        version="v1.0.99",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        mae=3.5,
        mape=12.4,
        rmse=5.1,
        mape_14d=11.2,
        estado="APTA",
        observacion="Cumple el umbral (11.2% ≤ 15%). Pendiente de aprobación para publicación."
    )
    db_session.add(mv)
    db_session.commit()
    db_session.refresh(mv)

    assert mv.id_modelo is not None
    assert mv.observacion == "Cumple el umbral (11.2% ≤ 15%). Pendiente de aprobación para publicación."


def test_evaluacion_candidato_descartada_cuando_supera_umbral(db_session):
    umbral = db_session.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
    if not umbral:
        umbral = UmbralConfiguracion(id_usuario=1, tipo_umbral="mape_max", valor=15.0)
        db_session.add(umbral)
    else:
        umbral.valor = 15.0
    db_session.commit()

    active_mock = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="inicial",
        estado="ACTIVA",
        mape=13.0,
        mape_14d=12.5
    )
    db_session.add(active_mock)
    db_session.commit()

    cols = MLForecastService.FEATURE_COLS + ["y_real"]
    df_matrix = pd.DataFrame({c: [1.0] for c in cols})

    with patch.object(MLForecastService, "load_clean_sales_grid") as mock_grid, \
         patch.object(MLForecastService, "run_walk_forward_backtest") as mock_backtest, \
         patch.object(MLForecastService, "generate_training_matrix", return_value=df_matrix), \
         patch("xgboost.train") as mock_xgb_train:

        df_dummy = pd.DataFrame({
            "fecha": [date(2026, 10, 20)],
            "id_producto": [1],
            "cantidad_vendida": [10]
        })
        mock_grid.return_value = (df_dummy, {1: {"sku": "SKU01", "categoria": "CAT1", "precio_unitario": 20.0}}, {"SKU01": 0}, {"CAT1": 0})

        mock_backtest.return_value = (
            [{"mape": 18.0, "rmse": 6.0, "mae": 4.0, "wape": 17.0, "mape_14d": 17.5, "corte_idx": 1}],
            {},
            {},
            {},
            93.5
        )
        mock_booster = MagicMock()
        mock_xgb_train.return_value = mock_booster

        res = MLForecastService.entrenar_modelo_candidato(
            db=db_session,
            motivo="reentrenamiento_programado"
        )

        assert res["estado"] == "DESCARTADA"
        assert "supera el umbral de 15%" in res["observacion"]
        assert "Se mantiene la versión v1.0.0 en producción." in res["observacion"]

        cand_db = db_session.query(ModeloVersion).filter(ModeloVersion.id_modelo == res["id_modelo"]).first()
        assert cand_db.estado == "DESCARTADA"

        activa_db = db_session.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
        assert activa_db.id_modelo == active_mock.id_modelo


def test_evaluacion_candidato_apta_cuando_cumple_umbral(db_session):
    cols = MLForecastService.FEATURE_COLS + ["y_real"]
    df_matrix = pd.DataFrame({c: [1.0] for c in cols})

    with patch.object(MLForecastService, "load_clean_sales_grid") as mock_grid, \
         patch.object(MLForecastService, "run_walk_forward_backtest") as mock_backtest, \
         patch.object(MLForecastService, "generate_training_matrix", return_value=df_matrix), \
         patch("xgboost.train") as mock_xgb_train:

        df_dummy = pd.DataFrame({
            "fecha": [date(2026, 10, 20)],
            "id_producto": [1],
            "cantidad_vendida": [10]
        })
        mock_grid.return_value = (df_dummy, {1: {"sku": "SKU01", "categoria": "CAT1", "precio_unitario": 20.0}}, {"SKU01": 0}, {"CAT1": 0})

        mock_backtest.return_value = (
            [{"mape": 12.0, "rmse": 4.0, "mae": 2.5, "wape": 11.0, "mape_14d": 10.66, "corte_idx": 1}],
            {},
            {},
            {},
            95.2
        )
        mock_booster = MagicMock()
        mock_xgb_train.return_value = mock_booster

        res = MLForecastService.entrenar_modelo_candidato(
            db=db_session,
            motivo="reentrenamiento_manual"
        )

        assert res["estado"] == "APTA"
        assert "Cumple el umbral (10.66% ≤ 15%)." in res["observacion"]

        cand_db = db_session.query(ModeloVersion).filter(ModeloVersion.id_modelo == res["id_modelo"]).first()
        assert cand_db.estado == "APTA"


def test_bloqueo_concurrencia_reentrenamiento(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    with patch.object(MLForecastService, "is_entrenamiento_en_curso", return_value=True):
        resp = client.post("/api/v1/modelos/entrenar", headers=headers)
        assert resp.status_code == 409
        assert "Ya existe un reentrenamiento en ejecución." in resp.json()["detail"]


def test_comparacion_modelo_candidato_vs_activo(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    activa = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10),
        motivo_entrenamiento="inicial",
        estado="ACTIVA",
        mae=3.8,
        mape=14.2,
        rmse=6.1,
        mape_14d=13.5
    )
    candidato = ModeloVersion(
        version="v1.1.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="APTA",
        mae=3.2,
        mape=12.1,
        rmse=5.4,
        mape_14d=11.0,
        observacion="Cumple el umbral (11% ≤ 15%). Pendiente de aprobación para publicación."
    )
    db_session.add_all([activa, candidato])
    db_session.commit()

    resp = client.get(f"/api/v1/modelos/{candidato.id_modelo}/comparacion", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["id_candidato"] == candidato.id_modelo
    assert data["version_candidato"] == "v1.1.0"
    assert data["id_activa"] == activa.id_modelo
    assert data["version_activa"] == "v1.0.0"
    assert data["cumple_umbral"] is True
    assert data["mejora_vigente"] is True
    assert data["candidato"]["mape_14d"] == 11.0
    assert data["activa"]["mape_14d"] == 13.5
    assert data["diferencia"]["mape_14d"] == -2.5


def test_publicar_modelo_apta_exitoso(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    activa = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5),
        motivo_entrenamiento="inicial",
        estado="ACTIVA",
        mae=3.8,
        mape=14.0,
        mape_14d=13.0
    )
    candidata = ModeloVersion(
        version="v1.1.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="APTA",
        mae=3.1,
        mape=11.5,
        mape_14d=10.2,
        observacion="Cumple el umbral (10.2% ≤ 15%). Pendiente de aprobación para publicación."
    )
    db_session.add_all([activa, candidata])
    db_session.commit()

    with patch.object(MLForecastService, "generar_pronosticos_lote", return_value=140):
        resp = client.post(f"/api/v1/modelos/{candidata.id_modelo}/publicar", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado"] == "ACTIVA"
        assert "Publicada el" in data["observacion"]

    db_session.refresh(activa)
    db_session.refresh(candidata)
    assert activa.estado == "ANTERIOR"
    assert candidata.estado == "ACTIVA"

    audit = db_session.query(Auditoria).filter(Auditoria.accion == "Publicación de modelo").order_by(Auditoria.id_auditoria.desc()).first()
    assert audit is not None
    assert audit.detalle["id_modelo"] == candidata.id_modelo


def test_publicar_modelo_no_apta_falla_400(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    descartada = ModeloVersion(
        version="v1.1.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="DESCARTADA",
        mae=5.0,
        mape=18.0,
        mape_14d=17.5
    )
    db_session.add(descartada)
    db_session.commit()

    resp = client.post(f"/api/v1/modelos/{descartada.id_modelo}/publicar", headers=headers)
    assert resp.status_code == 400
    assert "Solo se pueden publicar modelos con estado APTA" in resp.json()["detail"]


def test_descartar_modelo_apta_exitoso(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    candidata = ModeloVersion(
        version="v1.2.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_programado",
        estado="APTA",
        mae=3.4,
        mape=12.0,
        mape_14d=11.5,
        observacion="Cumple el umbral (11.5% ≤ 15%). Pendiente de aprobación para publicación."
    )
    db_session.add(candidata)
    db_session.commit()

    payload = {"comentario": "Comportamiento errático en categoría snacks"}
    resp = client.post(f"/api/v1/modelos/{candidata.id_modelo}/descartar", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] == "DESCARTADA"
    assert data["observacion"] == "Descartada manualmente: Comportamiento errático en categoría snacks"

    db_session.refresh(candidata)
    assert candidata.estado == "DESCARTADA"

    audit = db_session.query(Auditoria).filter(Auditoria.accion == "Descarte de modelo").order_by(Auditoria.id_auditoria.desc()).first()
    assert audit is not None
    assert audit.detalle["comentario"] == "Comportamiento errático en categoría snacks"


def test_restringir_activar_directo_descartada_o_candidata(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    cand = ModeloVersion(
        version="v1.3.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="CANDIDATA"
    )
    desc = ModeloVersion(
        version="v1.4.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="DESCARTADA"
    )
    db_session.add_all([cand, desc])
    db_session.commit()

    r1 = client.patch(f"/api/v1/modelos/{cand.id_modelo}/activar", headers=headers)
    assert r1.status_code == 400
    assert "No se puede activar directamente un modelo con estado CANDIDATA" in r1.json()["detail"]

    r2 = client.patch(f"/api/v1/modelos/{desc.id_modelo}/activar", headers=headers)
    assert r2.status_code == 400
    assert "No se puede activar directamente un modelo con estado DESCARTADA" in r2.json()["detail"]


def test_trigger_cada_4_semanas_configuracion_y_proceso(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}

    tr = construir_trigger_proceso(
        frecuencia="cada_4_semanas",
        hora_str="01:30",
        dia_str="domingo",
        dia_semana=6
    )
    assert tr is not None

    patch_payload = {
        "frecuencia": "cada_4_semanas",
        "hora": "01:30",
        "dia_semana": 6
    }
    resp = client.patch("/api/v1/procesos/configuracion/reentrenamiento", json=patch_payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["frecuencia"] == "cada_4_semanas"

    r_list = client.get("/api/v1/procesos", headers=headers)
    assert r_list.status_code == 200
    p_reent = [p for p in r_list.json() if p["id_proceso"] == "reentrenamiento_semanal"][0]
    assert p_reent["frecuencia"] == "Cada 4 semanas (Domingo)"


def test_reentrenamiento_por_acumulacion_disparador(db_session):
    calib_file = os.path.join(settings.STORAGE_DIR, "modelos", "calibracion_activa.json")
    os.makedirs(os.path.dirname(calib_file), exist_ok=True)
    with open(calib_file, "w", encoding="utf-8") as f:
        json.dump({"fecha_max_ventas": "2026-10-20"}, f)

    p = db_session.query(Producto).first()
    if not p:
        p = Producto(sku="SKU-ACC-01", nombre="Producto Test Acc", categoria="General", estado="activo")
        db_session.add(p)
        db_session.commit()

    carga = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.now(timezone.utc).replace(tzinfo=None),
        estado="COMPLETADO",
        registros_procesados=850,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add(carga)
    db_session.commit()

    ventas_nuevas = [
        VentaHistorica(
            id_producto=p.id_producto,
            id_carga=carga.id_carga,
            fecha=date(2026, 10, 21) + timedelta(days=i),
            cantidad_vendida=5,
            precio_unitario=15.0
        )
        for i in range(850)
    ]
    db_session.add_all(ventas_nuevas)
    db_session.commit()

    with patch.object(MLForecastService, "is_entrenamiento_en_curso", return_value=False), \
         patch.object(MLForecastService, "entrenar_modelo_candidato") as mock_train:

        verificar_reentrenamiento_por_acumulacion(db_session)
        import time
        time.sleep(0.5)

        assert mock_train.called


def test_notificaciones_modelos_candidatos(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    m1 = ModeloVersion(
        version="v1.5.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
        motivo_entrenamiento="reentrenamiento_programado",
        mape_14d=17.2,
        estado="DESCARTADA"
    )
    m2 = ModeloVersion(
        version="v1.6.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2),
        motivo_entrenamiento="reentrenamiento_manual",
        mape_14d=11.4,
        estado="APTA"
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    resp = client.get("/api/v1/notificaciones/cargas?limite=10", headers=headers)
    assert resp.status_code == 200
    items = resp.json()

    msgs = [it["mensaje"] for it in items]
    assert any("Modelo candidato v1.5.0 descartado: MAPE (demanda 14 días) 17.2% supera el umbral de 15%." in m for m in msgs)
    assert any("Modelo candidato v1.6.0 apto: pendiente de aprobación para publicación." in m for m in msgs)

    r_mod = client.get("/api/v1/notificaciones/modelos?limite=10", headers=headers)
    assert r_mod.status_code == 200
    mod_msgs = [it["mensaje"] for it in r_mod.json()]
    assert any("Modelo candidato v1.5.0 descartado" in m for m in mod_msgs)
    assert any("Modelo candidato v1.6.0 apto" in m for m in mod_msgs)


def test_monitoreo_expone_proximo_reentrenamiento(client, analyst_token):
    headers = {"Authorization": f"Bearer {analyst_token}"}
    resp = client.get("/api/v1/modelos/monitoreo", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "proximo_reentrenamiento_programado" in data


def test_ficha_tecnica_y_monitoreo_cobertura_identica(client, analyst_token, admin_token, db_session):
    headers_an = {"Authorization": f"Bearer {analyst_token}"}

    activa = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="inicial",
        estado="ACTIVA",
        mae=3.8,
        mape=14.0,
        mape_14d=13.0
    )
    corte_bt = ModeloVersion(
        version="v0.backtest.01",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30),
        motivo_entrenamiento="backtest",
        mae=7.22,
        mape=19.23,
        rmse=10.98,
        estado="DESCARTADA"
    )
    db_session.add_all([activa, corte_bt])
    db_session.commit()

    r_ficha = client.get("/api/v1/modelos/activa", headers=headers_an)
    assert r_ficha.status_code == 200
    cob_ficha = r_ficha.json()["cobertura_intervalo_95"]

    r_mon = client.get("/api/v1/modelos/monitoreo", headers=headers_an)
    assert r_mon.status_code == 200
    cob_mon = r_mon.json()["cobertura_intervalo_95"]

    assert cob_ficha == cob_mon


def test_notificaciones_usa_umbral_de_evaluacion_de_la_version(client, analyst_token, admin_token, db_session):
    headers_an = {"Authorization": f"Bearer {analyst_token}"}
    headers_ad = {"Authorization": f"Bearer {admin_token}"}

    u_mape = db_session.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
    if u_mape:
        u_mape.valor = 15.0
    else:
        db_session.add(UmbralConfiguracion(tipo_umbral="mape_max", valor=15.0))
    db_session.commit()

    cand1 = ModeloVersion(
        version="v1.7.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="DESCARTADA",
        mape_14d=10.73,
        umbral_mape_evaluacion=10.0,
        observacion="MAPE (demanda 14 días) 10.73% supera el umbral de 10%. Se mantiene la versión v1.0.0 en producción."
    )
    cand2 = ModeloVersion(
        version="v1.8.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="DESCARTADA",
        mape_14d=12.5,
        umbral_mape_evaluacion=None,
        observacion="MAPE (demanda 14 días) 12.5% supera el umbral de 12%. Se mantiene la versión v1.0.0 en producción."
    )
    db_session.add_all([cand1, cand2])
    db_session.commit()

    resp_cargas = client.get("/api/v1/notificaciones/cargas?limite=10", headers=headers_an)
    assert resp_cargas.status_code == 200
    msgs_cargas = {it["id_carga"]: it for it in resp_cargas.json()}
    assert cand1.id_modelo in msgs_cargas
    assert "supera el umbral de 10%." in msgs_cargas[cand1.id_modelo]["mensaje"]
    assert msgs_cargas[cand1.id_modelo]["umbral_calidad"] == 10.0
    assert cand2.id_modelo in msgs_cargas
    assert "supera el umbral de 12%." in msgs_cargas[cand2.id_modelo]["mensaje"]
    assert msgs_cargas[cand2.id_modelo]["umbral_calidad"] == 12.0

    resp_modelos = client.get("/api/v1/notificaciones/modelos?limite=10", headers=headers_an)
    assert resp_modelos.status_code == 200
    msgs_modelos = {it["id_carga"]: it for it in resp_modelos.json()}
    assert "supera el umbral de 10%." in msgs_modelos[cand1.id_modelo]["mensaje"]

    resp_comp = client.get(f"/api/v1/modelos/{cand1.id_modelo}/comparacion", headers=headers_ad)
    assert resp_comp.status_code == 200
    assert resp_comp.json()["umbral_mape_evaluacion"] == 10.0


def test_fecha_publicacion_hora_america_lima(client, admin_token, db_session):
    headers_ad = {"Authorization": f"Bearer {admin_token}"}

    cand = ModeloVersion(
        version="v1.9.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="APTA",
        mae=2.5,
        mape=12.0,
        mape_14d=11.2,
        wape=19.90,
        umbral_mape_evaluacion=15.0,
        observacion="Cumple el umbral (11.2% ≤ 15%). Pendiente de aprobación para publicación."
    )
    db_session.add(cand)
    db_session.commit()

    resp = client.post(f"/api/v1/modelos/{cand.id_modelo}/publicar", headers=headers_ad)
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] == "ACTIVA"

    expected_prefix = datetime.now(ZoneInfo("America/Lima")).strftime("Publicada el %d/%m/%Y %H")
    assert data["observacion"].startswith(expected_prefix)


def test_wape_por_version_historial_comparacion_ficha_y_monitoreo(client, admin_token, analyst_token, db_session):
    headers_ad = {"Authorization": f"Bearer {admin_token}"}
    headers_an = {"Authorization": f"Bearer {analyst_token}"}

    activa_prev = db_session.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    if activa_prev:
        activa_prev.wape = 20.01
    else:
        activa_prev = ModeloVersion(
            version="v1.0.0",
            fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
            motivo_entrenamiento="inicial",
            estado="ACTIVA",
            mae=3.0,
            mape=14.0,
            mape_14d=12.0,
            wape=20.01
        )
        db_session.add(activa_prev)
    db_session.commit()

    cand = ModeloVersion(
        version="v1.10.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="APTA",
        mae=2.4,
        mape=11.5,
        mape_14d=10.2,
        wape=19.90,
        umbral_mape_evaluacion=15.0,
        observacion="Cumple el umbral (10.2% ≤ 15%). Pendiente de aprobación para publicación."
    )
    db_session.add(cand)
    db_session.commit()

    r_hist = client.get("/api/v1/modelos/historial", headers=headers_an)
    assert r_hist.status_code == 200
    hist_dict = {item["id_modelo"]: item for item in r_hist.json()}
    assert hist_dict[cand.id_modelo]["wape"] == 19.90
    assert hist_dict[activa_prev.id_modelo]["wape"] == 20.01

    r_comp = client.get(f"/api/v1/modelos/{cand.id_modelo}/comparacion", headers=headers_ad)
    assert r_comp.status_code == 200
    comp_data = r_comp.json()
    assert comp_data["candidato"]["wape"] == 19.90
    assert comp_data["activa"]["wape"] == 20.01

    r_pub = client.post(f"/api/v1/modelos/{cand.id_modelo}/publicar", headers=headers_ad)
    assert r_pub.status_code == 200

    met_path = os.path.join(settings.STORAGE_DIR, "modelos", "metricas_modelo.json")
    with open(met_path, "r", encoding="utf-8") as f:
        met_data = json.load(f)
    assert met_data["wape"] == 19.90

    r_ficha = client.get("/api/v1/modelos/activa", headers=headers_an)
    assert r_ficha.status_code == 200
    ficha_data = r_ficha.json()
    assert ficha_data["wape"] == 19.90
    assert "proximo_reentrenamiento_programado" in ficha_data

    r_ficha_alias = client.get("/api/v1/modelos/ficha", headers=headers_an)
    assert r_ficha_alias.status_code == 200
    assert r_ficha_alias.json()["wape"] == 19.90

    r_mon = client.get("/api/v1/modelos/monitoreo", headers=headers_an)
    assert r_mon.status_code == 200
    assert r_mon.json()["wape"] == 19.90


def test_comparacion_vigente_equivalente_mejora_empeora(client, admin_token, db_session):
    headers_ad = {"Authorization": f"Bearer {admin_token}"}

    activa = db_session.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    if activa:
        activa.mape_14d = 11.00
    else:
        activa = ModeloVersion(
            version="v1.0.0",
            fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
            motivo_entrenamiento="inicial",
            estado="ACTIVA",
            mape_14d=11.00
        )
        db_session.add(activa)
    db_session.commit()

    cand_equiv = ModeloVersion(
        version="v1.11.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="APTA",
        mape_14d=11.03,
        umbral_mape_evaluacion=15.0,
        observacion="Cumple el umbral"
    )
    cand_mejora = ModeloVersion(
        version="v1.12.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="APTA",
        mape_14d=10.40,
        umbral_mape_evaluacion=15.0,
        observacion="Cumple el umbral"
    )
    cand_empeora = ModeloVersion(
        version="v1.13.0",
        fecha_entrenamiento=datetime.now(timezone.utc).replace(tzinfo=None),
        motivo_entrenamiento="reentrenamiento_manual",
        estado="APTA",
        mape_14d=11.60,
        umbral_mape_evaluacion=15.0,
        observacion="Cumple el umbral"
    )
    db_session.add_all([cand_equiv, cand_mejora, cand_empeora])
    db_session.commit()

    r1 = client.get(f"/api/v1/modelos/{cand_equiv.id_modelo}/comparacion", headers=headers_ad)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["comparacion_vigente"] == "equivalente"
    assert d1["mejora_vigente"] is False

    r2 = client.get(f"/api/v1/modelos/{cand_mejora.id_modelo}/comparacion", headers=headers_ad)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["comparacion_vigente"] == "mejora"
    assert d2["mejora_vigente"] is True

    r3 = client.get(f"/api/v1/modelos/{cand_empeora.id_modelo}/comparacion", headers=headers_ad)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["comparacion_vigente"] == "empeora"
    assert d3["mejora_vigente"] is False
