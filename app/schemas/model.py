from typing import List, Optional, Dict, Any
from datetime import datetime
from app.schemas.common import RetailProBaseModel


class FeatureImportanceItem(RetailProBaseModel):
    feature: str
    importancia: float
    descripcion: Optional[str] = None


class FichaModeloResponse(RetailProBaseModel):
    id_modelo: int
    version: str
    algoritmo: str = "XGBoost Regressor"
    estado: str
    fecha_entrenamiento: datetime
    motivo_entrenamiento: str
    mae: Optional[float] = None
    mape: Optional[float] = None
    rmse: Optional[float] = None
    wape: Optional[float] = None
    mape_14d: Optional[float] = None
    cobertura_intervalo_95: Optional[float] = None
    umbral_mape_max: float = 15.0
    cumple_meta: bool = True
    parametros: Dict[str, Any]
    importancia_variables: List[FeatureImportanceItem]
    observacion: Optional[str] = None
    proximo_reentrenamiento_programado: Optional[datetime] = None


class ModeloHistorialItem(RetailProBaseModel):
    id_modelo: int
    version: str
    fecha_entrenamiento: datetime
    motivo_entrenamiento: str
    mae: Optional[float] = None
    mape: Optional[float] = None
    rmse: Optional[float] = None
    wape: Optional[float] = None
    mape_14d: Optional[float] = None
    estado: str
    observacion: Optional[str] = None


class MapeMensualMonitoreoItem(RetailProBaseModel):
    periodo: str
    corte: str
    mape: float
    mape_14d: Optional[float] = None
    rmse: float
    mae: float
    umbral_mape: float = 15.0
    estado_alerta: str


class ModeloMonitoreoResponse(RetailProBaseModel):
    version_activa: str
    mape_promedio_historico: float
    mape_14d: Optional[float] = None
    mape_14d_promedio_historico: Optional[float] = None
    umbral_mape_max: float = 15.0
    alerta_degradacion: bool
    total_cortes_evaluados: int
    wape: Optional[float] = None
    cobertura_intervalo_95: Optional[float] = None
    cobertura_fuera_muestra: Optional[float] = None
    serie_mensual: List[MapeMensualMonitoreoItem]
    proximo_reentrenamiento_programado: Optional[datetime] = None


class EntrenarModeloRequest(RetailProBaseModel):
    motivo: Optional[str] = "reentrenamiento_manual"


class EntrenarModeloResponse(RetailProBaseModel):
    mensaje: str


class ReevaluarModeloResponse(RetailProBaseModel):
    mensaje: str
    id_modelo: int
    version: str
    mape_14d: Optional[float] = None
    mape: Optional[float] = None
    mae: Optional[float] = None
    rmse: Optional[float] = None
    wape: Optional[float] = None
    cobertura_intervalo_95: Optional[float] = None
    cortes_evaluados: int


class DescartarModeloRequest(RetailProBaseModel):
    comentario: str


class MetricasModeloItem(RetailProBaseModel):
    id_modelo: int
    version: str
    estado: str
    mae: Optional[float] = None
    mape: Optional[float] = None
    rmse: Optional[float] = None
    wape: Optional[float] = None
    mape_14d: Optional[float] = None
    cobertura_intervalo_95: Optional[float] = None


class DiferenciaMetricasItem(RetailProBaseModel):
    mape_14d: Optional[float] = None
    mape: Optional[float] = None
    mae: Optional[float] = None
    rmse: Optional[float] = None
    wape: Optional[float] = None
    cobertura_intervalo_95: Optional[float] = None


class CorteComparacionItem(RetailProBaseModel):
    corte_idx: int
    periodo: str
    mape_14d_candidato: Optional[float] = None
    mape_14d_activa: Optional[float] = None
    diferencia: Optional[float] = None


class ComparacionModeloResponse(RetailProBaseModel):
    id_candidato: int
    version_candidato: str
    id_activa: Optional[int] = None
    version_activa: Optional[str] = None
    candidato: MetricasModeloItem
    activa: Optional[MetricasModeloItem] = None
    diferencia: DiferenciaMetricasItem
    cortes: List[CorteComparacionItem]
    cumple_umbral: bool
    mejora_vigente: bool
    comparacion_vigente: str = "equivalente"
    umbral_mape: float = 15.0
    umbral_mape_evaluacion: Optional[float] = None


class PublicarModeloResponse(RetailProBaseModel):
    mensaje: str
    id_modelo: int
    version: str
    estado: str
    observacion: Optional[str] = None


class DescartarModeloResponse(RetailProBaseModel):
    mensaje: str
    id_modelo: int
    version: str
    estado: str
    observacion: Optional[str] = None
