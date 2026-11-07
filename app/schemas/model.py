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
    cobertura_intervalo_95: Optional[float] = None
    umbral_mape_max: float = 15.0
    cumple_meta: bool = True
    parametros: Dict[str, Any]
    importancia_variables: List[FeatureImportanceItem]


class ModeloHistorialItem(RetailProBaseModel):
    id_modelo: int
    version: str
    fecha_entrenamiento: datetime
    motivo_entrenamiento: str
    mae: Optional[float] = None
    mape: Optional[float] = None
    rmse: Optional[float] = None
    wape: Optional[float] = None
    estado: str


class MapeMensualMonitoreoItem(RetailProBaseModel):
    periodo: str
    corte: str
    mape: float
    rmse: float
    mae: float
    umbral_mape: float = 15.0
    estado_alerta: str


class ModeloMonitoreoResponse(RetailProBaseModel):
    version_activa: str
    mape_promedio_historico: float
    umbral_mape_max: float = 15.0
    alerta_degradacion: bool
    total_cortes_evaluados: int
    cobertura_intervalo_95: Optional[float] = None
    cobertura_fuera_muestra: Optional[float] = None
    serie_mensual: List[MapeMensualMonitoreoItem]


class EntrenarModeloRequest(RetailProBaseModel):
    motivo: Optional[str] = "reentrenamiento_manual"
