from typing import List, Optional
from pydantic import Field
from datetime import date, datetime
from app.schemas.common import RetailProBaseModel


class RecomendacionItem(RetailProBaseModel):
    id_pronostico: int
    id_producto: int
    sku: str
    nombre_producto: str
    categoria: str
    stock_actual: int
    punto_reorden: int
    demanda_proyectada_14d: float
    dias_cobertura: float
    probabilidad_quiebre: float
    cantidad_sugerida: int
    cantidad_ajustada: Optional[int] = None
    fecha_limite: Optional[date] = None
    prioridad: str
    motivo_prioridad: str


class ReposicionListResponse(RetailProBaseModel):
    total_recomendaciones: int
    fecha_generacion: Optional[datetime] = None
    total_sugerido_unidades: int
    items: List[RecomendacionItem]


class AjusteReposicionRequest(RetailProBaseModel):
    cantidad_ajustada: int = Field(..., ge=0, description="Cantidad ajustada por el analista (>= 0)")
    motivo_ajuste: Optional[str] = Field("Ajuste por lote mínimo / capacidad de almacén", description="Justificación del analista")


class AjusteReposicionResponse(RetailProBaseModel):
    id_pronostico: int
    id_producto: int
    sku: str
    cantidad_sugerida: int
    cantidad_ajustada: int
    mensaje: str = "Ajuste de reposición guardado exitosamente."


class ExportarReposicionRequest(RetailProBaseModel):
    formato: str = Field("xlsx", description="Formato: 'xlsx' o 'csv'")
    categoria: Optional[str] = None
    prioridad: Optional[str] = None
    solo_con_orden: bool = False
    sku: Optional[str] = None
    q: Optional[str] = None
    fecha_limite_desde: Optional[date] = None
    fecha_limite_hasta: Optional[date] = None
