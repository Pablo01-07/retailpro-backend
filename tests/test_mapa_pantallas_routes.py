import os
import re
import pytest
from app.main import app


def test_mapa_pantallas_endpoints_match_real_openapi_routes():
    doc_path = os.path.join(os.getcwd(), "docs", "mapa-pantallas-endpoints.md")
    assert os.path.isfile(doc_path), f"El archivo {doc_path} no existe."

    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"`(/api/v1/[^`\s]+)`"
    endpoints_in_doc = set(re.findall(pattern, content))

    assert len(endpoints_in_doc) > 0, "No se encontraron endpoints en docs/mapa-pantallas-endpoints.md"

    openapi_paths = app.openapi()["paths"]
    real_endpoints = set(openapi_paths.keys())

    endpoints_discrepantes = endpoints_in_doc - real_endpoints
    assert not endpoints_discrepantes, (
        f"Se encontraron endpoints ficticios o inexistentes en docs/mapa-pantallas-endpoints.md: {endpoints_discrepantes}"
    )

    endpoints_esenciales = [
        "/api/v1/auth/login",
        "/api/v1/auth/password-recovery",
        "/api/v1/datos/estado",
        "/api/v1/datos/upload",
        "/api/v1/datos/cargas",
        "/api/v1/datos/calidad",
        "/api/v1/procesos",
        "/api/v1/procesos/ejecutar/{tipo_proceso}",
        "/api/v1/procesos/{id_carga}",
        "/api/v1/procesos/configuracion",
        "/api/v1/pronosticos",
        "/api/v1/modelos/activa",
        "/api/v1/modelos/monitoreo",
        "/api/v1/modelos/historial",
        "/api/v1/modelos/{id_modelo}/activar",
        "/api/v1/dashboard",
        "/api/v1/dashboard/powerbi",
        "/api/v1/pronosticos/tendencias",
        "/api/v1/reposicion",
        "/api/v1/reposicion/exportar",
        "/api/v1/reposicion/{id_pronostico}",
        "/api/v1/dashboard/nivel-servicio",
        "/api/v1/alertas",
        "/api/v1/umbrales",
        "/api/v1/reportes/pronostico/preview",
        "/api/v1/reportes/pronostico/export",
        "/api/v1/reportes/inventario/export",
        "/api/v1/reportes/ventas/export",
        "/api/v1/reportes/indicadores/export",
        "/api/v1/reportes/historial",
        "/api/v1/reportes/descargar/{filename}",
        "/api/v1/usuarios",
        "/api/v1/auditoria",
    ]

    for ep in endpoints_esenciales:
        assert ep in endpoints_in_doc, f"El endpoint esencial '{ep}' falta en docs/mapa-pantallas-endpoints.md"
