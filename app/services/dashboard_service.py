from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.core.config import settings
from app.models.carga_datos import CargaDatos
from app.models.producto import Producto
from app.models.pronostico import Pronostico
from app.models.modelo_version import ModeloVersion
from app.models.alerta import Alerta
from app.models.venta_historica import VentaHistorica
from app.models.umbral_configuracion import UmbralConfiguracion
from app.services.alert_service import AlertService
from app.schemas.dashboard import (
    DashboardResumenResponse,
    KpiItem,
    CategoriaResumen,
    NivelServicioResponse,
    NivelServicioCategoriaItem,
    ProductoMasVendidoItem
)


class DashboardService:
    @classmethod
    def get_dashboard_resumen(cls, db: Session) -> DashboardResumenResponse:
        modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
        mape_global = float(modelo_activo.mape_14d) if (modelo_activo and modelo_activo.mape_14d is not None) else (float(modelo_activo.mape) if (modelo_activo and modelo_activo.mape is not None) else None)

        demanda_total_proy = 0.0
        pronosticos_activos = []
        if modelo_activo:
            max_fecha_gen = db.query(func.max(Pronostico.fecha_generacion)).filter(
                Pronostico.id_modelo == modelo_activo.id_modelo
            ).scalar()
            if max_fecha_gen:
                pronosticos_activos = db.query(Pronostico).filter(
                    Pronostico.id_modelo == modelo_activo.id_modelo,
                    Pronostico.fecha_generacion == max_fecha_gen
                ).all()
            demanda_total_proy = sum(float(p.cantidad_proyectada) for p in pronosticos_activos)

        productos = db.query(Producto).all()
        total_skus = len(productos)
        pron_by_prod: Dict[int, List[Pronostico]] = {}
        for pr in pronosticos_activos:
            pron_by_prod.setdefault(pr.id_producto, []).append(pr)

        u_ns = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "nivel_servicio_ref").first()
        meta_ns = float(u_ns.valor) if u_ns else 95.0
        u_mape = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
        meta_mape = float(u_mape.valor) if u_mape else 15.0
        u_quiebre_dias = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "quiebre_dias_cobertura").first()
        umbral_quiebre_dias = float(u_quiebre_dias.valor) if u_quiebre_dias else 7.0

        alertas_activas = db.query(Alerta, Producto, Pronostico).join(
            Producto, Alerta.id_producto == Producto.id_producto
        ).outerjoin(
            Pronostico, Alerta.id_pronostico == Pronostico.id_pronostico
        ).filter(func.upper(Alerta.estado).in_(["ACTIVA", "PENDIENTE"])).all()

        alertas_criticas = 0
        advertencias = 0

        for a, prod, pron in alertas_activas:
            if a.tipo_alerta == "QUIEBRE":
                prob_q = 0.0
                dias_c = 0.0
                if pron and pron.explicacion_shap and isinstance(pron.explicacion_shap, dict):
                    prob_q = float(pron.explicacion_shap.get("probabilidad_quiebre", 0.0))
                    dias_c = float(pron.explicacion_shap.get("dias_cobertura_stock", 0.0))
                elif pron:
                    dem_d = float(pron.cantidad_proyectada)
                    dias_c = round(prod.stock_actual / dem_d, 1) if dem_d > 0 else 999.0
                if AlertService.es_quiebre_critico(prob_q, dias_c, prod.stock_actual, prod.punto_reorden, umbral_quiebre_dias):
                    alertas_criticas += 1
                else:
                    advertencias += 1
            else:
                advertencias += 1

        skus_en_riesgo = sum(1 for p in productos if p.stock_actual <= p.punto_reorden)
        disp_global = round(((total_skus - skus_en_riesgo) / total_skus * 100.0), 1) if total_skus > 0 else 100.0

        demanda_satisfecha_total = 0.0
        for p in productos:
            p_demanda = sum(float(pr.cantidad_proyectada) for pr in pron_by_prod.get(p.id_producto, []))
            demanda_satisfecha_total += min(float(p.stock_actual), p_demanda)

        ns_global = round((demanda_satisfecha_total / demanda_total_proy * 100.0), 2) if demanda_total_proy > 0 else 100.0

        max_fecha_v = db.query(func.max(VentaHistorica.fecha)).scalar() or (date.today() - timedelta(days=1))
        fechas_hist = [max_fecha_v - timedelta(days=i) for i in range(13, -1, -1)]
        ventas_hist = db.query(
            VentaHistorica.fecha,
            func.sum(VentaHistorica.cantidad_vendida).label("total")
        ).filter(VentaHistorica.fecha.in_(fechas_hist)).group_by(VentaHistorica.fecha).order_by(VentaHistorica.fecha).all()
        total_ventas_14d_hist = sum(float(vh[1]) for vh in ventas_hist)
        tendencia_demanda = round(((demanda_total_proy - total_ventas_14d_hist) / total_ventas_14d_hist * 100.0), 1) if total_ventas_14d_hist > 0 else 0.0

        modelo_ant = db.query(ModeloVersion).filter(ModeloVersion.estado == "ANTERIOR").order_by(ModeloVersion.id_modelo.desc()).first()
        mape_activo_val = float(modelo_activo.mape_14d) if (modelo_activo and modelo_activo.mape_14d is not None) else (float(modelo_activo.mape) if (modelo_activo and modelo_activo.mape is not None) else None)
        mape_ant_val = float(modelo_ant.mape_14d) if (modelo_ant and modelo_ant.mape_14d is not None) else (float(modelo_ant.mape) if (modelo_ant and modelo_ant.mape is not None) else None)
        tendencia_mape = round(mape_activo_val - mape_ant_val, 2) if (mape_activo_val is not None and mape_ant_val is not None) else None

        precios_avg = dict(db.query(VentaHistorica.id_producto, func.avg(VentaHistorica.precio_unitario)).group_by(VentaHistorica.id_producto).all())
        valor_inventario_total = sum(p.stock_actual * float(precios_avg.get(p.id_producto, 0.0)) for p in productos)

        kpis = [
            KpiItem(
                nombre="Demanda Total Proyectada (14 días)",
                valor=f"{int(demanda_total_proy):,} und.",
                valor_numerico=round(demanda_total_proy, 2),
                unidad="unidades",
                tendencia_pct=tendencia_demanda,
                estado="POSITIVO"
            ),
            KpiItem(
                nombre="Valor Total del Inventario",
                valor=f"S/ {valor_inventario_total:,.2f}",
                valor_numerico=round(valor_inventario_total, 2),
                unidad="PEN",
                tendencia_pct=0.0,
                estado="POSITIVO"
            ),
            KpiItem(
                nombre="Precisión Global (MAPE Fuera de Muestra)",
                valor=f"{mape_global:.2f}%" if mape_global is not None else "—",
                valor_numerico=mape_global,
                unidad="%" if mape_global is not None else None,
                tendencia_pct=tendencia_mape,
                estado=("POSITIVO" if mape_global <= meta_mape else "ALERTA") if mape_global is not None else "NEUTRO"
            ),
            KpiItem(
                nombre="Nivel de Servicio Estimado (Fill Rate)",
                valor=f"{ns_global:.2f}%",
                valor_numerico=ns_global,
                unidad="%",
                tendencia_pct=None,
                estado="POSITIVO" if ns_global >= meta_ns else "ALERTA"
            ),
            KpiItem(
                nombre="Disponibilidad de Catálogo",
                valor=f"{disp_global:.1f}%",
                valor_numerico=disp_global,
                unidad="%",
                tendencia_pct=0.0,
                estado="POSITIVO" if disp_global >= meta_ns else "ALERTA"
            ),
            KpiItem(
                nombre="Alertas Críticas (Quiebre Inminente)",
                valor=str(alertas_criticas),
                valor_numerico=float(alertas_criticas),
                unidad="alertas",
                tendencia_pct=None,
                estado="ALERTA" if alertas_criticas > 0 else "POSITIVO"
            ),
            KpiItem(
                nombre="Advertencias de Inventario",
                valor=str(advertencias),
                valor_numerico=float(advertencias),
                unidad="alertas",
                tendencia_pct=0.0,
                estado="ALERTA" if advertencias > 5 else "POSITIVO"
            )
        ]

        categorias_unicas = sorted(list(set(p.categoria for p in productos)))

        categorias_resumen = []
        for cat in categorias_unicas:
            prods_cat = [p for p in productos if p.categoria == cat]
            stock_cat = sum(p.stock_actual for p in prods_cat)
            demanda_cat = sum(sum(float(x.cantidad_proyectada) for x in pron_by_prod.get(p.id_producto, [])) for p in prods_cat)
            satisfecha_cat = sum(min(float(p.stock_actual), sum(float(x.cantidad_proyectada) for x in pron_by_prod.get(p.id_producto, []))) for p in prods_cat)
            ns_cat = round((satisfecha_cat / demanda_cat * 100.0), 2) if demanda_cat > 0 else 100.0

            aq = db.query(Alerta).join(Producto).filter(Producto.categoria == cat, Alerta.tipo_alerta == "QUIEBRE", func.upper(Alerta.estado).in_(["ACTIVA", "PENDIENTE"])).count()
            asob = db.query(Alerta).join(Producto).filter(Producto.categoria == cat, Alerta.tipo_alerta == "SOBRESTOCK", func.upper(Alerta.estado).in_(["ACTIVA", "PENDIENTE"])).count()

            categorias_resumen.append(CategoriaResumen(
                categoria=cat,
                total_skus=len(prods_cat),
                stock_total=stock_cat,
                demanda_proyectada_14d=round(demanda_cat, 2),
                nivel_servicio_estimado_pct=ns_cat,
                alertas_quiebre=aq,
                alertas_sobrestock=asob
            ))

        candidatos_quiebre = []
        for p in productos:
            pr_list = pron_by_prod.get(p.id_producto, [])
            d_14 = sum(float(x.cantidad_proyectada) for x in pr_list) if pr_list else 1.0
            d_dia = d_14 / 14.0 if d_14 > 0 else 1.0
            cob = round(p.stock_actual / d_dia, 1)
            p_q = 0.0
            if pr_list and pr_list[0].explicacion_shap and isinstance(pr_list[0].explicacion_shap, dict):
                p_q = float(pr_list[0].explicacion_shap.get("probabilidad_quiebre", 0.0))

            candidatos_quiebre.append({
                "sku": p.sku,
                "nombre": p.nombre,
                "categoria": p.categoria,
                "stock_actual": p.stock_actual,
                "dias_cobertura": cob,
                "probabilidad_quiebre": p_q
            })

        candidatos_quiebre = sorted(candidatos_quiebre, key=lambda x: (x["dias_cobertura"], -x["probabilidad_quiebre"]))[:5]

        max_fecha_v = db.query(func.max(VentaHistorica.fecha)).scalar() or (date.today() - timedelta(days=1))
        fechas_hist = [max_fecha_v - timedelta(days=i) for i in range(13, -1, -1)]
        ventas_hist = db.query(
            VentaHistorica.fecha,
            func.sum(VentaHistorica.cantidad_vendida).label("total")
        ).filter(VentaHistorica.fecha.in_(fechas_hist)).group_by(VentaHistorica.fecha).order_by(VentaHistorica.fecha).all()

        v_dict = {vh[0]: vh[1] for vh in ventas_hist}
        tendencia = []
        for fh in fechas_hist:
            tendencia.append({
                "tipo": "historico",
                "fecha": fh.isoformat(),
                "volumen": int(v_dict.get(fh, 0))
            })

        if pronosticos_activos:
            p_por_dia = {}
            for pr in pronosticos_activos:
                f_obj = (pr.fecha_generacion + timedelta(days=pr.horizonte_dias)).date()
                p_por_dia[f_obj] = p_por_dia.get(f_obj, 0.0) + float(pr.cantidad_proyectada)
            for f_obj in sorted(p_por_dia.keys()):
                tendencia.append({
                    "tipo": "proyectado",
                    "fecha": f_obj.isoformat(),
                    "volumen": round(p_por_dia[f_obj], 2)
                })

        productos_mas_vendidos = cls.get_productos_mas_vendidos(db)

        ult_v = db.query(CargaDatos).filter(
            CargaDatos.tipo_carga == "ventas",
            CargaDatos.estado.in_(["COMPLETADO", "CON_ADVERTENCIAS"])
        ).order_by(CargaDatos.fecha_ejecucion.desc()).first()

        ult_i = db.query(CargaDatos).filter(
            CargaDatos.tipo_carga == "inventario",
            CargaDatos.estado.in_(["COMPLETADO", "CON_ADVERTENCIAS"])
        ).order_by(CargaDatos.fecha_ejecucion.desc()).first()

        fechas_cargas = [c.fecha_ejecucion for c in [ult_v, ult_i] if c and c.fecha_ejecucion]
        if len(fechas_cargas) == 2:
            ultima_actualizacion_datos = min(fechas_cargas)
        elif len(fechas_cargas) == 1:
            ultima_actualizacion_datos = fechas_cargas[0]
        else:
            ultima_actualizacion_datos = None

        datos_desactualizados = False
        if ultima_actualizacion_datos:
            now = datetime.now(timezone.utc)
            dt_comp = ultima_actualizacion_datos.replace(tzinfo=timezone.utc) if ultima_actualizacion_datos.tzinfo is None else ultima_actualizacion_datos
            datos_desactualizados = (now - dt_comp) > timedelta(hours=settings.DASHBOARD_STALE_HOURS)

        return DashboardResumenResponse(
            kpis=kpis,
            categorias=categorias_resumen,
            top_riesgo_quiebre=candidatos_quiebre,
            tendencia_diaria_general=tendencia,
            productos_mas_vendidos=productos_mas_vendidos,
            ultima_actualizacion_datos=ultima_actualizacion_datos,
            datos_desactualizados=datos_desactualizados
        )

    @classmethod
    def get_productos_mas_vendidos(cls, db: Session, dias: int = 30) -> List[ProductoMasVendidoItem]:
        max_d = db.query(func.max(VentaHistorica.fecha)).scalar()
        if not max_d:
            return []

        t_start_act = max_d - timedelta(days=dias - 1)
        t_end_ant = max_d - timedelta(days=dias)
        t_start_ant = max_d - timedelta(days=(2 * dias) - 1)

        v_act = db.query(
            VentaHistorica.id_producto,
            func.sum(VentaHistorica.cantidad_vendida).label("unidades"),
            func.sum(VentaHistorica.cantidad_vendida * VentaHistorica.precio_unitario).label("ingresos")
        ).filter(
            VentaHistorica.fecha.between(t_start_act, max_d)
        ).group_by(VentaHistorica.id_producto).all()

        v_act_dict = {r[0]: {"unidades": int(r[1]), "ingresos": float(r[2])} for r in v_act}

        v_ant = db.query(
            VentaHistorica.id_producto,
            func.sum(VentaHistorica.cantidad_vendida).label("unidades")
        ).filter(
            VentaHistorica.fecha.between(t_start_ant, t_end_ant)
        ).group_by(VentaHistorica.id_producto).all()

        v_ant_dict = {r[0]: int(r[1]) for r in v_ant}

        top5_ids = sorted(v_act_dict.keys(), key=lambda pid: v_act_dict[pid]["unidades"], reverse=True)[:5]
        prods = {p.id_producto: p for p in db.query(Producto).filter(Producto.id_producto.in_(top5_ids)).all()}

        top5 = []
        for pid in top5_ids:
            p = prods.get(pid)
            if not p:
                continue
            u_act = v_act_dict[pid]["unidades"]
            ing_act = round(v_act_dict[pid]["ingresos"], 2)
            u_ant = v_ant_dict.get(pid, 0)
            if u_ant > 0:
                var = round(((u_act - u_ant) / u_ant * 100.0), 2)
            else:
                var = 100.0 if u_act > 0 else 0.0

            top5.append(ProductoMasVendidoItem(
                sku=p.sku,
                nombre=p.nombre,
                categoria=p.categoria,
                unidades_vendidas=u_act,
                ingresos_totales=ing_act,
                unidades_periodo_anterior=u_ant,
                variacion_pct=var,
                periodo_dias=dias,
                fecha_inicio=t_start_act.isoformat(),
                fecha_fin=max_d.isoformat()
            ))

        return top5

    @classmethod
    def get_nivel_servicio_detalle(
        cls,
        db: Session,
        sku: Optional[str] = None,
        categoria: Optional[str] = None,
        periodo: Optional[str] = None,
        almacen: Optional[str] = "Principal"
    ) -> NivelServicioResponse:
        u_ns = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "nivel_servicio_ref").first()
        meta_ns = float(u_ns.valor) if u_ns else 95.0

        q_prod = db.query(Producto)
        if categoria:
            q_prod = q_prod.filter(Producto.categoria == categoria)
        if sku:
            q_prod = q_prod.filter(Producto.sku == sku.upper().strip())
        productos = q_prod.all()

        modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()

        pron_by_prod: Dict[int, float] = {}
        if modelo_activo:
            max_fecha_gen = db.query(func.max(Pronostico.fecha_generacion)).filter(
                Pronostico.id_modelo == modelo_activo.id_modelo
            ).scalar()
            if max_fecha_gen:
                pronosticos = db.query(Pronostico).filter(
                    Pronostico.id_modelo == modelo_activo.id_modelo,
                    Pronostico.fecha_generacion == max_fecha_gen
                ).all()
                for p in pronosticos:
                    pron_by_prod[p.id_producto] = pron_by_prod.get(p.id_producto, 0.0) + float(p.cantidad_proyectada)

        categorias_unicas = sorted(list(set(p.categoria for p in productos)))
        items_cat = []

        total_skus_global = len(productos)
        skus_riesgo_global = 0
        demanda_acum_total = 0.0
        demanda_satisfecha_total = 0.0

        for cat in categorias_unicas:
            prods_cat = [p for p in productos if p.categoria == cat]
            t_skus = len(prods_cat)
            riesgo = sum(1 for p in prods_cat if p.stock_actual <= p.punto_reorden)
            skus_riesgo_global += riesgo

            stock_total = sum(p.stock_actual for p in prods_cat)
            demanda_cat = sum(pron_by_prod.get(p.id_producto, 0.0) for p in prods_cat)

            satisfecha_cat = sum(min(p.stock_actual, pron_by_prod.get(p.id_producto, 0.0)) for p in prods_cat)
            demanda_acum_total += demanda_cat
            demanda_satisfecha_total += satisfecha_cat

            fill_rate = round((satisfecha_cat / demanda_cat * 100.0), 2) if demanda_cat > 0 else 100.0
            disp_cat = round(((t_skus - riesgo) / t_skus * 100.0), 2) if t_skus > 0 else 100.0

            items_cat.append(NivelServicioCategoriaItem(
                categoria=cat,
                total_skus=t_skus,
                skus_en_riesgo=riesgo,
                stock_total=stock_total,
                demanda_proyectada=round(demanda_cat, 2),
                fill_rate_estimado_pct=fill_rate,
                disponibilidad_catalogo_pct=disp_cat,
                cumple_meta=(fill_rate >= meta_ns)
            ))

        ns_global = round((demanda_satisfecha_total / demanda_acum_total * 100.0), 2) if demanda_acum_total > 0 else 100.0
        disp_global = round(((total_skus_global - skus_riesgo_global) / total_skus_global * 100.0), 2) if total_skus_global > 0 else 100.0

        return NivelServicioResponse(
            meta_referencial_pct=meta_ns,
            nivel_servicio_global_pct=ns_global,
            disponibilidad_global_pct=disp_global,
            total_skus=total_skus_global,
            skus_disponibles=total_skus_global - skus_riesgo_global,
            skus_en_riesgo=skus_riesgo_global,
            es_estimacion=True,
            nota_metodologica="Métrica analítica modelada sobre el catálogo activo y el pronóstico a 14 días ante la ausencia de registros de saldos físicos diarios en la base transaccional de FasRetail.",
            linea_base_historica_disponible=False,
            mensaje_linea_base="No existen saldos diarios históricos de inventario; el nivel de servicio proyectado se compara contra la meta referencial.",
            almacenes=["Principal"],
            almacen_seleccionado=almacen or "Principal",
            categoria_filtrada=categoria,
            sku_filtrado=sku,
            periodo_filtrado=periodo,
            por_categoria=items_cat
        )
