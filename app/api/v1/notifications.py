from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_admin
from app.models.usuario import Usuario
from app.services.scheduler import get_procesos_config
from app.services.email_service import EmailService, parse_emails_destinatarios
from app.services.alert_service import AlertService

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones de Alertas"])


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
