from typing import List, Optional, Dict, Any
from pydantic import Field
from datetime import date, datetime
from decimal import Decimal
from app.schemas.common import RetailProBaseModel


class FactoresShapItem(RetailProBaseModel):
    feature: str
    impacto: float


class PronosticoDiaItem(RetailProBaseModel):
    horizonte_dias: int
    fecha_objetivo: date
    cantidad_proyectada: float
    intervalo_confianza_inf: float
    intervalo_confianza_sup: float
    nivel_incertidumbre: str
    explicacion_shap: Optional[Dict[str, Any]] = None


class PronosticoSkuResumen(RetailProBaseModel):
    id_producto: int
    sku: str
    nombre_producto: str
    categoria: str
    stock_actual: int
    punto_reorden: int
    demanda_total_proyectada_14d: float
    probabilidad_quiebre: float
    nivel_incertidumbre: str
    fecha_generacion: Optional[datetime] = None
    version_modelo: str
    estado: Optional[str] = "activo"
    pronostico_disponible: bool = True
    historial_suficiente: bool = True


class PronosticoSkuDetalle(RetailProBaseModel):
    id_producto: int
    sku: str
    nombre_producto: str
    categoria: str
    stock_actual: int
    punto_reorden: int
    demanda_total_proyectada_14d: float
    probabilidad_quiebre: float
    nivel_incertidumbre: str
    fecha_generacion: Optional[datetime] = None
    id_modelo: int
    version_modelo: str
    mape_modelo: Optional[float] = None
    serie_14_dias: List[PronosticoDiaItem]
    historico_reciente: List[Dict[str, Any]]
    pronostico_disponible: bool = True


class PronosticoListResponse(RetailProBaseModel):
    total_skus: int
    fecha_generacion: Optional[datetime] = None
    version_modelo: Optional[str] = None
    items: List[PronosticoSkuResumen]


class TendenciaMensualItem(RetailProBaseModel):
    mes: str
    venta_real: float
    venta_proyectada: float
    error_absoluto: float
    mape_mensual: float


class TendenciasResponse(RetailProBaseModel):
    total_meses: int
    items: List[TendenciaMensualItem]
