import os
import json
import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_admin, require_roles, RoleCode
from app.core.audit import create_audit_log
from app.models.usuario import Usuario
from app.models.carga_datos import CargaDatos
from app.models.umbral_configuracion import UmbralConfiguracion
from app.services.email_service import EmailService
from app.schemas.processes import (
    ProcesoConfigSchema,
    ProcesoConfigPatchRequest,
    ProcesoConfigItemResponse,
    ProcesoItemResponse,
    DetalleEjecucionResponse,
    EtapaProcesoItem,
    ReintentoEjecucionResponse
)
from app.services.scheduler import (
    get_procesos_config,
    save_procesos_config,
    configurar_jobs_scheduler,
    ensure_scheduler_started,
    reprogramar_job_en_scheduler,
    get_job_proxima_ejecucion,
    ejecutar_proceso_manual,
    get_storage_carga_dir,
    DIAS_SEMANA_MAP,
    NOMBRE_A_NUMERO_DIA,
    PROCESOS_METADATA,
    scheduler
)
from app.services.etl_service import (
    get_carga_nombre_archivo,
    get_tipo_carga_etiqueta,
    get_calidad_min_threshold,
    reintentar_ejecucion_carga
)

router = APIRouter(prefix="/procesos", tags=["Monitoreo y Configuración de Procesos Batch"])


