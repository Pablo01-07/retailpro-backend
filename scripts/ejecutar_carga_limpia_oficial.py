import sys
import os
import psycopg
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.main import app

client = TestClient(app)


def reset_database():
    print("[*] 1. Limpiando retailpro_db...")
    conn = psycopg.connect(
        "host=localhost port=5432 user=retailpro_app password=retailpro_app_pwd_2026 dbname=retailpro_db",
        autocommit=True
    )
    with conn.cursor() as cur:
        for t in ['alerta', 'pronostico', 'modelo_version', 'venta_historica', 'producto', 'carga_datos', 'umbral_configuracion', 'auditoria', 'usuario']:
            cur.execute(f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE;')
    conn.close()
    print("[+] Tablas truncadas exitosamente.")

    from scripts.seed import run_seed
    run_seed()


def ejecutar_pipeline():
    reset_database()

    print("\n[*] 2. Autenticando contra la API...")
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": settings.SEED_ADMIN_EMAIL, "password": settings.SEED_ADMIN_PASSWORD}
    )
    if login_resp.status_code != 200:
        print(f"[-] Error en autenticación: {login_resp.status_code} - {login_resp.text}")
        return

    access_token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    print(f"[+] Autenticado exitosamente como: {login_resp.json()['user']['nombre_completo']}")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "datos_carga")

    archivos = [
        ("productos_fasretail.csv", "productos", True, "Catálogo limpio"),
        ("inventario_fasretail.csv", "inventario", True, "Inventario inicial limpio"),
        ("ventas_fasretail.csv", "ventas", True, "Ventas históricas limpias (2 años)"),
        ("ventas_defectuoso_advertencia.csv", "ventas", False, "Archivo con observaciones (>98% calidad, SIN procesar válidos)"),
        ("ventas_defectuoso_rechazado.csv", "ventas", False, "Archivo rechazado (<98% calidad, SIN procesar válidos)")
    ]

    print("\n" + "=" * 85)
    print(f"{'ARCHIVO':<36} | {'ESTADO BD':<16} | {'EN PANTALLA':<24} | {'CALIDAD':<7} | {'PROCESAR VÁLIDOS'}")
    print("=" * 85)

    for filename, tipo_carga, procesar_validos_flag, desc in archivos:
        filepath = os.path.join(data_dir, filename)
        with open(filepath, "rb") as f:
            file_bytes = f.read()

        upload_resp = client.post(
            "/api/v1/datos/upload",
            headers=headers,
            data={"tipo_carga": tipo_carga},
            files={"file": (filename, file_bytes, "text/csv")}
        )
        data = upload_resp.json()
        id_carga = data["id_carga"]
        estado_bd = data["estado"]
        estado_disp = data["estado_display"]
        calidad = data["porcentaje_calidad"]

        if procesar_validos_flag and data["apto_para_procesar"]:
            proc_resp = client.post(
                f"/api/v1/datos/cargas/{id_carga}/procesar-validos",
                headers=headers
            )
            p_data = proc_resp.json()
            estado_bd = p_data["estado"]
            estado_disp = p_data.get("estado_display", estado_bd)
            flag_text = f"SÍ ({p_data['registros_afectados']} reg.)"
        else:
            flag_text = "NO (Sólo subida / Visibilidad)"

        print(f"{filename:<36} | {estado_bd:<16} | {estado_disp:<24} | {calidad:>5.1f}% | {flag_text}")

    print("\n" + "=" * 85)
    print("REPORTE DE CALIDAD GLOBAL PONDERADO (GET /api/v1/datos/calidad)")
    print("=" * 85)
    q_resp = client.get("/api/v1/datos/calidad", headers=headers)
    q_data = q_resp.json()
    print(f"Calidad Promedio Ponderada: {q_data['calidad_promedio_pct']}%")
    print(f"Umbral Mínimo Requerido:   {q_data['umbral_minimo_pct']}%")
    print(f"Total Cargas Evaluadas:   {q_data['total_cargas']}")
    print(f"Cargas Conformes (>=98%):  {q_data['cargas_conformes']}")
    print(f"Cargas No Conformes (<98%):{q_data['cargas_no_conformes']}")
    print(f"Total Registros Procesados:{q_data['total_registros_procesados']}")
    print(f"Total Registros Rechazados:{q_data['total_registros_rechazados']}")
    print("Desglose Total de Incidencias:")
    for k, v in q_data["desglose_errores"].items():
        print(f"  - {k.capitalize()}: {v}")

    print("\n" + "=" * 85)
    print("CONTEO FINAL DE FILAS POR TABLA EN POSTGRESQL (retailpro_db)")
    print("=" * 85)
    conn = psycopg.connect("host=localhost port=5432 user=retailpro_app password=retailpro_app_pwd_2026 dbname=retailpro_db")
    tablas = [
        "usuario",
        "auditoria",
        "umbral_configuracion",
        "carga_datos",
        "producto",
        "venta_historica",
        "modelo_version",
        "pronostico",
        "alerta"
    ]
    with conn.cursor() as cur:
        for t in tablas:
            cur.execute(f"SELECT COUNT(*) FROM {t};")
            count = cur.fetchone()[0]
            print(f"  - {t:<22}: {count:>6} filas")
    conn.close()


if __name__ == "__main__":
    ejecutar_pipeline()
