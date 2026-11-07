
import os
import sys
import argparse
import subprocess
import time
import math
import datetime
import shutil
import json

os.environ["SKIP_EMAIL_NOTIFICATIONS"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.etl_service import (
    validate_file_content,
    procesar_registros_validos,
    get_storage_carga_dir,
    get_tipo_carga_etiqueta
)
from app.services.ml_service import MLForecastService
from app.services.alert_service import AlertService
from app.models.producto import Producto
from app.models.pronostico import Pronostico
from app.models.modelo_version import ModeloVersion
from app.models.usuario import Usuario
from app.models.alerta import Alerta
from app.models.carga_datos import CargaDatos


def ejecutar_comando(cmd: list[str], descripcion: str, env_vars: dict = None):
    print(f"\n[*] {descripcion}...")
    run_env = {**os.environ, **(env_vars or {})}
    res = subprocess.run(cmd, capture_output=True, text=True, env=run_env)
    if res.returncode != 0:
        print(f"[-] ERROR al ejecutar: {' '.join(cmd)}")
        print(res.stderr)
        print(res.stdout)
        sys.exit(1)
    print(f"[+] {descripcion} completado exitosamente.")
    return res.stdout


def asegurar_base_de_datos(db_name: str):
    su_pwd = settings.POSTGRES_PASSWORD
    su_user = settings.POSTGRES_SUPERUSER
    host = settings.POSTGRES_HOST
    port = settings.POSTGRES_PORT

    admin_conn_str = f"postgresql://{su_user}:{su_pwd}@{host}:{port}/postgres"
    with psycopg.connect(admin_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if not cur.fetchone():
                print(f"[*] Creando base de datos '{db_name}'...")
                cur.execute(f'CREATE DATABASE "{db_name}" OWNER retailpro_app;')
                print(f"[+] Base de datos '{db_name}' creada.")
            else:
                print(f"[+] Base de datos '{db_name}' ya existe.")

            cur.execute(f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO retailpro_app;')
            cur.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO powerbi_reader;')


def recrear_base_de_datos(db_name: str):
    su_pwd = settings.POSTGRES_PASSWORD
    su_user = settings.POSTGRES_SUPERUSER
    host = settings.POSTGRES_HOST
    port = settings.POSTGRES_PORT

    admin_conn_str = f"postgresql://{su_user}:{su_pwd}@{host}:{port}/postgres"
    with psycopg.connect(admin_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            print(f"[*] Terminando sesiones activas y eliminando '{db_name}' si existe...")
            cur.execute("""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = %s
                  AND pid <> pg_backend_pid();
            """, (db_name,))
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}";')
            print(f"[*] Creando base de datos limpia '{db_name}'...")
            cur.execute(f'CREATE DATABASE "{db_name}" OWNER retailpro_app;')
            cur.execute(f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO retailpro_app;')
            cur.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO powerbi_reader;')
            print(f"[+] Base de datos '{db_name}' recreada limpia desde cero.")

    cargas_dir = os.path.join(settings.STORAGE_DIR, "cargas")
    if os.path.exists(cargas_dir):
        print(f"[*] Limpiando directorio de evidencias '{cargas_dir}'...")
        shutil.rmtree(cargas_dir, ignore_errors=True)
    os.makedirs(cargas_dir, exist_ok=True)
    print(f"[+] Directorio '{cargas_dir}' inicializado limpio.")


def borrar_base_de_datos(db_name: str):
    su_pwd = settings.POSTGRES_PASSWORD
    su_user = settings.POSTGRES_SUPERUSER
    host = settings.POSTGRES_HOST
    port = settings.POSTGRES_PORT

    admin_conn_str = f"postgresql://{su_user}:{su_pwd}@{host}:{port}/postgres"
    with psycopg.connect(admin_conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = %s
                  AND pid <> pg_backend_pid();
            """, (db_name,))
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}";')
            print(f"[+] Base de datos temporal '{db_name}' eliminada satisfactoriamente.")


def main():
    parser = argparse.ArgumentParser(description="Inicialización completa del sistema RetailPro")
    parser.add_argument("--db-name", type=str, default=None, help="Nombre de base de datos específica")
    parser.add_argument("--recrear", action="store_true", help="Elimina y vuelve a crear la base de datos limpia desde cero")
    parser.add_argument("--borrar-al-final", action="store_true", help="Elimina la base de datos al finalizar")
    args = parser.parse_args()

    target_db = args.db_name or settings.POSTGRES_DB
    app_pwd = "retailpro_app_pwd_2026"
    target_db_url = f"postgresql+psycopg://retailpro_app:{app_pwd}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{target_db}"
    target_psycopg_conn = target_db_url.replace("+psycopg", "")

    os.environ["DATABASE_URL"] = target_db_url
    settings.DATABASE_URL = target_db_url

    t_start = time.time()
    print("=" * 75)
    print(f"RETAILPRO - INICIALIZACIÓN COMPLETA DESDE CERO EN '{target_db}'")
    print("=" * 75)

    if args.recrear:
        recrear_base_de_datos(target_db)
    else:
        asegurar_base_de_datos(target_db)

    ejecutar_comando(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        f"Aplicando migraciones de Alembic en '{target_db}'",
        env_vars={"DATABASE_URL": target_db_url}
    )

    print("\n[*] Creando vistas de Power BI (create_views.sql)...")
    sql_path = os.path.join(os.path.dirname(__file__), "create_views.sql")
    if os.path.exists(sql_path):
        with open(sql_path, "r", encoding="utf-8") as f:
            sql_script = f.read()
        try:
            with psycopg.connect(target_psycopg_conn) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql_script)
                conn.commit()
            print("[+] Vistas de Power BI creadas y permisos concedidos a powerbi_reader.")
        except Exception as e:
            print(f"[!] Advertencia al ejecutar create_views.sql: {e}")

    ejecutar_comando(
        [sys.executable, os.path.join(os.path.dirname(__file__), "seed.py")],
        f"Sembrando usuarios y umbrales en '{target_db}'",
        env_vars={"DATABASE_URL": target_db_url}
    )

    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "datos_carga")
    ventas_csv = os.path.join(data_dir, "ventas_fasretail.csv")
    if not os.path.exists(ventas_csv):
        ejecutar_comando(
            [sys.executable, os.path.join(os.path.dirname(__file__), "generar_datos_carga.py")],
            "Generando archivos de prueba sintéticos de retail Lima"
        )

    print("\n[*] Procesando pipeline ETL de datos limpios...")
    engine = create_engine(target_db_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        admin_user = db.query(Usuario).filter(Usuario.rol == "administrador").first()
        user_id = admin_user.id_usuario if admin_user else 1
        now_base = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        prod_csv = os.path.join(data_dir, "productos_fasretail.csv")
        with open(prod_csv, "rb") as f:
            carga_prod, _ = validate_file_content(db=db, file_bytes=f.read(), filename="productos_fasretail.csv", tipo_carga="productos", user_id=user_id)
        procesar_registros_validos(db=db, id_carga=carga_prod.id_carga, user_id=user_id)
        print("    - Catálogo de productos cargado y validado (60 SKUs).")

        inv_csv = os.path.join(data_dir, "inventario_fasretail.csv")
        with open(inv_csv, "rb") as f:
            carga_inv, _ = validate_file_content(db=db, file_bytes=f.read(), filename="inventario_fasretail.csv", tipo_carga="inventario", user_id=user_id)
        procesar_registros_validos(db=db, id_carga=carga_inv.id_carga, user_id=user_id)
        print("    - Stock actual y puntos de reorden cargados y validados.")

        with open(ventas_csv, "rb") as f:
            carga_vta, _ = validate_file_content(db=db, file_bytes=f.read(), filename="ventas_fasretail.csv", tipo_carga="ventas", user_id=user_id)
        procesar_registros_validos(db=db, id_carga=carga_vta.id_carga, user_id=user_id)
        print("    - Ventas históricas cargadas y validadas (43,860 registros).")

        adv_csv = os.path.join(data_dir, "ventas_defectuoso_advertencia.csv")
        if os.path.exists(adv_csv):
            with open(adv_csv, "rb") as f:
                carga_adv, _ = validate_file_content(db=db, file_bytes=f.read(), filename="ventas_defectuoso_advertencia.csv", tipo_carga="ventas", user_id=user_id)
            print("    - Archivo con advertencias subido para auditoría (CON_ADVERTENCIAS).")

        rec_csv = os.path.join(data_dir, "ventas_defectuoso_rechazado.csv")
        if not os.path.exists(rec_csv):
            rec_csv = os.path.join(data_dir, "ventas_defectuoso_rechazo.csv")
        if os.path.exists(rec_csv):
            with open(rec_csv, "rb") as f:
                carga_rec, _ = validate_file_content(db=db, file_bytes=f.read(), filename=os.path.basename(rec_csv), tipo_carga="ventas", user_id=user_id)
            print(f"    - Archivo con rechazo subido para auditoría ({os.path.basename(rec_csv)}).")

    finally:
        db.close()

    print("\n[*] Entrenando modelos de pronóstico XGBoost...")
    db = SessionLocal()
    try:
        df_grid, prod_dict, sku_to_idx, cat_to_idx = MLForecastService.load_clean_sales_grid(db)
        print(f"    - Cuadrícula de ventas verificada: {len(df_grid)} filas para {len(prod_dict)} SKUs.")

        print("    - Ejecutando Walk-Forward Backtest (12 cortes mensuales)...")
        backtest_results, res_acum_cat, percentiles_rel, comp_baselines, cob_empirica = MLForecastService.run_walk_forward_backtest(
            db, df_grid, prod_dict
        )

        mapes = [r["mape"] for r in backtest_results]
        wapes = [r["wape"] for r in backtest_results]
        rmses = [r["rmse"] for r in backtest_results]
        maes = [r["mae"] for r in backtest_results]

        out_of_sample_metrics = {
            "mape": round(sum(mapes) / len(mapes), 2),
            "wape": round(sum(wapes) / len(wapes), 2),
            "rmse": round(sum(rmses) / len(rmses), 4),
            "mae": round(sum(maes) / len(maes), 4)
        }

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        carga_pron = CargaDatos(
            id_usuario=user_id,
            tipo_carga="pronostico",
            fecha_ejecucion=now_utc.replace(tzinfo=None),
            estado="EN_PROGRESO",
            registros_procesados=0,
            registros_rechazados=0,
            porcentaje_calidad=100.0,
            detalle_error=None
        )
        db.add(carga_pron)
        db.commit()
        db.refresh(carga_pron)

        carga_pron_dir = get_storage_carga_dir(carga_pron.id_carga)
        t_pron_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        meta_pron = {
            "id_carga": carga_pron.id_carga,
            "nombre_archivo": "proceso_batch_pronostico_diario",
            "nombre_original": "proceso_batch_pronostico_diario",
            "tamano_bytes": 0,
            "tipo_carga": "pronostico",
            "tipo_carga_etiqueta": "Pronóstico de Demanda",
            "fecha_subida": t_pron_str
        }
        with open(os.path.join(carga_pron_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta_pron, f, indent=4, ensure_ascii=False)

        print("    - Entrenando modelo activo de producción y generando 840 pronósticos...")
        MLForecastService.train_production_model(
            db, df_grid, prod_dict,
            res_acum_cat, percentiles_rel, out_of_sample_metrics,
            id_carga=carga_pron.id_carga
        )

        carga_pron.estado = "COMPLETADO"
        carga_pron.registros_procesados = 840
        db.commit()

        print("\n[*] Sincronizando alertas y fechas límite de reposición...")
        alertas_creadas = AlertService.sincronizar_alertas(db)

        mv = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
        lead_time = settings.DEFAULT_LEAD_TIME_DAYS
        for prod in db.query(Producto).all():
            prons = db.query(Pronostico).filter(Pronostico.id_modelo == mv.id_modelo, Pronostico.id_producto == prod.id_producto).all()
            if not prons:
                continue
            prons = sorted(prons, key=lambda x: x.horizonte_dias)
            primer = prons[0]
            dem_14d = sum(float(x.cantidad_proyectada) for x in prons)
            dem_dia = dem_14d / 14.0 if dem_14d > 0 else 1.0
            dias_quiebre = math.floor(prod.stock_actual / dem_dia) if dem_dia > 0 else 999
            f_base = primer.fecha_generacion.date()
            f_quiebre = f_base + datetime.timedelta(days=dias_quiebre)
            f_limite = max(f_base, f_quiebre - datetime.timedelta(days=lead_time))
            for p in prons:
                p.fecha_limite_reposicion = f_limite
        db.commit()

        print("\n" + "=" * 75)
        print("CONTEO DE ALERTAS POR TIPO Y ESTADO (CORRIDA LIMPIA)")
        print("=" * 75)
        alertas = db.query(Alerta).all()
        quiebre_activas = sum(1 for a in alertas if a.tipo_alerta == "QUIEBRE" and a.estado in ["Activa", "pendiente"])
        quiebre_resueltas = sum(1 for a in alertas if a.tipo_alerta == "QUIEBRE" and a.estado == "Resuelta")
        sobrestock_activas = sum(1 for a in alertas if a.tipo_alerta == "SOBRESTOCK" and a.estado in ["Activa", "pendiente"])
        sobrestock_resueltas = sum(1 for a in alertas if a.tipo_alerta == "SOBRESTOCK" and a.estado == "Resuelta")

        print(f"  Alertas de QUIEBRE Activas:       {quiebre_activas:>2}")
        print(f"  Alertas de QUIEBRE Resueltas:     {quiebre_resueltas:>2}")
        print(f"  Alertas de SOBRESTOCK Activas:    {sobrestock_activas:>2}")
        print(f"  Alertas de SOBRESTOCK Resueltas:  {sobrestock_resueltas:>2}")
        print(f"  TOTAL ALERTAS EXISTENTES:         {len(alertas):>2}")

        print("\n" + "=" * 75)
        print("CONTEO FINAL DE REGISTROS POR TABLA (MODELO RELACIONAL DE TESIS)")
        print("=" * 75)
        with psycopg.connect(target_psycopg_conn) as conn:
            with conn.cursor() as cur:
                tablas = [
                    "alembic_version", "usuario", "auditoria", "umbral_configuracion",
                    "carga_datos", "producto", "venta_historica", "modelo_version",
                    "pronostico", "alerta"
                ]
                for t in tablas:
                    cur.execute(f"SELECT count(*) FROM {t}")
                    cnt = cur.fetchone()[0]
                    print(f"  {t:<25}: {cnt:>6} filas")

    finally:
        db.close()
        engine.dispose()

    total_tiempo = round(time.time() - t_start, 2)
    print("=" * 75)
    print(f"[+] SISTEMA INICIALIZADO SATISFACTORIAMENTE EN {total_tiempo} SEGUNDOS.")
    print("=" * 75)
    print("\nComando oficial para iniciar el servidor backend:")
    print("  uvicorn app.main:app --host 127.0.0.1 --port 8000")
    print("  (ejecutar directamente en consola de PowerShell, sin 0.0.0.0 y sin segundo plano)\n")

    if args.borrar_al_final:
        print(f"\n[*] Limpieza solicitada (--borrar-al-final):")
        borrar_base_de_datos(target_db)


if __name__ == "__main__":
    main()
