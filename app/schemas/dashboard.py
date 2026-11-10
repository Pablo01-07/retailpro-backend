from typing import List, Optional, Dict, Any
from app.schemas.common import RetailProBaseModel


class KpiItem(RetailProBaseModel):
    nombre: str
    valor: str
    valor_numerico: Optional[float] = None
    unidad: Optional[str] = None
    tendencia_pct: Optional[float] = None
    estado: Optional[str] = None


class CategoriaResumen(RetailProBaseModel):
    categoria: str
    total_skus: int
    stock_total: int
    demanda_proyectada_14d: float
    nivel_servicio_estimado_pct: float
    alertas_quiebre: int
    alertas_sobrestock: int


class ProductoMasVendidoItem(RetailProBaseModel):
    sku: str
    nombre: str
    categoria: str
    unidades_vendidas: int
    ingresos_totales: float
    unidades_periodo_anterior: int
    variacion_pct: float
    periodo_dias: int = 30
    fecha_inicio: str
    fecha_fin: str


class DashboardResumenResponse(RetailProBaseModel):
    kpis: List[KpiItem]
    categorias: List[CategoriaResumen]
    top_riesgo_quiebre: List[Dict[str, Any]]
    tendencia_diaria_general: List[Dict[str, Any]]
    productos_mas_vendidos: List[ProductoMasVendidoItem] = []


class NivelServicioCategoriaItem(RetailProBaseModel):
    categoria: str
    total_skus: int
    skus_en_riesgo: int
    stock_total: int
    demanda_proyectada: float
    fill_rate_estimado_pct: float
    disponibilidad_catalogo_pct: float
    cumple_meta: bool


class NivelServicioResponse(RetailProBaseModel):
    meta_referencial_pct: float
    nivel_servicio_global_pct: float
    disponibilidad_global_pct: float
    total_skus: int
    skus_disponibles: int
    skus_en_riesgo: int
    es_estimacion: bool = True
    nota_metodologica: str
    almacenes: List[str] = ["Principal"]
    almacen_seleccionado: str = "Principal"
    categoria_filtrada: Optional[str] = None
    sku_filtrado: Optional[str] = None
    periodo_filtrado: Optional[str] = None
    linea_base_historica_disponible: bool = False
    mensaje_linea_base: Optional[str] = None
    por_categoria: List[NivelServicioCategoriaItem]
