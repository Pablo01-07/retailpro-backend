import sys
import os
import psycopg
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.main import app

client = TestClient(app)


def main():
    print("=" * 80)
    print("EJECUCIÓN DEL PIPELINE DE CARGA DE DATOS (API RETAILPRO)")
    print("=" * 80)

    print("\n[*] 1. Autenticación contra la API...")
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

    archivos_pipeline = [
        ("productos_fasretail.csv", "productos", True),
        ("inventario_fasretail.csv", "inventario", True),
        ("ventas_fasretail.csv", "ventas", True),
        ("ventas_defectuoso_advertencia.csv", "ventas", False),
        ("ventas_defectuoso_rechazado.csv", "ventas", False),
    ]

    resumenes_carga = []

    for filename, tipo_carga, procesar_validos_flag in archivos_pipeline:
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath):
            print(f"[!] Archivo no encontrado: {filepath}")
            continue

        print(f"\n---> Subiendo archivo: {filename} (Tipo: {tipo_carga})...")
        with open(filepath, "rb") as f:
            file_bytes = f.read()

        upload_resp = client.post(
            "/api/v1/datos/upload",
            headers=headers,
            data={"tipo_carga": tipo_carga},
            files={"file": (filename, file_bytes, "text/csv")}
        )

        if upload_resp.status_code != 200:
            print(f"[-] Error en upload de {filename}: {upload_resp.status_code} - {upload_resp.text}")
            continue

        upload_data = upload_resp.json()
        id_carga = upload_data["id_carga"]
        estado = upload_data["estado"]
        procesados = upload_data["registros_procesados"]
        validos = upload_data["registros_validos"]
        rechazados = upload_data["registros_rechazados"]
        calidad = upload_data["porcentaje_calidad"]
        desglose = upload_data["resumen_errores"]

        estado_display = upload_data.get("estado_display", estado)
        print(f"  [Upload] ID Carga: {id_carga}")
        print(f"  [Calidad] Estado en BD: {estado} | En Interfaz: '{estado_display}' | Calidad: {calidad}% (Umbral: {upload_data['umbral_calidad']}%)")
        print(f"  [Métricas] Procesados: {procesados} | Válidos: {validos} | Rechazados: {rechazados}")
        print(f"  [Desglose Errores] Duplicados: {desglose.get('duplicados', 0)} | Nulos: {desglose.get('nulos', 0)} | Formato: {desglose.get('formato', 0)} | SKU Inexistente: {desglose.get('sku_inexistente', 0)}")

        estado_final = estado
        if procesar_validos_flag and upload_data["apto_para_procesar"]:
            print(f"  [*] Procesando registros válidos en base de datos...")
            proc_resp = client.post(
                f"/api/v1/datos/cargas/{id_carga}/procesar-validos",
                headers=headers
            )
            if proc_resp.status_code == 200:
                proc_data = proc_resp.json()
                estado_final = proc_data["estado"]
                print(f"  [+] Ingesta completada: {proc_data['registros_afectados']} registros consolidados. Estado: {estado_final}")
            else:
                print(f"  [-] Error en ingesta: {proc_resp.text}")

        resumenes_carga.append({
            "archivo": filename,
            "id_carga": id_carga,
            "tipo": tipo_carga,
            "procesados": procesados,
            "validos": validos,
            "rechazados": rechazados,
            "duplicados": desglose.get("duplicados", 0),
            "calidad": calidad,
            "estado_final": estado_final
        })

    print("\n" + "=" * 80)
    print("REPORTE DE CALIDAD DE DATOS GLOBAL (GET /api/v1/datos/calidad)")
    print("=" * 80)
    calidad_resp = client.get("/api/v1/datos/calidad", headers=headers)
    if calidad_resp.status_code == 200:
        q_data = calidad_resp.json()
        print(f"Calidad Promedio Histórica: {q_data['calidad_promedio_pct']}%")
        print(f"Umbral Mínimo Requerido:    {q_data['umbral_minimo_pct']}%")
        print(f"Total Cargas Evaluadas:    {q_data['total_cargas']}")
        print(f"Cargas Conformes (>=98%):   {q_data['cargas_conformes']}")
        print(f"Cargas No Conformes (<98%): {q_data['cargas_no_conformes']}")
        print(f"Total Registros Procesados: {q_data['total_registros_procesados']}")
        print(f"Total Registros Rechazados: {q_data['total_registros_rechazados']}")
        print("Desglose Total de Incidencias:")
        for k, v in q_data["desglose_errores"].items():
            print(f"  - {k.capitalize()}: {v}")

    print("\n" + "=" * 80)
    print("CONTEO DE FILAS POR TABLA EN POSTGRESQL (retailpro_db)")
    print("=" * 80)
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
    main()
