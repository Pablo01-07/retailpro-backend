import os
import json
import io
import time
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List, Tuple
from fastapi import HTTPException, status
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.models.carga_datos import CargaDatos
from app.models.producto import Producto
from app.models.venta_historica import VentaHistorica
from app.models.umbral_configuracion import UmbralConfiguracion
from app.core.audit import create_audit_log


ESTADOS_CARGA = {"PENDIENTE", "EN_PROGRESO", "COMPLETADO", "CON_ADVERTENCIAS", "FALLIDO"}

INCIDENCIA_ETIQUETAS: Dict[str, str] = {
    "nulo": "Valores nulos",
    "nulos": "Valores nulos",
    "formato": "Formato inválido",
    "duplicado": "Registros duplicados",
    "duplicados": "Registros duplicados",
    "duplicados_base": "Registros duplicados",
    "sku_inexistente": "SKU inexistente en el catálogo",
    "atipico": "Valores atípicos",
    "atipicos": "Valores atípicos"
}

TIPO_CARGA_ETIQUETAS: Dict[str, str] = {
    "ventas": "Transacciones de Ventas",
    "inventario": "Nivel de Stock",
    "productos": "Catálogo Maestro de Productos"
}


def get_incidencia_etiqueta(tipo_error: str) -> str:
    return INCIDENCIA_ETIQUETAS.get(str(tipo_error).lower().strip(), str(tipo_error))


def get_tipo_carga_etiqueta(tipo_carga: str) -> str:
    return TIPO_CARGA_ETIQUETAS.get(str(tipo_carga).lower().strip(), str(tipo_carga))


