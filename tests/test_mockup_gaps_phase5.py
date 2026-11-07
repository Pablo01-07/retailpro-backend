import os
import pytest
from datetime import datetime, date, timedelta
from app.models.producto import Producto
from app.models.modelo_version import ModeloVersion
from app.models.pronostico import Pronostico
from app.models.auditoria import Auditoria
from app.models.carga_datos import CargaDatos
from app.models.venta_historica import VentaHistorica
from app.core.config import settings


@pytest.fixture
def mock_data_env(db_session):
    m_activa = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow() - timedelta(days=10),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=1.8,
        mape=14.2,
        rmse=2.3,
        estado="ACTIVA"
    )
    m_ant = ModeloVersion(
        version="v0.9.0",
        fecha_entrenamiento=datetime.utcnow() - timedelta(days=30),
        motivo_entrenamiento="entrenamiento_inicial",
        mae=2.1,
        mape=16.5,
        rmse=2.7,
        estado="ANTERIOR"
    )
    m_backtest = ModeloVersion(
        version="corte_01_backtest",
        fecha_entrenamiento=datetime.utcnow() - timedelta(days=60),
        motivo_entrenamiento="backtest",
        mae=1.9,
        mape=15.1,
        rmse=2.4,
        estado="DESCARTADA"
    )
    db_session.add_all([m_activa, m_ant, m_backtest])
    db_session.commit()

    p1 = Producto(
        sku="SKU-ABA-001",
        nombre="Arroz Costeño 1kg",
        categoria="Abarrotes",
        stock_actual=150,
        punto_reorden=50,
        estado=True
    )
    p2 = Producto(
        sku="SKU-BEB-001",
        nombre="Inca Kola 1.5L",
        categoria="Bebidas",
        stock_actual=20,
        punto_reorden=40,
        estado=True
    )
    db_session.add_all([p1, p2])
    db_session.commit()

    fecha_gen_test = datetime.utcnow() - timedelta(days=1)
    pron1 = Pronostico(
        id_producto=p1.id_producto,
        id_modelo=m_activa.id_modelo,
        fecha_generacion=fecha_gen_test,
        horizonte_dias=1,
        cantidad_proyectada=10.0,
        intervalo_confianza_inf=8.0,
        intervalo_confianza_sup=12.0,
        nivel_incertidumbre="BAJO",
        explicacion_shap={"probabilidad_quiebre": 2.0, "demanda_acumulada_14d": 140.0, "dias_cobertura_stock": 15.0},
        cantidad_sugerida_reposicion=0,
        fecha_limite_reposicion=date.today() + timedelta(days=10)
    )
    pron2 = Pronostico(
        id_producto=p2.id_producto,
        id_modelo=m_activa.id_modelo,
        fecha_generacion=fecha_gen_test,
        horizonte_dias=1,
        cantidad_proyectada=15.0,
        intervalo_confianza_inf=10.0,
        intervalo_confianza_sup=20.0,
        nivel_incertidumbre="ALTO",
        explicacion_shap={"probabilidad_quiebre": 85.0, "demanda_acumulada_14d": 210.0, "dias_cobertura_stock": 1.3},
        cantidad_sugerida_reposicion=230,
        fecha_limite_reposicion=date.today()
    )
    db_session.add_all([pron1, pron2])

    c1 = CargaDatos(
        tipo_carga="ventas",
        fecha_ejecucion=datetime.utcnow() - timedelta(days=2),
        estado="COMPLETADO",
        registros_procesados=100,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    c2 = CargaDatos(
        tipo_carga="inventario",
        fecha_ejecucion=datetime.utcnow() - timedelta(days=1),
        estado="COMPLETADO",
        registros_procesados=50,
        registros_rechazados=0,
        porcentaje_calidad=100.0
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    v1 = VentaHistorica(
        id_producto=p1.id_producto,
        id_carga=c1.id_carga,
        fecha=date.today() - timedelta(days=5),
        cantidad_vendida=12,
        precio_unitario=4.50
    )
    v2 = VentaHistorica(
        id_producto=p2.id_producto,
        id_carga=c1.id_carga,
        fecha=date.today() - timedelta(days=5),
        cantidad_vendida=18,
        precio_unitario=6.00
    )
    db_session.add_all([v1, v2])
    db_session.commit()

    return {
        "m_activa": m_activa,
        "m_ant": m_ant,
        "m_backtest": m_backtest,
        "p1": p1,
        "p2": p2
    }


def test_activar_modelo_produccion_exitoso(client, admin_token, mock_data_env, db_session):
    m_ant = mock_data_env["m_ant"]
    m_activa = mock_data_env["m_activa"]

    resp = client.patch(
        f"/api/v1/modelos/{m_ant.id_modelo}/activar",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id_modelo"] == m_ant.id_modelo
    assert data["estado"] == "ACTIVA"

    db_session.refresh(m_activa)
    assert m_activa.estado == "ANTERIOR"

    audit = db_session.query(Auditoria).filter(Auditoria.accion == "ACTIVACION_MODELO").first()
    assert audit is not None
    assert audit.detalle.get("id_modelo") == m_ant.id_modelo


def test_activar_modelo_backtest_rechazo_400(client, admin_token, mock_data_env):
    m_backtest = mock_data_env["m_backtest"]

    resp = client.patch(
        f"/api/v1/modelos/{m_backtest.id_modelo}/activar",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 400
    assert "backtest" in resp.json()["message"].lower()


def test_activar_modelo_rbac_analista_denegado(client, analyst_token, mock_data_env):
    m_ant = mock_data_env["m_ant"]

    resp = client.patch(
        f"/api/v1/modelos/{m_ant.id_modelo}/activar",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert resp.status_code == 403


def test_exportar_inventario_pdf_xlsx_csv(client, admin_token, mock_data_env):
    for fmt in ["csv", "xlsx", "pdf"]:
        resp = client.post(
            "/api/v1/reportes/inventario/export",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"formato": fmt, "categoria": "Abarrotes"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["formato"] == fmt
        assert os.path.basename(data["nombre_archivo"]) == data["nombre_archivo"]
        assert data["url_descarga"].startswith("/api/v1/reportes/descargar/")


def test_exportar_ventas_e_indicadores(client, analyst_token, mock_data_env):
    resp_ventas = client.post(
        "/api/v1/reportes/ventas/export",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"formato": "xlsx"}
    )
    assert resp_ventas.status_code == 200

    resp_ind = client.post(
        "/api/v1/reportes/indicadores/export",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"formato": "pdf"}
    )
    assert resp_ind.status_code == 200


def test_exportar_reposicion_xlsx_csv(client, admin_token, mock_data_env):
    resp_rep = client.post(
        "/api/v1/reposicion/exportar",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"formato": "xlsx", "categoria": "Bebidas", "prioridad": "ALTA"}
    )
    assert resp_rep.status_code == 200
    assert resp_rep.json()["formato"] == "xlsx"


def test_get_historial_reportes_solo_archivos_existentes(client, admin_token, logistics_token, mock_data_env, db_session):
    resp_gen = client.post(
        "/api/v1/reportes/inventario/export",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"formato": "csv"}
    )
    assert resp_gen.status_code == 200
    nombre_archivo_real = resp_gen.json()["nombre_archivo"]

    audit_fantasma = Auditoria(
        id_usuario=1,
        accion="EXPORTACION_REPORTE",
        modulo_afectado="reportes",
        detalle={"nombre_archivo": "archivo_inexistente_12345.csv", "formato": "csv"}
    )
    db_session.add(audit_fantasma)
    db_session.commit()

    resp_hist = client.get(
        "/api/v1/reportes/historial",
        headers={"Authorization": f"Bearer {logistics_token}"}
    )
    assert resp_hist.status_code == 200
    data = resp_hist.json()
    assert data["total_reportes"] >= 1
    archivos = [it["nombre_archivo"] for it in data["items"]]
    assert nombre_archivo_real in archivos
    assert "archivo_inexistente_12345.csv" not in archivos


def test_filtros_reposicion(client, analyst_token, mock_data_env):
    resp_sku = client.get(
        "/api/v1/reposicion?sku=SKU-BEB-001",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert resp_sku.status_code == 200
    assert len(resp_sku.json()["items"]) == 1
    assert resp_sku.json()["items"][0]["sku"] == "SKU-BEB-001"

    resp_q = client.get(
        "/api/v1/reposicion?q=costeño",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert resp_q.status_code == 200
    assert len(resp_q.json()["items"]) == 1
    assert "Arroz" in resp_q.json()["items"][0]["nombre_producto"]

    en_30_dias = date.today() + timedelta(days=30)
    resp_fecha = client.get(
        f"/api/v1/reposicion?fecha_limite_hasta={en_30_dias.isoformat()}",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert resp_fecha.status_code == 200
    assert len(resp_fecha.json()["items"]) == 1


def test_filtros_dashboard_nivel_servicio_y_almacen(client, admin_token, mock_data_env):
    resp = client.get(
        "/api/v1/dashboard/nivel-servicio?categoria=Abarrotes&almacen=Principal",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["almacenes"] == ["Principal"]
    assert data["almacen_seleccionado"] == "Principal"
    assert data["categoria_filtrada"] == "Abarrotes"
    assert len(data["por_categoria"]) == 1
    assert data["por_categoria"][0]["categoria"] == "Abarrotes"


def test_filtros_datos_calidad(client, admin_token, mock_data_env):
    resp = client.get(
        "/api/v1/datos/calidad?tipo_informacion=ventas",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    for hc in data["historico_cargas"]:
        assert hc["tipo_carga"] == "ventas"


def test_filtros_pronosticos_tendencias(client, admin_token, mock_data_env):
    resp = client.get(
        "/api/v1/pronosticos/tendencias?categoria=Abarrotes",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert "items" in resp.json()
