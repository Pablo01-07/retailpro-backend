from typing import List, Optional
from pydantic import Field
from datetime import datetime
from app.schemas.common import RetailProBaseModel


class AlertaItem(RetailProBaseModel):
    id_alerta: int
    id_producto: int
    sku: str
    nombre_producto: str
    categoria: str
    tipo_alerta: str
    nivel_severidad: str
    prioridad: Optional[str] = "ALTA"
    fecha_generacion: datetime
    estado: str
    fecha_revision: Optional[datetime] = None
    stock_actual: int
    punto_reorden: int
    dias_cobertura: float
    probabilidad_quiebre: float
    detalle_motivo: str


class ConteosAlertas(RetailProBaseModel):
    activas: int
    criticas: int
    advertencias: int
    quiebre: int
    sobrestock: int
    resueltas: int
    descartadas: int = 0


class AlertasResumen(RetailProBaseModel):
    activas: int
    criticas: int
    advertencias: int
    quiebre: int
    sobrestock: int
    resueltas: int
    descartadas: int = 0
    total_activas: int
    total_criticas: int
    total_advertencias: int
    total_quiebre: int
    total_sobrestock: int
    total_resueltas: int
    total_descartadas: int = 0
    conteos: Optional[ConteosAlertas] = None
    items: List[AlertaItem]


class ActualizarEstadoAlertaRequest(RetailProBaseModel):
    nuevo_estado: str = Field(..., description="Nuevo estado: 'ACTIVA', 'RESUELTA', 'DESCARTADA'")
    comentario: Optional[str] = "Revisión operativa de inventario"


class UmbralItem(RetailProBaseModel):
    tipo_umbral: str
    nombre_display: str
    valor: float
    unidad: str
    descripcion: str
    fecha_actualizacion: Optional[datetime] = None


class UmbralesResponse(RetailProBaseModel):
    umbrales: List[UmbralItem]


class ActualizarUmbralesRequest(RetailProBaseModel):
    quiebre_prob_min: Optional[float] = Field(None, ge=0.0, le=100.0)
    quiebre_dias_cobertura: Optional[float] = Field(None, ge=1.0, le=90.0)
    sobrestock_pct: Optional[float] = Field(None, ge=100.0, le=500.0)
    sobrestock_dias: Optional[float] = Field(None, ge=15.0, le=365.0)
    calidad_min: Optional[float] = Field(None, ge=50.0, le=100.0)
    mape_max: Optional[float] = Field(None, ge=1.0, le=100.0)
    nivel_servicio_ref: Optional[float] = Field(None, ge=50.0, le=100.0)