def get_carga_metadata(id_carga: int) -> Optional[Dict[str, Any]]:
    carga_dir = get_storage_carga_dir(id_carga)
    meta_path = os.path.join(carga_dir, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def get_carga_nombre_archivo(id_carga: int) -> Optional[str]:
    meta = get_carga_metadata(id_carga)
    if meta and isinstance(meta, dict):
        return meta.get("nombre_archivo") or meta.get("nombre_original")
    return None


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_calidad_min_threshold(db: Session) -> float:
    umbral = db.query(UmbralConfiguracion).filter(
        UmbralConfiguracion.tipo_umbral == "calidad_min"
    ).first()
    return float(umbral.valor) if umbral else float(settings.DEFAULT_DATA_QUALITY_THRESHOLD)


def get_storage_carga_dir(id_carga: int) -> str:
    path = os.path.join(settings.STORAGE_DIR, "cargas", str(id_carga))
    os.makedirs(path, exist_ok=True)
    return path


def get_estado_display(estado: str, rechazos: int = 0) -> str:
    if estado == "COMPLETADO":
        return "Completado"
    elif estado == "CON_ADVERTENCIAS":
        return "Completado con advertencias"
    elif estado == "FALLIDO":
        return "Fallido"
    elif estado == "EN_PROGRESO":
        return "En progreso"
    elif estado == "PENDIENTE":
        return "Pendiente de procesamiento (con observaciones)" if rechazos > 0 else "Pendiente de procesamiento"
    return estado


def validate_file_content(
    db: Session,
    file_bytes: bytes,
    filename: str,
    tipo_carga: str,
    user_id: Optional[int] = None,
    carga_existente: Optional[CargaDatos] = None
) -> Tuple[CargaDatos, Dict[str, Any]]:
    inicio_ms = int(time.time() * 1000)
    etapas = []

    t0 = time.time()
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        else:
            raise ValueError(f"Formato no soportado para el archivo '{filename}'. Use CSV o Excel (.xlsx).")
    except Exception as e:
        raise ValueError(f"Error al parsear el archivo: {str(e)}")

    duracion_lectura = int((time.time() - t0) * 1000)
    etapas.append({
        "etapa": "Lectura y parseo del archivo",
        "estado": "exitoso",
        "timestamp": get_utc_now().isoformat(),
        "duracion_ms": duracion_lectura,
        "detalle": f"Filas leídas: {len(df)}"
    })

    df.columns = [str(col).strip().lower() for col in df.columns]

    t0 = time.time()
    columnas_requeridas = {
        "productos": ["sku", "nombre", "categoria"],
        "inventario": ["sku", "stock_actual", "punto_reorden"],
        "ventas": ["fecha", "sku", "cantidad_vendida", "precio_unitario"]
    }

    if tipo_carga not in columnas_requeridas:
        raise ValueError(f"Tipo de carga '{tipo_carga}' no reconocido. Tipos permitidos: productos, inventario, ventas")

    req_cols = columnas_requeridas[tipo_carga]
    faltantes = [c for c in req_cols if c not in df.columns]
    if faltantes:
        raise ValueError(f"Columnas requeridas faltantes para '{tipo_carga}': {', '.join(faltantes)}")

    etapas.append({
        "etapa": "Validación de esquema y columnas",
        "estado": "exitoso",
        "timestamp": get_utc_now().isoformat(),
        "duracion_ms": int((time.time() - t0) * 1000),
        "detalle": f"Columnas conformes: {', '.join(req_cols)}"
    })

    t0 = time.time()
    incidencias = []
    filas_rechazadas_set = set()
    desglose_errores = {
        "nulos": 0,
        "formato": 0,
        "duplicados": 0,
        "duplicados_base": 0,
        "sku_inexistente": 0,
        "atipicos": 0
    }

    skus_existentes = set()
    ventas_existentes_db = set()
    if tipo_carga == "ventas":
        skus_existentes = set(r[0] for r in db.query(Producto.sku).all())
        ventas_existentes_db = set(
            f"{r[1].strftime('%Y-%m-%d')}_{r[0].upper()}"
            for r in db.query(Producto.sku, VentaHistorica.fecha)
            .join(Producto, VentaHistorica.id_producto == Producto.id_producto).all()
        )

    iqr_por_sku = {}
    if tipo_carga == "ventas":
        cantidades_por_sku = {}
        for _, r in df.iterrows():
            sku_k = str(r.get("sku", "")).strip().upper()
            try:
                c_val = float(r.get("cantidad_vendida", 0))
                if c_val >= 0:
                    cantidades_por_sku.setdefault(sku_k, []).append(c_val)
            except Exception:
                pass

        for sku_k, vals in cantidades_por_sku.items():
            if len(vals) >= 4:
                s = pd.Series(vals)
                q1 = s.quantile(0.25)
                q3 = s.quantile(0.75)
                iqr = q3 - q1
                iqr_por_sku[sku_k] = max(20.0, float(q3 + 3.0 * iqr))

    vistos_claves_archivo = set()

    for idx, row in df.iterrows():
        fila_num = idx + 2
        tiene_error = False

        for col in req_cols:
            val = row.get(col)
            if pd.isna(val) or val is None or str(val).strip() == "" or str(val).strip().lower() in ["nan", "null", "none"]:
                incidencias.append({
                    "fila": fila_num,
                    "columna": col,
                    "tipo_error": "nulo",
                    "motivo": f"El campo '{col}' es obligatorio y no puede ser nulo o vacío.",
                    "valor": str(val) if val is not None else ""
                })
                desglose_errores["nulos"] += 1
                tiene_error = True

        if tiene_error:
            filas_rechazadas_set.add(idx)
            continue

        sku_val = str(row["sku"]).strip().upper()

        if tipo_carga in ["productos", "inventario"]:
            clave_dup = sku_val
        else:
            fecha_val_raw = str(row["fecha"]).strip()
            clave_dup = f"{fecha_val_raw}_{sku_val}"

        if clave_dup in vistos_claves_archivo:
            incidencias.append({
                "fila": fila_num,
                "columna": "sku" if tipo_carga != "ventas" else "fecha, sku",
                "tipo_error": "duplicado",
                "motivo": f"Registro duplicado dentro del archivo para la clave '{clave_dup}'.",
                "valor": clave_dup
            })
            desglose_errores["duplicados"] += 1
            tiene_error = True
        else:
            vistos_claves_archivo.add(clave_dup)

        if tipo_carga == "ventas":
            fecha_str = str(row["fecha"]).strip()
            parsed_date = None
            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"]:
                try:
                    parsed_date = datetime.strptime(fecha_str, fmt).date()
                    break
                except ValueError:
                    pass

            if not parsed_date:
                incidencias.append({
                    "fila": fila_num,
                    "columna": "fecha",
                    "tipo_error": "formato",
                    "motivo": f"Formato de fecha inválido '{fecha_str}'. Debe ser YYYY-MM-DD.",
                    "valor": fecha_str
                })
                desglose_errores["formato"] += 1
                tiene_error = True

            try:
                cant = int(float(row["cantidad_vendida"]))
                if cant < 0:
                    incidencias.append({
                        "fila": fila_num,
                        "columna": "cantidad_vendida",
                        "tipo_error": "formato",
                        "motivo": f"La cantidad vendida no puede ser negativa ({cant}).",
                        "valor": str(cant)
                    })
                    desglose_errores["formato"] += 1
                    tiene_error = True
                else:
                    umbral_atipico = iqr_por_sku.get(sku_val)
                    if umbral_atipico and cant > umbral_atipico:
                        incidencias.append({
                            "fila": fila_num,
                            "columna": "cantidad_vendida",
                            "tipo_error": "atipico",
                            "motivo": f"Valor atípico detectado para SKU '{sku_val}': {cant} unidades supera el límite IQR ({umbral_atipico:.1f}).",
                            "valor": str(cant)
                        })
                        desglose_errores["atipicos"] += 1
            except (ValueError, TypeError):
                incidencias.append({
                    "fila": fila_num,
                    "columna": "cantidad_vendida",
                    "tipo_error": "formato",
                    "motivo": "La cantidad vendida debe ser un número entero válido.",
                    "valor": str(row["cantidad_vendida"])
                })
                desglose_errores["formato"] += 1
                tiene_error = True

            try:
                precio = float(row["precio_unitario"])
                if precio <= 0:
                    incidencias.append({
                        "fila": fila_num,
                        "columna": "precio_unitario",
                        "tipo_error": "formato",
                        "motivo": f"El precio unitario debe ser mayor a 0 ({precio}).",
                        "valor": str(precio)
                    })
                    desglose_errores["formato"] += 1
                    tiene_error = True
            except (ValueError, TypeError):
                incidencias.append({
                    "fila": fila_num,
                    "columna": "precio_unitario",
                    "tipo_error": "formato",
                    "motivo": "El precio unitario debe ser un valor decimal válido.",
                    "valor": str(row["precio_unitario"])
                })
                desglose_errores["formato"] += 1
                tiene_error = True

            if skus_existentes and str(row["sku"]).strip() not in skus_existentes:
                incidencias.append({
                    "fila": fila_num,
                    "columna": "sku",
                    "tipo_error": "sku_inexistente",
                    "motivo": f"El SKU '{row['sku']}' no existe en el catálogo de productos.",
                    "valor": str(row["sku"])
                })
                desglose_errores["sku_inexistente"] += 1
                tiene_error = True

            if not tiene_error and parsed_date:
                clave_db = f"{parsed_date.strftime('%Y-%m-%d')}_{sku_val}"
                if clave_db in ventas_existentes_db:
                    desglose_errores["duplicados_base"] += 1

        elif tipo_carga in ["productos", "inventario"]:
            for campo_num in ["stock_actual", "punto_reorden"]:
                if campo_num in df.columns:
                    val_num = row.get(campo_num)
                    if pd.notna(val_num) and str(val_num).strip() != "":
                        try:
                            n = int(float(val_num))
                            if n < 0:
                                incidencias.append({
                                    "fila": fila_num,
                                    "columna": campo_num,
                                    "tipo_error": "formato",
                                    "motivo": f"El campo '{campo_num}' no puede ser negativo ({n}).",
                                    "valor": str(n)
                                })
                                desglose_errores["formato"] += 1
                                tiene_error = True
                        except (ValueError, TypeError):
                            incidencias.append({
                                "fila": fila_num,
                                "columna": campo_num,
                                "tipo_error": "formato",
                                "motivo": f"El campo '{campo_num}' debe ser numérico.",
                                "valor": str(val_num)
                            })
                            desglose_errores["formato"] += 1
                            tiene_error = True

        if tipo_carga == "productos" and "estado" in df.columns:
            val_est = row.get("estado")
            if pd.notna(val_est) and str(val_est).strip() != "" and str(val_est).strip().lower() not in ["nan", "null", "none"]:
                st_str = str(val_est).strip().lower()
                if st_str not in ["activo", "descontinuado"]:
                    incidencias.append({
                        "fila": fila_num,
                        "columna": "estado",
                        "tipo_error": "formato",
                        "motivo": f"El campo 'estado' solo admite 'activo' o 'descontinuado' (valor recibido: '{val_est}').",
                        "valor": str(val_est)
                    })
                    desglose_errores["formato"] += 1
                    tiene_error = True

        if tiene_error:
            filas_rechazadas_set.add(idx)

    total_procesados = len(df)
    total_rechazados = len(filas_rechazadas_set)
    total_validos = total_procesados - total_rechazados

    porcentaje_calidad = round((total_validos / total_procesados * 100), 2) if total_procesados > 0 else 0.00
    calidad_min = get_calidad_min_threshold(db)

    if porcentaje_calidad < calidad_min:
        estado_carga = "FALLIDO"
        detalle_error = f"Calidad de datos ({porcentaje_calidad}%) inferior al umbral mínimo requerido ({calidad_min}%)."
    else:
        estado_carga = "PENDIENTE"
        if total_rechazados > 0:
            detalle_error = f"Validado con {total_rechazados} observaciones ({porcentaje_calidad}% calidad). Pendiente de consolidación."
        else:
            detalle_error = None

    etapas.append({
        "etapa": "Evaluación de reglas de calidad y consistencia",
        "estado": "exitoso" if estado_carga != "FALLIDO" else "error",
        "timestamp": get_utc_now().isoformat(),
        "duracion_ms": int((time.time() - t0) * 1000),
        "detalle": f"Válidos: {total_validos}, Rechazados: {total_rechazados}, Calidad: {porcentaje_calidad}%"
    })

    if carga_existente:
        carga = carga_existente
        carga.estado = estado_carga
        carga.registros_procesados = total_procesados
        carga.registros_rechazados = total_rechazados
        carga.porcentaje_calidad = porcentaje_calidad
        carga.detalle_error = detalle_error
        db.commit()
    else:
        carga = CargaDatos(
            id_usuario=user_id,
            tipo_carga=tipo_carga,
            fecha_ejecucion=get_utc_now(),
            estado=estado_carga,
            registros_procesados=total_procesados,
            registros_rechazados=total_rechazados,
            porcentaje_calidad=porcentaje_calidad,
            detalle_error=detalle_error
        )
        db.add(carga)
        db.commit()
        db.refresh(carga)

    if porcentaje_calidad < calidad_min:
        try:
            from app.services.scheduler import get_procesos_config
            from app.services.email_service import EmailService, parse_emails_destinatarios

            cfg = get_procesos_config()
            notificar_calidad = cfg.get("calidad_bajo_umbral", cfg.get("notificar_calidad_baja", True))
            if notificar_calidad:
                raw_email = cfg.get("correo_alertas") or cfg.get("alertas_notificacion_email", "alertas@fasretail.com")
                try:
                    destinatarios = parse_emails_destinatarios(raw_email)
                except Exception as ve:
                    logger.warning(f"Destinatarios de alertas inválidos en procesos.json: {ve}")
                    destinatarios = []

                if destinatarios:
                    EmailService.enviar_alerta_calidad(
                        destinatarios=destinatarios,
                        filename=filename,
                        calidad_obtenida=porcentaje_calidad,
                        umbral_requerido=calidad_min,
                        total_procesados=total_procesados,
                        total_rechazados=total_rechazados,
                        db=db
                    )
        except Exception as exc:
            logger.error(f"Error al enviar notificación de calidad insuficiente por correo: {exc}")

    carga_dir = get_storage_carga_dir(carga.id_carga)

    ext = os.path.splitext(filename)[1] or ".csv"
    with open(os.path.join(carga_dir, f"archivo_original{ext}"), "wb") as f:
        f.write(file_bytes)

    meta_path = os.path.join(carga_dir, "meta.json")
    reintentos_prev = 0
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f_prev:
                reintentos_prev = json.load(f_prev).get("reintentos", 0)
        except Exception:
            reintentos_prev = 0

    meta_data = {
        "id_carga": carga.id_carga,
        "nombre_archivo": filename,
        "nombre_original": filename,
        "tamano_bytes": len(file_bytes),
        "tipo_carga": tipo_carga,
        "tipo_carga_etiqueta": get_tipo_carga_etiqueta(tipo_carga),
        "fecha_subida": get_utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reintentos": reintentos_prev
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, indent=4, ensure_ascii=False)

    resumen = {
        "id_carga": carga.id_carga,
        "tipo_carga": tipo_carga,
        "tipo_carga_etiqueta": get_tipo_carga_etiqueta(tipo_carga),
        "filename": filename,
        "nombre_archivo": filename,
        "estado": carga.estado,
        "estado_display": get_estado_display(carga.estado, total_rechazados),
        "registros_procesados": total_procesados,
        "registros_validos": total_validos,
        "registros_rechazados": total_rechazados,
        "porcentaje_calidad": porcentaje_calidad,
        "umbral_calidad": calidad_min,
        "apto_para_procesar": (porcentaje_calidad >= calidad_min),
        "filas_rechazadas_indices": sorted(list(filas_rechazadas_set)),
        "desglose_errores": desglose_errores
    }

    with open(os.path.join(carga_dir, "incidencias.json"), "w", encoding="utf-8") as f:
        json.dump({
            "resumen": resumen,
            "incidencias": incidencias[:500]
        }, f, indent=4, ensure_ascii=False)

    etapas.append({
        "etapa": "Persistencia de evidencias y bitácora de incidencias",
        "estado": "exitoso",
        "timestamp": get_utc_now().isoformat(),
        "duracion_ms": int((time.time() * 1000) - inicio_ms),
        "detalle": f"Guardado en storage/cargas/{carga.id_carga}/"
    })

    with open(os.path.join(carga_dir, "etapas.json"), "w", encoding="utf-8") as f:
        json.dump(etapas, f, indent=4, ensure_ascii=False)

    if not carga_existente:
        create_audit_log(
            db=db,
            accion=f"carga_archivo_{tipo_carga}",
            modulo_afectado="datos",
            id_usuario=user_id,
            detalle={
                "id_carga": carga.id_carga,
                "filename": filename,
                "estado": carga.estado,
                "calidad": float(porcentaje_calidad),
                "procesados": total_procesados,
                "rechazados": total_rechazados
            }
        )

    return carga, resumen


def procesar_registros_validos(
    db: Session,
    id_carga: int,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    carga = db.query(CargaDatos).filter(CargaDatos.id_carga == id_carga).first()
    if not carga:
        raise ValueError(f"Carga con ID {id_carga} no encontrada.")

    if carga.estado in ["COMPLETADO", "CON_ADVERTENCIAS"]:
        return {
            "mensaje": "La carga ya fue procesada previamente.",
            "id_carga": carga.id_carga,
            "estado": carga.estado,
            "estado_display": get_estado_display(carga.estado, carga.registros_rechazados),
            "registros_afectados": carga.registros_procesados - carga.registros_rechazados
        }

    if carga.estado == "FALLIDO":
        raise ValueError(f"No es posible procesar la carga {id_carga} porque fue rechazada por calidad insuficiente ({carga.porcentaje_calidad}%).")

    carga.estado = "EN_PROGRESO"
    db.commit()

    carga_dir = get_storage_carga_dir(id_carga)
    incidencias_path = os.path.join(carga_dir, "incidencias.json")
    if not os.path.exists(incidencias_path):
        carga.estado = "FALLIDO"
        db.commit()
        raise ValueError(f"No se encontró el archivo de incidencias para la carga {id_carga}.")

    with open(incidencias_path, "r", encoding="utf-8") as f:
        incidencias_data = json.load(f)

    rechazados_indices = set(incidencias_data.get("resumen", {}).get("filas_rechazadas_indices", []))

    archivo_original = None
    for f_name in os.listdir(carga_dir):
        if f_name.startswith("archivo_original"):
            archivo_original = os.path.join(carga_dir, f_name)
            break

    if not archivo_original or not os.path.exists(archivo_original):
        carga.estado = "FALLIDO"
        db.commit()
        raise ValueError(f"No se encontró el archivo original de la carga {id_carga}.")

    if archivo_original.endswith(".csv"):
        df = pd.read_csv(archivo_original, dtype=str)
    else:
        df = pd.read_excel(archivo_original, dtype=str)

    df.columns = [str(c).strip().lower() for c in df.columns]

    valid_indices = [idx for idx in df.index if idx not in rechazados_indices]
    df_valid = df.loc[valid_indices]

    registros_afectados = 0
    nuevos_insertados = 0
    existentes_actualizados = 0
    t0 = time.time()

    if carga.tipo_carga == "productos":
        tiene_col_estado = "estado" in df_valid.columns
        for _, row in df_valid.iterrows():
            sku = str(row["sku"]).strip()
            nombre = str(row["nombre"]).strip()
            cat = str(row["categoria"]).strip()
            stock = int(float(row.get("stock_actual", 0))) if pd.notna(row.get("stock_actual")) and str(row.get("stock_actual")).strip() != "" else 0
            reorden = int(float(row.get("punto_reorden", 0))) if pd.notna(row.get("punto_reorden")) and str(row.get("punto_reorden")).strip() != "" else 0

            estado_row = None
            if tiene_col_estado:
                val_e = row.get("estado")
                if pd.notna(val_e) and str(val_e).strip() != "" and str(val_e).strip().lower() in ["activo", "descontinuado"]:
                    estado_row = str(val_e).strip().lower()

            prod = db.query(Producto).filter(Producto.sku == sku).first()
            if prod:
                prod.nombre = nombre
                prod.categoria = cat
                if "stock_actual" in df_valid.columns:
                    prod.stock_actual = stock
                if "punto_reorden" in df_valid.columns:
                    prod.punto_reorden = reorden
                if estado_row is not None:
                    prod.estado = estado_row
                    if estado_row == "descontinuado":
                        from app.models.pronostico import Pronostico
                        db.query(Pronostico).filter(Pronostico.id_producto == prod.id_producto).delete(synchronize_session=False)
                existentes_actualizados += 1
            else:
                prod = Producto(
                    sku=sku,
                    nombre=nombre,
                    categoria=cat,
                    stock_actual=stock,
                    punto_reorden=reorden,
                    estado=estado_row if estado_row is not None else "activo",
                    fecha_creacion=get_utc_now()
                )
                db.add(prod)
                nuevos_insertados += 1
            registros_afectados += 1
        db.commit()

    elif carga.tipo_carga == "inventario":
        for _, row in df_valid.iterrows():
            sku = str(row["sku"]).strip()
            stock = int(float(row["stock_actual"]))
            reorden = int(float(row["punto_reorden"]))

            prod = db.query(Producto).filter(Producto.sku == sku).first()
            if prod:
                prod.stock_actual = stock
                prod.punto_reorden = reorden
                registros_afectados += 1
                existentes_actualizados += 1
        db.commit()

    elif carga.tipo_carga == "ventas":
        productos_map = {p.sku: p.id_producto for p in db.query(Producto.sku, Producto.id_producto).all()}

        ventas_existentes_set = set(
            (r.id_producto, r.fecha)
            for r in db.query(VentaHistorica.id_producto, VentaHistorica.fecha).all()
        )

        ventas_batch = []
        for _, row in df_valid.iterrows():
            sku = str(row["sku"]).strip()
            prod_id = productos_map.get(sku)
            if not prod_id:
                continue

            fecha_str = str(row["fecha"]).strip()
            fecha_parsed = None
            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"]:
                try:
                    fecha_parsed = datetime.strptime(fecha_str, fmt).date()
                    break
                except ValueError:
                    pass

            if not fecha_parsed:
                continue

            cant = int(float(row["cantidad_vendida"]))
            precio = float(row["precio_unitario"])

            if (prod_id, fecha_parsed) in ventas_existentes_set:
                existentes_actualizados += 1
            else:
                nuevos_insertados += 1
                ventas_existentes_set.add((prod_id, fecha_parsed))

            ventas_batch.append({
                "id_producto": prod_id,
                "id_carga": carga.id_carga,
                "fecha": fecha_parsed,
                "cantidad_vendida": cant,
                "precio_unitario": precio
            })

            if len(ventas_batch) >= 2000:
                stmt = pg_insert(VentaHistorica).values(ventas_batch)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_venta_producto_fecha",
                    set_={
                        "cantidad_vendida": stmt.excluded.cantidad_vendida,
                        "precio_unitario": stmt.excluded.precio_unitario,
                        "id_carga": stmt.excluded.id_carga
                    }
                )
                db.execute(stmt)
                db.commit()
                registros_afectados += len(ventas_batch)
                ventas_batch = []

        if ventas_batch:
            stmt = pg_insert(VentaHistorica).values(ventas_batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_venta_producto_fecha",
                set_={
                    "cantidad_vendida": stmt.excluded.cantidad_vendida,
                    "precio_unitario": stmt.excluded.precio_unitario,
                    "id_carga": stmt.excluded.id_carga
                }
            )
            db.execute(stmt)
            db.commit()
            registros_afectados += len(ventas_batch)

    if carga.registros_rechazados > 0:
        carga.estado = "CON_ADVERTENCIAS"
        validos = (carga.registros_procesados or 0) - (carga.registros_rechazados or 0)
        rechazados = carga.registros_rechazados
        calidad = carga.porcentaje_calidad
        carga.detalle_error = f"Consolidado: {validos} registros válidos incorporados; {rechazados} registros con observaciones excluidos ({calidad}% de calidad)."
    else:
        carga.estado = "COMPLETADO"
        carga.detalle_error = None
    db.commit()

    etapas_path = os.path.join(carga_dir, "etapas.json")
    etapas = []
    if os.path.exists(etapas_path):
        try:
            with open(etapas_path, "r", encoding="utf-8") as f:
                etapas = json.load(f)
        except Exception:
            etapas = []

    etapas.append({
        "etapa": "Ingesta y consolidación en base de datos",
        "estado": "exitoso",
        "timestamp": get_utc_now().isoformat(),
        "duracion_ms": int((time.time() - t0) * 1000),
        "detalle": f"Total procesados: {registros_afectados} (Nuevos: {nuevos_insertados}, Actualizados idempotentes: {existentes_actualizados})"
    })

    with open(etapas_path, "w", encoding="utf-8") as f:
        json.dump(etapas, f, indent=4, ensure_ascii=False)

    create_audit_log(
        db=db,
        accion="procesar_registros_validos",
        modulo_afectado="datos",
        id_usuario=user_id,
        detalle={
            "id_carga": carga.id_carga,
            "tipo_carga": carga.tipo_carga,
            "registros_afectados": registros_afectados,
            "nuevos_insertados": nuevos_insertados,
            "existentes_actualizados": existentes_actualizados,
            "estado": carga.estado
        }
    )

    if carga.tipo_carga == "ventas" and carga.estado in ["COMPLETADO", "CON_ADVERTENCIAS"]:
        verificar_reentrenamiento_por_acumulacion(db)

    return {
        "mensaje": f"Carga {carga.id_carga} consolidada exitosamente.",
        "id_carga": carga.id_carga,
        "tipo_carga": carga.tipo_carga,
        "registros_afectados": registros_afectados,
        "nuevos_insertados": nuevos_insertados,
        "existentes_actualizados": existentes_actualizados,
        "estado": carga.estado,
        "estado_display": get_estado_display(carga.estado, carga.registros_rechazados)
    }


def verificar_reentrenamiento_por_acumulacion(db: Session):
    try:
        from app.services.scheduler import get_procesos_config
        from app.models.venta_historica import VentaHistorica
        from app.services.ml_service import MLForecastService
        import threading

        if MLForecastService.is_entrenamiento_en_curso():
            return

        cfg = get_procesos_config()
        umbral_registros = int(cfg.get("reentrenamiento_umbral_registros", 840))

        calib_file = os.path.join(settings.STORAGE_DIR, "modelos", "calibracion_activa.json")
        fecha_max = None
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    f_str = cdata.get("fecha_max_ventas")
                    if f_str:
                        if isinstance(f_str, str):
                            fecha_max = datetime.fromisoformat(f_str).date()
            except Exception:
                pass

        if not fecha_max:
            return

        nuevos = db.query(func.count(VentaHistorica.id_venta)).filter(
            VentaHistorica.fecha > fecha_max
        ).scalar() or 0

        if nuevos >= umbral_registros:
            def _bg_entrenar():
                from app.core.database import SessionLocal
                with SessionLocal() as bg_db:
                    try:
                        MLForecastService.entrenar_modelo_candidato(
                            db=bg_db,
                            motivo="reentrenamiento_por_datos"
                        )
                    except Exception as exc:
                        logger.error(f"Error en reentrenamiento por acumulación: {exc}")

            t = threading.Thread(target=_bg_entrenar, daemon=True)
            t.start()
    except Exception as e:
        logger.error(f"Error al verificar reentrenamiento por acumulación: {e}")


def reintentar_ejecucion_carga(
    db: Session,
    id_carga: int,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    carga = db.query(CargaDatos).filter(CargaDatos.id_carga == id_carga).first()
    if not carga:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ejecución no encontrada"
        )

    if carga.tipo_carga not in ["ventas", "inventario", "productos"] or carga.estado != "FALLIDO":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se pueden reintentar ejecuciones de carga de datos en estado FALLIDO."
        )

    carga_dir = get_storage_carga_dir(id_carga)
    meta_path = os.path.join(carga_dir, "meta.json")
    meta_data = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta_data = json.load(f)
        except Exception:
            meta_data = {}

    reintentos = meta_data.get("reintentos", 0)
    if reintentos >= 3:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Se alcanzó el límite de 3 reintentos para esta ejecución. Contacte al equipo técnico o espere la siguiente ejecución programada."
        )

    archivo_original = None
    if os.path.exists(carga_dir):
        for f_name in os.listdir(carga_dir):
            if f_name.startswith("archivo_original"):
                archivo_original = os.path.join(carga_dir, f_name)
                break

    if not archivo_original or not os.path.exists(archivo_original):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El archivo original de esta ejecución no está disponible para reintento."
        )

    reintentos += 1
    meta_data["reintentos"] = reintentos
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, indent=4, ensure_ascii=False)

    with open(archivo_original, "rb") as f:
        file_bytes = f.read()

    filename = meta_data.get("nombre_original") or meta_data.get("nombre_archivo") or os.path.basename(archivo_original)

    carga, resumen = validate_file_content(
        db=db,
        file_bytes=file_bytes,
        filename=filename,
        tipo_carga=carga.tipo_carga,
        user_id=user_id,
        carga_existente=carga
    )

    meta_data["reintentos"] = reintentos
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, indent=4, ensure_ascii=False)

    calidad_min = get_calidad_min_threshold(db)
    if float(carga.porcentaje_calidad) >= calidad_min:
        procesar_registros_validos(db, carga.id_carga, user_id=user_id)
        db.refresh(carga)
        mensaje = "Reintento exitoso: la ejecución se completó correctamente."
    else:
        mensaje = f"El reintento no resolvió el problema: {carga.detalle_error}"

    create_audit_log(
        db=db,
        accion="Reintento de ejecución",
        modulo_afectado="procesos",
        id_usuario=user_id,
        detalle={
            "id_carga": carga.id_carga,
            "tipo_carga": carga.tipo_carga,
            "reintentos": reintentos,
            "estado": carga.estado,
            "porcentaje_calidad": float(carga.porcentaje_calidad),
            "mensaje": mensaje
        }
    )

    reintento_permitido = (carga.estado == "FALLIDO" and reintentos < 3)
    return {
        "id_carga": carga.id_carga,
        "estado": carga.estado,
        "reintentos": reintentos,
        "reintentos_max": 3,
        "reintento_permitido": reintento_permitido,
        "mensaje": mensaje
    }


