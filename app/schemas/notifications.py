from datetime import datetime
from typing import Optional, List
from app.schemas.common import RetailProBaseModel


class NotificacionCargaItem(RetailProBaseModel):
    id_carga: int
    tipo_carga: str
    tipo_carga_etiqueta: str
    fecha_ejecucion: datetime
    registros_procesados: int
    porcentaje_calidad: float
    umbral_calidad: float
    tipo_notificacion: str
    mensaje: str
