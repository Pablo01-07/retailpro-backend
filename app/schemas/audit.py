import datetime
from typing import Optional, List, Any
from app.schemas.common import RetailProBaseModel


class AuditLogResponse(RetailProBaseModel):
    id_auditoria: int
    id_usuario: Optional[int] = None
    accion: str
    modulo_afectado: str
    fecha_hora: datetime.datetime
    detalle: Optional[Any] = None


class AuditKPIsResponse(RetailProBaseModel):
    total_actions: int
    successful_actions: int
    success_rate_pct: float
    failed_actions: int
    failure_rate_pct: float
    active_users: int


class AuditListResponse(RetailProBaseModel):
    items: List[AuditLogResponse]
    total: int
    page: int
    size: int
    pages: int
    kpis: AuditKPIsResponse
