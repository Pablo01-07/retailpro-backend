import os
import json
from datetime import datetime, timedelta, date
from unittest.mock import patch
from app.models.carga_datos import CargaDatos
from app.models.producto import Producto
from app.models.venta_historica import VentaHistorica
from app.models.modelo_version import ModeloVersion
from app.models.pronostico import Pronostico
from app.models.alerta import Alerta
from app.models.auditoria import Auditoria
from app.services.etl_service import get_storage_carga_dir
from app.services.ml_service import MLForecastService
from app.services.reporting_service import ReportingService
from app.core.config import settings


def test_datos_desactualizados_24h(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    c_ventas_vieja = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow() - timedelta(hours=30),
        estado="COMPLETADO",
        registros_procesados=100,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    c_inv_nueva = CargaDatos(
        tipo_carga="inventario",
        fecha_ejecucion=datetime.utcnow() - timedelta(hours=5),
        estado="CON_ADVERTENCIAS",
        registros_procesados=50,
        registros_rechazados=1,
        porcentaje_calidad=98.0
    )
    db_session.add_all([c_ventas_vieja, c_inv_nueva])
    db_session.commit()

    resp = client.get("/api/v1/datos/estado", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["ventas"]["desactualizado"] is True
    assert data["ventas"]["estado"] == "Desactualizado"
    assert data["ventas"]["ultima_actualizacion"] is not None

    assert data["inventario"]["desactualizado"] is False
    assert data["inventario"]["estado"] == "Actualizado"
    assert data["inventario"]["ultima_actualizacion"] is not None


def test_dashboard_aviso_datos_antiguos_48h(client, logistics_token, db_session):
    headers = {"Authorization": f"Bearer {logistics_token}"}

    c_ventas = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow() - timedelta(hours=10),
        estado="COMPLETADO",
        registros_procesados=100,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    c_inv = CargaDatos(
        tipo_carga="inventario",
        fecha_ejecucion=datetime.utcnow() - timedelta(hours=55),
        estado="COMPLETADO",
        registros_procesados=50,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add_all([c_ventas, c_inv])
    db_session.commit()

    resp = client.get("/api/v1/dashboard", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["datos_desactualizados"] is True
    assert data["ultima_actualizacion_datos"] is not None


def test_calidad_ultima_carga(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    c1 = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow() - timedelta(hours=10),
        estado="COMPLETADO",
        registros_procesados=100,
        registros_rechazados=1,
        porcentaje_calidad=99.0
    )
    c2 = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow() - timedelta(hours=2),
        estado="FALLIDO",
        registros_procesados=100,
        registros_rechazados=20,
        porcentaje_calidad=80.0
    )
    c3 = CargaDatos(
        tipo_carga="inventario",
        fecha_ejecucion=datetime.utcnow() - timedelta(hours=1),
        estado="COMPLETADO",
        registros_procesados=50,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add_all([c1, c2, c3])
    db_session.commit()

    resp_ventas = client.get("/api/v1/datos/calidad?tipo_informacion=ventas", headers=headers)
    assert resp_ventas.status_code == 200
    d_v = resp_ventas.json()
    assert d_v["ultima_carga_pct"] == 80.0
    assert d_v["ultima_carga_tipo"] == "ventas"
    assert d_v["ultima_carga_cumple"] is False

    resp_inv = client.get("/api/v1/datos/calidad?tipo_informacion=inventario", headers=headers)
    assert resp_inv.status_code == 200
    d_i = resp_inv.json()
    assert d_i["ultima_carga_pct"] == 100.0
    assert d_i["ultima_carga_tipo"] == "inventario"
    assert d_i["ultima_carga_cumple"] is True


def test_historial_insuficiente_excluido_y_422(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    p_suf = Producto(
        sku="SKU-SUF-01",
        nombre="Producto Suficiente",
        categoria="Snacks",
        stock_actual=100,
        punto_reorden=20,
        estado="activo"
    )
    p_insuf = Producto(
        sku="SKU-INSUF-01",
        nombre="Producto Insuficiente",
        categoria="Snacks",
        stock_actual=100,
        punto_reorden=20,
        estado="activo"
    )
    p_sin_ventas = Producto(
        sku="SKU-NOVENTAS-01",
        nombre="Producto Sin Ventas",
        categoria="Snacks",
        stock_actual=50,
        punto_reorden=10,
        estado="activo"
    )
    db_session.add_all([p_suf, p_insuf, p_sin_ventas])
    db_session.commit()

    carga = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow(),
        estado="COMPLETADO",
        registros_procesados=300,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add(carga)
    db_session.commit()

    f_base = date(2026, 1, 1)
    ventas = []
    for d in range(200):
        ventas.append(VentaHistorica(
            id_producto=p_suf.id_producto,
            id_carga=carga.id_carga,
            fecha=f_base + timedelta(days=d),
            cantidad_vendida=5,
            precio_unitario=2.0
        ))

    for d in range(160, 200):
        ventas.append(VentaHistorica(
            id_producto=p_insuf.id_producto,
            id_carga=carga.id_carga,
            fecha=f_base + timedelta(days=d),
            cantidad_vendida=3,
            precio_unitario=2.0
        ))

    db_session.add_all(ventas)
    db_session.commit()

    assert MLForecastService.tiene_historial_suficiente(db_session, p_suf.id_producto) is True
    assert MLForecastService.tiene_historial_suficiente(db_session, p_insuf.id_producto) is False
    assert MLForecastService.tiene_historial_suficiente(db_session, p_sin_ventas.id_producto) is False

    resp_insuf = client.get("/api/v1/pronosticos/SKU-INSUF-01", headers=headers)
    assert resp_insuf.status_code == 422
    assert resp_insuf.json()["detail"] == "Historial insuficiente para generar un pronóstico confiable"

    resp_list = client.get("/api/v1/pronosticos?incluir_sin_pronostico=true", headers=headers)
    assert resp_list.status_code == 200
    items = resp_list.json()["items"]
    it_suf = next(x for x in items if x["sku"] == "SKU-SUF-01")
    it_ins = next(x for x in items if x["sku"] == "SKU-INSUF-01")
    it_nov = next(x for x in items if x["sku"] == "SKU-NOVENTAS-01")

    assert it_suf["historial_suficiente"] is True
    assert it_ins["historial_suficiente"] is False
    assert it_nov["historial_suficiente"] is False


def test_excedente_estimado_sobrestock(client, analyst_token, db_session):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    prod = Producto(
        sku="SKU-SOBRE-01",
        nombre="Producto Sobrestock",
        categoria="Bebidas",
        stock_actual=500,
        punto_reorden=30,
        estado="activo"
    )
    db_session.add(prod)
    db_session.commit()

    mv = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=1.5,
        mape=12.0,
        rmse=2.0,
        estado="ACTIVA"
    )
    db_session.add(mv)
    db_session.commit()

    pron = Pronostico(
        id_producto=prod.id_producto,
        id_modelo=mv.id_modelo,
        fecha_generacion=datetime.utcnow(),
        horizonte_dias=1,
        cantidad_proyectada=2.0,
        intervalo_confianza_inf=1.0,
        intervalo_confianza_sup=3.0,
        nivel_incertidumbre="BAJO",
        explicacion_shap={
            "probabilidad_quiebre": 0.0,
            "demanda_acumulada_14d": 28.0,
            "dias_cobertura_stock": 250.0
        },
        cantidad_sugerida_reposicion=0
    )
    db_session.add(pron)
    db_session.commit()

    alerta_sobre = Alerta(
        id_producto=prod.id_producto,
        id_pronostico=pron.id_pronostico,
        tipo_alerta="SOBRESTOCK",
        fecha_generacion=datetime.utcnow(),
        estado="ACTIVA"
    )
    db_session.add(alerta_sobre)
    db_session.commit()

    resp = client.get("/api/v1/alertas", headers=headers)
    assert resp.status_code == 200
    alertas = resp.json()["items"]
    alerta_resp = next(a for a in alertas if a["sku"] == "SKU-SOBRE-01")

    assert alerta_resp["excedente_estimado"] is not None
    assert alerta_resp["excedente_estimado"] > 0
    assert f"Excedente estimado: {alerta_resp['excedente_estimado']} u." in alerta_resp["detalle_motivo"]


def test_error_al_generar_pdf_500(client, analyst_token, db_session, monkeypatch):
    headers = {"Authorization": f"Bearer {analyst_token}"}

    prod = Producto(
        sku="SKU-PDF-01",
        nombre="Producto PDF",
        categoria="Snacks",
        stock_actual=100,
        punto_reorden=20,
        estado="activo"
    )
    db_session.add(prod)
    db_session.commit()

    mv = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=1.5,
        mape=12.0,
        rmse=2.0,
        estado="ACTIVA"
    )
    db_session.add(mv)
    db_session.commit()

    pron = Pronostico(
        id_producto=prod.id_producto,
        id_modelo=mv.id_modelo,
        fecha_generacion=datetime.utcnow(),
        horizonte_dias=1,
        cantidad_proyectada=2.0,
        intervalo_confianza_inf=1.0,
        intervalo_confianza_sup=3.0,
        nivel_incertidumbre="BAJO",
        explicacion_shap={"probabilidad_quiebre": 0.0, "demanda_acumulada_14d": 28.0, "dias_cobertura_stock": 50.0},
        cantidad_sugerida_reposicion=0
    )
    db_session.add(pron)
    db_session.commit()

    def mock_build_fallido(*args, **kwargs):
        raise RuntimeError("Falla simulada en motor de renderizado PDF")

    monkeypatch.setattr("reportlab.platypus.SimpleDocTemplate.build", mock_build_fallido)

    storage_rep = os.path.join(settings.STORAGE_DIR, "reportes")
    archivos_antes = set(os.listdir(storage_rep)) if os.path.exists(storage_rep) else set()
    auditorias_antes = db_session.query(Auditoria).count()

    payload = {"formato": "pdf"}
    resp = client.post("/api/v1/reportes/pronostico/export", headers=headers, json=payload)

    assert resp.status_code == 500
    assert resp.json()["detail"] == "No se pudo generar el documento PDF. Intente nuevamente."

    archivos_despues = set(os.listdir(storage_rep)) if os.path.exists(storage_rep) else set()
    assert archivos_despues == archivos_antes

    auditorias_despues = db_session.query(Auditoria).count()
    assert auditorias_despues == auditorias_antes
