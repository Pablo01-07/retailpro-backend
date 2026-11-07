from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles, RoleCode
from app.models.usuario import Usuario
from app.schemas.replenishment import (
    ReposicionListResponse,
    AjusteReposicionRequest,
    AjusteReposicionResponse,
    ExportarReposicionRequest
)
from app.schemas.reports import ExportarReporteResponse
from app.services.replenishment_service import ReplenishmentService

router = APIRouter(prefix="/reposicion", tags=["Recomendaciones de Reposición"])


@router.get("", response_model=ReposicionListResponse)
def get_recomendaciones_reposicion(
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    prioridad: Optional[str] = Query(None, description="Filtrar por prioridad ('ALTA', 'MEDIA', 'BAJA')"),
    solo_con_orden: bool = Query(False, description="Mostrar solo sugerencias mayores a cero"),
    sku: Optional[str] = Query(None, description="Filtrar por SKU específico"),
    q: Optional[str] = Query(None, description="Búsqueda de texto en SKU o nombre de producto"),
    fecha_limite_desde: Optional[date] = Query(None, description="Fecha límite de reposición desde"),
    fecha_limite_hasta: Optional[date] = Query(None, description="Fecha límite de reposición hasta"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Lista de sugerencias de reposición de inventario con prioridad calculada en consulta (Pantalla 16).
    Soporta filtros por categoría, prioridad, solo con orden, SKU, búsqueda general q y rango de fechas.
    """
    return ReplenishmentService.list_recomendaciones(
        db=db,
        categoria=categoria,
        prioridad=prioridad,
        solo_con_orden=solo_con_orden,
        sku=sku,
        q=q,
        fecha_limite_desde=fecha_limite_desde,
        fecha_limite_hasta=fecha_limite_hasta
    )


@router.post("/exportar", response_model=ExportarReporteResponse)
def exportar_recomendaciones_reposicion(
    payload: ExportarReposicionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Exportación de recomendaciones de reposición en formato XLSX o CSV (Pantalla 16).
    Aplica los mismos filtros de búsqueda que la vista de reposición.
    Registra la acción en la bitácora de auditoría.
    Accesible para administrador y analista.
    """
    try:
        return ReplenishmentService.exportar_reposicion(
            db=db,
            payload=payload,
            user_id=current_user.id_usuario
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{id_pronostico}", response_model=AjusteReposicionResponse)
def ajustar_cantidad_reposicion(
    id_pronostico: int,
    payload: AjusteReposicionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Ajuste manual de la cantidad de reposición por parte del analista (Pantalla 16).
    Registra el cambio en auditoría conforme a Ley N.° 29733.
    """
    try:
        return ReplenishmentService.ajustar_reposicion(
            db=db,
            id_pronostico=id_pronostico,
            cantidad_ajustada=payload.cantidad_ajustada,
            user_id=current_user.id_usuario,
            motivo=payload.motivo_ajuste
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
