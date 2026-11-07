import os
import json
import pytest
from datetime import datetime, date, timedelta
from app.models.producto import Producto
from app.models.modelo_version import ModeloVersion
from app.models.pronostico import Pronostico
from app.models.alerta import Alerta
from app.models.carga_datos import CargaDatos
from app.models.venta_historica import VentaHistorica
from app.models.auditoria import Auditoria


@pytest.fixture
def rbac_seed(db_session):
    prod = Producto(
        sku="PRD-001",
        nombre="Producto Prueba RBAC",
        categoria="Abarrotes",
        stock_actual=100,
        punto_reorden=30,
        estado=True
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)

    m1 = ModeloVersion(
        version="v1.0.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="INICIAL",
        mape=12.5,
        mae=10.0,
        rmse=15.0,
        estado="ACTIVA"
    )
    m2 = ModeloVersion(
        version="v1.1.0",
        fecha_entrenamiento=datetime.utcnow(),
        motivo_entrenamiento="REENTRENAMIENTO",
        mape=11.2,
        mae=9.0,
        rmse=14.0,
        estado="ANTERIOR"
    )
    db_session.add_all([m1, m2])
    db_session.commit()
    db_session.refresh(m1)
    db_session.refresh(m2)

    pron = Pronostico(
        id_producto=prod.id_producto,
        id_modelo=m1.id_modelo,
        fecha_generacion=datetime.utcnow(),
        horizonte_dias=1,
        cantidad_proyectada=25.0,
        intervalo_confianza_inf=20.0,
        intervalo_confianza_sup=30.0,
        nivel_incertidumbre="BAJO",
        explicacion_shap={"probabilidad_quiebre": 10.0, "dias_cobertura_stock": 15.0},
        cantidad_sugerida_reposicion=10,
        fecha_limite_reposicion=date.today() + timedelta(days=3)
    )
    db_session.add(pron)
    db_session.commit()
    db_session.refresh(pron)

    alerta = Alerta(
        id_producto=prod.id_producto,
        id_pronostico=pron.id_pronostico,
        tipo_alerta="QUIEBRE",
        estado="ACTIVA",
        fecha_generacion=datetime.utcnow()
    )
    db_session.add(alerta)
    db_session.commit()
    db_session.refresh(alerta)

    carga = CargaDatos(
        id_usuario=1,
        tipo_carga="ventas",
        estado="COMPLETADO",
        registros_procesados=100,
        registros_rechazados=0,
        porcentaje_calidad=100.0,
        fecha_ejecucion=datetime.utcnow()
    )
    db_session.add(carga)
    db_session.commit()
    db_session.refresh(carga)

    carga_dir = os.path.join("storage", "cargas", str(carga.id_carga))
    os.makedirs(carga_dir, exist_ok=True)
    with open(os.path.join(carga_dir, "etapas.json"), "w", encoding="utf-8") as f:
        json.dump([
            {"nombre": "Lectura", "estado": "COMPLETADO", "inicio": "2026-10-23T10:00:00Z", "fin": "2026-10-23T10:00:01Z", "duracion_ms": 1000}
        ], f)

    reportes_dir = os.path.join("storage", "reportes")
    os.makedirs(reportes_dir, exist_ok=True)
    report_file = os.path.join(reportes_dir, "reporte_demo.csv")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("id,sku,fecha,cantidad\n1,PRD-001,2026-10-23,10\n")

    return {
        "prod": prod,
        "m1": m1,
        "m2": m2,
        "pron": pron,
        "alerta": alerta,
        "carga": carga
    }


RBAC_MATRIX = [
    ("GET", "/api/v1/datos/estado", None, 200, 200, 403),
    ("GET", "/api/v1/datos/cargas", None, 200, 200, 403),
    ("GET", "/api/v1/datos/cargas/1", None, 200, 200, 403),
    ("GET", "/api/v1/datos/calidad", None, 200, 200, 403),
    ("GET", "/api/v1/datos/incidencias/frecuentes", None, 200, 200, 403),
    ("POST", "/api/v1/datos/sincronizar", None, 200, 200, 403),

    ("GET", "/api/v1/procesos", None, 200, 200, 403),
    ("GET", "/api/v1/procesos/1", None, 200, 200, 403),
    ("GET", "/api/v1/procesos/configuracion", None, 200, 403, 403),
    ("PUT", "/api/v1/procesos/configuracion", {"frecuencia_cron": "0 2 * * *"}, 200, 403, 403),
    ("POST", "/api/v1/procesos/ejecutar/pronostico", None, 200, 200, 403),
    ("POST", "/api/v1/notificaciones/resumen-alertas", None, 200, 403, 403),
    ("POST", "/api/v1/notificaciones/prueba", None, 200, 403, 403),

    ("GET", "/api/v1/pronosticos", None, 200, 200, 200),
    ("GET", "/api/v1/pronosticos/tendencias", None, 200, 200, 200),
    ("GET", "/api/v1/pronosticos/PRD-001", None, 200, 200, 200),
    ("GET", "/api/v1/modelos/activa", None, 200, 200, 200),
    ("GET", "/api/v1/modelos/historial", None, 200, 200, 200),
    ("GET", "/api/v1/modelos/monitoreo", None, 200, 200, 200),
    ("PATCH", "/api/v1/modelos/2/activar", None, 200, 403, 403),

    ("GET", "/api/v1/dashboard", None, 200, 200, 200),
    ("GET", "/api/v1/dashboard/productos-mas-vendidos", None, 200, 200, 200),
    ("GET", "/api/v1/dashboard/nivel-servicio", None, 200, 200, 200),
    ("GET", "/api/v1/dashboard/powerbi", None, 200, 200, 200),

    ("GET", "/api/v1/reposicion", None, 200, 200, 200),
    ("PATCH", "/api/v1/reposicion/1", {"cantidad_ajustada": 50}, 200, 200, 403),
    ("POST", "/api/v1/reposicion/exportar", {"formato": "csv"}, 200, 200, 403),

    ("GET", "/api/v1/alertas", None, 200, 200, 200),
    ("PATCH", "/api/v1/alertas/1", {"nuevo_estado": "RESUELTA"}, 200, 200, 403),
    ("GET", "/api/v1/umbrales", None, 200, 200, 200),
    ("PUT", "/api/v1/umbrales", {"quiebre_prob_min": 5.0}, 200, 403, 403),

    ("GET", "/api/v1/reportes/historial", None, 200, 200, 200),
    ("GET", "/api/v1/reportes/pronostico/preview", None, 200, 200, 200),
    ("GET", "/api/v1/reportes/descargar/reporte_demo.csv", None, 200, 200, 200),
    ("POST", "/api/v1/reportes/pronostico/export", {"formato": "csv"}, 200, 200, 403),
    ("POST", "/api/v1/reportes/inventario/export", {"formato": "csv"}, 200, 200, 403),
    ("POST", "/api/v1/reportes/ventas/export", {"formato": "csv"}, 200, 200, 403),
    ("POST", "/api/v1/reportes/indicadores/export", {"formato": "csv"}, 200, 200, 403),

    ("GET", "/api/v1/usuarios", None, 200, 403, 403),
    ("GET", "/api/v1/auditoria", None, 200, 403, 403),
    ("GET", "/api/v1/auditoria/exportar", None, 200, 403, 403),
]


