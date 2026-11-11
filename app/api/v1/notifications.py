import re
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_admin, get_current_user
from app.models.usuario import Usuario
from app.models.carga_datos import CargaDatos
from app.models.modelo_version import ModeloVersion
from app.models.umbral_configuracion import UmbralConfiguracion
from app.services.scheduler import get_procesos_config
from app.services.email_service import EmailService, parse_emails_destinatarios
from app.services.alert_service import AlertService
from app.services.etl_service import get_tipo_carga_etiqueta, get_calidad_min_threshold
from app.schemas.notifications import NotificacionCargaItem

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones de Alertas"])


def _format_pct(val: float) -> str:
    vf = float(val)
    if vf.is_integer():
        return f"{int(vf)}"
    return f"{vf:g}"


@router.get("/cargas", response_model=List[NotificacionCargaItem])
def get_notificaciones_cargas(
    limite: int = Query(10, ge=1, le=100, description="Cantidad máxima de notificaciones a retornar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las notificaciones de las cargas de datos más recientes con estado completado.
    Disponible para todos los roles autenticados.
    """
    cargas = db.query(CargaDatos).filter(
        CargaDatos.tipo_carga.in_(["ventas", "inventario", "productos"]),
        CargaDatos.estado.in_(["COMPLETADO", "CON_ADVERTENCIAS"])
    ).order_by(CargaDatos.fecha_ejecucion.desc()).limit(limite).all()

    umbral_vigente = get_calidad_min_threshold(db)

    resultado = []
    for c in cargas:
        p_calidad = float(c.porcentaje_calidad)
        etiqueta = get_tipo_carga_etiqueta(c.tipo_carga)
        if p_calidad >= umbral_vigente:
            tipo_notif = "exito"
            msg = f"Los datos de {etiqueta} fueron actualizados correctamente."
        else:
            tipo_notif = "advertencia_calidad"
            x_str = _format_pct(p_calidad)
            u_str = _format_pct(umbral_vigente)
            msg = f"Carga de {etiqueta} completada con advertencia: la calidad de datos ({x_str}%) está por debajo del umbral ({u_str}%)."

        resultado.append(NotificacionCargaItem(
            id_carga=c.id_carga,
            tipo_carga=c.tipo_carga,
            tipo_carga_etiqueta=etiqueta,
            fecha_ejecucion=c.fecha_ejecucion,
            registros_procesados=c.registros_procesados,
            porcentaje_calidad=p_calidad,
            umbral_calidad=umbral_vigente,
            tipo_notificacion=tipo_notif,
            mensaje=msg
        ))

    modelos_candidatos = db.query(ModeloVersion).filter(
        ModeloVersion.motivo_entrenamiento.like("reentrenamiento_%"),
        ModeloVersion.estado.in_(["APTA", "DESCARTADA"])
    ).order_by(ModeloVersion.fecha_entrenamiento.desc()).limit(limite).all()

    u_mape = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
    umbral_mape = float(u_mape.valor) if u_mape else 15.0

    for m in modelos_candidatos:
        mape_14d_val = float(m.mape_14d) if m.mape_14d is not None else (float(m.mape) if m.mape is not None else 0.0)
        x_num = int(mape_14d_val) if float(mape_14d_val).is_integer() else mape_14d_val

        u_eval = m.umbral_mape_evaluacion
        if u_eval is None and m.observacion:
            match_disc = re.search(r"umbral de\s+([\d\.]+)%", m.observacion)
            if match_disc:
                try:
                    u_eval = float(match_disc.group(1))
                except Exception:
                    pass
            else:
                match_apt = re.search(r"≤\s*([\d\.]+)%\)", m.observacion)
                if match_apt:
                    try:
                        u_eval = float(match_apt.group(1))
                    except Exception:
                        pass
        if u_eval is None:
            u_eval = umbral_mape

        u_num = int(u_eval) if float(u_eval).is_integer() else u_eval

        if m.estado == "DESCARTADA":
            tipo_n = "advertencia"
            msg = f"Modelo candidato {m.version} descartado: MAPE (demanda 14 días) {x_num}% supera el umbral de {u_num}%."
        else:
            tipo_n = "exito"
            msg = f"Modelo candidato {m.version} apto: pendiente de aprobación para publicación."

        resultado.append(NotificacionCargaItem(
            id_carga=m.id_modelo,
            tipo_carga="entrenamiento",
            tipo_carga_etiqueta="Modelo de Pronóstico",
            fecha_ejecucion=m.fecha_entrenamiento,
            registros_procesados=0,
            porcentaje_calidad=100.0,
            umbral_calidad=float(u_eval),
            tipo_notificacion=tipo_n,
            mensaje=msg
        ))

    resultado.sort(key=lambda x: x.fecha_ejecucion, reverse=True)
    return resultado[:limite]


@router.get("/modelos", response_model=List[NotificacionCargaItem])
def get_notificaciones_modelos(
    limite: int = Query(10, ge=1, le=100, description="Cantidad máxima de notificaciones a retornar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    modelos_candidatos = db.query(ModeloVersion).filter(
        ModeloVersion.motivo_entrenamiento.like("reentrenamiento_%"),
        ModeloVersion.estado.in_(["APTA", "DESCARTADA"])
    ).order_by(ModeloVersion.fecha_entrenamiento.desc()).limit(limite).all()

    u_mape = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
    umbral_mape = float(u_mape.valor) if u_mape else 15.0

    resultado = []
    for m in modelos_candidatos:
        mape_14d_val = float(m.mape_14d) if m.mape_14d is not None else (float(m.mape) if m.mape is not None else 0.0)
        x_num = int(mape_14d_val) if float(mape_14d_val).is_integer() else mape_14d_val

        u_eval = m.umbral_mape_evaluacion
        if u_eval is None and m.observacion:
            match_disc = re.search(r"umbral de\s+([\d\.]+)%", m.observacion)
            if match_disc:
                try:
                    u_eval = float(match_disc.group(1))
                except Exception:
                    pass
            else:
                match_apt = re.search(r"≤\s*([\d\.]+)%\)", m.observacion)
                if match_apt:
                    try:
                        u_eval = float(match_apt.group(1))
                    except Exception:
                        pass
        if u_eval is None:
            u_eval = umbral_mape

        u_num = int(u_eval) if float(u_eval).is_integer() else u_eval

        if m.estado == "DESCARTADA":
            tipo_n = "advertencia"
            msg = f"Modelo candidato {m.version} descartado: MAPE (demanda 14 días) {x_num}% supera el umbral de {u_num}%."
        else:
            tipo_n = "exito"
            msg = f"Modelo candidato {m.version} apto: pendiente de aprobación para publicación."

        resultado.append(NotificacionCargaItem(
            id_carga=m.id_modelo,
            tipo_carga="entrenamiento",
            tipo_carga_etiqueta="Modelo de Pronóstico",
            fecha_ejecucion=m.fecha_entrenamiento,
            registros_procesados=0,
            porcentaje_calidad=100.0,
            umbral_calidad=float(u_eval),
            tipo_notificacion=tipo_n,
            mensaje=msg
        ))
    resultado.sort(key=lambda x: x.fecha_ejecucion, reverse=True)
    return resultado[:limite]


class ResumenAlertasRequest(BaseModel):
    destinatario: Optional[str] = None


class ResumenAlertasResponse(BaseModel):
    success: bool
    enviado: bool
    cantidad_alertas: int = 0
    destinatarios: List[str] = []
    message: str


@router.post("/resumen-alertas", response_model=ResumenAlertasResponse)
@router.post("/prueba", response_model=ResumenAlertasResponse, include_in_schema=True)
def enviar_resumen_alertas_endpoint(
    payload: Optional[ResumenAlertasRequest] = None,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """
    Envía a los destinatarios configurados el resumen de alertas ACTIVAS actuales
    de los tipos habilitados (Mockup 09). Solo rol Administrador.
    La ruta /prueba actúa como alias de compatibilidad de /resumen-alertas.
    """
    cfg = get_procesos_config()
    correos_raw = None
    if payload and payload.destinatario:
        correos_raw = payload.destinatario
    else:
        correos_raw = cfg.get("correo_alertas") or cfg.get("alertas_notificacion_email", "")

    try:
        destinatarios = parse_emails_destinatarios(correos_raw)
    except Exception as e:
        return ResumenAlertasResponse(
            success=False,
            enviado=False,
            cantidad_alertas=0,
            destinatarios=[],
            message=f"Destinatarios no válidos en configuración: {str(e)}"
        )

    alertas_activas = AlertService.obtener_alertas_activas_para_resumen(db=db, cfg=cfg)

    if not alertas_activas:
        return ResumenAlertasResponse(
            success=True,
            enviado=False,
            cantidad_alertas=0,
            destinatarios=destinatarios,
            message="No hay alertas activas de los tipos seleccionados."
        )

    result = EmailService.enviar_resumen_alertas(
        destinatarios=destinatarios,
        alertas=alertas_activas,
        db=db,
        asunto="Resumen de alertas – RetailPro",
        accion="Notificación de alertas enviada",
        tipo_auditoria="manual",
        user=current_admin
    )

    dest_str = ", ".join(destinatarios)
    if result.success:
        return ResumenAlertasResponse(
            success=True,
            enviado=True,
            cantidad_alertas=len(alertas_activas),
            destinatarios=destinatarios,
            message=f"Resumen enviado a {dest_str}"
        )
    else:
        return ResumenAlertasResponse(
            success=False,
            enviado=False,
            cantidad_alertas=len(alertas_activas),
            destinatarios=destinatarios,
            message=result.message
        )
