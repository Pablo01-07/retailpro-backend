import pytest
import os
from datetime import datetime, date, timedelta
from app.models.producto import Producto
from app.models.pronostico import Pronostico
from app.models.modelo_version import ModeloVersion
from app.models.alerta import Alerta
from app.models.umbral_configuracion import UmbralConfiguracion
from app.models.auditoria import Auditoria


@pytest.fixture
def phase4_seed(db_session):
    prod = db_session.query(Producto).filter(Producto.sku == "PH4-001").first()
    if not prod:
        prod = Producto(
            sku="PH4-001",
            nombre="Producto Fase 4",
            categoria="Abarrotes",
            stock_actual=50,
            punto_reorden=30,
            estado="activo"
        )
        db_session.add(prod)
        db_session.commit()
        db_session.refresh(prod)

    mv = db_session.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    if not mv:
        mv = ModeloVersion(
            version="v1.0.0-test",
            motivo_entrenamiento="inicial_produccion",
            mae=5.5,
            mape=18.2,
            rmse=8.5,
            estado="ACTIVA"
        )
        db_session.add(mv)
        db_session.commit()
        db_session.refresh(mv)

    fecha_base = datetime.utcnow()
    for h in range(1, 15):
        pr = Pronostico(
            id_producto=prod.id_producto,
            id_modelo=mv.id_modelo,
            fecha_generacion=fecha_base,
            horizonte_dias=h,
            cantidad_proyectada=15.0,
            intervalo_confianza_inf=10.0,
            intervalo_confianza_sup=20.0,
            nivel_incertidumbre="MEDIO",
            explicacion_shap={
                "probabilidad_quiebre": 35.0,
                "dias_cobertura_stock": 3.3,
                "top_factores": [{"feature": "rolling_mean_7", "impacto": 2.1}]
            },
            cantidad_sugerida_reposicion=190,
            fecha_limite_reposicion=(fecha_base + timedelta(days=2)).date()
        )
        db_session.add(pr)
    db_session.commit()

    return {"prod": prod, "modelo": mv}


def test_reposicion_list_and_priority(client, analyst_token, phase4_seed):
    headers = {"Authorization": f"Bearer {analyst_token}"}
    resp = client.get("/api/v1/reposicion", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_recomendaciones"] >= 1
    item = next(it for it in data["items"] if it["sku"] == "PH4-001")
    assert item["prioridad"] == "ALTA"
    assert item["cantidad_sugerida"] == 190
    assert item["probabilidad_quiebre"] == 35.0


def test_reposicion_ajuste_analista(client, analyst_token, db_session, phase4_seed):
    headers = {"Authorization": f"Bearer {analyst_token}"}
    prod = phase4_seed["prod"]
    pron = db_session.query(Pronostico).filter(Pronostico.id_producto == prod.id_producto).first()

    payload = {
        "cantidad_ajustada": 250,
        "motivo_ajuste": "Ajuste por lote mínimo de compra del proveedor"
    }
    resp = client.patch(f"/api/v1/reposicion/{pron.id_pronostico}", headers=headers, json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["cantidad_ajustada"] == 250

    audit = db_session.query(Auditoria).filter(
        Auditoria.accion == "AJUSTE_MANUAL_REPOSICION"
    ).order_by(Auditoria.fecha_hora.desc()).first()
    assert audit is not None
    assert audit.detalle["cantidad_ajustada"] == 250


def test_alertas_list_and_sincronizacion(client, admin_token, phase4_seed):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = client.get("/api/v1/alertas", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_activas"] >= 1
    quiebres = [it for it in data["items"] if it["sku"] == "PH4-001" and it["tipo_alerta"] == "QUIEBRE"]
    assert len(quiebres) == 1
    assert quiebres[0]["estado"] in ["ACTIVA", "Activa", "pendiente"]


def test_alertas_actualizar_estado(client, analyst_token, db_session, phase4_seed):
    from app.services.alert_service import AlertService
    AlertService.sincronizar_alertas(db_session)
    headers = {"Authorization": f"Bearer {analyst_token}"}
    prod = phase4_seed["prod"]
    alerta = db_session.query(Alerta).filter(Alerta.id_producto == prod.id_producto).first()

    payload = {
        "nuevo_estado": "RESUELTA",
        "comentario": "Orden de compra emitida a proveedor"
    }
    resp = client.patch(f"/api/v1/alertas/{alerta.id_alerta}", headers=headers, json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["nuevo_estado"] in ["RESUELTA", "Resuelta"]
    assert data["fecha_revision"] is not None


def test_umbrales_get_and_put_admin(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp_get = client.get("/api/v1/umbrales", headers=headers)
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert len(data_get["umbrales"]) >= 6

    payload = {"quiebre_prob_min": 10.0, "sobrestock_dias": 60.0}
    resp_put = client.put("/api/v1/umbrales", headers=headers, json=payload)
    assert resp_put.status_code == 200

    u10 = db_session.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "quiebre_prob_min").first()
    assert float(u10.valor) == 10.0


def test_actualizar_umbrales_inconsistentes_422(client, admin_token, db_session):
    headers = {"Authorization": f"Bearer {admin_token}"}
    u_sob_antes = db_session.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "sobrestock_dias").first()
    u_qbr_antes = db_session.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "quiebre_dias_cobertura").first()
    val_sob_antes = float(u_sob_antes.valor) if u_sob_antes else 90.0
    val_qbr_antes = float(u_qbr_antes.valor) if u_qbr_antes else 7.0

    payload = {"sobrestock_dias": 20.0, "quiebre_dias_cobertura": 30.0}
    resp = client.put("/api/v1/umbrales", headers=headers, json=payload)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "El umbral de sobrestock debe ser mayor al umbral de quiebre: los días máximos de cobertura en almacén deben ser mayores a los días de cobertura mínima."

    db_session.expire_all()
    u_sob_despues = db_session.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "sobrestock_dias").first()
    u_qbr_despues = db_session.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "quiebre_dias_cobertura").first()
    assert float(u_sob_despues.valor) == val_sob_antes
    assert float(u_qbr_despues.valor) == val_qbr_antes


