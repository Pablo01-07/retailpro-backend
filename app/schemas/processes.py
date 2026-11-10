import datetime
from typing import Optional, List, Dict, Any
from pydantic import model_validator
from app.schemas.common import RetailProBaseModel
from app.services.email_service import parse_emails_destinatarios


class ProcesoConfigPatchRequest(RetailProBaseModel):
    activo: Optional[bool] = None
    frecuencia: Optional[str] = None
    hora: Optional[str] = None
    dia_semana: Optional[int] = None


class ProcesoConfigItemResponse(RetailProBaseModel):
    id_proceso: str
    nombre: str
    tipo: str
    activo: bool
    frecuencia: str
    hora: str
    dia_semana: Optional[int] = None
    dia: Optional[str] = None
    proxima_ejecucion: Optional[datetime.datetime] = None


class ProcesoConfigSchema(RetailProBaseModel):
    etl_activo: bool = True
    etl_frecuencia: str = "diario"
    etl_hora: str = "02:00"
    etl_dia: Optional[str] = None
    etl_dia_semana: Optional[int] = None
    etl_proxima_ejecucion: Optional[datetime.datetime] = None

    pronostico_activo: bool = True
    pronostico_frecuencia: str = "diario"
    pronostico_hora: str = "04:00"
    pronostico_dia: Optional[str] = None
    pronostico_dia_semana: Optional[int] = None
    pronostico_proxima_ejecucion: Optional[datetime.datetime] = None

    reentrenamiento_activo: bool = True
    reentrenamiento_frecuencia: str = "semanal"
    reentrenamiento_dia: str = "domingo"
    reentrenamiento_dia_semana: Optional[int] = 6
    reentrenamiento_hora: str = "01:00"
    reentrenamiento_proxima_ejecucion: Optional[datetime.datetime] = None

    alertas_notificacion_email: Optional[str] = "alertas@fasretail.com"
    correo_alertas: Optional[str] = "alertas@fasretail.com"
    quiebre_critico: bool = True
    notificar_quiebre: bool = True
    calidad_bajo_umbral: bool = True
    notificar_calidad_baja: bool = True
    sobrestock_prolongado: bool = True
    notificar_sobrestock: bool = True
    umbral_calidad: float = 90.0
    calidad_min: float = 90.0
    smtp_configurado: bool = False

    procesos: Optional[List[ProcesoConfigItemResponse]] = None

    @model_validator(mode="before")
    def validate_and_sync_notifications(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "correo_alertas" in data and data["correo_alertas"] is not None:
                parsed = parse_emails_destinatarios(data["correo_alertas"])
                data["correo_alertas"] = ", ".join(parsed)
                data["alertas_notificacion_email"] = ", ".join(parsed)
            elif "alertas_notificacion_email" in data and data["alertas_notificacion_email"] is not None:
                parsed = parse_emails_destinatarios(data["alertas_notificacion_email"])
                data["alertas_notificacion_email"] = ", ".join(parsed)
                data["correo_alertas"] = ", ".join(parsed)

            if "umbral_calidad" in data and data["umbral_calidad"] is not None:
                try:
                    val = float(data["umbral_calidad"])
                except (ValueError, TypeError):
                    raise ValueError("umbral_calidad debe ser un valor numérico.")
                if not (50.0 <= val <= 100.0):
                    raise ValueError("umbral_calidad debe estar comprendido entre 50.0% y 100.0%.")
                data["umbral_calidad"] = val
                data["calidad_min"] = val
            elif "calidad_min" in data and data["calidad_min"] is not None:
                try:
                    val = float(data["calidad_min"])
                except (ValueError, TypeError):
                    raise ValueError("calidad_min debe ser un valor numérico.")
                if not (50.0 <= val <= 100.0):
                    raise ValueError("calidad_min debe estar comprendido entre 50.0% y 100.0%.")
                data["calidad_min"] = val
                data["umbral_calidad"] = val

            if "quiebre_critico" in data:
                data["notificar_quiebre"] = bool(data["quiebre_critico"])
            elif "notificar_quiebre" in data:
                data["quiebre_critico"] = bool(data["notificar_quiebre"])

            if "calidad_bajo_umbral" in data:
                data["notificar_calidad_baja"] = bool(data["calidad_bajo_umbral"])
            elif "notificar_calidad_baja" in data:
                data["calidad_bajo_umbral"] = bool(data["notificar_calidad_baja"])

            if "sobrestock_prolongado" in data:
                data["notificar_sobrestock"] = bool(data["sobrestock_prolongado"])
            elif "notificar_sobrestock" in data:
                data["sobrestock_prolongado"] = bool(data["notificar_sobrestock"])

        return data


class ProcesoItemResponse(RetailProBaseModel):
    id_proceso: str
    nombre: str
    tipo: str
    frecuencia: str
    horario: str
    activo: bool = True
    ultima_ejecucion: Optional[datetime.datetime] = None
    proxima_ejecucion: Optional[datetime.datetime] = None
    estado_ultima_ejecucion: str
    id_ultima_carga: Optional[int] = None
    registros_afectados: int = 0


class EtapaProcesoItem(RetailProBaseModel):
    etapa: str
    estado: str
    timestamp: str
    duracion_ms: Optional[int] = None
    detalle: Optional[str] = None


class DetalleEjecucionResponse(RetailProBaseModel):
    id_carga: int
    tipo_proceso: str
    tipo_proceso_etiqueta: Optional[str] = None
    nombre_archivo: Optional[str] = None
    fecha_ejecucion: datetime.datetime
    estado: str
    registros_procesados: int
    registros_rechazados: int
    porcentaje_calidad: float
    duracion_total_segundos: Optional[float] = None
    etapas: List[EtapaProcesoItem]
    detalle_error: Optional[str] = None
    reintentos: int = 0
    reintentos_max: int = 3
    reintento_permitido: bool = False


class ReintentoEjecucionResponse(RetailProBaseModel):
    id_carga: int
    estado: str
    reintentos: int
    reintentos_max: int = 3
    reintento_permitido: bool
    mensaje: str
