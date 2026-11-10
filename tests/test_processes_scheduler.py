def test_list_procesos(client, admin_token):
    response = client.get(
        "/api/v1/procesos",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    ids = [p["id_proceso"] for p in data]
    assert "etl_diario" in ids
    assert "pronostico_diario" in ids
    assert "reentrenamiento_semanal" in ids


def test_get_and_update_configuracion_procesos(client, admin_token):
    get_resp = client.get(
        "/api/v1/procesos/configuracion",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert get_resp.status_code == 200
    config_orig = get_resp.json()

    put_resp = client.put(
        "/api/v1/procesos/configuracion",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "etl_frecuencia": "diario",
            "etl_hora": "03:30",
            "pronostico_frecuencia": "diario",
            "pronostico_hora": "05:00",
            "reentrenamiento_frecuencia": "semanal",
            "reentrenamiento_dia": "sabado",
            "reentrenamiento_hora": "23:00",
            "alertas_notificacion_email": "soporte@fasretail.com",
            "notificar_quiebre": True,
            "notificar_sobrestock": False,
            "notificar_calidad_baja": True
        }
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["etl_hora"] == "03:30"
    assert put_resp.json()["alertas_notificacion_email"] == "soporte@fasretail.com"


def test_ejecutar_proceso_manual(client, admin_token):
    resp = client.post(
        "/api/v1/procesos/ejecutar/pronostico",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    id_carga = resp.json().get("id_carga")
    assert id_carga is not None

    det_resp = client.get(
        f"/api/v1/procesos/{id_carga}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert det_resp.status_code == 200
    det_data = det_resp.json()
    assert det_data["id_carga"] == id_carga
    assert len(det_data["etapas"]) >= 3


def test_ejecutar_pronostico_idempotencia_diaria(client, admin_token, db_session):
    from datetime import datetime
    from app.models.producto import Producto
    from app.models.modelo_version import ModeloVersion
    from app.models.pronostico import Pronostico

    modelo = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=1.8,
        mape=14.2,
        rmse=2.3,
        estado="ACTIVA"
    )
    p1 = Producto(
        sku="TEST-SKU-001",
        nombre="Aceite Vegetal 1L",
        categoria="Abarrotes",
        stock_actual=100,
        punto_reorden=30,
        estado=True
    )
    p2 = Producto(
        sku="TEST-SKU-002",
        nombre="Arroz Extra 1kg",
        categoria="Abarrotes",
        stock_actual=200,
        punto_reorden=50,
        estado=True
    )
    db_session.add_all([modelo, p1, p2])
    db_session.commit()

    from app.models.carga_datos import CargaDatos
    from app.models.venta_historica import VentaHistorica
    from datetime import date, timedelta

    carga_seed = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow(),
        estado="COMPLETADO",
        registros_procesados=80,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add(carga_seed)
    db_session.commit()

    f_inicio = date(2026, 9, 1)
    ventas = []
    for d in range(40):
        dia_f = f_inicio + timedelta(days=d)
        ventas.append(VentaHistorica(
            id_producto=p1.id_producto,
            id_carga=carga_seed.id_carga,
            fecha=dia_f,
            cantidad_vendida=15 + (d % 6),
            precio_unitario=5.0
        ))
        ventas.append(VentaHistorica(
            id_producto=p2.id_producto,
            id_carga=carga_seed.id_carga,
            fecha=dia_f,
            cantidad_vendida=25 + (d % 8),
            precio_unitario=4.0
        ))
    db_session.add_all(ventas)
    db_session.commit()

    resp1 = client.post(
        "/api/v1/procesos/ejecutar/pronostico",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp1.status_code == 200

    count1 = db_session.query(Pronostico).filter(Pronostico.id_modelo == modelo.id_modelo).count()
    assert count1 == 28

    resp2 = client.post(
        "/api/v1/procesos/ejecutar/pronostico",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp2.status_code == 200

    count2 = db_session.query(Pronostico).filter(Pronostico.id_modelo == modelo.id_modelo).count()
    assert count2 == 28
    assert count2 == count1


def test_pronostico_no_constante_varianza_horizontes_e_intervalos(client, admin_token, db_session):
    from datetime import datetime, date, timedelta
    from app.models.producto import Producto
    from app.models.modelo_version import ModeloVersion
    from app.models.pronostico import Pronostico
    from app.models.venta_historica import VentaHistorica
    import numpy as np

    modelo = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=1.8,
        mape=14.2,
        rmse=2.3,
        estado="ACTIVA"
    )
    p = Producto(
        sku="VAR-SKU-001",
        nombre="Leche UHT 1L",
        categoria="Lácteos",
        stock_actual=150,
        punto_reorden=40,
        estado=True
    )
    db_session.add_all([modelo, p])
    db_session.commit()

    from app.models.carga_datos import CargaDatos
    carga_seed = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow(),
        estado="COMPLETADO",
        registros_procesados=60,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add(carga_seed)
    db_session.commit()

    f_inicio = date(2026, 8, 1)
    ventas = []
    for d in range(60):
        dia_f = f_inicio + timedelta(days=d)
        ventas.append(VentaHistorica(
            id_producto=p.id_producto,
            id_carga=carga_seed.id_carga,
            fecha=dia_f,
            cantidad_vendida=30 + (d % 7) * 4,
            precio_unitario=4.5
        ))
    db_session.add_all(ventas)
    db_session.commit()

    resp = client.post(
        "/api/v1/procesos/ejecutar/pronostico",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200

    prons = db_session.query(Pronostico).filter(
        Pronostico.id_producto == p.id_producto,
        Pronostico.id_modelo == modelo.id_modelo
    ).order_by(Pronostico.horizonte_dias.asc()).all()

    assert len(prons) == 14
    cants = [float(x.cantidad_proyectada) for x in prons]
    assert len(set(cants)) > 1, "Las cantidades proyectadas no deben ser constantes a lo largo de los 14 días"
    assert np.std(cants) > 0.1, "La desviación estándar de las cantidades proyectadas debe ser mayor a cero"

    anchos = [float(x.intervalo_confianza_sup - x.intervalo_confianza_inf) for x in prons]
    assert len(set(anchos)) > 1, "Los anchos de los intervalos de confianza deben ser proporcionales y variar entre horizontes"
    assert any(x != 6.0 for x in anchos), "El intervalo no debe ser el valor fijo por defecto (12 a 18)"

    primer_pron = prons[0]
    assert primer_pron.explicacion_shap is not None
    top_f = primer_pron.explicacion_shap.get("top_factores", [])
    assert len(top_f) == 5, "Deben existir exactamente 5 factores explicativos SHAP"


def test_pronostico_falla_inferencia_estado_fallido_sin_filas_falsas(client, admin_token, db_session, monkeypatch):
    from datetime import datetime
    from app.models.producto import Producto
    from app.models.modelo_version import ModeloVersion
    from app.models.pronostico import Pronostico
    from app.models.carga_datos import CargaDatos
    from app.services.ml_service import MLForecastService

    modelo = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=1.8,
        mape=14.2,
        rmse=2.3,
        estado="ACTIVA"
    )
    p = Producto(
        sku="FAIL-SKU-001",
        nombre="Producto Prueba Fallo",
        categoria="Abarrotes",
        stock_actual=50,
        punto_reorden=20,
        estado=True
    )
    db_session.add_all([modelo, p])
    db_session.commit()

    def mock_generar_fallido(*args, **kwargs):
        raise RuntimeError("Fallo simulado en la inferencia del modelo XGBoost")

    monkeypatch.setattr(MLForecastService, "generar_pronosticos_lote", mock_generar_fallido)

    resp = client.post(
        "/api/v1/procesos/ejecutar/pronostico",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] == "FALLIDO"
    assert "Fallo simulado" in data["mensaje"]
    id_carga = data["id_carga"]

    carga = db_session.query(CargaDatos).filter(CargaDatos.id_carga == id_carga).first()
    assert carga is not None
    assert carga.estado == "FALLIDO"
    assert "Fallo simulado en la inferencia" in carga.detalle_error
    assert carga.registros_procesados == 0

    filas_falsas = db_session.query(Pronostico).filter(Pronostico.id_producto == p.id_producto).count()
    assert filas_falsas == 0, "No deben existir filas de relleno tras una ejecución fallida"


def test_pronostico_determinismo_corridas_consecutivas(client, admin_token, db_session, monkeypatch):
    from datetime import datetime, date, timedelta
    import os
    import pandas as pd
    import numpy as np
    import xgboost as xgb
    from app.models.producto import Producto
    from app.models.modelo_version import ModeloVersion
    from app.models.pronostico import Pronostico
    from app.models.venta_historica import VentaHistorica
    from app.models.carga_datos import CargaDatos
    from app.services.ml_service import MLForecastService

    modelo = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=1.8,
        mape=14.2,
        rmse=2.3,
        estado="ACTIVA"
    )
    p = Producto(
        sku="DET-SKU-001",
        nombre="Galletas Vainilla 6pk",
        categoria="Snacks",
        stock_actual=120,
        punto_reorden=35,
        estado=True
    )
    db_session.add_all([modelo, p])
    db_session.commit()

    carga_seed = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow(),
        estado="COMPLETADO",
        registros_procesados=60,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add(carga_seed)
    db_session.commit()

    f_inicio = date(2026, 8, 1)
    ventas = []
    for d in range(60):
        dia_f = f_inicio + timedelta(days=d)
        ventas.append(VentaHistorica(
            id_producto=p.id_producto,
            id_carga=carga_seed.id_carga,
            fecha=dia_f,
            cantidad_vendida=25 + (d % 5) * 3,
            precio_unitario=3.8
        ))
    db_session.add_all(ventas)
    db_session.commit()

    model_dir = os.path.join("storage", "modelos")
    os.makedirs(model_dir, exist_ok=True)
    model_file = os.path.join(model_dir, f"modelo_{modelo.id_modelo}.json")
    fallback_file = os.path.join(model_dir, "modelo_activo.json")

    backup_bytes = None
    if os.path.exists(fallback_file):
        with open(fallback_file, "rb") as f:
            backup_bytes = f.read()

    try:
        dummy_model = xgb.XGBRegressor(n_estimators=10, max_depth=3, random_state=42, n_jobs=1)
        X_dummy = pd.DataFrame(np.ones((10, len(MLForecastService.FEATURE_COLS))), columns=MLForecastService.FEATURE_COLS)
        y_dummy = pd.Series([18.0 + (i % 3) * 4.0 for i in range(10)])
        dummy_model.fit(X_dummy, y_dummy)
        dummy_model.save_model(model_file)
        dummy_model.save_model(fallback_file)

        reentreno_llamado = []
        original_gen_mat = MLForecastService.generate_training_matrix
        def spy_gen_matrix(*args, **kwargs):
            reentreno_llamado.append(True)
            return original_gen_mat(*args, **kwargs)
        monkeypatch.setattr(MLForecastService, "generate_training_matrix", spy_gen_matrix)

        resp1 = client.post(
            "/api/v1/procesos/ejecutar/pronostico",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp1.status_code == 200

        prons1 = db_session.query(Pronostico).filter(
            Pronostico.id_producto == p.id_producto,
            Pronostico.id_modelo == modelo.id_modelo
        ).order_by(Pronostico.horizonte_dias.asc()).all()
        assert len(prons1) == 14
        cants1 = [float(x.cantidad_proyectada) for x in prons1]
        inf1 = [float(x.intervalo_confianza_inf) for x in prons1]
        sup1 = [float(x.intervalo_confianza_sup) for x in prons1]
        shap1 = prons1[0].explicacion_shap.get("top_factores")

        resp2 = client.post(
            "/api/v1/procesos/ejecutar/pronostico",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp2.status_code == 200

        prons2 = db_session.query(Pronostico).filter(
            Pronostico.id_producto == p.id_producto,
            Pronostico.id_modelo == modelo.id_modelo
        ).order_by(Pronostico.horizonte_dias.asc()).all()
        assert len(prons2) == 14
        cants2 = [float(x.cantidad_proyectada) for x in prons2]
        inf2 = [float(x.intervalo_confianza_inf) for x in prons2]
        sup2 = [float(x.intervalo_confianza_sup) for x in prons2]
        shap2 = prons2[0].explicacion_shap.get("top_factores")

        assert cants1 == cants2, "Las cantidades proyectadas deben ser exactamente idénticas entre dos corridas con los mismos datos"
        assert inf1 == inf2, "Los intervalos inferiores deben ser idénticos"
        assert sup1 == sup2, "Los intervalos superiores deben ser idénticos"
        assert shap1 == shap2, "Los top 5 factores SHAP y sus impactos deben ser exactamente idénticos"

        assert len(reentreno_llamado) == 0, "No debe llamarse a reentrenamiento cuando existe el modelo activo en disco"
    finally:
        if os.path.exists(model_file):
            try:
                os.remove(model_file)
            except Exception:
                pass
        if backup_bytes is not None:
            with open(fallback_file, "wb") as f:
                f.write(backup_bytes)
        elif os.path.exists(fallback_file):
            try:
                os.remove(fallback_file)
            except Exception:
                pass


def test_apagar_y_encender_proceso_scheduler_proxima_ejecucion(client, admin_token):
    from app.services.scheduler import scheduler

    r_ini = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"activo": True, "hora": "04:00"}
    )
    assert r_ini.status_code == 200
    data_ini = r_ini.json()
    assert data_ini["activo"] is True
    assert data_ini["proxima_ejecucion"] is not None

    job = scheduler.get_job("pronostico_diario")
    assert job is not None
    assert job.next_run_time is not None

    r_off = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"activo": False}
    )
    assert r_off.status_code == 200
    data_off = r_off.json()
    assert data_off["activo"] is False
    assert data_off["proxima_ejecucion"] is None

    assert job.next_run_time is None

    r_get_ind = client.get(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r_get_ind.status_code == 200
    assert r_get_ind.json()["activo"] is False
    assert r_get_ind.json()["proxima_ejecucion"] is None

    r_get_glob = client.get(
        "/api/v1/procesos/configuracion",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r_get_glob.status_code == 200
    assert r_get_glob.json()["pronostico_activo"] is False
    assert r_get_glob.json()["pronostico_proxima_ejecucion"] is None

    r_list = client.get(
        "/api/v1/procesos",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r_list.status_code == 200
    item_pr = next(p for p in r_list.json() if p["id_proceso"] == "pronostico_diario")
    assert item_pr["activo"] is False
    assert item_pr["proxima_ejecucion"] is None

    r_on = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"activo": True}
    )
    assert r_on.status_code == 200
    data_on = r_on.json()
    assert data_on["activo"] is True
    assert data_on["proxima_ejecucion"] is not None
    assert job.next_run_time is not None


def test_cambiar_hora_cambia_proxima_ejecucion(client, admin_token):
    from app.services.scheduler import scheduler

    r1 = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"activo": True, "hora": "04:00"}
    )
    assert r1.status_code == 200
    t1 = r1.json()["proxima_ejecucion"]
    assert t1 is not None

    r2 = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"hora": "07:45"}
    )
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["hora"] == "07:45"
    t2 = data2["proxima_ejecucion"]
    assert t2 is not None
    assert t2 != t1

    job = scheduler.get_job("pronostico_diario")
    assert job.next_run_time is not None
    assert job.next_run_time.hour == 7
    assert job.next_run_time.minute == 45


