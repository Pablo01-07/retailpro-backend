import os
import json
import math
from typing import Optional, List, Dict, Any, Tuple
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles, RoleCode
from app.models.usuario import Usuario
from app.models.carga_datos import CargaDatos
from app.models.producto import Producto
from app.models.venta_historica import VentaHistorica
from app.models.umbral_configuracion import UmbralConfiguracion
from app.schemas.data import (
    EstadoDatosResponse,
    EstadoItem,
    CategoriasItem,
    UploadResultResponse,
    CargaDatosResponse,
    CargaDetalleResponse,
    CalidadGlobalResponse,
    IncidenciaItem,
    IncidenciaFrecuenteItem
)
from app.services.etl_service import (
    validate_file_content,
    procesar_registros_validos,
    sincronizar_archivos_locales,
    get_storage_carga_dir,
    get_calidad_min_threshold,
    get_estado_display,
    get_carga_nombre_archivo,
    get_carga_metadata,
    get_incidencia_etiqueta,
    get_tipo_carga_etiqueta
)

router = APIRouter(prefix="/datos", tags=["Gestión de Datos y Calidad"])


@router.get("/estado", response_model=EstadoDatosResponse)
def get_estado_datos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Obtiene el estado general de las 4 dimensiones de datos de la plataforma (Mockup 03):
    1. Ventas históricas
    2. Inventario de almacén
    3. Catálogo de productos
    4. Categorías de productos
    """
    ult_carga_ventas = db.query(CargaDatos).filter(
        CargaDatos.tipo_carga == "ventas",
        CargaDatos.estado == "COMPLETADO"
    ).order_by(CargaDatos.fecha_ejecucion.desc()).first()
    total_ventas = db.query(VentaHistorica).count()
    ventas_item = EstadoItem(
        ultima_actualizacion=ult_carga_ventas.fecha_ejecucion if ult_carga_ventas else None,
        total_registros=total_ventas,
        estado="Actualizado" if total_ventas > 0 else "Sin datos",
        detalle=f"{total_ventas} registros de ventas diarias consolidados"
    )

    ult_carga_inv = db.query(CargaDatos).filter(
        CargaDatos.tipo_carga == "inventario",
        CargaDatos.estado == "COMPLETADO"
    ).order_by(CargaDatos.fecha_ejecucion.desc()).first()
    skus_con_stock = db.query(Producto).filter(Producto.stock_actual > 0).count()
    inv_item = EstadoItem(
        ultima_actualizacion=ult_carga_inv.fecha_ejecucion if ult_carga_inv else None,
        total_registros=skus_con_stock,
        estado="Actualizado" if skus_con_stock > 0 else "Pendiente",
        detalle=f"{skus_con_stock} SKUs con balance de stock disponible"
    )

    ult_carga_prod = db.query(CargaDatos).filter(
        CargaDatos.tipo_carga == "productos",
        CargaDatos.estado == "COMPLETADO"
    ).order_by(CargaDatos.fecha_ejecucion.desc()).first()
    total_productos = db.query(Producto).filter(Producto.estado == "activo").count()
    cat_item = EstadoItem(
        ultima_actualizacion=ult_carga_prod.fecha_ejecucion if ult_carga_prod else None,
        total_registros=total_productos,
        estado="Activo" if total_productos > 0 else "Sin catálogo",
        detalle=f"{total_productos} productos activos en catálogo maestro"
    )

    categorias_query = db.query(
        Producto.categoria,
        func.count(Producto.id_producto).label("total_skus")
    ).group_by(Producto.categoria).all()

    categorias_list = [{"categoria": r[0], "total_skus": r[1]} for r in categorias_query]
    categ_item = CategoriasItem(
        total_categorias=len(categorias_list),
        categorias=categorias_list
    )

    return EstadoDatosResponse(
        ventas=ventas_item,
        inventario=inv_item,
        catalogo=cat_item,
        categorias=categ_item
    )


@router.post("/sincronizar")
def sincronizar_datos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Sincroniza y procesa los archivos disponibles en la carpeta local storage/entrada/ (Mockup 03).
    Cumple con el Project Charter: NO conecta a sistemas ERP externos, solo ingesta local.
    """
    resultados = sincronizar_archivos_locales(db, user_id=current_user.id_usuario)
    return {
        "mensaje": f"Sincronización completada. Archivos procesados: {len(resultados)}",
        "archivos": resultados
    }


