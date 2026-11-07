import psycopg

conn_pbi = psycopg.connect("host=localhost port=5432 user=powerbi_reader password=powerbi_reader_pwd_2026 dbname=retailpro_db")
with conn_pbi.cursor() as cur:
    cur.execute("""
        SELECT table_name 
        FROM information_schema.views 
        WHERE table_schema = 'public' 
        ORDER BY table_name;
    """)
    views = [r[0] for r in cur.fetchall()]
    print(f"[+] Vistas detectadas en el esquema public ({len(views)} vistas):")
    for v in views:
        print(f"  - {v}")

    for v in views:
        cur.execute(f"SELECT COUNT(*) FROM {v};")
        count = cur.fetchone()[0]
        print(f"  [OK] SELECT en {v}: {count} filas")

    print("[*] Probando INSERT con usuario 'powerbi_reader' en tabla 'producto'...")
    try:
        cur.execute("INSERT INTO producto (sku, nombre, categoria) VALUES ('TEST-001', 'Test', 'Pruebas');")
        conn_pbi.commit()
        print("[-] ERROR: INSERT no debió ser permitido!")
    except Exception as e:
        conn_pbi.rollback()
        print(f"  [OK] INSERT denegado con éxito en tabla: {type(e).__name__} - {e}")

    print("[*] Probando INSERT con usuario 'powerbi_reader' en vista 'vw_ventas_diarias'...")
    try:
        cur.execute("INSERT INTO vw_ventas_diarias (fecha, total_cantidad_vendida) VALUES ('2025-01-01', 10);")
        conn_pbi.commit()
        print("[-] ERROR: INSERT en vista no debió ser permitido!")
    except Exception as e:
        conn_pbi.rollback()
        print(f"  [OK] INSERT denegado con éxito en vista: {type(e).__name__} - {e}")

conn_pbi.close()