def test_cambiar_frecuencia_y_dia_semana_scheduler(client, admin_token):
    r = client.patch(
        "/api/v1/procesos/configuracion/reentrenamiento_semanal",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"frecuencia": "semanal", "dia_semana": 4, "hora": "02:30"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["frecuencia"] == "semanal"
    assert data["dia_semana"] == 4
    assert data["dia"] == "viernes"
    assert data["hora"] == "02:30"
    assert data["proxima_ejecucion"] is not None


def test_patch_configuracion_valores_invalidos_dan_422(client, admin_token):
    r_frec = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"frecuencia": "anual"}
    )
    assert r_frec.status_code == 422
    assert "Frecuencia" in r_frec.json().get("detail", "") or "frecuencia" in r_frec.json().get("message", "")

    r_hora1 = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"hora": "25:00"}
    )
    assert r_hora1.status_code == 422

    r_hora2 = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"hora": "4:00pm"}
    )
    assert r_hora2.status_code == 422

    r_dia1 = client.patch(
        "/api/v1/procesos/configuracion/reentrenamiento_semanal",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dia_semana": 7}
    )
    assert r_dia1.status_code == 422

    r_dia2 = client.patch(
        "/api/v1/procesos/configuracion/reentrenamiento_semanal",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dia_semana": -1}
    )
    assert r_dia2.status_code == 422

    r_dia_diario = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"frecuencia": "diario", "dia_semana": 2}
    )
    assert r_dia_diario.status_code == 422
    assert "solo es válido para procesos con frecuencia 'semanal'" in (r_dia_diario.json().get("detail") or "")

    r_vacio = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={}
    )
    assert r_vacio.status_code == 422

    r_404 = client.patch(
        "/api/v1/procesos/configuracion/proceso_inexistente",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"activo": True}
    )
    assert r_404.status_code == 404


