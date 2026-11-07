import os
import csv
import uuid
import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from app.core.config import settings
from app.models.pronostico import Pronostico
from app.models.producto import Producto
from app.models.modelo_version import ModeloVersion
from app.models.auditoria import Auditoria
from app.services.alert_service import AlertService
from app.schemas.replenishment import (
    RecomendacionItem,
    ReposicionListResponse,
    AjusteReposicionResponse,
    ExportarReposicionRequest
)
from app.schemas.reports import ExportarReporteResponse


class ReplenishmentService:
    @classmethod
    def list_recomendaciones(
        cls,
        db: Session,
        categoria: Optional[str] = None,
        prioridad: Optional[str] = None,
        solo_con_orden: bool = False,
        sku: Optional[str] = None,
        q: Optional[str] = None,
        fecha_limite_desde: Optional[date] = None,
        fecha_limite_hasta: Optional[date] = None
    ) -> ReposicionListResponse:
        modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
        if not modelo_activo:
            return ReposicionListResponse(total_recomendaciones=0, total_sugerido_unidades=0, items=[])

        umbrales = AlertService.get_thresholds_dict(db)
        lead_time_dias = settings.DEFAULT_LEAD_TIME_DAYS

        max_fecha_gen = db.query(func.max(Pronostico.fecha_generacion)).filter(
            Pronostico.id_modelo == modelo_activo.id_modelo
        ).scalar()
        if not max_fecha_gen:
            return ReposicionListResponse(total_recomendaciones=0, total_sugerido_unidades=0, items=[])

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
        total_unidades = 0
        fecha_gen = None

        for prod in productos:
            p_list = pron_by_prod.get(prod.id_producto, [])
            if not p_list:
                continue

            if sku and prod.sku.upper() != sku.upper().strip():
                continue

            if q:
                term = q.upper().strip()
                if (term not in prod.sku.upper()) and (term not in prod.nombre.upper()):
                    continue

            p_list = sorted(p_list, key=lambda x: x.horizonte_dias)
            primer_pron = p_list[0]
            if fecha_gen is None:
                fecha_gen = primer_pron.fecha_generacion

            demanda_14d = sum(float(x.cantidad_proyectada) for x in p_list)
            demanda_diaria = demanda_14d / 14.0 if demanda_14d > 0 else 1.0
            dias_cob = round(prod.stock_actual / demanda_diaria, 1) if demanda_diaria > 0 else 999.0

            prob_quiebre = 0.0
            if primer_pron.explicacion_shap and isinstance(primer_pron.explicacion_shap, dict):
                prob_quiebre = float(primer_pron.explicacion_shap.get("probabilidad_quiebre", 0.0))

            cant_sug = primer_pron.cantidad_sugerida_reposicion
            cant_ajust = primer_pron.cantidad_ajustada_reposicion

            dias_hasta_quiebre = math.floor(prod.stock_actual / demanda_diaria) if demanda_diaria > 0 else 999
            fecha_base_dt = primer_pron.fecha_generacion.date() if primer_pron.fecha_generacion else date.today()
            fecha_est_quiebre = fecha_base_dt + timedelta(days=dias_hasta_quiebre)
            fecha_lim = max(fecha_base_dt, fecha_est_quiebre - timedelta(days=lead_time_dias))

            if fecha_limite_desde and fecha_lim < fecha_limite_desde:
                continue
            if fecha_limite_hasta and fecha_lim > fecha_limite_hasta:
                continue

            umbral_cob_quiebre = umbrales["quiebre_dias_cobertura"]
            umbral_prob_quiebre = umbrales["quiebre_prob_min"]

            if dias_cob <= umbral_cob_quiebre or prob_quiebre >= (umbral_prob_quiebre * 5.0) or prod.stock_actual <= prod.punto_reorden:
                prio = "ALTA"
                motivo_prio = f"Cobertura crítica ({dias_cob} días frente a umbral {umbral_cob_quiebre:.1f}d) o quiebre inminente ({prob_quiebre:.1f}%)."
            elif dias_cob <= (umbral_cob_quiebre * 2.0):
                prio = "MEDIA"
                motivo_prio = f"Cobertura preventiva ajustada ({dias_cob} días)."
            else:
                prio = "BAJA"
                motivo_prio = f"Stock holgado ({dias_cob} días de cobertura)."

            if prioridad and prio != prioridad.upper():
                continue
            if solo_con_orden and cant_sug <= 0 and (cant_ajust is None or cant_ajust <= 0):
                continue

            unidades_item = cant_ajust if cant_ajust is not None else cant_sug
            total_unidades += unidades_item

            items.append(RecomendacionItem(
                id_pronostico=primer_pron.id_pronostico,
                id_producto=prod.id_producto,
                sku=prod.sku,
                nombre_producto=prod.nombre,
                categoria=prod.categoria,
                stock_actual=prod.stock_actual,
                punto_reorden=prod.punto_reorden,
                demanda_proyectada_14d=round(demanda_14d, 2),
                dias_cobertura=dias_cob,
                probabilidad_quiebre=prob_quiebre,
                cantidad_sugerida=cant_sug,
                cantidad_ajustada=cant_ajust,
                fecha_limite=fecha_lim,
                prioridad=prio,
                motivo_prioridad=motivo_prio
            ))

        prio_order = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
        items = sorted(items, key=lambda x: (prio_order.get(x.prioridad, 3), -x.probabilidad_quiebre))

        return ReposicionListResponse(
            total_recomendaciones=len(items),
            fecha_generacion=fecha_gen,
            total_sugerido_unidades=total_unidades,
            items=items
        )

    @classmethod
    def exportar_reposicion(
        cls,
        db: Session,
        payload: ExportarReposicionRequest,
        user_id: int
    ) -> ExportarReporteResponse:
        rep_dir = os.path.join(os.getcwd(), settings.STORAGE_REPORTES_DIR)
        os.makedirs(rep_dir, exist_ok=True)

        formato = payload.formato.lower().strip()
        if formato not in ["xlsx", "excel", "csv"]:
            raise ValueError(f"Formato no soportado: '{formato}'. Use 'xlsx' o 'csv'.")
        if formato == "excel":
            formato = "xlsx"

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_id = str(uuid.uuid4())[:8]

        res = cls.list_recomendaciones(
            db=db,
            categoria=payload.categoria,
            prioridad=payload.prioridad,
            solo_con_orden=payload.solo_con_orden,
            sku=payload.sku,
            q=payload.q,
            fecha_limite_desde=payload.fecha_limite_desde,
            fecha_limite_hasta=payload.fecha_limite_hasta
        )

        filename = f"reporte_reposicion_{timestamp_str}_{report_id}.{formato}"
        filepath = os.path.join(rep_dir, filename)

        if formato == "csv":
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "SKU", "Producto", "Categoría", "Stock Actual", "Punto Reorden",
                    "Demanda Proy. 14d", "Cobertura (días)", "P(Quiebre) %", "Sugerido Compra",
                    "Ajustado", "Fecha Límite", "Prioridad", "Motivo Prioridad"
                ])
                for it in res.items:
                    writer.writerow([
                        it.sku, it.nombre_producto, it.categoria, it.stock_actual, it.punto_reorden,
                        it.demanda_proyectada_14d, it.dias_cobertura, f"{it.probabilidad_quiebre}%",
                        it.cantidad_sugerida, it.cantidad_ajustada if it.cantidad_ajustada is not None else "",
                        it.fecha_limite.isoformat() if it.fecha_limite else "",
                        it.prioridad, it.motivo_prioridad
                    ])
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Recomendaciones"
            headers = [
                "SKU", "Producto", "Categoría", "Stock Actual", "Punto Reorden",
                "Demanda Proy. 14d", "Cobertura (días)", "P(Quiebre) %", "Sugerido Compra",
                "Ajustado", "Fecha Límite", "Prioridad", "Motivo Prioridad"
            ]
            ws.append(headers)

            header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_num)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")

            data_font = Font(name="Segoe UI", size=10)
            for it in res.items:
                ws.append([
                    it.sku, it.nombre_producto, it.categoria, it.stock_actual, it.punto_reorden,
                    it.demanda_proyectada_14d, it.dias_cobertura, f"{it.probabilidad_quiebre}%",
                    it.cantidad_sugerida, it.cantidad_ajustada if it.cantidad_ajustada is not None else "",
                    it.fecha_limite.isoformat() if it.fecha_limite else "",
                    it.prioridad, it.motivo_prioridad
                ])

            for row in ws.iter_rows(min_row=2, max_row=len(res.items) + 1, min_col=1, max_col=len(headers)):
                for cell in row:
                    cell.font = data_font

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

            wb.save(filepath)

        tamano_bytes = os.path.getsize(filepath)

        audit = Auditoria(
            id_usuario=user_id,
            accion="EXPORTACION_REPOSICION",
            modulo_afectado="reposicion",
            detalle={
                "tipo_reporte": "reposicion",
                "formato": formato,
                "nombre_archivo": filename,
                "tamano_bytes": tamano_bytes,
                "total_registros": len(res.items)
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
    def ajustar_reposicion(
        cls,
        db: Session,
        id_pronostico: int,
        cantidad_ajustada: int,
        user_id: int,
        motivo: Optional[str] = None
    ) -> AjusteReposicionResponse:
        pron = db.query(Pronostico).filter(Pronostico.id_pronostico == id_pronostico).first()
        if not pron:
            raise ValueError(f"Pronóstico con ID {id_pronostico} no encontrado.")

        prod = db.query(Producto).filter(Producto.id_producto == pron.id_producto).first()
        cant_ant = pron.cantidad_ajustada_reposicion

        pron.cantidad_ajustada_reposicion = cantidad_ajustada
        db.commit()

        audit = Auditoria(
            id_usuario=user_id,
            accion="AJUSTE_MANUAL_REPOSICION",
            modulo_afectado="reposicion",
            detalle={
                "id_pronostico": id_pronostico,
                "id_producto": prod.id_producto if prod else None,
                "sku": prod.sku if prod else "N/A",
                "cantidad_sugerida": pron.cantidad_sugerida_reposicion,
                "cantidad_anterior": cant_ant,
                "cantidad_ajustada": cantidad_ajustada,
                "motivo": motivo or "Ajuste manual del analista de inventarios"
            }
        )
        db.add(audit)
        db.commit()

        return AjusteReposicionResponse(
            id_pronostico=id_pronostico,
            id_producto=prod.id_producto if prod else 0,
            sku=prod.sku if prod else "",
            cantidad_sugerida=pron.cantidad_sugerida_reposicion,
            cantidad_ajustada=cantidad_ajustada,
            mensaje=f"Ajuste manual de {cantidad_ajustada} unidades registrado exitosamente para el SKU {prod.sku if prod else ''}."
        )
