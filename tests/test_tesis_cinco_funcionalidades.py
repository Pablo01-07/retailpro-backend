import os
import json
from datetime import datetime, timedelta, date
from app.models.carga_datos import CargaDatos
from app.models.producto import Producto
from app.models.venta_historica import VentaHistorica
from app.models.modelo_version import ModeloVersion
from app.models.pronostico import Pronostico
from app.models.auditoria import Auditoria
from app.services.etl_service import get_storage_carga_dir
from app.core.config import settings


def test_notificaciones_cargas_completadas(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    c1 = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow() - timedelta(minutes=2),
        estado="COMPLETADO",
        registros_procesados=200,
        registros_rechazados=0,
        porcentaje_calidad=100.0,
        detalle_error=None
    )
    c2 = CargaDatos(
        tipo_carga="inventario",
        fecha_ejecucion=datetime.utcnow() - timedelta(minutes=5),
        estado="CON_ADVERTENCIAS",
        registros_procesados=60,
        registros_rechazados=3,
        porcentaje_calidad=95.0,
        detalle_error="Consolidado con 3 observaciones."
    )
    c3 = CargaDatos(
        tipo_carga="productos",
        fecha_ejecucion=datetime.utcnow() - timedelta(minutes=10),
        estado="FALLIDO",
        registros_procesados=30,
        registros_rechazados=20,
        porcentaje_calidad=33.33,
        detalle_error="Calidad insuficiente."
    )
    c4 = CargaDatos(
        tipo_carga="productos",
        fecha_ejecucion=datetime.utcnow() - timedelta(minutes=15),
        estado="PENDIENTE",
        registros_procesados=10,
        registros_rechazados=0,
        porcentaje_calidad=100.0,
        detalle_error=None
    )
    db_session.add_all([c1, c2, c3, c4])
    db_session.commit()

    resp = client.get("/api/v1/notificaciones/cargas?limite=10", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 2
    ids = [item["id_carga"] for item in data]
    assert c1.id_carga in ids
    assert c2.id_carga in ids
    assert c3.id_carga not in ids
    assert c4.id_carga not in ids

    item_exito = next(it for it in data if it["id_carga"] == c1.id_carga)
    assert item_exito["tipo_notificacion"] == "exito"
    assert item_exito["mensaje"] == "Los datos de Transacciones de Ventas fueron actualizados correctamente."
    assert item_exito["umbral_calidad"] == 98.0

    item_adv = next(it for it in data if it["id_carga"] == c2.id_carga)
    assert item_adv["tipo_notificacion"] == "advertencia_calidad"
    assert item_adv["mensaje"] == "Carga de Nivel de Stock completada con advertencia: la calidad de datos (95%) está por debajo del umbral (98%)."


def test_reintento_ejecucion_exito_y_rbac(client, admin_token, analyst_token, db_session):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}

    prod = Producto(
        sku="SKU-REINT-01",
        nombre="Producto Reintento",
        categoria="Abarrotes",
        stock_actual=10,
        punto_reorden=5,
        estado="activo"
    )
    db_session.add(prod)
    db_session.commit()

    carga = CargaDatos(
        tipo_carga="inventario",
        fecha_ejecucion=datetime.utcnow(),
        estado="FALLIDO",
        registros_procesados=1,
        registros_rechazados=0,
        porcentaje_calidad=100.0,
        detalle_error="Falla temporal simulada"
    )
    db_session.add(carga)
    db_session.commit()

    carga_dir = get_storage_carga_dir(carga.id_carga)
    csv_content = "sku,stock_actual,punto_reorden\nSKU-REINT-01,80,25\n"
    with open(os.path.join(carga_dir, "archivo_original.csv"), "w", encoding="utf-8") as f:
        f.write(csv_content)

    with open(os.path.join(carga_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"reintentos": 0, "tipo_carga": "inventario"}, f)

    resp_forbidden = client.post(f"/api/v1/procesos/{carga.id_carga}/reintentar", headers=analyst_headers)
    assert resp_forbidden.status_code == 403

    resp_retry = client.post(f"/api/v1/procesos/{carga.id_carga}/reintentar", headers=admin_headers)
    assert resp_retry.status_code == 200
    data_retry = resp_retry.json()
    assert data_retry["id_carga"] == carga.id_carga
    assert data_retry["reintentos"] == 1
    assert data_retry["reintentos_max"] == 3
    assert data_retry["reintento_permitido"] is False
    assert data_retry["estado"] == "COMPLETADO"
    assert data_retry["mensaje"] == "Reintento exitoso: la ejecución se completó correctamente."

    db_session.refresh(prod)
    assert prod.stock_actual == 80
    assert prod.punto_reorden == 25

    audit = db_session.query(Auditoria).filter(Auditoria.accion == "Reintento de ejecución").first()
    assert audit is not None
    assert audit.detalle["id_carga"] == carga.id_carga

    resp_det = client.get(f"/api/v1/procesos/{carga.id_carga}", headers=admin_headers)
    assert resp_det.status_code == 200
    data_det = resp_det.json()
    assert data_det["reintentos"] == 1
    assert data_det["reintentos_max"] == 3
    assert data_det["reintento_permitido"] is False


