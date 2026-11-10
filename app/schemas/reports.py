from typing import List, Optional, Dict, Any
from pydantic import Field
from datetime import datetime, date
from app.schemas.common import RetailProBaseModel


class ReportePreviewItem(RetailProBaseModel):
    id_producto: int
    sku: str
    nombre_producto: str
    categoria: str
    stock_actual: int
    punto_reorden: int
    demanda_proyectada_14d: float
    cantidad_sugerida: int
    probabilidad_quiebre: float
    nivel_incertidumbre: str


class ReportePreviewResponse(RetailProBaseModel):
    total_registros: int
    fecha_generacion: datetime
    categoria_filtrada: Optional[str] = None
    items: List[ReportePreviewItem]


class ExportarReporteRequest(RetailProBaseModel):
    formato: str = Field(..., description="Formato: 'csv', 'xlsx', 'pdf'")
    tipo_reporte: str = Field("pronostico_reposicion", description="Tipo: 'pronostico_reposicion', 'inventario', 'ventas', 'indicadores'")
    categoria: Optional[str] = None
    sku: Optional[str] = None


class ExportarReporteConFiltrosRequest(RetailProBaseModel):
    formato: str = Field(..., description="Formato: 'csv', 'xlsx', 'pdf'")
    categoria: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None


class ExportarReporteResponse(RetailProBaseModel):
    id_reporte: str
    formato: str
    nombre_archivo: str
    url_descarga: str
    tamaño_bytes: int
    fecha_generacion: datetime
    mensaje: str = "Reporte exportado exitosamente."


class ReporteHistorialItem(RetailProBaseModel):
    id_auditoria: int
    nombre: str
    tipo: str
    fecha: datetime
    formato: str
    tamano_bytes: int
    usuario: str
    nombre_archivo: str
    url_descarga: str


class ReporteHistorialResponse(RetailProBaseModel):
    total_reportes: int
    page: int
    limit: int
    items: List[ReporteHistorialItem]
