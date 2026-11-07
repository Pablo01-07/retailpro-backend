import os
import csv
import uuid
import math
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from app.core.config import settings
from app.models.producto import Producto
from app.models.pronostico import Pronostico
from app.models.modelo_version import ModeloVersion
from app.models.auditoria import Auditoria
from app.models.usuario import Usuario
from app.models.venta_historica import VentaHistorica
from app.models.umbral_configuracion import UmbralConfiguracion
from app.schemas.reports import (
    ExportarReporteResponse,
    ReportePreviewResponse,
    ReportePreviewItem,
    ReporteHistorialResponse,
    ReporteHistorialItem
)
from app.services.alert_service import AlertService


class ReportingService:
    @staticmethod
    def ensure_storage_dir() -> str:
        rep_dir = os.path.join(os.getcwd(), settings.STORAGE_REPORTES_DIR)
        os.makedirs(rep_dir, exist_ok=True)
        return rep_dir

    @classmethod
    def get_preview_data(cls, db: Session, categoria: Optional[str] = None) -> ReportePreviewResponse:
        modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
        if not modelo_activo:
            return ReportePreviewResponse(total_registros=0, fecha_generacion=datetime.utcnow(), items=[])

        max_fecha_gen = db.query(func.max(Pronostico.fecha_generacion)).filter(
            Pronostico.id_modelo == modelo_activo.id_modelo
        ).scalar()
        if not max_fecha_gen:
            return ReportePreviewResponse(total_registros=0, fecha_generacion=datetime.utcnow(), items=[])

        pronosticos = db.query(Pronostico).filter(
            Pronostico.id_modelo == modelo_activo.id_modelo,
            Pronostico.fecha_generacion == max_fecha_gen
        ).all()
        pron_by_prod: Dict[int, List[Pronostico]] = {}
        for p in pronosticos:
            pron_by_prod.setdefault(p.id_producto, []).append(p)

        q_prod = db.query(Producto)
        if categoria:
            q_prod = q_prod.filter(Producto.categoria == categoria)
        productos = q_prod.all()

        items = []
        fecha_gen = datetime.utcnow()

        for prod in productos:
            p_list = pron_by_prod.get(prod.id_producto, [])
            if not p_list:
                continue

            p_list = sorted(p_list, key=lambda x: x.horizonte_dias)
            primer = p_list[0]
            fecha_gen = primer.fecha_generacion

            demanda_14d = sum(float(x.cantidad_proyectada) for x in p_list)
            prob_q = 0.0
            if primer.explicacion_shap and isinstance(primer.explicacion_shap, dict):
                prob_q = float(primer.explicacion_shap.get("probabilidad_quiebre", 0.0))

            items.append(ReportePreviewItem(
                id_producto=prod.id_producto,
                sku=prod.sku,
                nombre_producto=prod.nombre,
                categoria=prod.categoria,
                stock_actual=prod.stock_actual,
                punto_reorden=prod.punto_reorden,
                demanda_proyectada_14d=round(demanda_14d, 2),
                cantidad_sugerida=primer.cantidad_sugerida_reposicion,
                probabilidad_quiebre=prob_q,
                nivel_incertidumbre=primer.nivel_incertidumbre
            ))

        return ReportePreviewResponse(
            total_registros=len(items),
            fecha_generacion=fecha_gen,
            categoria_filtrada=categoria,
            items=items
        )

    @classmethod
    def get_historial_reportes(cls, db: Session, page: int = 1, limit: int = 20) -> ReporteHistorialResponse:
        storage_dir = cls.ensure_storage_dir()

        auditorias = db.query(Auditoria).join(
            Usuario, Auditoria.id_usuario == Usuario.id_usuario, isouter=True
        ).filter(
            (Auditoria.accion.like("%EXPORT%")) | (Auditoria.modulo_afectado.in_(["reportes", "reposicion"]))
        ).order_by(Auditoria.fecha_hora.desc()).all()

        valid_items: List[ReporteHistorialItem] = []

        nombre_map = {
            "inventario": "Reporte de Inventario y Cobertura",
            "ventas": "Reporte de Ventas Históricas",
            "indicadores": "Reporte de Indicadores de Rendimiento",
            "pronostico_reposicion": "Reporte de Pronóstico y Reposición",
            "reposicion": "Reporte de Recomendaciones de Reposición"
        }

        for a in auditorias:
            detalle = a.detalle if isinstance(a.detalle, dict) else {}
            filename = detalle.get("nombre_archivo")
            if not filename:
                continue

            safe_filename = os.path.basename(filename)
            filepath = os.path.join(storage_dir, safe_filename)

            if not os.path.isfile(filepath):
                continue

            user_name = a.usuario.nombre_completo if a.usuario else "Usuario del Sistema"
            formato = (detalle.get("formato") or os.path.splitext(safe_filename)[1].replace(".", "")).lower()
            tamano = os.path.getsize(filepath)

            tipo_reporte = detalle.get("tipo_reporte")
            if not tipo_reporte:
                if "inventario" in safe_filename:
                    tipo_reporte = "inventario"
                elif "ventas" in safe_filename:
                    tipo_reporte = "ventas"
                elif "indicadores" in safe_filename:
                    tipo_reporte = "indicadores"
                elif "reposicion" in safe_filename:
                    tipo_reporte = "reposicion"
                else:
                    tipo_reporte = "pronostico_reposicion"

            nombre_humano = nombre_map.get(tipo_reporte, f"Reporte de {tipo_reporte.capitalize()}")

            valid_items.append(ReporteHistorialItem(
                id_auditoria=a.id_auditoria,
                nombre=nombre_humano,
                tipo=tipo_reporte,
                fecha=a.fecha_hora,
                formato=formato.upper(),
                tamano_bytes=tamano,
                usuario=user_name,
                nombre_archivo=safe_filename,
                url_descarga=f"/api/v1/reportes/descargar/{safe_filename}"
            ))

        total_rep = len(valid_items)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit

        return ReporteHistorialResponse(
            total_reportes=total_rep,
            page=page,
            limit=limit,
            items=valid_items[start_idx:end_idx]
        )

    @classmethod
    def exportar_reporte(
        cls,
        db: Session,
        formato: str,
        user_id: int,
        categoria: Optional[str] = None
    ) -> ExportarReporteResponse:
        storage_dir = cls.ensure_storage_dir()
        formato = formato.lower().strip()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_id = str(uuid.uuid4())[:8]

        preview_data = cls.get_preview_data(db, categoria)
        items = preview_data.items

        filename = f"reporte_pronostico_{timestamp_str}_{report_id}.{formato}"
        filepath = os.path.join(storage_dir, filename)

        if formato == "csv":
            cls._export_csv(filepath, items)
        elif formato in ["xlsx", "excel"]:
            filename = f"reporte_pronostico_{timestamp_str}_{report_id}.xlsx"
            filepath = os.path.join(storage_dir, filename)
            formato = "xlsx"
            cls._export_xlsx(filepath, items)
        elif formato == "pdf":
            cls._export_pdf(filepath, items)
        else:
            raise ValueError(f"Formato no soportado: '{formato}'. Use 'csv', 'xlsx' o 'pdf'.")

        tamano_bytes = os.path.getsize(filepath)

        audit = Auditoria(
            id_usuario=user_id,
            accion="EXPORTACION_REPORTE",
            modulo_afectado="reportes",
            detalle={
                "tipo_reporte": "pronostico_reposicion",
                "formato": formato,
                "nombre_archivo": filename,
                "tamano_bytes": tamano_bytes,
                "categoria_filtro": categoria,
                "total_registros": len(items)
            }
        )
        db.add(audit)
        db.commit()

        url_descarga = f"/api/v1/reportes/descargar/{filename}"

        return ExportarReporteResponse(
            id_reporte=report_id,
            formato=formato,
            nombre_archivo=filename,
            url_descarga=url_descarga,
            tamaño_bytes=tamano_bytes,
            fecha_generacion=datetime.utcnow()
        )

    @classmethod
    def exportar_inventario(
        cls,
        db: Session,
        formato: str,
        user_id: int,
        categoria: Optional[str] = None,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None
    ) -> ExportarReporteResponse:
        storage_dir = cls.ensure_storage_dir()
        formato = formato.lower().strip()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_id = str(uuid.uuid4())[:8]

        umbrales = AlertService.get_thresholds_dict(db)
        umbral_quiebre_dias = umbrales["quiebre_dias_cobertura"]
        umbral_sobrestock_dias = umbrales["sobrestock_dias"]

        modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
        pron_dict: Dict[int, float] = {}
        if modelo_activo:
            max_fecha_gen = db.query(func.max(Pronostico.fecha_generacion)).filter(
                Pronostico.id_modelo == modelo_activo.id_modelo
            ).scalar()
            if max_fecha_gen:
                prs = db.query(Pronostico).filter(
                    Pronostico.id_modelo == modelo_activo.id_modelo,
                    Pronostico.fecha_generacion == max_fecha_gen
                ).all()
                for p in prs:
                    pron_dict[p.id_producto] = pron_dict.get(p.id_producto, 0.0) + float(p.cantidad_proyectada)

        q_prod = db.query(Producto)
        if categoria:
            q_prod = q_prod.filter(Producto.categoria == categoria)
        productos = q_prod.order_by(Producto.categoria, Producto.sku).all()

        data_rows = []
        for p in productos:
            demanda_14d = pron_dict.get(p.id_producto, 28.0)
            demanda_diaria = demanda_14d / 14.0 if demanda_14d > 0 else 1.0
            cob_dias = round(p.stock_actual / demanda_diaria, 1) if demanda_diaria > 0 else 999.0

            if cob_dias <= umbral_quiebre_dias or p.stock_actual <= p.punto_reorden:
                alerta = "QUIEBRE"
            elif cob_dias >= umbral_sobrestock_dias:
                alerta = "SOBRESTOCK"
            else:
                alerta = "NORMAL"

            data_rows.append({
                "sku": p.sku,
                "producto": p.nombre,
                "categoria": p.categoria,
                "stock_actual": p.stock_actual,
                "cobertura_dias": cob_dias,
                "punto_reorden": p.punto_reorden,
                "estado_alerta": alerta
            })

        filename = f"reporte_inventario_{timestamp_str}_{report_id}.{formato}"
        filepath = os.path.join(storage_dir, filename)

        if formato == "csv":
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["SKU", "Producto", "Categoría", "Stock Actual", "Cobertura (Días)", "Punto Reorden", "Estado de Alerta"])
                for r in data_rows:
                    writer.writerow([r["sku"], r["producto"], r["categoria"], r["stock_actual"], r["cobertura_dias"], r["punto_reorden"], r["estado_alerta"]])
        elif formato in ["xlsx", "excel"]:
            filename = f"reporte_inventario_{timestamp_str}_{report_id}.xlsx"
            filepath = os.path.join(storage_dir, filename)
            formato = "xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Inventario"
            headers = ["SKU", "Producto", "Categoría", "Stock Actual", "Cobertura (Días)", "Punto Reorden", "Estado de Alerta"]
            ws.append(headers)
            cls._style_excel_header(ws, len(headers))
            for r in data_rows:
                ws.append([r["sku"], r["producto"], r["categoria"], r["stock_actual"], r["cobertura_dias"], r["punto_reorden"], r["estado_alerta"]])
            cls._auto_adjust_columns(ws)
            wb.save(filepath)
        elif formato == "pdf":
            cls._export_pdf_generic(
                filepath=filepath,
                titulo="FasRetail - Reporte de Inventario y Cobertura",
                subtitulo=f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Total SKUs: {len(data_rows)}",
                headers=["SKU", "Producto", "Cat.", "Stock", "Cob.(d)", "P.Reorden", "Alerta"],
                col_widths=[60, 160, 50, 50, 55, 60, 65],
                rows=[[r["sku"], r["producto"][:22], r["categoria"][:6], str(r["stock_actual"]), str(r["cobertura_dias"]), str(r["punto_reorden"]), r["estado_alerta"]] for r in data_rows[:60]]
            )
        else:
            raise ValueError(f"Formato no soportado: '{formato}'. Use 'csv', 'xlsx' o 'pdf'.")

        tamano_bytes = os.path.getsize(filepath)

        audit = Auditoria(
            id_usuario=user_id,
            accion="EXPORTACION_INVENTARIO",
            modulo_afectado="reportes",
            detalle={
                "tipo_reporte": "inventario",
                "formato": formato,
                "nombre_archivo": filename,
                "tamano_bytes": tamano_bytes,
                "categoria_filtro": categoria,
                "total_registros": len(data_rows)
            }
        )
        db.add(audit)
        db.commit()

        return ExportarReporteResponse(
            id_reporte=report_id,
            formato=formato,
            nombre_archivo=filename,
            url_descarga=f"/api/v1/reportes/descargar/{filename}",
            tamaño_bytes=tamano_bytes,
            fecha_generacion=datetime.utcnow()
        )

    @classmethod
    def exportar_ventas(
        cls,
        db: Session,
        formato: str,
        user_id: int,
        categoria: Optional[str] = None,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None
    ) -> ExportarReporteResponse:
        storage_dir = cls.ensure_storage_dir()
        formato = formato.lower().strip()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_id = str(uuid.uuid4())[:8]

        q = db.query(
            VentaHistorica.fecha,
            Producto.sku,
            Producto.nombre,
            Producto.categoria,
            VentaHistorica.cantidad_vendida,
            VentaHistorica.precio_unitario
        ).join(Producto, VentaHistorica.id_producto == Producto.id_producto)

        if categoria:
            q = q.filter(Producto.categoria == categoria)
        if fecha_inicio:
            q = q.filter(VentaHistorica.fecha >= fecha_inicio)
        if fecha_fin:
            q = q.filter(VentaHistorica.fecha <= fecha_fin)

        records = q.order_by(VentaHistorica.fecha.desc(), Producto.sku).limit(10000).all()

        filename = f"reporte_ventas_{timestamp_str}_{report_id}.{formato}"
        filepath = os.path.join(storage_dir, filename)

        if formato == "csv":
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Fecha", "SKU", "Producto", "Categoría", "Cantidad Vendida", "Precio Unitario", "Ingreso Total (S/.)"])
                for r in records:
                    ingreso = float(r[4]) * float(r[5])
                    writer.writerow([r[0].isoformat(), r[1], r[2], r[3], r[4], float(r[5]), round(ingreso, 2)])
        elif formato in ["xlsx", "excel"]:
            filename = f"reporte_ventas_{timestamp_str}_{report_id}.xlsx"
            filepath = os.path.join(storage_dir, filename)
            formato = "xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Ventas"
            headers = ["Fecha", "SKU", "Producto", "Categoría", "Cantidad Vendida", "Precio Unitario", "Ingreso Total (S/.)"]
            ws.append(headers)
            cls._style_excel_header(ws, len(headers))
            for r in records:
                ingreso = float(r[4]) * float(r[5])
                ws.append([r[0].isoformat(), r[1], r[2], r[3], r[4], float(r[5]), round(ingreso, 2)])
            cls._auto_adjust_columns(ws)
            wb.save(filepath)
        elif formato == "pdf":
            resumen_sku: Dict[str, Dict[str, Any]] = {}
            for r in records:
                sku_val = r[1]
                if sku_val not in resumen_sku:
                    resumen_sku[sku_val] = {
                        "sku": sku_val, "nombre": r[2], "cat": r[3], "cant": 0, "total": 0.0
                    }
                resumen_sku[sku_val]["cant"] += r[4]
                resumen_sku[sku_val]["total"] += float(r[4]) * float(r[5])

            filas_pdf = []
            for s_k, item in list(resumen_sku.items())[:60]:
                filas_pdf.append([
                    item["sku"], item["nombre"][:24], item["cat"][:6],
                    str(item["cant"]), f"S/. {item['total']:,.2f}"
                ])

            cls._export_pdf_generic(
                filepath=filepath,
                titulo="FasRetail - Reporte Ejecutivo de Ventas",
                subtitulo=f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Total Transacciones: {len(records)}",
                headers=["SKU", "Producto", "Cat.", "Unidades Vendidas", "Ingreso Acumulado"],
                col_widths=[65, 180, 60, 95, 100],
                rows=filas_pdf
            )
        else:
            raise ValueError(f"Formato no soportado: '{formato}'. Use 'csv', 'xlsx' o 'pdf'.")

        tamano_bytes = os.path.getsize(filepath)

        audit = Auditoria(
            id_usuario=user_id,
            accion="EXPORTACION_VENTAS",
            modulo_afectado="reportes",
            detalle={
                "tipo_reporte": "ventas",
                "formato": formato,
                "nombre_archivo": filename,
                "tamano_bytes": tamano_bytes,
                "categoria_filtro": categoria,
                "total_registros": len(records)
            }
        )
        db.add(audit)
        db.commit()

        return ExportarReporteResponse(
            id_reporte=report_id,
            formato=formato,
            nombre_archivo=filename,
            url_descarga=f"/api/v1/reportes/descargar/{filename}",
            tamaño_bytes=tamano_bytes,
            fecha_generacion=datetime.utcnow()
        )

    @staticmethod
    def calcular_wape_fuera_muestra(db: Session) -> Optional[float]:
        try:
            from app.models.modelo_version import ModeloVersion
            from app.models.pronostico import Pronostico
            from app.models.venta_historica import VentaHistorica

            cortes = db.query(ModeloVersion).filter(ModeloVersion.motivo_entrenamiento == "backtest").all()
            if not cortes:
                return None

            tot_abs_err = 0.0
            tot_real = 0.0
            for corte_mod in cortes:
                corte_dt = corte_mod.fecha_entrenamiento
                prons = db.query(Pronostico.id_producto, Pronostico.horizonte_dias, Pronostico.cantidad_proyectada).filter(
                    Pronostico.id_modelo == corte_mod.id_modelo
                ).all()
                if not prons:
                    continue
                fechas_val = [corte_dt.date() + timedelta(days=h) for h in range(1, 15)]
                ventas = db.query(VentaHistorica.id_producto, VentaHistorica.fecha, VentaHistorica.cantidad_vendida).filter(
                    VentaHistorica.fecha.in_(fechas_val)
                ).all()
                v_dict = {(v.id_producto, v.fecha): float(v.cantidad_vendida) for v in ventas}
                for pid, h, y_hat in prons:
                    f_obj = corte_dt.date() + timedelta(days=h)
                    y_real = v_dict.get((pid, f_obj), 0.0)
                    tot_abs_err += abs(y_real - float(y_hat))
                    tot_real += y_real

            if tot_real > 0:
                return round(tot_abs_err / tot_real * 100.0, 2)
        except Exception:
            pass
        return None

    @classmethod
    def exportar_indicadores(
        cls,
        db: Session,
        formato: str,
        user_id: int,
        categoria: Optional[str] = None,
        fecha_inicio: Optional[date] = None,
        fecha_fin: Optional[date] = None
    ) -> ExportarReporteResponse:
        storage_dir = cls.ensure_storage_dir()
        formato = formato.lower().strip()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_id = str(uuid.uuid4())[:8]

        modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
        mape_val = float(modelo_activo.mape) if modelo_activo and modelo_activo.mape is not None else None
        wape_val = cls.calcular_wape_fuera_muestra(db)
        rmse_val = float(modelo_activo.rmse) if modelo_activo and modelo_activo.rmse is not None else None
        mae_val = float(modelo_activo.mae) if modelo_activo and modelo_activo.mae is not None else None

        from app.services.dashboard_service import DashboardService
        from app.models.alerta import Alerta
        from app.models.umbral_configuracion import UmbralConfiguracion

        u_mape = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
        meta_mape = float(u_mape.valor) if u_mape else 15.0
        meta_mape_str = f"<= {meta_mape:.2f}%"

        u_wape = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "wape_max").first()
        meta_wape = float(u_wape.valor) if u_wape else meta_mape
        meta_wape_str = f"<= {meta_wape:.2f}%"

        u_rmse = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "rmse_max").first()
        meta_rmse = float(u_rmse.valor) if u_rmse else 15.0
        meta_rmse_str = f"<= {meta_rmse:.2f}"

        u_mae = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mae_max").first()
        meta_mae = float(u_mae.valor) if u_mae else 10.0
        meta_mae_str = f"<= {meta_mae:.2f}"

        u_ns = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "nivel_servicio_ref").first()
        meta_ns = float(u_ns.valor) if u_ns else 95.0
        meta_ns_str = f">= {meta_ns:.2f}%"

        ns_data = DashboardService.get_nivel_servicio_detalle(db)
        quiebres = db.query(Alerta).filter(Alerta.estado == "Activa", Alerta.tipo_alerta == "QUIEBRE").count()
        sobrestocks = db.query(Alerta).filter(Alerta.estado == "Activa", Alerta.tipo_alerta == "SOBRESTOCK").count()

        cumple_mape = (mape_val is not None) and (mape_val <= meta_mape)
        veredicto_mape = "CUMPLE" if cumple_mape else ("NO CUMPLE" if mape_val is not None else "—")
        cumple_wape = (wape_val is not None) and (wape_val <= meta_wape)
        veredicto_wape = "CUMPLE" if cumple_wape else ("NO CUMPLE" if wape_val is not None else "—")
        cumple_rmse = (rmse_val is not None) and (rmse_val <= meta_rmse)
        veredicto_rmse = "CUMPLE" if cumple_rmse else ("NO CUMPLE" if rmse_val is not None else "—")
        cumple_mae = (mae_val is not None) and (mae_val <= meta_mae)
        veredicto_mae = "CUMPLE" if cumple_mae else ("NO CUMPLE" if mae_val is not None else "—")
        cumple_ns = ns_data.nivel_servicio_global_pct >= meta_ns
        veredicto_ns = "CUMPLE" if cumple_ns else "NO CUMPLE"
        cumple_disp = ns_data.disponibilidad_global_pct >= meta_ns
        veredicto_disp = "CUMPLE" if cumple_disp else "NO CUMPLE"
        cumple_quiebres = quiebres == 0
        veredicto_quiebres = "CUMPLE" if cumple_quiebres else "NO CUMPLE"
        cumple_sobrestocks = sobrestocks <= 5
        veredicto_sobrestocks = "CUMPLE" if cumple_sobrestocks else "NO CUMPLE"

        indicadores_summary = [
            ("MAPE Fuera de Muestra (XGBoost)", f"{mape_val:.2f}%" if mape_val is not None else "—", meta_mape_str, veredicto_mape, "Desempeño predictivo fuera de muestra"),
            ("WAPE Fuera de Muestra", f"{wape_val:.2f}%" if wape_val is not None else "—", meta_wape_str, veredicto_wape, "Error absoluto ponderado por volumen"),
            ("RMSE Fuera de Muestra", f"{rmse_val:.4f}" if rmse_val is not None else "—", meta_rmse_str, veredicto_rmse, "Raíz del error cuadrático medio"),
            ("MAE Fuera de Muestra", f"{mae_val:.4f}" if mae_val is not None else "—", meta_mae_str, veredicto_mae, "Error absoluto medio"),
            ("Nivel de Servicio Estimado (Fill Rate)", f"{ns_data.nivel_servicio_global_pct:.2f}%", meta_ns_str, veredicto_ns, "Demanda satisfecha sobre demanda proyectada"),
            ("Disponibilidad de Catálogo", f"{ns_data.disponibilidad_global_pct:.1f}%", meta_ns_str, veredicto_disp, "Proporción de SKUs sin riesgo de quiebre"),
            ("Alertas Activas de Quiebre", str(quiebres), "0 críticas", veredicto_quiebres, "SKUs con stock <= punto reorden o cobertura crítica"),
            ("Alertas Activas de Sobrestock", str(sobrestocks), "<= 5", veredicto_sobrestocks, "SKUs con cobertura > umbral configurado")
        ]

        filename = f"reporte_indicadores_{timestamp_str}_{report_id}.{formato}"
        filepath = os.path.join(storage_dir, filename)

        if formato == "csv":
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Indicador", "Valor Actual", "Meta Referencial", "Estado", "Descripción Metodológica"])
                for ind in indicadores_summary:
                    writer.writerow(list(ind))
        elif formato in ["xlsx", "excel"]:
            filename = f"reporte_indicadores_{timestamp_str}_{report_id}.xlsx"
            filepath = os.path.join(storage_dir, filename)
            formato = "xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Indicadores"
            headers = ["Indicador", "Valor Actual", "Meta Referencial", "Estado", "Descripción Metodológica"]
            ws.append(headers)
            cls._style_excel_header(ws, len(headers))
            for ind in indicadores_summary:
                ws.append(list(ind))
            cls._auto_adjust_columns(ws)
            wb.save(filepath)
        elif formato == "pdf":
            cls._export_pdf_generic(
                filepath=filepath,
                titulo="FasRetail - Reporte de Indicadores de Rendimiento",
                subtitulo=f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Versión Modelo: {modelo_activo.version if modelo_activo else 'N/A'} | Veredicto MAPE: {veredicto_mape}",
                headers=["Indicador", "Valor", "Meta", "Estado", "Descripción"],
                col_widths=[140, 60, 65, 65, 170],
                rows=[[ind[0], ind[1], ind[2], ind[3], ind[4]] for ind in indicadores_summary]
            )
        else:
            raise ValueError(f"Formato no soportado: '{formato}'. Use 'csv', 'xlsx' o 'pdf'.")

        tamano_bytes = os.path.getsize(filepath)

        audit = Auditoria(
            id_usuario=user_id,
            accion="EXPORTACION_INDICADORES",
            modulo_afectado="reportes",
            detalle={
                "tipo_reporte": "indicadores",
                "formato": formato,
                "nombre_archivo": filename,
                "tamano_bytes": tamano_bytes,
                "categoria_filtro": categoria,
                "total_registros": len(indicadores_summary)
            }
        )
        db.add(audit)
        db.commit()

        return ExportarReporteResponse(
            id_reporte=report_id,
            formato=formato,
            nombre_archivo=filename,
            url_descarga=f"/api/v1/reportes/descargar/{filename}",
            tamaño_bytes=tamano_bytes,
            fecha_generacion=datetime.utcnow()
        )

    @staticmethod
    def _style_excel_header(ws, num_cols: int):
        header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
        for col_num in range(1, num_cols + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

    @staticmethod
    def _auto_adjust_columns(ws):
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = col[0].column_letter
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    @staticmethod
    def _export_csv(filepath: str, items: List[ReportePreviewItem]):
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "SKU", "Producto", "Categoría", "Stock Actual", "Punto Reorden",
                "Demanda Proyectada 14d", "Cantidad Sugerida", "Probabilidad Quiebre (%)", "Incertidumbre"
            ])
            for it in items:
                writer.writerow([
                    it.sku, it.nombre_producto, it.categoria, it.stock_actual, it.punto_reorden,
                    it.demanda_proyectada_14d, it.cantidad_sugerida, f"{it.probabilidad_quiebre}%", it.nivel_incertidumbre
                ])

    @staticmethod
    def _export_xlsx(filepath: str, items: List[ReportePreviewItem]):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Pronóstico y Reposición"

        headers = [
            "SKU", "Producto", "Categoría", "Stock Actual", "Punto Reorden",
            "Demanda Proy. 14d", "Sugerido Compra", "P(Quiebre) %", "Incertidumbre"
        ]
        ws.append(headers)
        ReportingService._style_excel_header(ws, len(headers))

        data_font = Font(name="Segoe UI", size=10)
        for it in items:
            ws.append([
                it.sku, it.nombre_producto, it.categoria, it.stock_actual, it.punto_reorden,
                it.demanda_proyectada_14d, it.cantidad_sugerida, f"{it.probabilidad_quiebre}%", it.nivel_incertidumbre
            ])

        for row in ws.iter_rows(min_row=2, max_row=len(items) + 1, min_col=1, max_col=len(headers)):
            for cell in row:
                cell.font = data_font

        ReportingService._auto_adjust_columns(ws)
        wb.save(filepath)

    @staticmethod
    def _export_pdf(filepath: str, items: List[ReportePreviewItem]):
        doc = SimpleDocTemplate(filepath, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            name="TitleStyle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#1A365D")
        )
        subtitle_style = ParagraphStyle(
            name="SubtitleStyle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#4A5568")
        )

        elements.append(Paragraph("FasRetail - Reporte Ejecutivo de Pronóstico y Reposición", title_style))
        elements.append(Paragraph(f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | Total SKUs: {len(items)}", subtitle_style))
        elements.append(Spacer(1, 15))

        table_data = [[
            "SKU", "Producto", "Cat.", "Stock", "P.Reorden", "Proy. 14d", "Sugerido", "P(Q) %", "Incert."
        ]]

        for it in items[:50]:
            nombre_trunc = (it.nombre_producto[:22] + "..") if len(it.nombre_producto) > 22 else it.nombre_producto
            table_data.append([
                it.sku, nombre_trunc, it.categoria[:4], str(it.stock_actual), str(it.punto_reorden),
                f"{it.demanda_proyectada_14d:.1f}", str(it.cantidad_sugerida), f"{it.probabilidad_quiebre:.1f}%", it.nivel_incertidumbre[:1]
            ])

        col_widths = [55, 140, 40, 45, 50, 55, 50, 45, 45]
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (1, 1), (1, -1), "LEFT"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))

        elements.append(t)
        doc.build(elements)

    @staticmethod
    def _export_pdf_generic(
        filepath: str,
        titulo: str,
        subtitulo: str,
        headers: List[str],
        col_widths: List[int],
        rows: List[List[str]]
    ):
        doc = SimpleDocTemplate(filepath, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            name="TitleGenStyle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#1A365D")
        )
        subtitle_style = ParagraphStyle(
            name="SubGenStyle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#4A5568")
        )

        elements.append(Paragraph(titulo, title_style))
        elements.append(Paragraph(subtitulo, subtitle_style))
        elements.append(Spacer(1, 14))

        table_data = [headers] + rows
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (1, 1), (1, -1), "LEFT"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))

        elements.append(t)
        doc.build(elements)