def test_reintento_limite_3_reintentos_409(client, admin_token, db_session):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    carga = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow(),
        estado="FALLIDO",
        registros_procesados=1,
        registros_rechazados=1,
        porcentaje_calidad=0.0,
        detalle_error="Error critico"
    )
    db_session.add(carga)
    db_session.commit()

    carga_dir = get_storage_carga_dir(carga.id_carga)
    with open(os.path.join(carga_dir, "archivo_original.csv"), "w", encoding="utf-8") as f:
        f.write("fecha,sku,cantidad_vendida,precio_unitario\n2026-01-01,SKU-001,10,5.0\n")

    with open(os.path.join(carga_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"reintentos": 3, "tipo_carga": "ventas"}, f)

    resp_retry_4 = client.post(f"/api/v1/procesos/{carga.id_carga}/reintentar", headers=admin_headers)
    assert resp_retry_4.status_code == 409
    assert resp_retry_4.json()["detail"] == "Se alcanzó el límite de 3 reintentos para esta ejecución. Contacte al equipo técnico o espere la siguiente ejecución programada."

    resp_det = client.get(f"/api/v1/procesos/{carga.id_carga}", headers=admin_headers)
    assert resp_det.status_code == 200
    assert resp_det.json()["reintento_permitido"] is False