def test_dashboard_and_nivel_servicio(client, logistics_token, phase4_seed):
    headers = {"Authorization": f"Bearer {logistics_token}"}

    resp_dash = client.get("/api/v1/dashboard", headers=headers)
    assert resp_dash.status_code == 200
    data_dash = resp_dash.json()
    assert len(data_dash["kpis"]) >= 4
    assert len(data_dash["categorias"]) >= 1

    resp_ns = client.get("/api/v1/dashboard/nivel-servicio", headers=headers)
    assert resp_ns.status_code == 200
    data_ns = resp_ns.json()
    assert data_ns["es_estimacion"] is True
    assert "nota_metodologica" in data_ns
    assert len(data_ns["por_categoria"]) >= 1

    resp_pbi = client.get("/api/v1/dashboard/powerbi", headers=headers)
    assert resp_pbi.status_code == 200
    data_pbi = resp_pbi.json()
    assert data_pbi["enabled"] is False
    assert data_pbi["embed_url"] is None

    resp_cors = client.options(
        "/api/v1/dashboard",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET"
        }
    )
    assert resp_cors.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_reportes_preview_and_exports(client, analyst_token, phase4_seed):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    resp_prev = client.get("/api/v1/reportes/pronostico/preview", headers=headers)
    assert resp_prev.status_code == 200
    data_prev = resp_prev.json()
    assert data_prev["total_registros"] >= 1

    resp_csv = client.post("/api/v1/reportes/pronostico/export", headers=headers, json={"formato": "csv"})
    assert resp_csv.status_code == 200
    data_csv = resp_csv.json()
    assert data_csv["nombre_archivo"].endswith(".csv")

    resp_xlsx = client.post("/api/v1/reportes/pronostico/export", headers=headers, json={"formato": "xlsx"})
    assert resp_xlsx.status_code == 200
    data_xlsx = resp_xlsx.json()
    assert data_xlsx["nombre_archivo"].endswith(".xlsx")

    resp_pdf = client.post("/api/v1/reportes/pronostico/export", headers=headers, json={"formato": "pdf"})
    assert resp_pdf.status_code == 200
    data_pdf = resp_pdf.json()
    assert data_pdf["nombre_archivo"].endswith(".pdf")

    url_descarga = data_csv["url_descarga"]
    resp_dl = client.get(url_descarga, headers=headers)
    assert resp_dl.status_code == 200
    assert len(resp_dl.content) > 0


