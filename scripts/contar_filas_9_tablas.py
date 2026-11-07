import os
import sys

sys.path.insert(0, os.getcwd())

from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
tables = [
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

print("=" * 45)
print("  CONTEO DE FILAS - 9 TABLAS RELACIONALES")
print("=" * 45)
total_filas = 0
for t in tables:
    cnt = db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
    total_filas += cnt
    print(f"  {t:25}: {cnt:>6} filas")
print("-" * 45)
print(f"  {'TOTAL':25}: {total_filas:>6} filas")
print("=" * 45)
db.close()