@router.get("", response_model=List[ProcesoItemResponse])
def list_procesos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Monitoreo del estado de los 3 procesos batch del sistema (Mockup 07):
    1. ETL diario (extracción y validación)
    2. Pronóstico de ventas diario (XGBoost)
    3. Reentrenamiento semanal del modelo
    """
    ensure_scheduler_started()
    cfg = get_procesos_config()

    ult_etl = db.query(CargaDatos).filter(
        CargaDatos.tipo_carga.in_(["ventas", "productos", "inventario"])
    ).order_by(CargaDatos.id_carga.desc()).first()

    etl_activo = cfg.get("etl_activo", True)
    item_etl = ProcesoItemResponse(
        id_proceso="etl_diario",
        nombre="Extracción y Validación ETL",
        tipo="Extracción y Calidad",
        activo=etl_activo,
        frecuencia=cfg.get("etl_frecuencia", "diario").capitalize(),
        horario=cfg.get("etl_hora", "02:00"),
        ultima_ejecucion=ult_etl.fecha_ejecucion if ult_etl else None,
        proxima_ejecucion=get_job_proxima_ejecucion("etl_diario") if etl_activo else None,
        estado_ultima_ejecucion=ult_etl.estado if ult_etl else "PENDIENTE",
        id_ultima_carga=ult_etl.id_carga if ult_etl else None,
        registros_afectados=ult_etl.registros_procesados if ult_etl else 0
    )

    ult_pron = db.query(CargaDatos).filter(
        CargaDatos.tipo_carga == "pronostico"
    ).order_by(CargaDatos.id_carga.desc()).first()

    pr_activo = cfg.get("pronostico_activo", True)
    item_pron = ProcesoItemResponse(
        id_proceso="pronostico_diario",
        nombre="Generación de Pronósticos",
        tipo="Inferencia XGBoost",
        activo=pr_activo,
        frecuencia=cfg.get("pronostico_frecuencia", "diario").capitalize(),
        horario=cfg.get("pronostico_hora", "04:00"),
        ultima_ejecucion=ult_pron.fecha_ejecucion if ult_pron else None,
        proxima_ejecucion=get_job_proxima_ejecucion("pronostico_diario") if pr_activo else None,
        estado_ultima_ejecucion=ult_pron.estado if ult_pron else "PENDIENTE",
        id_ultima_carga=ult_pron.id_carga if ult_pron else None,
        registros_afectados=ult_pron.registros_procesados if ult_pron else 0
    )

    ult_reent = db.query(CargaDatos).filter(
        CargaDatos.tipo_carga == "entrenamiento"
    ).order_by(CargaDatos.id_carga.desc()).first()

    re_activo = cfg.get("reentrenamiento_activo", True)
    item_reent = ProcesoItemResponse(
        id_proceso="reentrenamiento_semanal",
        nombre="Reentrenamiento del Modelo",
        tipo="Entrenamiento XGBoost",
        activo=re_activo,
        frecuencia=f"{cfg.get('reentrenamiento_frecuencia', 'semanal').capitalize()} ({cfg.get('reentrenamiento_dia', 'domingo').capitalize()})",
        horario=cfg.get("reentrenamiento_hora", "01:00"),
        ultima_ejecucion=ult_reent.fecha_ejecucion if ult_reent else None,
        proxima_ejecucion=get_job_proxima_ejecucion("reentrenamiento_semanal") if re_activo else None,
        estado_ultima_ejecucion=ult_reent.estado if ult_reent else "PENDIENTE",
        id_ultima_carga=ult_reent.id_carga if ult_reent else None,
        registros_afectados=ult_reent.registros_procesados if ult_reent else 0
    )

    return [item_etl, item_pron, item_reent]


@router.get("/configuracion", response_model=ProcesoConfigSchema)
def get_configuracion_procesos(
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Obtiene los parámetros de programación de tareas batch y alertas por correo (Mockup 09). Solo Administradores."""
    ensure_scheduler_started()
    cfg = get_procesos_config()

    etl_activo = cfg.get("etl_activo", True)
    pr_activo = cfg.get("pronostico_activo", True)
    re_activo = cfg.get("reentrenamiento_activo", True)

    cfg["etl_activo"] = etl_activo
    cfg["etl_proxima_ejecucion"] = get_job_proxima_ejecucion("etl_diario") if etl_activo else None

    cfg["pronostico_activo"] = pr_activo
    cfg["pronostico_proxima_ejecucion"] = get_job_proxima_ejecucion("pronostico_diario") if pr_activo else None

    cfg["reentrenamiento_activo"] = re_activo
    cfg["reentrenamiento_proxima_ejecucion"] = get_job_proxima_ejecucion("reentrenamiento_semanal") if re_activo else None

    re_dia_sem = cfg.get("reentrenamiento_dia_semana")
    if re_dia_sem is None and cfg.get("reentrenamiento_dia"):
        re_dia_sem = NOMBRE_A_NUMERO_DIA.get(cfg.get("reentrenamiento_dia", "domingo").lower(), 6)
    cfg["reentrenamiento_dia_semana"] = re_dia_sem

    calidad_min_db = get_calidad_min_threshold(db)
    cfg["calidad_min"] = calidad_min_db
    cfg["umbral_calidad"] = calidad_min_db

    correo = cfg.get("correo_alertas") or cfg.get("alertas_notificacion_email", "alertas@fasretail.com")
    cfg["correo_alertas"] = correo
    cfg["alertas_notificacion_email"] = correo

    q_crit = cfg.get("quiebre_critico", cfg.get("notificar_quiebre", True))
    cfg["quiebre_critico"] = q_crit
    cfg["notificar_quiebre"] = q_crit

    c_baja = cfg.get("calidad_bajo_umbral", cfg.get("notificar_calidad_baja", True))
    cfg["calidad_bajo_umbral"] = c_baja
    cfg["notificar_calidad_baja"] = c_baja

    s_prol = cfg.get("sobrestock_prolongado", cfg.get("notificar_sobrestock", True))
    cfg["sobrestock_prolongado"] = s_prol
    cfg["notificar_sobrestock"] = s_prol

    cfg["smtp_configurado"] = EmailService.is_smtp_configured()

    cfg["procesos"] = [
        ProcesoConfigItemResponse(
            id_proceso="etl_diario",
            nombre="Extracción y Validación ETL",
            tipo="Extracción y Calidad",
            activo=etl_activo,
            frecuencia=cfg.get("etl_frecuencia", "diario"),
            hora=cfg.get("etl_hora", "02:00"),
            dia_semana=cfg.get("etl_dia_semana"),
            dia=cfg.get("etl_dia"),
            proxima_ejecucion=cfg["etl_proxima_ejecucion"]
        ),
        ProcesoConfigItemResponse(
            id_proceso="pronostico_diario",
            nombre="Generación de Pronósticos",
            tipo="Inferencia XGBoost",
            activo=pr_activo,
            frecuencia=cfg.get("pronostico_frecuencia", "diario"),
            hora=cfg.get("pronostico_hora", "04:00"),
            dia_semana=cfg.get("pronostico_dia_semana"),
            dia=cfg.get("pronostico_dia"),
            proxima_ejecucion=cfg["pronostico_proxima_ejecucion"]
        ),
        ProcesoConfigItemResponse(
            id_proceso="reentrenamiento_semanal",
            nombre="Reentrenamiento del Modelo",
            tipo="Entrenamiento XGBoost",
            activo=re_activo,
            frecuencia=cfg.get("reentrenamiento_frecuencia", "semanal"),
            hora=cfg.get("reentrenamiento_hora", "01:00"),
            dia_semana=re_dia_sem,
            dia=cfg.get("reentrenamiento_dia", "domingo"),
            proxima_ejecucion=cfg["reentrenamiento_proxima_ejecucion"]
        )
    ]

    return ProcesoConfigSchema(**cfg)