def test_reportes_preview_filtro_sku(client, analyst_token, phase4_seed):
    headers = {"Authorization": f"Bearer {analyst_token}"}
    resp = client.get("/api/v1/reportes/pronostico/preview?sku=PH4-001", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_registros"] >= 1
    assert all(item["sku"] == "PH4-001" for item in data["items"])

    resp_inexistente = client.get("/api/v1/reportes/pronostico/preview?sku=SKU-NO-EXISTE", headers=headers)
    assert resp_inexistente.status_code == 200
    data_inexistente = resp_inexistente.json()
    assert data_inexistente["total_registros"] == 0
    assert len(data_inexistente["items"]) == 0


def test_reportes_exportar_sin_datos_400(client, analyst_token, phase4_seed):
    headers = {"Authorization": f"Bearer {analyst_token}"}
    resp_sku = client.post("/api/v1/reportes/pronostico/export", headers=headers, json={"formato": "csv", "sku": "SKU-NO-EXISTE"})
    assert resp_sku.status_code == 400
    assert resp_sku.json()["detail"] == "No hay datos para los filtros seleccionados. Ajuste los filtros antes de exportar."

    resp_cat = client.post("/api/v1/reportes/pronostico/export", headers=headers, json={"formato": "csv", "categoria": "Lacteos", "sku": "PH4-001"})
    assert resp_cat.status_code == 400
    assert resp_cat.json()["detail"] == "No hay datos para los filtros seleccionados. Ajuste los filtros antes de exportar."


def test_rbac_logistics_restricted_actions(client, logistics_token, db_session, phase4_seed):
    headers = {"Authorization": f"Bearer {logistics_token}"}

    assert client.get("/api/v1/dashboard", headers=headers).status_code == 200
    assert client.get("/api/v1/alertas", headers=headers).status_code == 200
    assert client.get("/api/v1/dashboard/nivel-servicio", headers=headers).status_code == 200
    assert client.get("/api/v1/reportes/pronostico/preview", headers=headers).status_code == 200

    prod = phase4_seed["prod"]
    pron = db_session.query(Pronostico).filter(Pronostico.id_producto == prod.id_producto).first()
    alerta = db_session.query(Alerta).filter(Alerta.id_producto == prod.id_producto).first()

    resp_patch_repo = client.patch(f"/api/v1/reposicion/{pron.id_pronostico}", headers=headers, json={"cantidad_ajustada": 100})
    assert resp_patch_repo.status_code == 403

    if alerta:
        resp_patch_alerta = client.patch(f"/api/v1/alertas/{alerta.id_alerta}", headers=headers, json={"nuevo_estado": "Resuelta"})
        assert resp_patch_alerta.status_code == 403

    resp_put_umbrales = client.put("/api/v1/umbrales", headers=headers, json={"quiebre_prob_min": 15.0})
    assert resp_put_umbrales.status_code == 403

    resp_export = client.post("/api/v1/reportes/pronostico/export", headers=headers, json={"formato": "csv"})
    assert resp_export.status_code == 403


def test_dynamic_threshold_changes_alerts(client, admin_token, phase4_seed):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    resp_put1 = client.put("/api/v1/umbrales", headers=admin_headers, json={"quiebre_dias_cobertura": 2.0})
    assert resp_put1.status_code == 200

    resp_alertas1 = client.get("/api/v1/alertas", headers=admin_headers)
    assert resp_alertas1.status_code == 200
    items1 = resp_alertas1.json()["items"]
    for it in items1:
        if it["tipo_alerta"] == "QUIEBRE":
            assert "umbral: 2.0d" in it["detalle_motivo"]

    resp_put2 = client.put("/api/v1/umbrales", headers=admin_headers, json={"quiebre_dias_cobertura": 12.0})
    assert resp_put2.status_code == 200

    resp_alertas2 = client.get("/api/v1/alertas", headers=admin_headers)
    assert resp_alertas2.status_code == 200
    items2 = resp_alertas2.json()["items"]
    for it in items2:
        if it["tipo_alerta"] == "QUIEBRE":
            assert "umbral: 12.0d" in it["detalle_motivo"]

    client.put("/api/v1/umbrales", headers=admin_headers, json={"quiebre_dias_cobertura": 7.0})


def test_alertas_sku_sin_pronostico_no_genera_alerta_quiebre(client, admin_token, db_session):
    from app.models.producto import Producto
    from app.models.alerta import Alerta
    from app.models.modelo_version import ModeloVersion
    from app.services.alert_service import AlertService
    from datetime import datetime

    modelo = db_session.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    if not modelo:
        modelo = ModeloVersion(
            version="v1.0.0",
            fecha_entrenamiento=datetime.utcnow(),
            motivo_entrenamiento="entrenamiento_inicial",
            mae=1.8,
            mape=14.2,
            rmse=2.3,
            estado="ACTIVA"
        )
        db_session.add(modelo)
        db_session.commit()

    p_sin_pron = Producto(
        sku="SIN-PRON-001",
        nombre="Producto Nuevo Sin Histórico Ni Pronóstico",
        categoria="Abarrotes",
        stock_actual=50,
        punto_reorden=20,
        estado=True
    )
    db_session.add(p_sin_pron)
    db_session.commit()

    AlertService.sincronizar_alertas(db_session)

    alerta_q = db_session.query(Alerta).filter(
        Alerta.id_producto == p_sin_pron.id_producto,
        Alerta.tipo_alerta == "QUIEBRE"
    ).first()
    assert alerta_q is None, "Un SKU sin pronóstico no debe generar alerta de quiebre falsa"

    alerta_dummy = Alerta(
        id_producto=p_sin_pron.id_producto,
        id_pronostico=None,
        tipo_alerta="QUIEBRE",
        fecha_generacion=datetime.utcnow(),
        estado="Activa"
    )
    db_session.add(alerta_dummy)
    db_session.commit()

    resumen = AlertService.list_alertas(db_session, tipo="QUIEBRE")
    item_alerta = next((it for it in resumen.items if it.id_producto == p_sin_pron.id_producto), None)
    assert item_alerta is not None
    assert item_alerta.nivel_severidad == "ADVERTENCIA", "Alerta sin pronóstico no debe clasificarse como CRITICA por cobertura 0.0"
    assert item_alerta.dias_cobertura != 0.0, "La cobertura de un SKU sin pronóstico no debe ser 0.0"


def test_alertas_resumen_conteos_directos(client, admin_token, db_session):
    from datetime import datetime
    from app.models.producto import Producto
    from app.models.alerta import Alerta

    p = Producto(sku="CNT-001", nombre="Producto Conteo", categoria="Snacks", stock_actual=10, punto_reorden=30, estado=True)
    db_session.add(p)
    db_session.commit()

    a1 = Alerta(id_producto=p.id_producto, tipo_alerta="QUIEBRE", estado="ACTIVA", fecha_generacion=datetime.utcnow())
    a2 = Alerta(id_producto=p.id_producto, tipo_alerta="SOBRESTOCK", estado="ACTIVA", fecha_generacion=datetime.utcnow())
    a3 = Alerta(id_producto=p.id_producto, tipo_alerta="QUIEBRE", estado="RESUELTA", fecha_generacion=datetime.utcnow())
    db_session.add_all([a1, a2, a3])
    db_session.commit()

    resp = client.get("/api/v1/alertas", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["activas"] == 2
    assert data["quiebre"] == 1
    assert data["sobrestock"] == 1
    assert data["resueltas"] == 1
    assert data["criticas"] == 1
    assert data["advertencias"] == 1
    assert data["criticas"] + data["advertencias"] == data["activas"]

    items_by_tipo = {it["tipo_alerta"]: it for it in data["items"] if it["estado"] == "ACTIVA"}
    assert items_by_tipo["QUIEBRE"]["prioridad"] == "ALTA"
    assert items_by_tipo["QUIEBRE"]["nivel_severidad"] == "CRITICA"
    assert items_by_tipo["SOBRESTOCK"]["prioridad"] == "MEDIA"
    assert items_by_tipo["SOBRESTOCK"]["nivel_severidad"] == "ADVERTENCIA"


def test_dashboard_productos_mas_vendidos(client, admin_token, db_session):
    from datetime import date, timedelta
    from app.models.producto import Producto
    from app.models.carga_datos import CargaDatos
    from app.models.venta_historica import VentaHistorica

    p1 = Producto(sku="TOP-001", nombre="Producto Top 1", categoria="Bebidas", stock_actual=100, punto_reorden=20, estado=True)
    p2 = Producto(sku="TOP-002", nombre="Producto Top 2", categoria="Abarrotes", stock_actual=80, punto_reorden=15, estado=True)
    db_session.add_all([p1, p2])
    db_session.commit()

    carga = CargaDatos(tipo_carga="ventas", estado="COMPLETADO", registros_procesados=10, registros_rechazados=0, porcentaje_calidad=100.0)
    db_session.add(carga)
    db_session.commit()

    t_max = date(2026, 10, 20)
    ventas = []
    ventas.append(VentaHistorica(id_producto=p1.id_producto, id_carga=carga.id_carga, fecha=t_max - timedelta(days=5), cantidad_vendida=100, precio_unitario=2.5))
    ventas.append(VentaHistorica(id_producto=p1.id_producto, id_carga=carga.id_carga, fecha=t_max - timedelta(days=40), cantidad_vendida=50, precio_unitario=2.5))

    ventas.append(VentaHistorica(id_producto=p2.id_producto, id_carga=carga.id_carga, fecha=t_max - timedelta(days=10), cantidad_vendida=60, precio_unitario=4.0))
    ventas.append(VentaHistorica(id_producto=p2.id_producto, id_carga=carga.id_carga, fecha=t_max - timedelta(days=45), cantidad_vendida=80, precio_unitario=4.0))

    db_session.add_all(ventas)
    db_session.commit()

    resp = client.get("/api/v1/dashboard/productos-mas-vendidos", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    top_items = resp.json()

    assert len(top_items) == 2
    assert top_items[0]["sku"] == "TOP-001"
    assert top_items[0]["unidades_vendidas"] == 100
    assert top_items[0]["variacion_pct"] == 100.0

    assert top_items[1]["sku"] == "TOP-002"
    assert top_items[1]["unidades_vendidas"] == 60
    assert top_items[1]["variacion_pct"] == -25.0


def test_alertas_ciclo_vida_antireapertura_y_reactivacion(client, admin_token, db_session):
    from datetime import datetime, date
    from app.models.producto import Producto
    from app.models.modelo_version import ModeloVersion
    from app.models.pronostico import Pronostico
    from app.models.alerta import Alerta
    from app.models.auditoria import Auditoria
    from app.services.alert_service import AlertService

    headers = {"Authorization": f"Bearer {admin_token}"}

    modelo = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=1.8,
        mape=14.2,
        rmse=2.3,
        estado="ACTIVA"
    )
    p = Producto(sku="LIFE-001", nombre="Producto Ciclo Vida", categoria="Abarrotes", stock_actual=10, punto_reorden=50, estado=True)
    db_session.add_all([modelo, p])
    db_session.commit()

    f_gen = datetime(2026, 10, 20, 0, 0, 0)
    pron = Pronostico(
        id_producto=p.id_producto,
        id_modelo=modelo.id_modelo,
        fecha_generacion=f_gen,
        horizonte_dias=1,
        cantidad_proyectada=20.0,
        intervalo_confianza_inf=15.0,
        intervalo_confianza_sup=25.0,
        nivel_incertidumbre="BAJO",
        explicacion_shap={"probabilidad_quiebre": 80.0, "dias_cobertura_stock": 0.5},
        cantidad_sugerida_reposicion=60,
        fecha_limite_reposicion=date(2026, 10, 20)
    )
    db_session.add(pron)
    db_session.commit()

    AlertService.sincronizar_alertas(db_session)
    resp_init = client.get("/api/v1/alertas", headers=headers)
    assert resp_init.status_code == 200
    data_init = resp_init.json()
    assert data_init["activas"] == 1
    assert data_init["resueltas"] == 0
    assert data_init["quiebre"] == 1

    alerta = db_session.query(Alerta).filter(Alerta.id_producto == p.id_producto).first()
    assert alerta is not None
    assert alerta.estado == "ACTIVA"

    resp_resolve = client.patch(
        f"/api/v1/alertas/{alerta.id_alerta}",
        headers=headers,
        json={"nuevo_estado": "RESUELTA", "comentario": "Orden de compra colocada"}
    )
    assert resp_resolve.status_code == 200
    assert resp_resolve.json()["nuevo_estado"] == "RESUELTA"

    resp_after_resolve = client.get("/api/v1/alertas", headers=headers)
    data_after_resolve = resp_after_resolve.json()
    assert data_after_resolve["activas"] == 0
    assert data_after_resolve["resueltas"] == 1
    assert data_after_resolve["quiebre"] == 0

    audit_resolve = db_session.query(Auditoria).filter(
        Auditoria.accion == "ACTUALIZACION_ESTADO_ALERTA"
    ).order_by(Auditoria.id_auditoria.desc()).first()
    assert audit_resolve is not None
    assert audit_resolve.detalle["estado_anterior"] == "ACTIVA"
    assert audit_resolve.detalle["nuevo_estado"] == "RESUELTA"

    AlertService.sincronizar_alertas(db_session)
    resp_after_sync = client.get("/api/v1/alertas", headers=headers)
    data_after_sync = resp_after_sync.json()
    assert data_after_sync["activas"] == 0
    assert data_after_sync["resueltas"] == 1
    assert data_after_sync["quiebre"] == 0

    resp_put_u = client.put(
        "/api/v1/umbrales",
        headers=headers,
        json={"quiebre_prob_min": 5.0}
    )
    assert resp_put_u.status_code == 200
    resp_after_put = client.get("/api/v1/alertas", headers=headers)
    data_after_put = resp_after_put.json()
    assert data_after_put["activas"] == 0
    assert data_after_put["resueltas"] == 1

    resp_reactivate = client.patch(
        f"/api/v1/alertas/{alerta.id_alerta}",
        headers=headers,
        json={"nuevo_estado": "ACTIVA", "comentario": "Reactivada para seguimiento"}
    )
    assert resp_reactivate.status_code == 200
    assert resp_reactivate.json()["nuevo_estado"] == "ACTIVA"

    resp_after_reactivate = client.get("/api/v1/alertas", headers=headers)
    data_after_reactivate = resp_after_reactivate.json()
    assert data_after_reactivate["activas"] == 1
    assert data_after_reactivate["resueltas"] == 0
    assert data_after_reactivate["quiebre"] == 1

    db_session.refresh(alerta)
    assert alerta.estado == "ACTIVA"


def test_auditoria_nunca_guarda_credenciales_ni_tokens(client, admin_token, db_session):
    import json
    from app.models.auditoria import Auditoria
    from app.models.usuario import Usuario

    headers = {"Authorization": f"Bearer {admin_token}"}
    plain_password_user = "SecretPass2026!#"

    resp_create = client.post(
        "/api/v1/usuarios",
        headers=headers,
        json={
            "correo": "audit.test@retailpro.com",
            "nombre_completo": "Usuario Prueba Auditoría",
            "password": plain_password_user,
            "rol": "analista",
            "estado": True
        }
    )
    assert resp_create.status_code == 201
    user_created_id = resp_create.json()["id_usuario"]

    new_plain_password = "UpdatedSecretPass999!#"
    resp_update = client.put(
        f"/api/v1/usuarios/{user_created_id}",
        headers=headers,
        json={
            "nombre_completo": "Usuario Prueba Editado",
            "password": new_plain_password
        }
    )
    assert resp_update.status_code == 200

    resp_login = client.post(
        "/api/v1/auth/login",
        json={"email": "audit.test@retailpro.com", "password": new_plain_password}
    )
    assert resp_login.status_code == 200
    access_token_val = resp_login.json()["access_token"]
    refresh_token_val = resp_login.json()["refresh_token"]

    bad_password = "WrongPasswordAttempt777!#"
    resp_bad_login = client.post(
        "/api/v1/auth/login",
        json={"email": "audit.test@retailpro.com", "password": bad_password}
    )
    assert resp_bad_login.status_code == 401

    resp_rec = client.post(
        "/api/v1/auth/password-recovery",
        json={"email": "audit.test@retailpro.com"}
    )
    assert resp_rec.status_code == 200

    audit_direct = Auditoria(
        id_usuario=user_created_id,
        accion="PRUEBA_DIRECTA_SANITIZACION",
        modulo_afectado="seguridad",
        detalle={
            "password": "un_password_directo",
            "clave_hash": "$2b$12$eX4mpleHashNotAllowedInAuditLogs",
            "access_token": access_token_val,
            "data_valida": "ok"
        }
    )
    db_session.add(audit_direct)
    db_session.commit()
    db_session.refresh(audit_direct)

    all_audits = db_session.query(Auditoria).all()
    assert len(all_audits) > 0

    prohibited_strings = [
        plain_password_user,
        new_plain_password,
        bad_password,
        access_token_val,
        refresh_token_val,
        "un_password_directo"
    ]

    for log in all_audits:
        if not log.detalle:
            continue
        detalle_str = json.dumps(log.detalle)

        for k in log.detalle.keys():
            k_lower = k.lower()
            assert not any(sens in k_lower for sens in ["password", "clave_hash", "refresh_token", "access_token"]), (
                f"Clave sensible encontrada en auditoria ID {log.id_auditoria}: {k}"
            )

        for prohibited in prohibited_strings:
            assert prohibited not in detalle_str, (
                f"Dato sensible prohibido encontrado en detalle de auditoría ID {log.id_auditoria}: {prohibited}"
            )

    assert "password" not in audit_direct.detalle
    assert "clave_hash" not in audit_direct.detalle
    assert "access_token" not in audit_direct.detalle
    assert audit_direct.detalle["data_valida"] == "ok"

