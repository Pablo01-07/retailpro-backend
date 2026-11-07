import io
import os
import datetime
import pytest
from app.models.producto import Producto
from app.models.venta_historica import VentaHistorica
from app.models.carga_datos import CargaDatos


def test_get_estado_datos(client, admin_token):
    response = client.get(
        "/api/v1/datos/estado",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "ventas" in data
    assert "inventario" in data
    assert "catalogo" in data
    assert "categorias" in data


def test_upload_and_process_productos(client, analyst_token, db_session):
    csv_content = (
        "sku,nombre,categoria,stock_actual,punto_reorden\n"
        "PROD-001,Arroz Superior 1kg,Abarrotes,100,20\n"
        "PROD-002,Aceite de Oliva 500ml,Abarrotes,50,15\n"
    )

    response = client.post(
        "/api/v1/datos/upload",
        headers={"Authorization": f"Bearer {analyst_token}"},
        data={"tipo_carga": "productos"},
        files={"file": ("productos_test.csv", csv_content.encode("utf-8"), "text/csv")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["estado"] == "PENDIENTE"
    assert data["porcentaje_calidad"] == 100.0
    assert data["registros_procesados"] == 2
    id_carga = data["id_carga"]

    proc_resp = client.post(
        f"/api/v1/datos/cargas/{id_carga}/procesar-validos",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert proc_resp.status_code == 200
    assert proc_resp.json()["estado"] == "COMPLETADO"

    prods = db_session.query(Producto).all()
    assert len(prods) >= 2


def test_upload_and_process_inventario(client, analyst_token, db_session):
    prod = Producto(sku="INV-TEST-01", nombre="Producto Test", categoria="Bebidas", stock_actual=10, punto_reorden=5)
    db_session.add(prod)
    db_session.commit()

    csv_content = (
        "sku,stock_actual,punto_reorden\n"
        "INV-TEST-01,250,50\n"
    )

    response = client.post(
        "/api/v1/datos/upload",
        headers={"Authorization": f"Bearer {analyst_token}"},
        data={"tipo_carga": "inventario"},
        files={"file": ("inventario_test.csv", csv_content.encode("utf-8"), "text/csv")}
    )
    assert response.status_code == 200
    id_carga = response.json()["id_carga"]

    proc_resp = client.post(
        f"/api/v1/datos/cargas/{id_carga}/procesar-validos",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert proc_resp.status_code == 200
    assert proc_resp.json()["estado"] == "COMPLETADO"

    db_session.refresh(prod)
    assert prod.stock_actual == 250
    assert prod.punto_reorden == 50


def test_upload_and_process_ventas(client, analyst_token, db_session):
    prod = Producto(sku="VTA-TEST-01", nombre="Gaseosa 500ml", categoria="Bebidas", stock_actual=100, punto_reorden=20)
    db_session.add(prod)
    db_session.commit()

    csv_content = (
        "fecha,sku,cantidad_vendida,precio_unitario\n"
        "2025-01-01,VTA-TEST-01,15,3.50\n"
        "2025-01-02,VTA-TEST-01,20,3.50\n"
    )

    response = client.post(
        "/api/v1/datos/upload",
        headers={"Authorization": f"Bearer {analyst_token}"},
        data={"tipo_carga": "ventas"},
        files={"file": ("ventas_test.csv", csv_content.encode("utf-8"), "text/csv")}
    )
    assert response.status_code == 200
    id_carga = response.json()["id_carga"]
    assert response.json()["estado"] == "PENDIENTE"

    proc_resp = client.post(
        f"/api/v1/datos/cargas/{id_carga}/procesar-validos",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert proc_resp.status_code == 200
    assert proc_resp.json()["estado"] == "COMPLETADO"

    ventas = db_session.query(VentaHistorica).filter(VentaHistorica.id_producto == prod.id_producto).all()
    assert len(ventas) == 2


def test_upload_defective_high_quality_con_observaciones(client, analyst_token):
    filas = ["fecha,sku,cantidad_vendida,precio_unitario"]
    filas.append("fecha_invalida,SKU-001,10,5.0")
    for i in range(99):
        filas.append(f"2025-01-01,SKU-{i+100},10,5.0")
    csv_content = "\n".join(filas)

    response = client.post(
        "/api/v1/datos/upload",
        headers={"Authorization": f"Bearer {analyst_token}"},
        data={"tipo_carga": "ventas"},
        files={"file": ("ventas_obs.csv", csv_content.encode("utf-8"), "text/csv")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["estado"] == "PENDIENTE"
    assert data["porcentaje_calidad"] >= 98.0
    assert data["apto_para_procesar"] is True
    assert data["registros_rechazados"] == 1

    id_carga = data["id_carga"]
    proc_resp = client.post(
        f"/api/v1/datos/cargas/{id_carga}/procesar-validos",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert proc_resp.status_code == 200
    assert proc_resp.json()["estado"] == "CON_ADVERTENCIAS"
    assert "advertencias" in proc_resp.json()["estado_display"].lower()


def test_upload_defective_low_quality_rechazado(client, analyst_token):
    filas = [
        "fecha,sku,cantidad_vendida,precio_unitario",
        "2025-01-01,SKU-01,-10,5.0",
        ",SKU-02,10,5.0",
        "2025-01-03,,10,5.0",
        "2025-01-04,SKU-04,10,5.0",
        "2025-01-05,SKU-05,10,5.0",
        "2025-01-06,SKU-06,10,5.0",
        "2025-01-07,SKU-07,10,5.0",
        "2025-01-08,SKU-08,10,5.0",
        "2025-01-09,SKU-09,10,5.0",
        "2025-01-10,SKU-10,10,5.0"
    ]
    csv_content = "\n".join(filas)

    response = client.post(
        "/api/v1/datos/upload",
        headers={"Authorization": f"Bearer {analyst_token}"},
        data={"tipo_carga": "ventas"},
        files={"file": ("ventas_bad.csv", csv_content.encode("utf-8"), "text/csv")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["estado"] == "FALLIDO"
    assert data["porcentaje_calidad"] < 98.0
    assert data["apto_para_procesar"] is False


def test_idempotencia_carga_ventas(client, analyst_token, db_session):
    prod = Producto(sku="IDEMP-01", nombre="Producto Idempotente", categoria="Abarrotes", stock_actual=50, punto_reorden=10)
    db_session.add(prod)
    db_session.commit()

    csv_content = (
        "fecha,sku,cantidad_vendida,precio_unitario\n"
        "2025-01-01,IDEMP-01,10,5.00\n"
        "2025-01-02,IDEMP-01,15,5.00\n"
        "2025-01-03,IDEMP-01,20,5.00\n"
    )

    resp1 = client.post(
        "/api/v1/datos/upload",
        headers={"Authorization": f"Bearer {analyst_token}"},
        data={"tipo_carga": "ventas"},
        files={"file": ("ventas_idemp.csv", csv_content.encode("utf-8"), "text/csv")}
    )
    id1 = resp1.json()["id_carga"]
    proc1 = client.post(f"/api/v1/datos/cargas/{id1}/procesar-validos", headers={"Authorization": f"Bearer {analyst_token}"})
    assert proc1.status_code == 200
    assert proc1.json()["nuevos_insertados"] == 3
    assert proc1.json()["existentes_actualizados"] == 0

    count_primera_vez = db_session.query(VentaHistorica).filter(VentaHistorica.id_producto == prod.id_producto).count()
    assert count_primera_vez == 3

    csv_actualizado = (
        "fecha,sku,cantidad_vendida,precio_unitario\n"
        "2025-01-01,IDEMP-01,10,5.50\n"
        "2025-01-02,IDEMP-01,15,5.50\n"
        "2025-01-03,IDEMP-01,20,5.50\n"
    )
    resp2 = client.post(
        "/api/v1/datos/upload",
        headers={"Authorization": f"Bearer {analyst_token}"},
        data={"tipo_carga": "ventas"},
        files={"file": ("ventas_idemp_v2.csv", csv_actualizado.encode("utf-8"), "text/csv")}
    )
    id2 = resp2.json()["id_carga"]
    assert resp2.json()["resumen_errores"]["duplicados_base"] == 3

    proc2 = client.post(f"/api/v1/datos/cargas/{id2}/procesar-validos", headers={"Authorization": f"Bearer {analyst_token}"})
    assert proc2.status_code == 200
    assert proc2.json()["nuevos_insertados"] == 0
    assert proc2.json()["existentes_actualizados"] == 3

    count_segunda_vez = db_session.query(VentaHistorica).filter(VentaHistorica.id_producto == prod.id_producto).count()
    assert count_segunda_vez == count_primera_vez == 3

    import datetime
    v1 = db_session.query(VentaHistorica).filter(
        VentaHistorica.id_producto == prod.id_producto,
        VentaHistorica.fecha == datetime.date(2025, 1, 1)
    ).first()
    assert float(v1.precio_unitario) == 5.50


def test_get_calidad_global_and_incidencias(client, analyst_token):
    response = client.get(
        "/api/v1/datos/calidad",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "calidad_promedio_pct" in data
    assert "desglose_errores" in data
    assert "historico_cargas" in data


def test_sincronizar_datos(client, analyst_token):
    response = client.post(
        "/api/v1/datos/sincronizar",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert response.status_code == 200
    assert "archivos" in response.json()


def test_meta_nombre_archivo_etiquetas_y_fechas_utc(client, analyst_token, admin_token, db_session):
    csv_content = (
        "sku,nombre,categoria,stock_actual,punto_reorden\n"
        "TEST-META-01,Producto Meta Test,Abarrotes,120,30\n"
    )

    resp_upload = client.post(
        "/api/v1/datos/upload",
        headers={"Authorization": f"Bearer {analyst_token}"},
        data={"tipo_carga": "productos"},
        files={"file": ("mi_archivo_catalogo.csv", csv_content.encode("utf-8"), "text/csv")}
    )
    assert resp_upload.status_code == 200
    upload_data = resp_upload.json()
    id_carga = upload_data["id_carga"]
    assert upload_data["nombre_archivo"] == "mi_archivo_catalogo.csv"
    assert upload_data["tipo_carga_etiqueta"] == "Catálogo Maestro de Productos"
    assert upload_data["tipo_informacion_etiqueta"] == "Catálogo Maestro de Productos"

    resp_cargas = client.get(
        "/api/v1/datos/cargas",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert resp_cargas.status_code == 200
    cargas_list = resp_cargas.json()
    matched = [c for c in cargas_list if c["id_carga"] == id_carga]
    assert len(matched) == 1
    carga_item = matched[0]
    assert carga_item["nombre_archivo"] == "mi_archivo_catalogo.csv"
    assert carga_item["tipo_carga_etiqueta"] == "Catálogo Maestro de Productos"
    assert carga_item["fecha_ejecucion"].endswith("Z")

    resp_det = client.get(
        f"/api/v1/datos/cargas/{id_carga}",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert resp_det.status_code == 200
    det_data = resp_det.json()
    assert det_data["nombre_archivo"] == "mi_archivo_catalogo.csv"
    assert det_data["carga"]["nombre_archivo"] == "mi_archivo_catalogo.csv"
    assert det_data["carga"]["tipo_carga_etiqueta"] == "Catálogo Maestro de Productos"
    assert det_data["carga"]["fecha_ejecucion"].endswith("Z")

    resp_proc = client.get(
        f"/api/v1/procesos/{id_carga}",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert resp_proc.status_code == 200
    proc_data = resp_proc.json()
    assert proc_data["nombre_archivo"] == "mi_archivo_catalogo.csv"
    assert proc_data["tipo_proceso_etiqueta"] == "Catálogo Maestro de Productos"
    assert proc_data["fecha_ejecucion"].endswith("Z")

    carga_sys = CargaDatos(
        tipo_carga="pronostico",
        fecha_ejecucion=datetime.datetime.utcnow(),
        estado="COMPLETADO",
        registros_procesados=840,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add(carga_sys)
    db_session.commit()
    db_session.refresh(carga_sys)

    from app.services.etl_service import get_storage_carga_dir
    meta_sys_path = os.path.join(get_storage_carga_dir(carga_sys.id_carga), "meta.json")
    if os.path.exists(meta_sys_path):
        os.remove(meta_sys_path)

    resp_proc_sys = client.get(
        f"/api/v1/procesos/{carga_sys.id_carga}",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert resp_proc_sys.status_code == 200
    assert resp_proc_sys.json()["nombre_archivo"] is None

    for endpoint in ["/api/v1/datos/calidad/incidencias-frecuentes", "/api/v1/datos/incidencias/frecuentes"]:
        resp_frec = client.get(endpoint, headers={"Authorization": f"Bearer {analyst_token}"})
        assert resp_frec.status_code == 200
        items_frec = resp_frec.json()
        assert len(items_frec) == 5
        etiquetas_recibidas = {it["etiqueta"] for it in items_frec}
        etiquetas_esperadas = {
            "Valores nulos",
            "Formato inválido",
            "Registros duplicados",
            "SKU inexistente en el catálogo",
            "Valores atípicos"
        }
        assert etiquetas_esperadas.issubset(etiquetas_recibidas)