def test_patch_configuracion_rbac_solo_administrador(client, admin_token, analyst_token, logistics_token):
    payload = {"hora": "05:00"}

    r_ana = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json=payload
    )
    assert r_ana.status_code == 403

    r_log = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {logistics_token}"},
        json=payload
    )
    assert r_log.status_code == 403

    r_adm = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=payload
    )
    assert r_adm.status_code == 200


def test_auditoria_registra_cambios_de_configuracion(client, admin_token, db_session):
    from app.models.auditoria import Auditoria
    from app.services.scheduler import get_procesos_config

    cfg = get_procesos_config()
    nueva_hora = "06:45" if cfg.get("pronostico_hora") != "06:45" else "07:15"

    resp = client.patch(
        "/api/v1/procesos/configuracion/pronostico_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"hora": nueva_hora}
    )
    assert resp.status_code == 200

    logs = db_session.query(Auditoria).filter(
        Auditoria.accion.in_(["Configuración de proceso modificada", "modificar_configuracion_proceso"]),
        Auditoria.modulo_afectado == "procesos"
    ).order_by(Auditoria.id_auditoria.desc()).all()

    assert len(logs) > 0
    recent_hora_log = next((l for l in logs if l.detalle and l.detalle.get("campo") == "hora"), None)
    assert recent_hora_log is not None
    assert recent_hora_log.detalle["proceso"] == "pronostico_diario"
    assert recent_hora_log.detalle["valor_nuevo"] == nueva_hora
    assert "valor_anterior" in recent_hora_log.detalle