def sincronizar_archivos_locales(db: Session, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    entrada_dir = settings.STORAGE_ENTRADA_DIR
    os.makedirs(entrada_dir, exist_ok=True)

    archivos = [f for f in os.listdir(entrada_dir) if f.endswith((".csv", ".xlsx", ".xls"))]
    resultados = []

    def orden_tipo(nombre):
        n = nombre.lower()
        if "producto" in n:
            return 1
        elif "inventario" in n:
            return 2
        elif "venta" in n:
            return 3
        return 4

    archivos.sort(key=orden_tipo)

    for f_name in archivos:
        f_path = os.path.join(entrada_dir, f_name)
        n_lower = f_name.lower()

        if "producto" in n_lower:
            tipo = "productos"
        elif "inventario" in n_lower:
            tipo = "inventario"
        elif "venta" in n_lower:
            tipo = "ventas"
        else:
            continue

        with open(f_path, "rb") as f:
            file_bytes = f.read()

        try:
            carga, resumen = validate_file_content(
                db=db,
                file_bytes=file_bytes,
                filename=f_name,
                tipo_carga=tipo,
                user_id=user_id
            )

            if carga.estado == "PENDIENTE" and resumen.get("apto_para_procesar"):
                res_proc = procesar_registros_validos(db, carga.id_carga, user_id=user_id)
                resultados.append({
                    "archivo": f_name,
                    "tipo_carga": tipo,
                    "id_carga": carga.id_carga,
                    "estado": res_proc.get("estado"),
                    "calidad": float(carga.porcentaje_calidad),
                    "registros_afectados": res_proc.get("registros_afectados", 0)
                })
            else:
                resultados.append({
                    "archivo": f_name,
                    "tipo_carga": tipo,
                    "id_carga": carga.id_carga,
                    "estado": carga.estado,
                    "calidad": float(carga.porcentaje_calidad),
                    "motivo": carga.detalle_error
                })
        except Exception as e:
            resultados.append({
                "archivo": f_name,
                "tipo_carga": tipo,
                "estado": "FALLIDO",
                "error": str(e)
            })

    create_audit_log(
        db=db,
        accion="sincronizacion_datos_entrada",
        modulo_afectado="datos",
        id_usuario=user_id,
        detalle={"archivos_procesados": len(resultados)}
    )

    return resultados