@router.get("/configuracion/{proceso_id}", response_model=ProcesoConfigItemResponse)
def get_configuracion_individual_proceso(
    proceso_id: str,
    current_admin: Usuario = Depends(get_current_admin)
):
    """Consulta la configuración individual y próxima ejecución de un proceso batch. Solo Administradores."""
    pid_norm = proceso_id.lower().strip()
    if pid_norm in ["etl", "etl_diario"]:
        key = "etl"
    elif pid_norm in ["pronostico", "pronostico_diario"]:
        key = "pronostico"
    elif pid_norm in ["reentrenamiento", "reentrenamiento_semanal"]:
        key = "reentrenamiento"
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proceso '{proceso_id}' no encontrado. Opciones válidas: etl, pronostico, reentrenamiento."
        )

    info = PROCESOS_METADATA[key]
    cfg = get_procesos_config()
    ensure_scheduler_started()

    activo = cfg.get(f"{key}_activo", True)
    proxima_ejec = get_job_proxima_ejecucion(info["id_proceso"]) if activo else None

    dia_sem = cfg.get(f"{key}_dia_semana")
    if dia_sem is None and cfg.get(f"{key}_dia"):
        dia_sem = NOMBRE_A_NUMERO_DIA.get(cfg.get(f"{key}_dia", "").lower())

    return ProcesoConfigItemResponse(
        id_proceso=info["id_proceso"],
        nombre=info["nombre"],
        tipo=info["tipo"],
        activo=activo,
        frecuencia=cfg.get(f"{key}_frecuencia", info["default_frec"]),
        hora=cfg.get(f"{key}_hora", info["default_hora"]),
        dia_semana=dia_sem,
        dia=cfg.get(f"{key}_dia"),
        proxima_ejecucion=proxima_ejec
    )


