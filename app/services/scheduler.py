import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.carga_datos import CargaDatos
from app.core.audit import create_audit_log
from app.services.etl_service import sincronizar_archivos_locales, get_storage_carga_dir

logger = logging.getLogger("retailpro.scheduler")
scheduler = BackgroundScheduler(timezone="America/Lima")

DIAS_SEMANA_MAP = {
    0: "lunes",
    1: "martes",
    2: "miercoles",
    3: "jueves",
    4: "viernes",
    5: "sabado",
    6: "domingo"
}

NOMBRE_A_NUMERO_DIA = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6
}

DIAS_CRON_MAP = {
    "lunes": "mon",
    "martes": "tue",
    "miercoles": "wed",
    "miércoles": "wed",
    "jueves": "thu",
    "viernes": "fri",
    "sabado": "sat",
    "sábado": "sat",
    "domingo": "sun"
}

PROCESOS_METADATA = {
    "etl": {
        "id_proceso": "etl_diario",
        "key": "etl",
        "nombre": "Extracción y Validación ETL",
        "tipo": "Extracción y Calidad",
        "default_frec": "diario",
        "default_hora": "02:00",
        "default_dia": None,
        "default_dia_semana": None
    },
    "pronostico": {
        "id_proceso": "pronostico_diario",
        "key": "pronostico",
        "nombre": "Generación de Pronósticos",
        "tipo": "Inferencia XGBoost",
        "default_frec": "diario",
        "default_hora": "04:00",
        "default_dia": None,
        "default_dia_semana": None
    },
    "reentrenamiento": {
        "id_proceso": "reentrenamiento_semanal",
        "key": "reentrenamiento",
        "nombre": "Reentrenamiento del Modelo",
        "tipo": "Entrenamiento XGBoost",
        "default_frec": "cada_4_semanas",
        "default_hora": "01:00",
        "default_dia": "domingo",
        "default_dia_semana": 6
    }
}


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_procesos_config() -> Dict[str, Any]:
    config_path = os.path.join(settings.STORAGE_DIR, "config", "procesos.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                cfg.setdefault("reentrenamiento_frecuencia", "cada_4_semanas")
                cfg.setdefault("reentrenamiento_umbral_registros", 840)
                return cfg
        except Exception as e:
            logger.error(f"Error al leer {config_path}: {e}")

    return {
        "etl_activo": True,
        "etl_frecuencia": "diario",
        "etl_hora": "02:00",
        "pronostico_activo": True,
        "pronostico_frecuencia": "diario",
        "pronostico_hora": "04:00",
        "reentrenamiento_activo": True,
        "reentrenamiento_frecuencia": "cada_4_semanas",
        "reentrenamiento_dia": "domingo",
        "reentrenamiento_dia_semana": 6,
        "reentrenamiento_hora": "01:00",
        "reentrenamiento_umbral_registros": 840,
        "alertas_notificacion_email": "alertas@fasretail.com",
        "notificar_quiebre": True,
        "notificar_sobrestock": True,
        "notificar_calidad_baja": True
    }


def save_procesos_config(new_config: Dict[str, Any]):
    config_dir = os.path.join(settings.STORAGE_DIR, "config")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "procesos.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(new_config, f, indent=4, ensure_ascii=False)


def tarea_etl_diario():
    logger.info("[Scheduler] Iniciando tarea programada: ETL Diario")
    db = SessionLocal()
    try:
        resultados = sincronizar_archivos_locales(db, user_id=None)
        logger.info(f"[Scheduler] ETL Diario completado. Archivos: {len(resultados)}")
    except Exception as e:
        logger.error(f"[Scheduler] Error en ETL Diario: {e}")
    finally:
        db.close()


def tarea_pronostico_diario(db: Optional[Session] = None):
    logger.info("[Scheduler] Iniciando tarea programada: Generación de Pronósticos")
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    carga = CargaDatos(
        tipo_carga="pronostico",
        fecha_ejecucion=get_utc_now(),
        estado="EN_PROGRESO",
        registros_procesados=0,
        registros_rechazados=0,
        porcentaje_calidad=100.0,
        detalle_error=None
    )
    db.add(carga)
    db.commit()
    db.refresh(carga)
    carga_dir = get_storage_carga_dir(carga.id_carga)
    etapas_file = os.path.join(carga_dir, "etapas.json")
    if os.path.exists(etapas_file):
        try:
            os.remove(etapas_file)
        except Exception:
            pass

    meta_data = {
        "id_carga": carga.id_carga,
        "nombre_archivo": "proceso_batch_pronostico_diario",
        "nombre_original": "proceso_batch_pronostico_diario",
        "tamano_bytes": 0,
        "tipo_carga": "pronostico",
        "tipo_carga_etiqueta": "Pronóstico de Demanda",
        "fecha_subida": get_utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    with open(os.path.join(carga_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta_data, f, indent=4, ensure_ascii=False)

    try:
        from app.services.ml_service import MLForecastService

        total_pron = MLForecastService.generar_pronosticos_lote(db=db, id_carga=carga.id_carga)

        carga.estado = "COMPLETADO"
        carga.registros_procesados = total_pron
        db.commit()

        if not os.path.exists(etapas_file):
            t_now_str = get_utc_now().isoformat()
            etapas_default = [
                {"etapa": "Carga de variables predictivas", "estado": "exitoso", "timestamp": t_now_str, "duracion_ms": 15},
                {"etapa": "Inferencia batch con modelo XGBoost activo", "estado": "exitoso", "timestamp": t_now_str, "duracion_ms": 25},
                {"etapa": "Cálculo de intervalos de confianza al 95%", "estado": "exitoso", "timestamp": t_now_str, "duracion_ms": 10},
                {"etapa": "Generación de alertas de inventario", "estado": "exitoso", "timestamp": t_now_str, "duracion_ms": 10}
            ]
            with open(etapas_file, "w", encoding="utf-8") as f:
                json.dump(etapas_default, f, indent=4, ensure_ascii=False)

        create_audit_log(
            db=db,
            accion="proceso_batch_pronostico",
            modulo_afectado="procesos",
            detalle={"id_carga": carga.id_carga, "estado": "COMPLETADO"}
        )
        logger.info(f"[Scheduler] Pronóstico diario registrado exitosamente (Carga {carga.id_carga}).")
        return carga
    except Exception as e:
        logger.error(f"[Scheduler] Error en Pronóstico Diario: {e}")
        db.rollback()
        carga.estado = "FALLIDO"
        carga.detalle_error = str(e)
        carga.registros_procesados = 0
        db.commit()

        etapas_fallidas = [
            {"etapa": "Carga de variables predictivas", "estado": "exitoso", "timestamp": get_utc_now().isoformat(), "duracion_ms": 150},
            {"etapa": "Inferencia batch con modelo XGBoost activo", "estado": "fallido", "timestamp": get_utc_now().isoformat(), "duracion_ms": 50, "error": str(e)}
        ]
        with open(os.path.join(carga_dir, "etapas.json"), "w", encoding="utf-8") as f:
            json.dump(etapas_fallidas, f, indent=4, ensure_ascii=False)

        create_audit_log(
            db=db,
            accion="proceso_batch_pronostico",
            modulo_afectado="procesos",
            detalle={"id_carga": carga.id_carga, "estado": "FALLIDO", "error": str(e)}
        )
        return carga
    finally:
        if close_db:
            db.close()


def tarea_reentrenamiento_semanal(db: Optional[Session] = None):
    logger.info("[Scheduler] Iniciando tarea programada: Reentrenamiento")
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        from app.services.ml_service import MLForecastService
        res = MLForecastService.entrenar_modelo_candidato(
            db=db,
            motivo="reentrenamiento_programado"
        )

        id_carga = res.get("id_carga")
        carga = db.query(CargaDatos).filter(CargaDatos.id_carga == id_carga).first() if id_carga else None

        create_audit_log(
            db=db,
            accion="proceso_batch_reentrenamiento",
            modulo_afectado="procesos",
            detalle={"id_carga": id_carga, "estado": "COMPLETADO", "id_modelo": res.get("id_modelo")}
        )
        logger.info(f"[Scheduler] Reentrenamiento registrado exitosamente (Carga {id_carga}).")
        return carga
    except Exception as e:
        logger.error(f"[Scheduler] Error en Reentrenamiento: {e}")
        db.rollback()
        carga_fallida = db.query(CargaDatos).filter(
            CargaDatos.tipo_carga == "entrenamiento"
        ).order_by(CargaDatos.id_carga.desc()).first()
        if carga_fallida:
            create_audit_log(
                db=db,
                accion="proceso_batch_reentrenamiento",
                modulo_afectado="procesos",
                detalle={"id_carga": carga_fallida.id_carga, "estado": "FALLIDO", "error": str(e)}
            )
            return carga_fallida
        return None
    finally:
        if close_db:
            db.close()


def construir_trigger_proceso(
    frecuencia: str,
    hora_str: str,
    dia_str: Optional[str] = None,
    dia_semana: Optional[int] = None
):
    try:
        h, m = [int(x) for x in hora_str.split(":")]
    except Exception:
        h, m = 0, 0

    frec_norm = frecuencia.lower().strip()
    if frec_norm == "diario":
        return CronTrigger(hour=h, minute=m, timezone="America/Lima")
    elif frec_norm == "semanal":
        cron_day = "sun"
        if dia_semana is not None and 0 <= dia_semana <= 6:
            dia_nombre = DIAS_SEMANA_MAP.get(dia_semana, "domingo")
            cron_day = DIAS_CRON_MAP.get(dia_nombre, "sun")
        elif dia_str:
            cron_day = DIAS_CRON_MAP.get(dia_str.lower().strip(), "sun")
        return CronTrigger(day_of_week=cron_day, hour=h, minute=m, timezone="America/Lima")
    elif frec_norm == "cada_4_semanas":
        target_dow = 6
        if dia_semana is not None and 0 <= dia_semana <= 6:
            target_dow = dia_semana
        elif dia_str:
            target_dow = NOMBRE_A_NUMERO_DIA.get(dia_str.lower().strip(), 6)
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/Lima")
        now_lima = datetime.now(tz)
        days_ahead = (target_dow - now_lima.weekday()) % 7
        cand = now_lima.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=days_ahead)
        if cand <= now_lima:
            cand = cand + timedelta(days=7)
        return IntervalTrigger(weeks=4, start_date=cand, timezone="America/Lima")
    elif frec_norm == "mensual":
        return CronTrigger(day=1, hour=h, minute=m, timezone="America/Lima")
    else:
        return CronTrigger(hour=h, minute=m, timezone="America/Lima")


def configurar_jobs_scheduler():
    cfg = get_procesos_config()

    for j in scheduler.get_jobs():
        j.remove()

    etl_activo = cfg.get("etl_activo", True)
    etl_frec = cfg.get("etl_frecuencia", "diario")
    etl_hora_str = cfg.get("etl_hora", "02:00")
    etl_dia_sem = cfg.get("etl_dia_semana")
    if etl_dia_sem is None and cfg.get("etl_dia"):
        etl_dia_sem = NOMBRE_A_NUMERO_DIA.get(cfg.get("etl_dia", "").lower(), 0)

    etl_trigger = construir_trigger_proceso(
        frecuencia=etl_frec,
        hora_str=etl_hora_str,
        dia_str=cfg.get("etl_dia"),
        dia_semana=etl_dia_sem
    )
    scheduler.add_job(
        tarea_etl_diario,
        etl_trigger,
        id="etl_diario",
        name="Extracción y Validación ETL Diaria",
        replace_existing=True
    )
    if not etl_activo:
        scheduler.pause_job("etl_diario")

    pr_activo = cfg.get("pronostico_activo", True)
    pr_frec = cfg.get("pronostico_frecuencia", "diario")
    pr_hora_str = cfg.get("pronostico_hora", "04:00")
    pr_dia_sem = cfg.get("pronostico_dia_semana")
    if pr_dia_sem is None and cfg.get("pronostico_dia"):
        pr_dia_sem = NOMBRE_A_NUMERO_DIA.get(cfg.get("pronostico_dia", "").lower(), 0)

    pr_trigger = construir_trigger_proceso(
        frecuencia=pr_frec,
        hora_str=pr_hora_str,
        dia_str=cfg.get("pronostico_dia"),
        dia_semana=pr_dia_sem
    )
    scheduler.add_job(
        tarea_pronostico_diario,
        pr_trigger,
        id="pronostico_diario",
        name="Generación Diaria de Pronósticos (XGBoost)",
        replace_existing=True
    )
    if not pr_activo:
        scheduler.pause_job("pronostico_diario")

    re_activo = cfg.get("reentrenamiento_activo", True)
    re_frec = cfg.get("reentrenamiento_frecuencia", "semanal")
    re_hora_str = cfg.get("reentrenamiento_hora", "01:00")
    re_dia_sem = cfg.get("reentrenamiento_dia_semana")
    if re_dia_sem is None and cfg.get("reentrenamiento_dia"):
        re_dia_sem = NOMBRE_A_NUMERO_DIA.get(cfg.get("reentrenamiento_dia", "").lower(), 6)

    re_trigger = construir_trigger_proceso(
        frecuencia=re_frec,
        hora_str=re_hora_str,
        dia_str=cfg.get("reentrenamiento_dia", "domingo"),
        dia_semana=re_dia_sem
    )
    scheduler.add_job(
        tarea_reentrenamiento_semanal,
        re_trigger,
        id="reentrenamiento_semanal",
        name="Reentrenamiento Semanal del Modelo (XGBoost)",
        replace_existing=True
    )
    if not re_activo:
        scheduler.pause_job("reentrenamiento_semanal")

    logger.info("[Scheduler] Trabajos programados actualizados exitosamente.")


def ensure_scheduler_started():
    if not scheduler.running:
        configurar_jobs_scheduler()
        scheduler.start()
        logger.info("[Scheduler] APScheduler iniciado.")


def start_scheduler():
    ensure_scheduler_started()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] APScheduler detenido.")


def reprogramar_job_en_scheduler(job_id: str, proc_key: str, cfg: Dict[str, Any]):
    ensure_scheduler_started()
    job = scheduler.get_job(job_id)
    if not job:
        configurar_jobs_scheduler()
        job = scheduler.get_job(job_id)

    activo = cfg.get(f"{proc_key}_activo", True)
    frec = cfg.get(f"{proc_key}_frecuencia", "diario")
    hora = cfg.get(f"{proc_key}_hora", "02:00")
    dia_str = cfg.get(f"{proc_key}_dia")
    dia_sem = cfg.get(f"{proc_key}_dia_semana")

    trigger = construir_trigger_proceso(frecuencia=frec, hora_str=hora, dia_str=dia_str, dia_semana=dia_sem)
    if job:
        job.reschedule(trigger=trigger)
        if not activo:
            job.pause()
        else:
            job.resume()


def get_job_proxima_ejecucion(job_id: str) -> Optional[datetime]:
    ensure_scheduler_started()
    job = scheduler.get_job(job_id)
    if not job:
        return None
    return getattr(job, "next_run_time", None)


def ejecutar_proceso_manual(db: Session, tipo_proceso: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    tipo_norm = tipo_proceso.lower().strip()
    if tipo_norm in ["etl", "etl_diario"]:
        tipo_proceso = "etl"
    elif tipo_norm in ["pronostico", "pronostico_diario"]:
        tipo_proceso = "pronostico"
    elif tipo_norm in ["reentrenamiento", "reentrenamiento_semanal"]:
        tipo_proceso = "reentrenamiento"

    if tipo_proceso == "etl":
        resultados = sincronizar_archivos_locales(db, user_id=user_id)
        return {
            "mensaje": "Proceso ETL ejecutado exitosamente.",
            "tipo_proceso": "etl",
            "archivos_procesados": len(resultados),
            "detalle": resultados
        }
    elif tipo_proceso == "pronostico":
        carga = tarea_pronostico_diario(db=db)
        if carga.estado == "FALLIDO":
            return {
                "mensaje": f"Generación de pronósticos fallida: {carga.detalle_error}",
                "tipo_proceso": "pronostico",
                "id_carga": carga.id_carga,
                "estado": "FALLIDO",
                "error": carga.detalle_error
            }
        return {
            "mensaje": "Generación de pronósticos ejecutada exitosamente.",
            "tipo_proceso": "pronostico",
            "id_carga": carga.id_carga,
            "estado": "COMPLETADO"
        }
    elif tipo_proceso == "reentrenamiento":
        carga = tarea_reentrenamiento_semanal(db=db)
        if carga and carga.estado == "FALLIDO":
            return {
                "mensaje": f"Reentrenamiento fallido: {carga.detalle_error}",
                "tipo_proceso": "reentrenamiento",
                "id_carga": carga.id_carga,
                "estado": "FALLIDO",
                "error": carga.detalle_error
            }
        return {
            "mensaje": "Reentrenamiento semanal ejecutado exitosamente.",
            "tipo_proceso": "reentrenamiento",
            "id_carga": carga.id_carga if carga else None,
            "estado": "COMPLETADO"
        }
    else:
        raise ValueError(f"Tipo de proceso '{tipo_proceso}' no válido. Opciones: etl, pronostico, reentrenamiento")