def test_reintento_carga_no_fallida_409(client, admin_token, db_session):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    carga = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow(),
        estado="COMPLETADO",
        registros_procesados=10,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add(carga)
    db_session.commit()

    resp = client.post(f"/api/v1/procesos/{carga.id_carga}/reintentar", headers=admin_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Solo se pueden reintentar ejecuciones de carga de datos en estado FALLIDO."


def test_productos_descontinuados_detalle_422(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    mv = ModeloVersion(
        version="v1.0.0-test",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="INICIAL",
        mape=12.0,
        estado="ACTIVA"
    )
    p_desc = Producto(
        sku="SKU-DESC-01",
        nombre="Producto Descontinuado Test",
        categoria="Abarrotes",
        stock_actual=10,
        punto_reorden=5,
        estado="descontinuado"
    )
    db_session.add_all([mv, p_desc])
    db_session.commit()

    resp = client.get(f"/api/v1/pronosticos/{p_desc.sku}", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "No se generan pronósticos para productos descontinuados"


def test_listado_pronosticos_incluir_sin_pronostico(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    mv = ModeloVersion(
        version="v1.0.0-test",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="INICIAL",
        mape=12.0,
        estado="ACTIVA"
    )
    p_con = Producto(
        sku="SKU-CON-01",
        nombre="Producto Con Pronostico",
        categoria="Bebidas",
        stock_actual=40,
        punto_reorden=10,
        estado="activo"
    )
    p_sin = Producto(
        sku="SKU-SIN-01",
        nombre="Producto Sin Pronostico",
        categoria="Bebidas",
        stock_actual=15,
        punto_reorden=5,
        estado="activo"
    )
    db_session.add_all([mv, p_con, p_sin])
    db_session.commit()

    pr = Pronostico(
        id_producto=p_con.id_producto,
        id_modelo=mv.id_modelo,
        fecha_generacion=datetime.utcnow(),
        horizonte_dias=1,
        cantidad_proyectada=20.0,
        intervalo_confianza_inf=15.0,
        intervalo_confianza_sup=25.0,
        nivel_incertidumbre="BAJO",
        explicacion_shap={"probabilidad_quiebre": 10.0}
    )
    db_session.add(pr)
    db_session.commit()

    resp_sin_flag = client.get("/api/v1/pronosticos?categoria=Bebidas", headers=headers)
    assert resp_sin_flag.status_code == 200
    data_sin_flag = resp_sin_flag.json()
    assert data_sin_flag["total_skus"] == 1
    assert data_sin_flag["items"][0]["sku"] == "SKU-CON-01"

    resp_con_flag = client.get("/api/v1/pronosticos?categoria=Bebidas&incluir_sin_pronostico=true", headers=headers)
    assert resp_con_flag.status_code == 200
    data_con_flag = resp_con_flag.json()
    assert data_con_flag["total_skus"] == 2

    item_sin = next(it for it in data_con_flag["items"] if it["sku"] == "SKU-SIN-01")
    assert item_sin["pronostico_disponible"] is False
    assert item_sin["nivel_incertidumbre"] == "N/D"
    assert item_sin["demanda_total_proyectada_14d"] == 0.0
    assert item_sin["fecha_generacion"] is None
    assert item_sin["estado"] == "activo"

    item_con = next(it for it in data_con_flag["items"] if it["sku"] == "SKU-CON-01")
    assert item_con["pronostico_disponible"] is True
    assert item_con["demanda_total_proyectada_14d"] == 20.0


def test_linea_base_historica_disponible_false(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}
    resp = client.get("/api/v1/dashboard/nivel-servicio", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["linea_base_historica_disponible"] is False
    assert data["mensaje_linea_base"] == "Línea base histórica no disponible: no existen saldos diarios históricos de inventario; el nivel proyectado se compara contra la meta referencial."


def test_limite_exportacion_superado_400(client, analyst_token, db_session, monkeypatch):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    carga = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow(),
        estado="COMPLETADO",
        registros_procesados=15,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add(carga)
    db_session.commit()

    prod = Producto(
        sku="SKU-LIM-01",
        nombre="Producto Limite",
        categoria="Snacks",
        stock_actual=10,
        punto_reorden=5,
        estado="activo"
    )
    db_session.add(prod)
    db_session.commit()

    for d in range(15):
        v = VentaHistorica(
            id_producto=prod.id_producto,
            id_carga=carga.id_carga,
            fecha=date(2026, 1, 1) + timedelta(days=d),
            cantidad_vendida=5,
            precio_unitario=2.5
        )
        db_session.add(v)
    db_session.commit()

    monkeypatch.setattr(settings, "EXPORT_MAX_FILAS", 10)

    payload = {"formato": "csv", "categoria": "Snacks"}
    resp = client.post("/api/v1/reportes/ventas/export", headers=headers, json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "La exportación supera el límite de 10000 registros. Reduzca el rango de filtros (por ejemplo, seleccione una categoría) antes de exportar."

    monkeypatch.setattr(settings, "EXPORT_MAX_FILAS", 10000)
    resp_ok = client.post("/api/v1/reportes/ventas/export", headers=headers, json=payload)
    assert resp_ok.status_code == 200
    assert resp_ok.json()["nombre_archivo"].endswith(".csv")
