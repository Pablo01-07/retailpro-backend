import math
import csv
import io
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_admin
from app.models.auditoria import Auditoria
from app.models.usuario import Usuario
from app.schemas.audit import (
    AuditLogResponse,
    AuditKPIsResponse,
    AuditListResponse
)

router = APIRouter(prefix="/auditoria", tags=["Auditoría del Sistema"])


@router.get("", response_model=AuditListResponse)
def list_audit_logs(
    page: int = Query(1, ge=1, description="Número de página"),
    size: int = Query(10, ge=1, le=100, description="Registros por página"),
    id_usuario: Optional[int] = Query(None, description="Filtrar por ID de usuario"),
    accion: Optional[str] = Query(None, description="Filtrar por acción"),
    modulo_afectado: Optional[str] = Query(None, description="Filtrar por módulo afectado"),
    fecha_inicio: Optional[datetime.date] = Query(None, description="Fecha de inicio (YYYY-MM-DD)"),
    fecha_fin: Optional[datetime.date] = Query(None, description="Fecha de fin (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Lista bitácora de auditoría con KPIs de actividad y filtros (Mockup 24). Solo administradores."""
    query = db.query(Auditoria)

    if id_usuario is not None:
        query = query.filter(Auditoria.id_usuario == id_usuario)
    if accion:
        query = query.filter(Auditoria.accion.ilike(f"%{accion}%"))
    if modulo_afectado:
        query = query.filter(Auditoria.modulo_afectado.ilike(modulo_afectado))
    if fecha_inicio:
        query = query.filter(Auditoria.fecha_hora >= datetime.datetime.combine(fecha_inicio, datetime.time.min))
    if fecha_fin:
        query = query.filter(Auditoria.fecha_hora <= datetime.datetime.combine(fecha_fin, datetime.time.max))

    total = query.count()
    pages = math.ceil(total / size) if total > 0 else 1
    items = query.order_by(Auditoria.fecha_hora.desc()).offset((page - 1) * size).limit(size).all()

    total_actions = db.query(Auditoria).count()
    failed_actions = db.query(Auditoria).filter(Auditoria.accion.ilike("%fallido%")).count()
    successful_actions = total_actions - failed_actions
    active_users = db.query(Usuario).filter(Usuario.estado == True).count()

    success_rate_pct = round((successful_actions / total_actions * 100), 1) if total_actions > 0 else 0.0
    failure_rate_pct = round((failed_actions / total_actions * 100), 1) if total_actions > 0 else 0.0

    kpis = AuditKPIsResponse(
        total_actions=total_actions,
        successful_actions=successful_actions,
        success_rate_pct=success_rate_pct,
        failed_actions=failed_actions,
        failure_rate_pct=failure_rate_pct,
        active_users=active_users
    )

    return AuditListResponse(
        items=[AuditLogResponse.model_validate(it) for it in items],
        total=total,
        page=page,
        size=size,
        pages=pages,
        kpis=kpis
    )


@router.get("/exportar")
def export_audit_logs_csv(
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin)
):
    """Exporta los registros de auditoría en formato CSV (Mockup 24). Cumple Ley N.° 29733."""
    logs = db.query(Auditoria).order_by(Auditoria.fecha_hora.desc()).limit(1000).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Fecha Hora", "ID Usuario", "Acción", "Módulo Afectado", "Detalle"])

    for log in logs:
        writer.writerow([
            log.id_auditoria,
            log.fecha_hora.strftime("%Y-%m-%d %H:%M:%S") if log.fecha_hora else "",
            log.id_usuario or "",
            log.accion,
            log.modulo_afectado,
            str(log.detalle or "")
        ])

    csv_data = output.getvalue()
    filename = f"auditoria_sistema_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
