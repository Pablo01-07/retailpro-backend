import datetime
from typing import Optional, List, Dict, Any
from app.schemas.common import RetailProBaseModel


class EstadoItem(RetailProBaseModel):
    ultima_actualizacion: Optional[datetime.datetime] = None
    total_registros: int
    estado: str
    detalle: Optional[str] = None


class CategoriasItem(RetailProBaseModel):
    total_categorias: int
    categorias: List[Dict[str, Any]]


class EstadoDatosResponse(RetailProBaseModel):
    ventas: EstadoItem
    inventario: EstadoItem
    catalogo: EstadoItem
    categorias: CategoriasItem


class IncidenciaItem(RetailProBaseModel):
    fila: int
    columna: str
    tipo_error: str
    tipo_error_etiqueta: Optional[str] = None
    etiqueta: Optional[str] = None
    motivo: str
    valor: Optional[str] = None


class IncidenciaFrecuenteItem(RetailProBaseModel):
    codigo: str
    etiqueta: str
    cantidad: int
    porcentaje: Optional[float] = None


class CargaDatosResponse(RetailProBaseModel):
    id_carga: int
    id_usuario: Optional[int] = None
    tipo_carga: str
    tipo_carga_etiqueta: Optional[str] = None
    tipo_informacion_etiqueta: Optional[str] = None
    nombre_archivo: Optional[str] = None
    fecha_ejecucion: datetime.datetime
    estado: str
    estado_display: Optional[str] = None
    registros_procesados: int
    registros_rechazados: int
    porcentaje_calidad: float
    detalle_error: Optional[str] = None


class UploadResultResponse(RetailProBaseModel):
    id_carga: int
    tipo_carga: str
    tipo_carga_etiqueta: Optional[str] = None
    tipo_informacion_etiqueta: Optional[str] = None
    nombre_archivo: Optional[str] = None
    estado: str
    estado_display: str
    registros_procesados: int
    registros_validos: int
    registros_rechazados: int
    porcentaje_calidad: float
    umbral_calidad: float
    apto_para_procesar: bool
    resumen_errores: Dict[str, int]
    resumen_errores_etiquetas: Optional[Dict[str, int]] = None
    incidencias_frecuentes: Optional[List[IncidenciaFrecuenteItem]] = None
    mensaje: str


class CargaDetalleResponse(RetailProBaseModel):
    carga: CargaDatosResponse
    nombre_archivo: Optional[str] = None
    resumen: Dict[str, Any]
    etapas: List[Dict[str, Any]]
    muestra_incidencias: List[IncidenciaItem]


class CalidadGlobalResponse(RetailProBaseModel):
    calidad_promedio_pct: float
    umbral_minimo_pct: float
    total_cargas: int
    cargas_conformes: int
    cargas_no_conformes: int
    total_registros_procesados: int
    total_registros_rechazados: int
    desglose_errores: Dict[str, int]
    desglose_errores_etiquetas: Optional[Dict[str, int]] = None
    incidencias_frecuentes: Optional[List[IncidenciaFrecuenteItem]] = None
    historico_cargas: List[Dict[str, Any]]
