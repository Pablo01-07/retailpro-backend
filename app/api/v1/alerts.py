from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles, RoleCode
from app.models.usuario import Usuario
from app.models.umbral_configuracion import UmbralConfiguracion
from app.models.auditoria import Auditoria
from app.schemas.alerts import (
    AlertasResumen,
    ActualizarEstadoAlertaRequest,
    UmbralesResponse,
    UmbralItem,
    ActualizarUmbralesRequest
)
from app.services.alert_service import AlertService

router = APIRouter(tags=["Centro de Alertas y Configuración de Umbrales"])


@router.get("/alertas", response_model=AlertasResumen)
def list_alertas(
    tipo: Optional[str] = Query(None, description="Filtrar por tipo: 'QUIEBRE' o 'SOBRESTOCK'"),
    estado: Optional[str] = Query(None, description="Filtrar por estado: 'Activa', 'Resuelta', 'Descartada'"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    prioridad: Optional[str] = Query(None, description="Filtrar por prioridad ('ALTA', 'MEDIA', 'BAJA')"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Lista de alertas de inventario (quiebre y sobrestock) para la Pantalla 18.
    Sincroniza automáticamente antes de consultar para garantizar consistencia.
    """
    AlertService.sincronizar_alertas(db)
    return AlertService.list_alertas(db=db, tipo=tipo, estado=estado, categoria=categoria, prioridad=prioridad)


@router.patch("/alertas/{id_alerta}")
def actualizar_estado_alerta(
    id_alerta: int,
    payload: ActualizarEstadoAlertaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Actualiza el estado de una alerta ('ACTIVA', 'RESUELTA', 'DESCARTADA') con fecha_revision y auditoría.
    """
    st_norm = payload.nuevo_estado.strip().upper()
    if st_norm not in ["ACTIVA", "RESUELTA", "DESCARTADA"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Estado inválido. Debe ser 'ACTIVA', 'RESUELTA' o 'DESCARTADA'."
        )
    try:
        alerta = AlertService.cambiar_estado_alerta(
            db=db,
            id_alerta=id_alerta,
            nuevo_estado=st_norm,
            user_id=current_user.id_usuario,
            comentario=payload.comentario
        )
        return {
            "id_alerta": alerta.id_alerta,
            "nuevo_estado": alerta.estado,
            "fecha_revision": alerta.fecha_revision,
            "mensaje": f"Alerta {alerta.id_alerta} actualizada a '{alerta.estado}' exitosamente."
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/umbrales", response_model=UmbralesResponse)
def get_umbrales_configuracion(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Consulta los umbrales configurables del sistema para la Pantalla 19.
    """
    umbrales = db.query(UmbralConfiguracion).all()
    meta_info = {
        "quiebre_prob_min": ("Probabilidad Mínima de Quiebre", "%", "Umbral probabilístico para emitir alerta de rotura de stock"),
        "quiebre_dias_cobertura": ("Días Mínimos de Cobertura", "días", "Días de inventario restantes por debajo de los cuales se alerta riesgo"),
        "sobrestock_pct": ("Porcentaje Máximo de Demanda (Sobrestock)", "%", "Exceso porcentual de stock sobre la demanda proyectada"),
        "sobrestock_dias": ("Días Máximos de Cobertura (Sobrestock)", "días", "Días de inventario por encima de los cuales se inmoviliza capital"),
        "calidad_min": ("Calidad Mínima Aceptable de Datos", "%", "Porcentaje mínimo de calidad requerido para ingesta de archivos"),
        "mape_max": ("Tolerancia Máxima de Error (MAPE)", "%", "Error porcentual máximo admisible para el modelo predictivo"),
        "nivel_servicio_ref": ("Nivel de Servicio Referencial", "%", "Meta corporativa de disponibilidad de producto (OTIF)")
    }

    items = []
    for u in umbrales:
        nombre, unidad, desc = meta_info.get(u.tipo_umbral, (u.tipo_umbral, "", "Umbral de configuración"))
        items.append(UmbralItem(
            tipo_umbral=u.tipo_umbral,
            nombre_display=nombre,
            valor=float(u.valor),
            unidad=unidad,
            descripcion=desc,
            fecha_actualizacion=u.fecha_actualizacion
        ))

    return UmbralesResponse(umbrales=items)


@router.put("/umbrales", response_model=UmbralesResponse)
def actualizar_umbrales_configuracion(
    payload: ActualizarUmbralesRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN]))
):
    """
    Actualiza los umbrales del sistema (Pantalla 19).
    Dispara automáticamente el recálculo y sincronización de las alertas.
    Solo permitido para el rol 'administrador'.
    """
    data_in = payload.model_dump(exclude_unset=True)
    umbrales_guardados = {u.tipo_umbral: float(u.valor) for u in db.query(UmbralConfiguracion).all()}

    res_sobrestock_dias = float(data_in["sobrestock_dias"]) if "sobrestock_dias" in data_in and data_in["sobrestock_dias"] is not None else umbrales_guardados.get("sobrestock_dias", 90.0)
    res_quiebre_dias = float(data_in["quiebre_dias_cobertura"]) if "quiebre_dias_cobertura" in data_in and data_in["quiebre_dias_cobertura"] is not None else umbrales_guardados.get("quiebre_dias_cobertura", 7.0)

    if res_sobrestock_dias <= res_quiebre_dias:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El umbral de sobrestock debe ser mayor al umbral de quiebre: los días máximos de cobertura en almacén deben ser mayores a los días de cobertura mínima."
        )

    cambios = {}
    for campo, val in data_in.items():
        if val is not None:
            u = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == campo).first()
            if u:
                cambios[campo] = {"anterior": float(u.valor), "nuevo": float(val)}
                u.valor = val
                u.id_usuario = current_user.id_usuario
                u.fecha_actualizacion = datetime.utcnow()
            else:
                cambios[campo] = {"anterior": None, "nuevo": float(val)}
                db.add(UmbralConfiguracion(
                    id_usuario=current_user.id_usuario,
                    tipo_umbral=campo,
                    valor=val,
                    fecha_actualizacion=datetime.utcnow()
                ))

    db.commit()

    AlertService.sincronizar_alertas(db)

    if cambios:
        audit = Auditoria(
            id_usuario=current_user.id_usuario,
            accion="CONFIGURACION_UMBRALES",
            modulo_afectado="configuracion",
            detalle={"umbrales_modificados": cambios}
        )
        db.add(audit)
        db.commit()

    return get_umbrales_configuracion(db=db, current_user=current_user)
