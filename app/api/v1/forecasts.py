from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, timedelta, date

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles, RoleCode
from app.models.usuario import Usuario
from app.models.producto import Producto
from app.models.modelo_version import ModeloVersion
from app.models.pronostico import Pronostico
from app.models.venta_historica import VentaHistorica
from app.services.ml_service import MLForecastService
from app.schemas.forecast import (
    PronosticoListResponse,
    PronosticoSkuResumen,
    PronosticoSkuDetalle,
    PronosticoDiaItem,
    TendenciasResponse,
    TendenciaMensualItem
)

router = APIRouter(prefix="/pronosticos", tags=["Pronósticos de Ventas"])


@router.get("", response_model=PronosticoListResponse)
def list_pronosticos_resumen(
    categoria: Optional[str] = Query(None, description="Filtrar por categoría de producto"),
    incluir_sin_pronostico: bool = Query(False, description="Incluir productos sin pronóstico vigente"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Lista el resumen de pronósticos activos a 14 días para todos los SKUs (Pantalla 10).
    """
    modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    q_prod = db.query(Producto)
    if categoria:
        q_prod = q_prod.filter(Producto.categoria == categoria)
    productos = q_prod.all()
    ids_insuf = MLForecastService.obtener_ids_productos_con_historial_insuficiente(db)

    if not modelo_activo:
        if incluir_sin_pronostico:
            items = [
                PronosticoSkuResumen(
                    id_producto=prod.id_producto,
                    sku=prod.sku,
                    nombre_producto=prod.nombre,
                    categoria=prod.categoria,
                    stock_actual=prod.stock_actual,
                    punto_reorden=prod.punto_reorden,
                    demanda_total_proyectada_14d=0.0,
                    probabilidad_quiebre=0.0,
                    nivel_incertidumbre="N/D",
                    fecha_generacion=None,
                    version_modelo="N/A",
                    estado=prod.estado,
                    pronostico_disponible=False,
                    historial_suficiente=(prod.id_producto not in ids_insuf)
                )
                for prod in productos
            ]
            return PronosticoListResponse(total_skus=len(items), fecha_generacion=None, version_modelo=None, items=items)
        return PronosticoListResponse(total_skus=0, fecha_generacion=None, version_modelo=None, items=[])

    max_fecha_gen = db.query(func.max(Pronostico.fecha_generacion)).filter(
        Pronostico.id_modelo == modelo_activo.id_modelo
    ).scalar()

    if not max_fecha_gen:
        if incluir_sin_pronostico:
            items = [
                PronosticoSkuResumen(
                    id_producto=prod.id_producto,
                    sku=prod.sku,
                    nombre_producto=prod.nombre,
                    categoria=prod.categoria,
                    stock_actual=prod.stock_actual,
                    punto_reorden=prod.punto_reorden,
                    demanda_total_proyectada_14d=0.0,
                    probabilidad_quiebre=0.0,
                    nivel_incertidumbre="N/D",
                    fecha_generacion=None,
                    version_modelo=modelo_activo.version,
                    estado=prod.estado,
                    pronostico_disponible=False,
                    historial_suficiente=(prod.id_producto not in ids_insuf)
                )
                for prod in productos
            ]
            return PronosticoListResponse(total_skus=len(items), fecha_generacion=None, version_modelo=modelo_activo.version, items=items)
        return PronosticoListResponse(total_skus=0, fecha_generacion=None, version_modelo=modelo_activo.version, items=[])

    pronosticos = db.query(Pronostico).filter(
        Pronostico.id_modelo == modelo_activo.id_modelo,
        Pronostico.fecha_generacion == max_fecha_gen
    ).all()

    pron_by_prod = {}
    for p in pronosticos:
        pron_by_prod.setdefault(p.id_producto, []).append(p)

    items = []
    fecha_gen = None

    for prod in productos:
        p_list = pron_by_prod.get(prod.id_producto, [])
        if not p_list:
            if not incluir_sin_pronostico:
                continue
            items.append(PronosticoSkuResumen(
                id_producto=prod.id_producto,
                sku=prod.sku,
                nombre_producto=prod.nombre,
                categoria=prod.categoria,
                stock_actual=prod.stock_actual,
                punto_reorden=prod.punto_reorden,
                demanda_total_proyectada_14d=0.0,
                probabilidad_quiebre=0.0,
                nivel_incertidumbre="N/D",
                fecha_generacion=None,
                version_modelo=modelo_activo.version,
                estado=prod.estado,
                pronostico_disponible=False,
                historial_suficiente=(prod.id_producto not in ids_insuf)
            ))
            continue

        p_list = sorted(p_list, key=lambda x: x.horizonte_dias)
        fecha_gen = p_list[0].fecha_generacion

        demanda_total = sum(float(x.cantidad_proyectada) for x in p_list)
        prob_quiebre = 0.0
        if p_list[0].explicacion_shap and isinstance(p_list[0].explicacion_shap, dict):
            prob_quiebre = float(p_list[0].explicacion_shap.get("probabilidad_quiebre", 0.0))

        niveles = [x.nivel_incertidumbre for x in p_list]
        nivel_pred = max(set(niveles), key=niveles.count) if niveles else "MEDIO"

        items.append(PronosticoSkuResumen(
            id_producto=prod.id_producto,
            sku=prod.sku,
            nombre_producto=prod.nombre,
            categoria=prod.categoria,
            stock_actual=prod.stock_actual,
            punto_reorden=prod.punto_reorden,
            demanda_total_proyectada_14d=round(demanda_total, 2),
            probabilidad_quiebre=prob_quiebre,
            nivel_incertidumbre=nivel_pred,
            fecha_generacion=fecha_gen,
            version_modelo=modelo_activo.version,
            estado=prod.estado,
            pronostico_disponible=True,
            historial_suficiente=(prod.id_producto not in ids_insuf)
        ))

    return PronosticoListResponse(
        total_skus=len(items),
        fecha_generacion=fecha_gen,
        version_modelo=modelo_activo.version,
        items=items
    )


@router.get("/tendencias", response_model=TendenciasResponse)
def get_tendencias_ventas(
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    sku: Optional[str] = Query(None, description="Filtrar por SKU"),
    fecha_inicio: Optional[date] = Query(None, description="Fecha de corte desde"),
    fecha_fin: Optional[date] = Query(None, description="Fecha de corte hasta"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Comparativa de Demanda Histórica vs Pronosticada mes a mes (Pantalla 15).
    Soporta filtros por categoria, sku, fecha_inicio y fecha_fin sobre los datos sintéticos de retail.
    Se deriva de los cortes del walk-forward backtest registrados en la tabla 'pronostico'
    y la tabla 'venta_historica'.
    """
    q_mb = db.query(ModeloVersion).filter(
        ModeloVersion.motivo_entrenamiento == "backtest"
    )
    if fecha_inicio:
        q_mb = q_mb.filter(func.date(ModeloVersion.fecha_entrenamiento) >= fecha_inicio)
    if fecha_fin:
        q_mb = q_mb.filter(func.date(ModeloVersion.fecha_entrenamiento) <= fecha_fin)

    modelos_backtest = q_mb.order_by(ModeloVersion.fecha_entrenamiento).all()

    items = []
    mapes = []

    for mb in modelos_backtest:
        corte_dt = mb.fecha_entrenamiento
        mes_str = corte_dt.strftime("%Y-%m")

        q_pron = db.query(Pronostico).join(Producto, Pronostico.id_producto == Producto.id_producto).filter(
            Pronostico.id_modelo == mb.id_modelo
        )
        if categoria:
            q_pron = q_pron.filter(Producto.categoria == categoria)
        if sku:
            q_pron = q_pron.filter(Producto.sku == sku.upper().strip())

        pronosticos = q_pron.all()

        if not pronosticos:
            continue

        suma_proy = sum(float(p.cantidad_proyectada) for p in pronosticos)

        fechas_val = [corte_dt.date() + timedelta(days=h) for h in range(1, 15)]
        q_ventas = db.query(func.sum(VentaHistorica.cantidad_vendida)).join(
            Producto, VentaHistorica.id_producto == Producto.id_producto
        ).filter(
            VentaHistorica.fecha.in_(fechas_val)
        )
        if categoria:
            q_ventas = q_ventas.filter(Producto.categoria == categoria)
        if sku:
            q_ventas = q_ventas.filter(Producto.sku == sku.upper().strip())

        ventas_val = q_ventas.scalar() or 0

        suma_real = float(ventas_val)
        err_abs = abs(suma_real - suma_proy)
        mape_mes = round((err_abs / suma_real * 100.0), 2) if suma_real > 0 else (float(mb.mape) if mb.mape else 0.0)
        mapes.append(mape_mes)

        items.append(TendenciaMensualItem(
            mes=mes_str,
            venta_real=round(suma_real, 2),
            venta_proyectada=round(suma_proy, 2),
            error_absoluto=round(err_abs, 2),
            mape_mensual=round(mape_mes, 2)
        ))

    avg_mape = round(sum(mapes) / len(mapes), 2) if mapes else 0.0
    return TendenciasResponse(
        total_meses=len(items),
        mape_promedio=avg_mape,
        items=items
    )


@router.get("/{sku_or_id}", response_model=PronosticoSkuDetalle)
def get_pronostico_detalle_sku(
    sku_or_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Detalle diario a 14 días con intervalos de confianza y SHAP para un SKU específico (Pantalla 10).
    """
    if sku_or_id.isdigit():
        prod = db.query(Producto).filter(Producto.id_producto == int(sku_or_id)).first()
    else:
        prod = db.query(Producto).filter(Producto.sku == sku_or_id.strip().upper()).first()

    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con identificador o SKU '{sku_or_id}' no encontrado."
        )

    if str(prod.estado).lower() == "descontinuado":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se generan pronósticos para productos descontinuados"
        )

    if not MLForecastService.tiene_historial_suficiente(db, prod.id_producto):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Historial insuficiente para generar un pronóstico confiable"
        )

    modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    if not modelo_activo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe un modelo de pronóstico activo actualmente."
        )

    max_fecha_gen = db.query(func.max(Pronostico.fecha_generacion)).filter(
        Pronostico.id_modelo == modelo_activo.id_modelo
    ).scalar()

    pronosticos = db.query(Pronostico).filter(
        Pronostico.id_modelo == modelo_activo.id_modelo,
        Pronostico.id_producto == prod.id_producto,
        Pronostico.fecha_generacion == max_fecha_gen
    ).order_by(Pronostico.horizonte_dias).all()

    if not pronosticos:
        ventas_recientes = db.query(VentaHistorica).filter(
            VentaHistorica.id_producto == prod.id_producto
        ).order_by(desc(VentaHistorica.fecha)).limit(30).all()

        historico = [
            {"fecha": v.fecha.isoformat(), "cantidad_vendida": v.cantidad_vendida, "precio": float(v.precio_unitario)}
            for v in reversed(ventas_recientes)
        ]

        return PronosticoSkuDetalle(
            id_producto=prod.id_producto,
            sku=prod.sku,
            nombre_producto=prod.nombre,
            categoria=prod.categoria,
            stock_actual=prod.stock_actual,
            punto_reorden=prod.punto_reorden,
            demanda_total_proyectada_14d=0.0,
            probabilidad_quiebre=0.0,
            nivel_incertidumbre="N/D",
            fecha_generacion=None,
            id_modelo=modelo_activo.id_modelo,
            version_modelo=modelo_activo.version,
            mape_modelo=float(modelo_activo.mape) if modelo_activo.mape else None,
            serie_14_dias=[],
            historico_reciente=historico,
            pronostico_disponible=False
        )

    fecha_gen = pronosticos[0].fecha_generacion
    prob_quiebre = 0.0
    if pronosticos[0].explicacion_shap and isinstance(pronosticos[0].explicacion_shap, dict):
        prob_quiebre = float(pronosticos[0].explicacion_shap.get("probabilidad_quiebre", 0.0))

    serie_14 = []
    for p in pronosticos:
        fecha_obj = (p.fecha_generacion + timedelta(days=p.horizonte_dias)).date()
        serie_14.append(PronosticoDiaItem(
            horizonte_dias=p.horizonte_dias,
            fecha_objetivo=fecha_obj,
            cantidad_proyectada=float(p.cantidad_proyectada),
            intervalo_confianza_inf=float(p.intervalo_confianza_inf),
            intervalo_confianza_sup=float(p.intervalo_confianza_sup),
            nivel_incertidumbre=p.nivel_incertidumbre,
            explicacion_shap=p.explicacion_shap
        ))

    demanda_total = sum(d.cantidad_proyectada for d in serie_14)
    niveles = [d.nivel_incertidumbre for d in serie_14]
    nivel_pred = max(set(niveles), key=niveles.count) if niveles else "MEDIO"

    ventas_recientes = db.query(VentaHistorica).filter(
        VentaHistorica.id_producto == prod.id_producto
    ).order_by(desc(VentaHistorica.fecha)).limit(30).all()

    historico = [
        {"fecha": v.fecha.isoformat(), "cantidad_vendida": v.cantidad_vendida, "precio": float(v.precio_unitario)}
        for v in reversed(ventas_recientes)
    ]

    return PronosticoSkuDetalle(
        id_producto=prod.id_producto,
        sku=prod.sku,
        nombre_producto=prod.nombre,
        categoria=prod.categoria,
        stock_actual=prod.stock_actual,
        punto_reorden=prod.punto_reorden,
        demanda_total_proyectada_14d=round(demanda_total, 2),
        probabilidad_quiebre=prob_quiebre,
        nivel_incertidumbre=nivel_pred,
        fecha_generacion=fecha_gen,
        id_modelo=modelo_activo.id_modelo,
        version_modelo=modelo_activo.version,
        mape_modelo=float(modelo_activo.mape) if modelo_activo.mape else None,
        serie_14_dias=serie_14,
        historico_reciente=historico,
        pronostico_disponible=True
    )