def test_ejecutar_ahora_tres_procesos_administrador(client, admin_token):
    r_etl = client.post(
        "/api/v1/procesos/ejecutar/etl",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r_etl.status_code == 200
    assert r_etl.json()["tipo_proceso"] == "etl"

    r_pron = client.post(
        "/api/v1/procesos/ejecutar/pronostico",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r_etl.status_code == 200
    assert r_pron.json()["tipo_proceso"] == "pronostico"

    r_reent = client.post(
        "/api/v1/procesos/ejecutar/reentrenamiento",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r_reent.status_code == 200
    assert r_reent.json()["tipo_proceso"] == "reentrenamiento"


def test_persistencia_procesos_json_sobrevive_reinicio(client, admin_token):
    import json
    import os
    from app.core.config import settings
    from app.services.scheduler import configurar_jobs_scheduler, scheduler

    client.patch(
        "/api/v1/procesos/configuracion/etl_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"activo": False, "hora": "03:15"}
    )

    config_path = os.path.join(settings.STORAGE_DIR, "config", "procesos.json")
    with open(config_path, "r", encoding="utf-8") as f:
        saved_cfg = json.load(f)

    assert saved_cfg["etl_activo"] is False
    assert saved_cfg["etl_hora"] == "03:15"

    configurar_jobs_scheduler()

    job = scheduler.get_job("etl_diario")
    assert job is not None
    assert job.next_run_time is None

    client.patch(
        "/api/v1/procesos/configuracion/etl_diario",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"activo": True, "hora": "02:00"}
    )


def test_conflicto_horarios_procesos_patch_y_put(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}

    client.patch("/api/v1/procesos/configuracion/pronostico_diario", headers=headers, json={"activo": True, "hora": "04:00"})
    client.patch("/api/v1/procesos/configuracion/etl_diario", headers=headers, json={"activo": True, "hora": "02:00"})

    r_patch_conflict = client.patch(
        "/api/v1/procesos/configuracion/etl_diario",
        headers=headers,
        json={"hora": "04:00"}
    )
    assert r_patch_conflict.status_code == 409
    assert r_patch_conflict.json()["detail"] == "Conflicto de horario: el proceso 'Generación de Pronósticos' ya está programado a las 04:00. Seleccione un horario distinto."

    r_patch_ok = client.patch(
        "/api/v1/procesos/configuracion/etl_diario",
        headers=headers,
        json={"hora": "02:00"}
    )
    assert r_patch_ok.status_code == 200

    r_put_conflict = client.put(
        "/api/v1/procesos/configuracion",
        headers=headers,
        json={"etl_hora": "04:00"}
    )
    assert r_put_conflict.status_code == 409
    assert r_put_conflict.json()["detail"] == "Conflicto de horario: el proceso 'Generación de Pronósticos' ya está programado a las 04:00. Seleccione un horario distinto."

    client.patch("/api/v1/procesos/configuracion/pronostico_diario", headers=headers, json={"activo": False})
    r_patch_inactivo_ok = client.patch(
        "/api/v1/procesos/configuracion/etl_diario",
        headers=headers,
        json={"hora": "04:00"}
    )
    assert r_patch_inactivo_ok.status_code == 200

    client.patch("/api/v1/procesos/configuracion/etl_diario", headers=headers, json={"activo": True, "hora": "02:00"})
    client.patch("/api/v1/procesos/configuracion/pronostico_diario", headers=headers, json={"activo": True, "hora": "04:00"})

