import sys
import os
import psycopg
from psycopg import sql

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings


def setup_database():
    host = settings.POSTGRES_HOST
    port = settings.POSTGRES_PORT
    user = settings.POSTGRES_SUPERUSER
    password = settings.POSTGRES_PASSWORD
    target_db = settings.POSTGRES_DB

    print(f"[*] Conectando a PostgreSQL como superusuario '{user}' en {host}:{port}...")
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname="postgres",
            autocommit=True
        )
    except Exception as e:
        print(f"[!] Error al conectar a PostgreSQL: {e}")
        print("[!] Por favor verifica que POSTGRES_PASSWORD en .env coincida con la de tu usuario postgres local.")
        return False

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        if not cur.fetchone():
            print(f"[*] Creando base de datos '{target_db}'...")
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
            print(f"[+] Base de datos '{target_db}' creada exitosamente.")
        else:
            print(f"[*] La base de datos '{target_db}' ya existe.")

        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'retailpro_app'")
        if not cur.fetchone():
            print("[*] Creando usuario 'retailpro_app'...")
            cur.execute("CREATE ROLE retailpro_app WITH LOGIN PASSWORD 'retailpro_app_pwd_2026'")
            print("[+] Usuario 'retailpro_app' creado.")
        else:
            print("[*] Usuario 'retailpro_app' ya existe.")

        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'powerbi_reader'")
        if not cur.fetchone():
            print("[*] Creando usuario 'powerbi_reader'...")
            cur.execute("CREATE ROLE powerbi_reader WITH LOGIN PASSWORD 'powerbi_reader_pwd_2026'")
            print("[+] Usuario 'powerbi_reader' creado.")
        else:
            print("[*] Usuario 'powerbi_reader' ya existe.")

        cur.execute(sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO retailpro_app").format(sql.Identifier(target_db)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO powerbi_reader").format(sql.Identifier(target_db)))

    conn.close()

    try:
        conn_target = psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=target_db,
            autocommit=True
        )
        with conn_target.cursor() as cur:
            cur.execute("GRANT USAGE, CREATE ON SCHEMA public TO retailpro_app;")
            cur.execute("GRANT USAGE ON SCHEMA public TO powerbi_reader;")
            cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO retailpro_app;")
            cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO retailpro_app;")
            cur.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO powerbi_reader;")
        conn_target.close()
        print("[+] Permisos y esquemas configurados correctamente.")
        return True
    except Exception as e:
        print(f"[!] Error configurando permisos en {target_db}: {e}")
        return False


if __name__ == "__main__":
    success = setup_database()
    if not success:
        sys.exit(1)
