import psycopg

for dbname in ["retailpro_db", "retailpro_test"]:
    conn = psycopg.connect(f"host=localhost port=5432 user=retailpro_app password=retailpro_app_pwd_2026 dbname={dbname}")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE' 
            ORDER BY table_name;
        """)
        tables = [r[0] for r in cur.fetchall()]
        print(f"Tablas creadas en {dbname} ({len(tables)} tablas):")
        for t in tables:
            print(f"  - {t}")
    conn.close()