@router.patch("/configuracion/{proceso_id}", response_model=ProcesoConfigItemResponse)
@router.put("/configuracion/{proceso_id}", response_model=ProcesoConfigItemResponse)
def patch_configuracion_proceso(
    proceso_id: str,
    patch_data: ProcesoConfigPatchRequest,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """
    Modifica la configuración de un proceso batch programado (Mockup 09). Solo rol Administrador.
    Parámetros admitidos:
    - activo: bool (pausa o reanuda el job en el scheduler en caliente)
    - frecuencia: str ('diario', 'semanal', 'mensual')
    - hora: str ('HH:MM' en formato 24 horas, 00:00 a 23:59)
    - dia_semana: int (0 a 6, donde 0=lunes y 6=domingo; solo aplicable a frecuencia semanal)
    """
    pid_norm = proceso_id.lower().strip()
    if pid_norm in ["etl", "etl_diario"]:
        key = "etl"
    elif pid_norm in ["pronostico", "pronostico_diario"]:
        key = "pronostico"
    elif pid_norm in ["reentrenamiento", "reentrenamiento_semanal"]:
        key = "reentrenamiento"
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proceso '{proceso_id}' no encontrado. Opciones válidas: etl, pronostico, reentrenamiento."
        )

    info = PROCESOS_METADATA[key]
    cfg = get_procesos_config()

    if (
        patch_data.activo is None
        and patch_data.frecuencia is None
        and patch_data.hora is None
        and patch_data.dia_semana is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe proporcionar al menos un campo para actualizar: activo, frecuencia, hora o dia_semana."
        )

    frec_nueva = None
    if patch_data.frecuencia is not None:
        frec_candidate = patch_data.frecuencia.lower().strip()
        if frec_candidate not in ["diario", "semanal", "mensual"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Frecuencia '{patch_data.frecuencia}' inválida. Valores permitidos: diario, semanal, mensual."
            )
        frec_nueva = frec_candidate

    hora_nueva = None
    if patch_data.hora is not None:
        hora_candidate = patch_data.hora.strip()
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", hora_candidate):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Hora '{patch_data.hora}' inválida. Formato requerido: HH:MM (00:00 a 23:59)."
            )
        hora_nueva = hora_candidate
        for otro in ["etl", "pronostico", "reentrenamiento"]:
            if otro != key:
                otro_activo = cfg.get(f"{otro}_activo", True)
                if otro_activo:
                    otro_hora = cfg.get(f"{otro}_hora", PROCESOS_METADATA[otro]["default_hora"])
                    if otro_hora == hora_nueva:
                        nom_otro = PROCESOS_METADATA[otro]["nombre"]
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Conflicto de horario: el proceso '{nom_otro}' ya está programado a las {hora_nueva}. Seleccione un horario distinto."
                        )

    frec_efectiva = (frec_nueva or cfg.get(f"{key}_frecuencia", info["default_frec"])).lower().strip()
    dia_semana_nuevo = None
    if patch_data.dia_semana is not None:
        if not isinstance(patch_data.dia_semana, int) or patch_data.dia_semana < 0 or patch_data.dia_semana > 6:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"dia_semana '{patch_data.dia_semana}' inválido. Debe ser un entero entre 0 (lunes) y 6 (domingo)."
            )
        if frec_efectiva != "semanal":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El campo 'dia_semana' solo es válido para procesos con frecuencia 'semanal' (la frecuencia resultante es '{frec_efectiva}')."
            )
        dia_semana_nuevo = patch_data.dia_semana

    cambios = []

    if patch_data.activo is not None:
        val_ant = cfg.get(f"{key}_activo", True)
        if val_ant != patch_data.activo:
            cambios.append(("activo", val_ant, patch_data.activo))
        cfg[f"{key}_activo"] = patch_data.activo

    if frec_nueva is not None:
        val_ant = cfg.get(f"{key}_frecuencia", info["default_frec"])
        if val_ant != frec_nueva:
            cambios.append(("frecuencia", val_ant, frec_nueva))
        cfg[f"{key}_frecuencia"] = frec_nueva

    if hora_nueva is not None:
        val_ant = cfg.get(f"{key}_hora", info["default_hora"])
        if val_ant != hora_nueva:
            cambios.append(("hora", val_ant, hora_nueva))
        cfg[f"{key}_hora"] = hora_nueva

    if dia_semana_nuevo is not None:
        dia_nom = DIAS_SEMANA_MAP[dia_semana_nuevo]
        val_ant = cfg.get(f"{key}_dia_semana")
        if val_ant is None and cfg.get(f"{key}_dia"):
            val_ant = NOMBRE_A_NUMERO_DIA.get(cfg.get(f"{key}_dia", "").lower(), 6)
        if val_ant != dia_semana_nuevo or cfg.get(f"{key}_dia") != dia_nom:
            cambios.append(("dia_semana", val_ant, dia_semana_nuevo))
        cfg[f"{key}_dia_semana"] = dia_semana_nuevo
        cfg[f"{key}_dia"] = dia_nom

    save_procesos_config(cfg)

    reprogramar_job_en_scheduler(info["id_proceso"], key, cfg)

    proc_label = "ETL" if key == "etl" else ("Pronóstico" if key == "pronostico" else "Reentrenamiento")
    for campo, val_ant, val_nue in cambios:
        desc = f"{proc_label}: {campo} {val_ant} → {val_nue}"
        create_audit_log(
            db=db,
            accion="Configuración de proceso modificada",
            modulo_afectado="procesos",
            user=current_admin,
            detalle={
                "descripcion": desc,
                "proceso": info["id_proceso"],
                "campo": campo,
                "valor_anterior": val_ant,
                "valor_nuevo": val_nue
            }
        )

    proxima_ejec = get_job_proxima_ejecucion(info["id_proceso"]) if cfg.get(f"{key}_activo", True) else None

    return ProcesoConfigItemResponse(
        id_proceso=info["id_proceso"],
        nombre=info["nombre"],
        tipo=info["tipo"],
        activo=cfg.get(f"{key}_activo", True),
        frecuencia=cfg.get(f"{key}_frecuencia", info["default_frec"]),
        hora=cfg.get(f"{key}_hora", info["default_hora"]),
        dia_semana=cfg.get(f"{key}_dia_semana"),
        dia=cfg.get(f"{key}_dia"),
        proxima_ejecucion=proxima_ejec
    )


