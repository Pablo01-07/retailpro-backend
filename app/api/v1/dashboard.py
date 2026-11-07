from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles, RoleCode
from app.models.usuario import Usuario
from app.schemas.dashboard import (
    DashboardResumenResponse,
    NivelServicioResponse,
    ProductoMasVendidoItem
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard y Nivel de Servicio"])


@router.get("", response_model=DashboardResumenResponse)
def get_dashboard_resumen(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    KPIs ejecutivos, tendencias y alertas para el Dashboard Principal (Pantalla 14).
    Calculado en consulta a partir de los datos en PostgreSQL.
    """
    return DashboardService.get_dashboard_resumen(db)


@router.get("/productos-mas-vendidos", response_model=List[ProductoMasVendidoItem])
def get_productos_mas_vendidos(
    dias: int = Query(30, description="Días de análisis para el ranking"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Ranking Top 5 de productos más vendidos en unidades (Pantalla 14).
    Calculado sobre venta_historica para los últimos 30 días con variación contra el período previo.
    """
    return DashboardService.get_productos_mas_vendidos(db=db, dias=dias)


@router.get("/nivel-servicio", response_model=NivelServicioResponse)
def get_nivel_servicio_detalle(
    sku: Optional[str] = Query(None, description="Filtrar por SKU específico"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    periodo: Optional[str] = Query(None, description="Período de análisis"),
    almacen: Optional[str] = Query("Principal", description="Almacén de análisis (FasRetail opera con 'Principal')"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Monitoreo detallado del Nivel de Servicio Estimado (Pantalla 17).
    Incluye nota metodológica de estimación ante la inexistencia de saldos diarios históricos.
    Soporta filtros por sku, categoria, periodo y almacen.
    """
    return DashboardService.get_nivel_servicio_detalle(
        db=db,
        sku=sku,
        categoria=categoria,
        periodo=periodo,
        almacen=almacen
    )


@router.get("/powerbi")
def get_dashboard_powerbi(
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Información de integración Power BI embebido para el Dashboard Ejecutivo (Pantalla 14).
    Retorna enabled: false cuando POWERBI_EMBED_URL no está configurado en .env.
    """
    embed_url = (settings.POWERBI_EMBED_URL or "").strip()
    return {
        "enabled": bool(embed_url),
        "embed_url": embed_url if embed_url else None,
        "mensaje": "Power BI disponible para visualización embebida." if embed_url else "Power BI embebido no configurado o deshabilitado en este entorno."
    }
