import os
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles, RoleCode
from app.core.config import settings
from app.models.usuario import Usuario
from app.schemas.reports import (
    ReportePreviewResponse,
    ExportarReporteRequest,
    ExportarReporteConFiltrosRequest,
    ExportarReporteResponse,
    ReporteHistorialResponse
)
from app.services.reporting_service import ReportingService

router = APIRouter(prefix="/reportes", tags=["Centro de Reportes y Exportación"])


@router.get("/historial", response_model=ReporteHistorialResponse)
def get_historial_reportes(
    page: int = Query(1, ge=1, description="Número de página"),
    limit: int = Query(20, ge=1, le=100, description="Cantidad de registros por página"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Lista paginada de reportes generados desde eventos de auditoría de exportación (Pantalla 20 / 21).
    Solo incluye reportes cuyos archivos existen físicamente en storage/reportes/.
    Accesible para administrador, analista y jefe_logistica.
    """
    return ReportingService.get_historial_reportes(db=db, page=page, limit=limit)


@router.get("/pronostico/preview", response_model=ReportePreviewResponse)
def get_reporte_preview(
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Vista previa de 14 días para el Centro de Reportes y Exportación (Pantalla 20 y 21).
    """
    return ReportingService.get_preview_data(db=db, categoria=categoria)


@router.post("/pronostico/export", response_model=ExportarReporteResponse)
def exportar_reporte_pronostico(
    payload: ExportarReporteRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Exportación de reportes de pronóstico en formato CSV, XLSX o PDF (Pantalla 21).
    Registra la acción en la tabla de auditoría.
    """
    try:
        return ReportingService.exportar_reporte(
            db=db,
            formato=payload.formato,
            user_id=current_user.id_usuario,
            categoria=payload.categoria
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/inventario/export", response_model=ExportarReporteResponse)
def exportar_reporte_inventario(
    payload: ExportarReporteConFiltrosRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Exportación de reporte de inventario en formato PDF, XLSX o CSV (Pantalla 21).
    Contenido: stock, cobertura en días, punto de reorden, estado de alerta.
    Registra la acción en auditoría.
    """
    try:
        return ReportingService.exportar_inventario(
            db=db,
            formato=payload.formato,
            user_id=current_user.id_usuario,
            categoria=payload.categoria,
            fecha_inicio=payload.fecha_inicio,
            fecha_fin=payload.fecha_fin
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/ventas/export", response_model=ExportarReporteResponse)
def exportar_reporte_ventas(
    payload: ExportarReporteConFiltrosRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Exportación de reporte de ventas en formato PDF, XLSX o CSV (Pantalla 21).
    Contenido: ventas por período, categoría y SKU.
    Registra la acción en auditoría.
    """
    try:
        return ReportingService.exportar_ventas(
            db=db,
            formato=payload.formato,
            user_id=current_user.id_usuario,
            categoria=payload.categoria,
            fecha_inicio=payload.fecha_inicio,
            fecha_fin=payload.fecha_fin
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/indicadores/export", response_model=ExportarReporteResponse)
def exportar_reporte_indicadores(
    payload: ExportarReporteConFiltrosRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Exportación de reporte de indicadores en formato PDF, XLSX o CSV (Pantalla 21).
    Contenido: MAPE y WAPE fuera de muestra, nivel de servicio estimado, disponibilidad, alertas activas por tipo.
    Registra la acción en auditoría.
    """
    try:
        return ReportingService.exportar_indicadores(
            db=db,
            formato=payload.formato,
            user_id=current_user.id_usuario,
            categoria=payload.categoria,
            fecha_inicio=payload.fecha_inicio,
            fecha_fin=payload.fecha_fin
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/descargar/{filename}")
def descargar_archivo_reporte(
    filename: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Descarga segura de reportes generados desde storage/reportes/.
    """
    storage_dir = os.path.join(os.getcwd(), settings.STORAGE_REPORTES_DIR)
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(storage_dir, safe_filename)

    if not os.path.isfile(filepath):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El archivo '{safe_filename}' no existe o ha expirado."
        )

    ext = os.path.splitext(safe_filename)[1].lower()
    media_types = {
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pdf": "application/pdf"
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=filepath,
        filename=safe_filename,
        media_type=media_type
    )