@router.put("/configuracion", response_model=ProcesoConfigSchema)
def update_configuracion_procesos(
    config_in: ProcesoConfigSchema,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Actualiza la programación horaria y notificaciones de procesos batch (Mockup 09). Reconfigura el Scheduler en vivo."""
    data = config_in.model_dump(exclude_unset=True)
    cfg = get_procesos_config()

    procesos_keys = ["etl", "pronostico", "reentrenamiento"]
    cambio_algun_horario = False
    for p in procesos_keys:
        k_hora = f"{p}_hora"
        if k_hora in data and data[k_hora] is not None:
            hora_act = cfg.get(k_hora, PROCESOS_METADATA[p]["default_hora"])
            if data[k_hora] != hora_act:
                cambio_algun_horario = True
                break

    if cambio_algun_horario:
        horas_res = {}
        activos_res = {}
        for p in procesos_keys:
            horas_res[p] = data.get(f"{p}_hora") or cfg.get(f"{p}_hora", PROCESOS_METADATA[p]["default_hora"])
            if f"{p}_activo" in data and data[f"{p}_activo"] is not None:
                activos_res[p] = bool(data[f"{p}_activo"])
            else:
                activos_res[p] = bool(cfg.get(f"{p}_activo", True))

        for p1 in procesos_keys:
            k1_hora = f"{p1}_hora"
            hora_cambio = (k1_hora in data and data[k1_hora] is not None and data[k1_hora] != cfg.get(k1_hora, PROCESOS_METADATA[p1]["default_hora"]))
            if hora_cambio and activos_res[p1]:
                for p2 in procesos_keys:
                    if p1 != p2 and activos_res[p2] and horas_res[p1] == horas_res[p2]:
                        nom_otro = PROCESOS_METADATA[p2]["nombre"]
                        h_conflicto = horas_res[p1]
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Conflicto de horario: el proceso '{nom_otro}' ya está programado a las {h_conflicto}. Seleccione un horario distinto."
                        )

    cambios_generales = []
    for k, v in data.items():
        if v is not None and k not in ["procesos", "etl_proxima_ejecucion", "pronostico_proxima_ejecucion", "reentrenamiento_proxima_ejecucion", "smtp_configurado"]:
            v_ant = cfg.get(k)
            if v_ant != v:
                cambios_generales.append((k, v_ant, v))
            cfg[k] = v

    if config_in.calidad_min is not None or config_in.umbral_calidad is not None:
        nuevo_umbral = float(config_in.calidad_min or config_in.umbral_calidad)
        u_calidad = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "calidad_min").first()
        if not u_calidad:
            u_calidad = UmbralConfiguracion(id_usuario=current_admin.id_usuario, tipo_umbral="calidad_min", valor=nuevo_umbral)
            db.add(u_calidad)
            cambios_generales.append(("calidad_min", None, nuevo_umbral))
        else:
            if float(u_calidad.valor) != nuevo_umbral:
                cambios_generales.append(("calidad_min", float(u_calidad.valor), nuevo_umbral))
                u_calidad.valor = nuevo_umbral
                u_calidad.id_usuario = current_admin.id_usuario
        db.commit()

    for proc in ["etl", "pronostico", "reentrenamiento"]:
        if cfg.get(f"{proc}_dia"):
            cfg[f"{proc}_dia_semana"] = NOMBRE_A_NUMERO_DIA.get(cfg[f"{proc}_dia"].lower(), 6)
        elif cfg.get(f"{proc}_dia_semana") is not None:
            cfg[f"{proc}_dia"] = DIAS_SEMANA_MAP.get(cfg[f"{proc}_dia_semana"], "domingo")

    save_procesos_config(cfg)
    configurar_jobs_scheduler()

    for k, v_ant, v_nue in cambios_generales:
        desc = f"Configuración: {k} {v_ant} → {v_nue}"
        create_audit_log(
            db=db,
            accion="Configuración de proceso modificada",
            modulo_afectado="procesos",
            user=current_admin,
            detalle={
                "descripcion": desc,
                "campo": k,
                "valor_anterior": v_ant,
                "valor_nuevo": v_nue
            }
        )

    return get_configuracion_procesos(db=db, current_admin=current_admin)


@router.post("/ejecutar/{tipo_proceso}")
def ejecutar_proceso(
    tipo_proceso: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Ejecuta de forma manual e inmediata un proceso batch: etl, pronostico o reentrenamiento (Mockup 07 / 09).
    - 'pronostico' está permitido para 'administrador' y 'analista'.
    - Otros procesos ('etl', 'reentrenamiento') requieren estrictamente rol 'administrador'.
    """
    tipo_norm = tipo_proceso.lower().strip()
    if tipo_norm in ["etl", "etl_diario"]:
        tipo_norm = "etl"
    elif tipo_norm in ["pronostico", "pronostico_diario"]:
        tipo_norm = "pronostico"
    elif tipo_norm in ["reentrenamiento", "reentrenamiento_semanal"]:
        tipo_norm = "reentrenamiento"

    if current_user.rol != RoleCode.ADMIN and tipo_norm != "pronostico":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acceso denegado: Se requiere rol '{RoleCode.ADMIN}' para ejecutar procesos de tipo '{tipo_norm}'."
        )

    try:
        resultado = ejecutar_proceso_manual(db, tipo_norm, user_id=current_user.id_usuario)
        return resultado
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.get("/{id_carga}", response_model=DetalleEjecucionResponse)
def get_detalle_ejecucion(
    id_carga: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """Obtiene la línea de tiempo y logs detallados por etapas de una ejecución batch (Mockup 08)."""
    carga = db.query(CargaDatos).filter(CargaDatos.id_carga == id_carga).first()
    if not carga:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ejecución no encontrada")

    carga_dir = get_storage_carga_dir(id_carga)
    etapas_path = os.path.join(carga_dir, "etapas.json")

    etapas = []
    duracion_total = None
    if os.path.exists(etapas_path):
        try:
            with open(etapas_path, "r", encoding="utf-8") as f:
                etapas_raw = json.load(f)
                etapas = [EtapaProcesoItem(**e) for e in etapas_raw]
                duracion_total = sum((e.duracion_ms or 0) for e in etapas) / 1000.0
        except Exception:
            pass

    meta_path = os.path.join(carga_dir, "meta.json")
    reintentos = 0
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f_meta:
                reintentos = json.load(f_meta).get("reintentos", 0)
        except Exception:
            reintentos = 0

    reintentos_max = 3
    reintento_permitido = (
        carga.estado == "FALLIDO" and
        carga.tipo_carga in ["ventas", "inventario", "productos"] and
        reintentos < reintentos_max
    )

    return DetalleEjecucionResponse(
        id_carga=carga.id_carga,
        tipo_proceso=carga.tipo_carga,
        tipo_proceso_etiqueta=get_tipo_carga_etiqueta(carga.tipo_carga),
        nombre_archivo=get_carga_nombre_archivo(carga.id_carga),
        fecha_ejecucion=carga.fecha_ejecucion,
        estado=carga.estado,
        registros_procesados=carga.registros_procesados,
        registros_rechazados=carga.registros_rechazados,
        porcentaje_calidad=float(carga.porcentaje_calidad),
        duracion_total_segundos=round(duracion_total, 2) if duracion_total else None,
        etapas=etapas,
        detalle_error=carga.detalle_error,
        reintentos=reintentos,
        reintentos_max=reintentos_max,
        reintento_permitido=reintento_permitido
    )


@router.post("/{id_carga}/reintentar", response_model=ReintentoEjecucionResponse)
def reintentar_ejecucion_endpoint(
    id_carga: int,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(require_roles([RoleCode.ADMIN]))
):
    """
    Reintenta la validación y carga de una ejecución batch fallida.
    Solo rol Administrador. Máximo 3 reintentos permitidos.
    """
    return reintentar_ejecucion_carga(db=db, id_carga=id_carga, user_id=current_admin.id_usuario)