def _ejecutar_req(client, method, path, body, token):
    headers = {"Authorization": f"Bearer {token}"}
    if method == "GET":
        return client.get(path, headers=headers)
    elif method == "POST":
        return client.post(path, json=body, headers=headers)
    elif method == "PUT":
        return client.put(path, json=body, headers=headers)
    elif method == "PATCH":
        return client.patch(path, json=body, headers=headers)
    elif method == "DELETE":
        return client.delete(path, headers=headers)
    raise ValueError(f"Método {method} no implementado")


@pytest.mark.parametrize("method, path, body, exp_admin, exp_analyst, exp_logistics", RBAC_MATRIX)
def test_rbac_endpoint_matrix(client, admin_token, analyst_token, logistics_token, rbac_seed, method, path, body, exp_admin, exp_analyst, exp_logistics):
    resp_adm = _ejecutar_req(client, method, path, body, admin_token)
    assert resp_adm.status_code == exp_admin, (
        f"Fallo RBAC [ADMINISTRADOR] en [{method} {path}]: "
        f"esperado {exp_admin}, obtenido {resp_adm.status_code} ({resp_adm.text})"
    )

    resp_ana = _ejecutar_req(client, method, path, body, analyst_token)
    assert resp_ana.status_code == exp_analyst, (
        f"Fallo RBAC [ANALISTA] en [{method} {path}]: "
        f"esperado {exp_analyst}, obtenido {resp_ana.status_code} ({resp_ana.text})"
    )

    resp_log = _ejecutar_req(client, method, path, body, logistics_token)
    assert resp_log.status_code == exp_logistics, (
        f"Fallo RBAC [JEFE_LOGISTICA] en [{method} {path}]: "
        f"esperado {exp_logistics}, obtenido {resp_log.status_code} ({resp_log.text})"
    )


def test_rbac_ejecutar_proceso_roles(client, admin_token, analyst_token, logistics_token, rbac_seed):
    headers_ana = {"Authorization": f"Bearer {analyst_token}"}
    headers_log = {"Authorization": f"Bearer {logistics_token}"}
    headers_adm = {"Authorization": f"Bearer {admin_token}"}

    r_ana_pron = client.post("/api/v1/procesos/ejecutar/pronostico", headers=headers_ana)
    assert r_ana_pron.status_code == 200, f"Analista debe poder ejecutar pronóstico: {r_ana_pron.text}"

    r_ana_etl = client.post("/api/v1/procesos/ejecutar/etl", headers=headers_ana)
    assert r_ana_etl.status_code == 403, f"Analista no debe poder ejecutar etl: {r_ana_etl.text}"

    r_ana_reent = client.post("/api/v1/procesos/ejecutar/reentrenamiento", headers=headers_ana)
    assert r_ana_reent.status_code == 403, f"Analista no debe poder ejecutar reentrenamiento: {r_ana_reent.text}"

    r_log_pron = client.post("/api/v1/procesos/ejecutar/pronostico", headers=headers_log)
    assert r_log_pron.status_code == 403, f"Jefe de logística no debe poder ejecutar pronóstico: {r_log_pron.text}"

    r_log_etl = client.post("/api/v1/procesos/ejecutar/etl", headers=headers_log)
    assert r_log_etl.status_code == 403, f"Jefe de logística no debe poder ejecutar etl: {r_log_etl.text}"

    r_adm_pron = client.post("/api/v1/procesos/ejecutar/pronostico", headers=headers_adm)
    assert r_adm_pron.status_code == 200, f"Administrador debe poder ejecutar pronóstico: {r_adm_pron.text}"

    r_adm_etl = client.post("/api/v1/procesos/ejecutar/etl", headers=headers_adm)
    assert r_adm_etl.status_code == 200, f"Administrador debe poder ejecutar etl: {r_adm_etl.text}"