@router.post("/upload", response_model=UploadResultResponse)
async def upload_file(
    file: UploadFile = File(...),
    tipo_carga: str = Form(..., description="Tipo de datos: productos, inventario, ventas"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Carga un archivo CSV o Excel, ejecuta el motor de validación de calidad y genera el resumen (Mockup 04).
    Compara con el umbral calidad_min (98%) y determina si el lote es apto para procesar.
    """
    if not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de archivo no admitido. Debe ser CSV o Excel (.xlsx, .xls)."
        )

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo proporcionado está vacío."
        )

    try:
        carga, resumen = validate_file_content(
            db=db,
            file_bytes=file_bytes,
            filename=file.filename,
            tipo_carga=tipo_carga.lower().strip(),
            user_id=current_user.id_usuario
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    nombre_archivo = get_carga_nombre_archivo(carga.id_carga) or file.filename
    tipo_etiqueta = get_tipo_carga_etiqueta(carga.tipo_carga)

    desglose_raw = resumen.get("desglose_errores", {})
    desglose_etiquetas = {get_incidencia_etiqueta(k): v for k, v in desglose_raw.items()}
    total_errs = sum(desglose_raw.values())
    inc_frec = []
    for cod in ["nulos", "formato", "duplicados", "sku_inexistente", "atipicos"]:
        cant = desglose_raw.get(cod, 0)
        pct = round((cant / total_errs * 100), 2) if total_errs > 0 else 0.0
        inc_frec.append(IncidenciaFrecuenteItem(
            codigo=cod,
            etiqueta=get_incidencia_etiqueta(cod),
            cantidad=cant,
            porcentaje=pct
        ))
    inc_frec = sorted(inc_frec, key=lambda x: x.cantidad, reverse=True)

    return UploadResultResponse(
        id_carga=carga.id_carga,
        tipo_carga=carga.tipo_carga,
        tipo_carga_etiqueta=tipo_etiqueta,
        tipo_informacion_etiqueta=tipo_etiqueta,
        nombre_archivo=nombre_archivo,
        estado=carga.estado,
        estado_display=resumen.get("estado_display", carga.estado),
        registros_procesados=carga.registros_procesados,
        registros_validos=resumen["registros_validos"],
        registros_rechazados=carga.registros_rechazados,
        porcentaje_calidad=float(carga.porcentaje_calidad),
        umbral_calidad=resumen["umbral_calidad"],
        apto_para_procesar=resumen["apto_para_procesar"],
        resumen_errores=desglose_raw,
        resumen_errores_etiquetas=desglose_etiquetas,
        incidencias_frecuentes=inc_frec,
        mensaje=f"Archivo evaluado con éxito. Calidad: {carga.porcentaje_calidad}% ({resumen.get('estado_display', carga.estado)})."
    )


@router.get("/cargas", response_model=List[CargaDatosResponse])
def list_cargas(
    tipo_carga: Optional[str] = Query(None, description="Filtrar por tipo de carga"),
    estado: Optional[str] = Query(None, description="Filtrar por estado"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """Lista el historial de cargas y validaciones de datos con etiquetas en español y nombre de archivo."""
    query = db.query(CargaDatos)
    if tipo_carga:
        query = query.filter(CargaDatos.tipo_carga == tipo_carga)
    if estado:
        query = query.filter(CargaDatos.estado == estado)

    items = query.order_by(CargaDatos.id_carga.desc()).offset((page - 1) * size).limit(size).all()
    results = []
    for c in items:
        resp_item = CargaDatosResponse.model_validate(c)
        resp_item.estado_display = get_estado_display(c.estado, c.registros_rechazados)
        resp_item.nombre_archivo = get_carga_nombre_archivo(c.id_carga)
        tipo_etiq = get_tipo_carga_etiqueta(c.tipo_carga)
        resp_item.tipo_carga_etiqueta = tipo_etiq
        resp_item.tipo_informacion_etiqueta = tipo_etiq
        results.append(resp_item)
    return results


@router.get("/cargas/{id_carga}", response_model=CargaDetalleResponse)
def get_carga_detalle(
    id_carga: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """Obtiene el resultado detallado de una carga con sus etapas e incidencias (Mockup 05)."""
    carga = db.query(CargaDatos).filter(CargaDatos.id_carga == id_carga).first()
    if not carga:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carga no encontrada")

    nombre_archivo = get_carga_nombre_archivo(id_carga)
    tipo_etiq = get_tipo_carga_etiqueta(carga.tipo_carga)

    carga_dir = get_storage_carga_dir(id_carga)
    incidencias_path = os.path.join(carga_dir, "incidencias.json")
    etapas_path = os.path.join(carga_dir, "etapas.json")

    resumen = {}
    muestra_incidencias = []
    if os.path.exists(incidencias_path):
        with open(incidencias_path, "r", encoding="utf-8") as f:
            inc_data = json.load(f)
            resumen = inc_data.get("resumen", {})
            muestra_incidencias = inc_data.get("incidencias", [])[:50]

    etapas = []
    if os.path.exists(etapas_path):
        with open(etapas_path, "r", encoding="utf-8") as f:
            etapas = json.load(f)

    carga_resp = CargaDatosResponse.model_validate(carga)
    carga_resp.estado_display = get_estado_display(carga.estado, carga.registros_rechazados)
    carga_resp.nombre_archivo = nombre_archivo
    carga_resp.tipo_carga_etiqueta = tipo_etiq
    carga_resp.tipo_informacion_etiqueta = tipo_etiq

    incidencias_items = []
    for item in muestra_incidencias:
        t_err = item.get("tipo_error", "")
        etiq = get_incidencia_etiqueta(t_err)
        item_copy = dict(item)
        item_copy["tipo_error_etiqueta"] = etiq
        item_copy["etiqueta"] = etiq
        incidencias_items.append(IncidenciaItem(**item_copy))

    return CargaDetalleResponse(
        carga=carga_resp,
        nombre_archivo=nombre_archivo,
        resumen=resumen,
        etapas=etapas,
        muestra_incidencias=incidencias_items
    )


@router.post("/cargas/{id_carga}/procesar-validos")
def procesar_validos(
    id_carga: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Ingesta los registros válidos de una carga en la base de datos (Mockup 05).
    Excluye filas rechazadas preservando la trazabilidad.
    """
    try:
        resultado = procesar_registros_validos(db, id_carga, user_id=current_user.id_usuario)
        return resultado
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.delete("/cargas/{id_carga}")
def descartar_carga(
    id_carga: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """Descarta una carga de datos que no se desea procesar."""
    carga = db.query(CargaDatos).filter(CargaDatos.id_carga == id_carga).first()
    if not carga:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carga no encontrada")

    carga.estado = "DESCARTADO"
    db.commit()
    return {"mensaje": f"Carga {id_carga} descartada exitosamente.", "id_carga": id_carga, "estado": "DESCARTADO"}


@router.get("/cargas/{id_carga}/incidencias", response_model=List[IncidenciaItem])
def get_carga_incidencias(
    id_carga: int,
    tipo_error: Optional[str] = Query(None, description="Filtrar por tipo: nulo, duplicado, formato, etc."),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """Descarga o consulta todas las incidencias registradas en una carga con etiquetas en español (Mockup 06)."""
    carga_dir = get_storage_carga_dir(id_carga)
    incidencias_path = os.path.join(carga_dir, "incidencias.json")
    if not os.path.exists(incidencias_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No se encontraron incidencias para esta carga")

    with open(incidencias_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("incidencias", [])
    if tipo_error:
        items = [it for it in items if it.get("tipo_error") == tipo_error]

    res = []
    for it in items:
        t_err = it.get("tipo_error", "")
        etiq = get_incidencia_etiqueta(t_err)
        it_copy = dict(it)
        it_copy["tipo_error_etiqueta"] = etiq
        it_copy["etiqueta"] = etiq
        res.append(IncidenciaItem(**it_copy))

    return res


def _calcular_incidencias_frecuentes_helper(db: Session, tipo_informacion: Optional[str] = None) -> Tuple[Dict[str, int], List[IncidenciaFrecuenteItem]]:
    q_cargas = db.query(CargaDatos)
    if tipo_informacion:
        q_cargas = q_cargas.filter(CargaDatos.tipo_carga == tipo_informacion.lower().strip())
    else:
        q_cargas = q_cargas.filter(CargaDatos.tipo_carga.in_(["ventas", "productos", "inventario"]))

    cargas = q_cargas.order_by(CargaDatos.id_carga.desc()).all()
    desglose_total = {"nulos": 0, "formato": 0, "duplicados": 0, "sku_inexistente": 0, "atipicos": 0}

    for c in cargas:
        carga_dir = get_storage_carga_dir(c.id_carga)
        inc_path = os.path.join(carga_dir, "incidencias.json")
        if os.path.exists(inc_path):
            try:
                with open(inc_path, "r", encoding="utf-8") as f:
                    local_resumen = json.load(f).get("resumen", {})
                    desglose_local = local_resumen.get("desglose_errores", {})
                    for k, v in desglose_local.items():
                        std_k = "duplicados" if k == "duplicados_base" else k
                        if std_k in desglose_total:
                            desglose_total[std_k] = desglose_total.get(std_k, 0) + v
            except Exception:
                pass

    total_errores = sum(desglose_total.values())
    incidencias_frecuentes = []
    for cod in ["nulos", "formato", "duplicados", "sku_inexistente", "atipicos"]:
        cant = desglose_total.get(cod, 0)
        pct = round((cant / total_errores * 100), 2) if total_errores > 0 else 0.0
        incidencias_frecuentes.append(IncidenciaFrecuenteItem(
            codigo=cod,
            etiqueta=get_incidencia_etiqueta(cod),
            cantidad=cant,
            porcentaje=pct
        ))

    incidencias_frecuentes = sorted(incidencias_frecuentes, key=lambda x: x.cantidad, reverse=True)
    return desglose_total, incidencias_frecuentes


@router.get("/calidad/incidencias-frecuentes", response_model=List[IncidenciaFrecuenteItem])
@router.get("/incidencias/frecuentes", response_model=List[IncidenciaFrecuenteItem])
def get_incidencias_frecuentes(
    tipo_informacion: Optional[str] = Query(None, description="Filtrar por tipo: ventas, productos, inventario"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Obtiene el listado de incidencias más frecuentes con código y etiqueta oficial en español (Mockup 06).
    Etiquetas garantizadas: 'Valores nulos', 'Formato inválido', 'Registros duplicados', 'SKU inexistente en el catálogo', 'Valores atípicos'.
    """
    _, incidencias_frecuentes = _calcular_incidencias_frecuentes_helper(db, tipo_informacion)
    return incidencias_frecuentes


@router.get("/calidad", response_model=CalidadGlobalResponse)
def get_calidad_global(
    tipo_informacion: Optional[str] = Query(None, description="Filtrar por tipo: ventas, productos, inventario"),
    fecha_inicio: Optional[date] = Query(None, description="Fecha de ejecución desde"),
    fecha_fin: Optional[date] = Query(None, description="Fecha de ejecución hasta"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST]))
):
    """
    Panel consolidado de calidad de datos (Mockup 06):
    - Calidad promedio histórica
    - Proporción de cargas conformes vs no conformes
    - Desglose acumulado de errores por categoría con etiquetas en español
    - Evolución histórica de calidad por lote con timestamps ISO 8601 UTC ('Z')
    Soporta filtros por tipo_informacion, fecha_inicio y fecha_fin.
    """
    q_cargas = db.query(CargaDatos)
    if tipo_informacion:
        q_cargas = q_cargas.filter(CargaDatos.tipo_carga == tipo_informacion.lower().strip())
    else:
        q_cargas = q_cargas.filter(CargaDatos.tipo_carga.in_(["ventas", "productos", "inventario"]))

    if fecha_inicio:
        q_cargas = q_cargas.filter(func.date(CargaDatos.fecha_ejecucion) >= fecha_inicio)
    if fecha_fin:
        q_cargas = q_cargas.filter(func.date(CargaDatos.fecha_ejecucion) <= fecha_fin)

    cargas = q_cargas.order_by(CargaDatos.id_carga.desc()).all()

    total_cargas = len(cargas)
    umbral_min = get_calidad_min_threshold(db)

    if total_cargas == 0:
        return CalidadGlobalResponse(
            calidad_promedio_pct=100.0,
            umbral_minimo_pct=umbral_min,
            total_cargas=0,
            cargas_conformes=0,
            cargas_no_conformes=0,
            total_registros_procesados=0,
            total_registros_rechazados=0,
            desglose_errores={"nulos": 0, "formato": 0, "duplicados": 0, "sku_inexistente": 0, "atipicos": 0},
            desglose_errores_etiquetas={
                "Valores nulos": 0,
                "Formato inválido": 0,
                "Registros duplicados": 0,
                "SKU inexistente en el catálogo": 0,
                "Valores atípicos": 0
            },
            incidencias_frecuentes=[],
            historico_cargas=[]
        )

    total_proc = sum(c.registros_procesados for c in cargas)
    total_rech = sum(c.registros_rechazados for c in cargas)
    total_val = total_proc - total_rech
    calidad_promedio = round((total_val / total_proc * 100), 2) if total_proc > 0 else 100.00
    conformes = sum(1 for c in cargas if float(c.porcentaje_calidad) >= umbral_min)
    no_conformes = total_cargas - conformes

    desglose_total = {"nulos": 0, "formato": 0, "duplicados": 0, "sku_inexistente": 0, "atipicos": 0}
    for c in cargas:
        carga_dir = get_storage_carga_dir(c.id_carga)
        inc_path = os.path.join(carga_dir, "incidencias.json")
        if os.path.exists(inc_path):
            try:
                with open(inc_path, "r", encoding="utf-8") as f:
                    local_resumen = json.load(f).get("resumen", {})
                    desglose_local = local_resumen.get("desglose_errores", {})
                    for k, v in desglose_local.items():
                        std_k = "duplicados" if k == "duplicados_base" else k
                        if std_k in desglose_total:
                            desglose_total[std_k] = desglose_total.get(std_k, 0) + v
            except Exception:
                pass

    historico = []
    for c in cargas[:15]:
        nombre_arch = get_carga_nombre_archivo(c.id_carga)
        tipo_etiq = get_tipo_carga_etiqueta(c.tipo_carga)

        historico.append({
            "id_carga": c.id_carga,
            "tipo_carga": c.tipo_carga,
            "tipo_carga_etiqueta": tipo_etiq,
            "tipo_informacion_etiqueta": tipo_etiq,
            "nombre_archivo": nombre_arch,
            "fecha": c.fecha_ejecucion.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "porcentaje_calidad": float(c.porcentaje_calidad),
            "estado": c.estado,
            "estado_display": get_estado_display(c.estado, c.registros_rechazados),
            "registros_procesados": c.registros_procesados,
            "registros_rechazados": c.registros_rechazados
        })

    total_errores = sum(desglose_total.values())
    incidencias_frecuentes = []
    for cod in ["nulos", "formato", "duplicados", "sku_inexistente", "atipicos"]:
        cant = desglose_total.get(cod, 0)
        pct = round((cant / total_errores * 100), 2) if total_errores > 0 else 0.0
        incidencias_frecuentes.append(IncidenciaFrecuenteItem(
            codigo=cod,
            etiqueta=get_incidencia_etiqueta(cod),
            cantidad=cant,
            porcentaje=pct
        ))

    incidencias_frecuentes = sorted(incidencias_frecuentes, key=lambda x: x.cantidad, reverse=True)
    desglose_etiquetas = {
        get_incidencia_etiqueta(k): v for k, v in desglose_total.items()
    }

    return CalidadGlobalResponse(
        calidad_promedio_pct=calidad_promedio,
        umbral_minimo_pct=umbral_min,
        total_cargas=total_cargas,
        cargas_conformes=conformes,
        cargas_no_conformes=no_conformes,
        total_registros_procesados=total_proc,
        total_registros_rechazados=total_rech,
        desglose_errores=desglose_total,
        desglose_errores_etiquetas=desglose_etiquetas,
        incidencias_frecuentes=incidencias_frecuentes,
        historico_cargas=historico
    )
