import sys
import os
import json
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import SessionLocal, engine, Base
from app.core.security import get_password_hash
from app.models.usuario import Usuario
from app.models.umbral_configuracion import UmbralConfiguracion


def run_seed():
    print("[*] Verificando esquemas y tablas...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        users_data = [
            {
                "correo": settings.SEED_ADMIN_EMAIL,
                "nombre_completo": "Administrador del Sistema",
                "password": settings.SEED_ADMIN_PASSWORD,
                "rol": "administrador",
                "estado": True
            },
            {
                "correo": settings.SEED_ANALYST_EMAIL,
                "nombre_completo": "Carlos López",
                "password": settings.SEED_ANALYST_PASSWORD,
                "rol": "analista",
                "estado": True
            },
            {
                "correo": settings.SEED_LOGISTICS_EMAIL,
                "nombre_completo": "Roberto Sánchez",
                "password": settings.SEED_LOGISTICS_PASSWORD,
                "rol": "jefe_logistica",
                "estado": True
            }
        ]

        admin_user = None
        for u_data in users_data:
            existing_user = db.query(Usuario).filter(Usuario.correo == u_data["correo"]).first()
            if not existing_user:
                new_user = Usuario(
                    correo=u_data["correo"],
                    nombre_completo=u_data["nombre_completo"],
                    clave_hash=get_password_hash(u_data["password"]),
                    rol=u_data["rol"],
                    estado=u_data["estado"]
                )
                db.add(new_user)
                db.flush()
                print(f"[+] Usuario creado desde .env: {new_user.nombre_completo} ({new_user.correo}) con rol '{new_user.rol}'")
                if u_data["rol"] == "administrador":
                    admin_user = new_user
            else:
                existing_user.clave_hash = get_password_hash(u_data["password"])
                existing_user.rol = u_data["rol"]
                existing_user.nombre_completo = u_data["nombre_completo"]
                db.flush()
                print(f"[*] Usuario actualizado desde .env: {existing_user.nombre_completo} ({existing_user.correo}) con rol '{existing_user.rol}'")
                if u_data["rol"] == "administrador":
                    admin_user = existing_user

        admin_id = admin_user.id_usuario if admin_user else None
        thresholds_data = [
            {"tipo_umbral": "quiebre_prob_min", "valor": settings.DEFAULT_STOCKOUT_MIN_PROBABILITY},
            {"tipo_umbral": "quiebre_dias_cobertura", "valor": float(settings.DEFAULT_STOCKOUT_MIN_COVERAGE_DAYS)},
            {"tipo_umbral": "sobrestock_pct", "valor": settings.DEFAULT_OVERSTOCK_MAX_DEMAND_PCT},
            {"tipo_umbral": "sobrestock_dias", "valor": float(settings.DEFAULT_OVERSTOCK_MAX_COVERAGE_DAYS)},
            {"tipo_umbral": "calidad_min", "valor": settings.DEFAULT_DATA_QUALITY_THRESHOLD},
            {"tipo_umbral": "mape_max", "valor": 15.00},
            {"tipo_umbral": "nivel_servicio_ref", "valor": 95.00},
        ]

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        for t_data in thresholds_data:
            existing_t = db.query(UmbralConfiguracion).filter(
                UmbralConfiguracion.tipo_umbral == t_data["tipo_umbral"]
            ).first()
            if not existing_t:
                new_t = UmbralConfiguracion(
                    id_usuario=admin_id,
                    tipo_umbral=t_data["tipo_umbral"],
                    valor=t_data["valor"],
                    fecha_actualizacion=now_utc
                )
                db.add(new_t)
                print(f"[+] Umbral configurado: {t_data['tipo_umbral']} = {t_data['valor']}")
            else:
                existing_t.valor = t_data["valor"]
                existing_t.fecha_actualizacion = now_utc

        db.commit()
        print("[+] Datos de base de datos sembrados exitosamente.")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        storage_base = settings.STORAGE_DIR if os.path.isabs(settings.STORAGE_DIR) else os.path.join(base_dir, settings.STORAGE_DIR)
        config_dir = os.path.join(storage_base, "config")
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(os.path.join(storage_base, "cargas"), exist_ok=True)
        os.makedirs(os.path.join(storage_base, "entrada"), exist_ok=True)
        os.makedirs(os.path.join(storage_base, "reportes"), exist_ok=True)
        os.makedirs(os.path.join(storage_base, "modelos"), exist_ok=True)

        procesos_json_path = os.path.join(config_dir, "procesos.json")
        if not os.path.exists(procesos_json_path):
            procesos_cfg = {
                "etl_frecuencia": "diario",
                "etl_hora": "02:00",
                "pronostico_frecuencia": "diario",
                "pronostico_hora": "04:00",
                "reentrenamiento_frecuencia": "semanal",
                "reentrenamiento_dia": "domingo",
                "reentrenamiento_hora": "01:00",
                "alertas_notificacion_email": "alertas@fasretail.com",
                "notificar_quiebre": True,
                "notificar_sobrestock": True,
                "notificar_calidad_baja": True
            }
            with open(procesos_json_path, "w", encoding="utf-8") as f:
                json.dump(procesos_cfg, f, indent=4, ensure_ascii=False)
            print(f"[+] Configuración de procesos creada en {procesos_json_path}")
            print("\nComando oficial para iniciar el servidor backend:")
            print("  uvicorn app.main:app --host 127.0.0.1 --port 8000 (sin 0.0.0.0)\n")

    except Exception as e:
        db.rollback()
        print(f"[-] Error durante el seed: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
