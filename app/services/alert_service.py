import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.models.alerta import Alerta
from app.models.producto import Producto
from app.models.pronostico import Pronostico
from app.models.modelo_version import ModeloVersion
from app.models.umbral_configuracion import UmbralConfiguracion
from app.models.auditoria import Auditoria
from app.schemas.alerts import AlertaItem, AlertasResumen

logger = logging.getLogger(__name__)


class AlertService:
    @staticmethod
    def get_thresholds_dict(db: Session) -> Dict[str, float]:
        umbrales = db.query(UmbralConfiguracion).all()
        u_dict = {u.tipo_umbral: float(u.valor) for u in umbrales}
        return {
            "quiebre_prob_min": u_dict.get("quiebre_prob_min", settings.DEFAULT_STOCKOUT_MIN_PROBABILITY),
            "quiebre_dias_cobertura": u_dict.get("quiebre_dias_cobertura", float(settings.DEFAULT_STOCKOUT_MIN_COVERAGE_DAYS)),
            "sobrestock_pct": u_dict.get("sobrestock_pct", settings.DEFAULT_OVERSTOCK_MAX_DEMAND_PCT),
            "sobrestock_dias": u_dict.get("sobrestock_dias", float(settings.DEFAULT_OVERSTOCK_MAX_COVERAGE_DAYS)),
            "calidad_min": u_dict.get("calidad_min", settings.DEFAULT_DATA_QUALITY_THRESHOLD),
            "mape_max": u_dict.get("mape_max", 15.0),
            "nivel_servicio_ref": u_dict.get("nivel_servicio_ref", 95.0),
        }

    @classmethod
    def sincronizar_alertas(cls, db: Session, notificar: bool = True) -> int:
        modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
        if not modelo_activo:
            return 0

        umbrales = cls.get_thresholds_dict(db)
        max_fecha_gen = db.query(func.max(Pronostico.fecha_generacion)).filter(
            Pronostico.id_modelo == modelo_activo.id_modelo
        ).scalar()
        if not max_fecha_gen:
            return 0

        pronosticos = db.query(Pronostico).filter(
            Pronostico.id_modelo == modelo_activo.id_modelo,
            Pronostico.fecha_generacion == max_fecha_gen
        ).all()

        pron_by_prod: Dict[int, List[Pronostico]] = {}
        for p in pronosticos:
            pron_by_prod.setdefault(p.id_producto, []).append(p)

        productos = db.query(Producto).all()
        alertas_creadas = 0
        nuevas_alertas_info: List[Dict[str, Any]] = []

        for prod in productos:
            p_list = pron_by_prod.get(prod.id_producto, [])
            if not p_list:
                logger.warning(
                    f"SKU {prod.sku} (ID {prod.id_producto}) no tiene pronósticos generados. "
                    "Se trata como 'sin dato', omitiendo generación de alerta de quiebre."
                )
                continue

            p_list = sorted(p_list, key=lambda x: x.horizonte_dias)
            primer_pron = p_list[0]
            demanda_acum_14d = sum(float(x.cantidad_proyectada) for x in p_list)
            if demanda_acum_14d <= 0:
                logger.warning(
                    f"SKU {prod.sku} (ID {prod.id_producto}) tiene demanda acumulada <= 0 ({demanda_acum_14d}). "
                    "Se trata como 'sin dato', omitiendo generación de alerta de quiebre."
                )
                continue

            db.query(Alerta).filter(
                Alerta.id_producto == prod.id_producto,
                Alerta.id_pronostico.is_(None)
            ).update({Alerta.id_pronostico: primer_pron.id_pronostico}, synchronize_session=False)

            demanda_prom_diaria = demanda_acum_14d / 14.0
            dias_cobertura = prod.stock_actual / demanda_prom_diaria if demanda_prom_diaria > 0 else 999.0
            prob_quiebre = 0.0
            if primer_pron.explicacion_shap and isinstance(primer_pron.explicacion_shap, dict):
                prob_quiebre = float(primer_pron.explicacion_shap.get("probabilidad_quiebre", 0.0))

            es_quiebre = (
                prob_quiebre >= umbrales["quiebre_prob_min"]
                or dias_cobertura <= umbrales["quiebre_dias_cobertura"]
                or prod.stock_actual <= prod.punto_reorden
            )

            alertas_quiebre = db.query(Alerta).filter(
                Alerta.id_producto == prod.id_producto,
                Alerta.tipo_alerta == "QUIEBRE"
            ).order_by(Alerta.id_alerta.desc()).all()

            alerta_quiebre_activa = next(
                (a for a in alertas_quiebre if (a.estado or "").upper() in ["ACTIVA", "PENDIENTE"]),
                None
            )
            ultima_quiebre_inactiva = next(
                (a for a in alertas_quiebre if (a.estado or "").upper() in ["RESUELTA", "DESCARTADA"]),
                None
            )

            if alerta_quiebre_activa:
                if es_quiebre:
                    if alerta_quiebre_activa.id_pronostico != primer_pron.id_pronostico:
                        alerta_quiebre_activa.id_pronostico = primer_pron.id_pronostico
                else:
                    alerta_quiebre_activa.estado = "RESUELTA"
                    alerta_quiebre_activa.fecha_revision = datetime.utcnow()
            elif es_quiebre:
                crear_alerta = True
                if ultima_quiebre_inactiva:
                    pron_ant = db.query(Pronostico).filter(
                        Pronostico.id_pronostico == ultima_quiebre_inactiva.id_pronostico
                    ).first() if ultima_quiebre_inactiva.id_pronostico else None

                    if pron_ant and primer_pron.fecha_generacion.date() <= pron_ant.fecha_generacion.date():
                        crear_alerta = False
                        if ultima_quiebre_inactiva.id_pronostico != primer_pron.id_pronostico:
                            ultima_quiebre_inactiva.id_pronostico = primer_pron.id_pronostico
                    elif ultima_quiebre_inactiva.id_pronostico == primer_pron.id_pronostico:
                        crear_alerta = False
                    elif ultima_quiebre_inactiva.fecha_generacion.date() >= primer_pron.fecha_generacion.date():
                        crear_alerta = False

                if crear_alerta:
                    db.add(Alerta(
                        id_producto=prod.id_producto,
                        id_pronostico=primer_pron.id_pronostico,
                        tipo_alerta="QUIEBRE",
                        fecha_generacion=datetime.utcnow(),
                        estado="ACTIVA"
                    ))
                    alertas_creadas += 1
                    es_crit = cls.es_quiebre_critico(
                        prob_quiebre=prob_quiebre,
                        dias_cob=dias_cobertura,
                        stock_actual=prod.stock_actual,
                        punto_reorden=prod.punto_reorden,
                        u_cob_quiebre=umbrales["quiebre_dias_cobertura"]
                    )
                    nuevas_alertas_info.append({
                        "sku": prod.sku,
                        "nombre_producto": prod.nombre,
                        "tipo_alerta": "QUIEBRE",
                        "tipo_notif": "quiebre_critico",
                        "prioridad": "ALTA" if es_crit else "MEDIA",
                        "dias_cobertura": round(dias_cobertura, 1),
                        "probabilidad_quiebre": round(prob_quiebre, 1)
                    })

            ratio_stock_reorden = (prod.stock_actual / prod.punto_reorden * 100.0) if prod.punto_reorden > 0 else 0.0
            es_sobrestock = (
                dias_cobertura > umbrales["sobrestock_dias"]
                and ratio_stock_reorden >= umbrales["sobrestock_pct"]
            )

            alertas_sobrestock = db.query(Alerta).filter(
                Alerta.id_producto == prod.id_producto,
                Alerta.tipo_alerta == "SOBRESTOCK"
            ).order_by(Alerta.id_alerta.desc()).all()

            alerta_sobrestock_activa = next(
                (a for a in alertas_sobrestock if (a.estado or "").upper() in ["ACTIVA", "PENDIENTE"]),
                None
            )
            ultima_sobrestock_inactiva = next(
                (a for a in alertas_sobrestock if (a.estado or "").upper() in ["RESUELTA", "DESCARTADA"]),
                None
            )

            if alerta_sobrestock_activa:
                if es_sobrestock:
                    if alerta_sobrestock_activa.id_pronostico != primer_pron.id_pronostico:
                        alerta_sobrestock_activa.id_pronostico = primer_pron.id_pronostico
                else:
                    alerta_sobrestock_activa.estado = "RESUELTA"
                    alerta_sobrestock_activa.fecha_revision = datetime.utcnow()
            elif es_sobrestock:
                crear_alerta_s = True
                if ultima_sobrestock_inactiva:
                    pron_ant_s = db.query(Pronostico).filter(
                        Pronostico.id_pronostico == ultima_sobrestock_inactiva.id_pronostico
                    ).first() if ultima_sobrestock_inactiva.id_pronostico else None

                    if pron_ant_s and primer_pron.fecha_generacion.date() <= pron_ant_s.fecha_generacion.date():
                        crear_alerta_s = False
                        if ultima_sobrestock_inactiva.id_pronostico != primer_pron.id_pronostico:
                            ultima_sobrestock_inactiva.id_pronostico = primer_pron.id_pronostico
                    elif ultima_sobrestock_inactiva.id_pronostico == primer_pron.id_pronostico:
                        crear_alerta_s = False
                    elif ultima_sobrestock_inactiva.fecha_generacion.date() >= primer_pron.fecha_generacion.date():
                        crear_alerta_s = False

                if crear_alerta_s:
                    db.add(Alerta(
                        id_producto=prod.id_producto,
                        id_pronostico=primer_pron.id_pronostico,
                        tipo_alerta="SOBRESTOCK",
                        fecha_generacion=datetime.utcnow(),
                        estado="ACTIVA"
                    ))
                    alertas_creadas += 1
                    nuevas_alertas_info.append({
                        "sku": prod.sku,
                        "nombre_producto": prod.nombre,
                        "tipo_alerta": "SOBRESTOCK",
                        "tipo_notif": "sobrestock_prolongado",
                        "prioridad": "MEDIA",
                        "dias_cobertura": round(dias_cobertura, 1),
                        "probabilidad_quiebre": None
                    })

        db.commit()

        if notificar and nuevas_alertas_info:
            try:
                from app.services.scheduler import get_procesos_config
                from app.services.email_service import EmailService, parse_emails_destinatarios

                cfg = get_procesos_config()
                notif_quiebre = cfg.get("quiebre_critico", cfg.get("notificar_quiebre", True))
                notif_sobrestock = cfg.get("sobrestock_prolongado", cfg.get("notificar_sobrestock", True))

                alertas_filtradas = []
                for a in nuevas_alertas_info:
                    if a["tipo_notif"] == "quiebre_critico" and notif_quiebre:
                        alertas_filtradas.append(a)
                    elif a["tipo_notif"] == "sobrestock_prolongado" and notif_sobrestock:
                        alertas_filtradas.append(a)

                if alertas_filtradas:
                    raw_email = cfg.get("correo_alertas") or cfg.get("alertas_notificacion_email", "alertas@fasretail.com")
                    try:
                        destinatarios = parse_emails_destinatarios(raw_email)
                    except Exception as ve:
                        logger.warning(f"Destinatarios de alertas inválidos en procesos.json: {ve}")
                        destinatarios = []

                    if destinatarios:
                        EmailService.enviar_resumen_alertas(
                            destinatarios=destinatarios,
                            alertas=alertas_filtradas,
                            db=db
                        )
            except Exception as exc:
                logger.error(f"Error al despachar notificación de alertas nuevas por correo: {exc}")

        return alertas_creadas

    @classmethod
    def es_quiebre_critico(
        cls,
        prob_quiebre: float,
        dias_cob: Optional[float],
        stock_actual: int,
        punto_reorden: int,
        u_cob_quiebre: float
    ) -> bool:
        limite_critico_dias = u_cob_quiebre * settings.ALERT_CRITICAL_COVERAGE_FACTOR
        limite_critico_stock = punto_reorden * settings.ALERT_CRITICAL_REORDER_POINT_FACTOR
        es_critico_dias = (dias_cob is not None and dias_cob <= limite_critico_dias)
        return (
            prob_quiebre >= settings.ALERT_CRITICAL_STOCKOUT_PROB_MIN
            or es_critico_dias
            or stock_actual <= limite_critico_stock
        )

    @classmethod
    def obtener_alertas_activas_para_resumen(
        cls,
        db: Session,
        cfg: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        if cfg is None:
            from app.services.scheduler import get_procesos_config
            cfg = get_procesos_config()

        notif_quiebre = cfg.get("quiebre_critico", cfg.get("notificar_quiebre", True))
        notif_sobrestock = cfg.get("sobrestock_prolongado", cfg.get("notificar_sobrestock", True))

        umbrales = cls.get_thresholds_dict(db)
        u_cob_quiebre = umbrales["quiebre_dias_cobertura"]

        alertas_activas_db = db.query(Alerta, Producto, Pronostico).join(
            Producto, Alerta.id_producto == Producto.id_producto
        ).outerjoin(
            Pronostico, Alerta.id_pronostico == Pronostico.id_pronostico
        ).filter(
            func.upper(Alerta.estado).in_(["ACTIVA", "PENDIENTE"])
        ).order_by(Alerta.id_alerta.desc()).all()

        alertas_resumen = []
        for alerta, prod, pron in alertas_activas_db:
            t_alerta = (alerta.tipo_alerta or "").upper()

            if t_alerta == "QUIEBRE" and not notif_quiebre:
                continue
            if t_alerta == "SOBRESTOCK" and not notif_sobrestock:
                continue

            prob_quiebre = 0.0
            dias_cob = None
            if pron and pron.explicacion_shap and isinstance(pron.explicacion_shap, dict):
                prob_quiebre = float(pron.explicacion_shap.get("probabilidad_quiebre", 0.0))
                dias_cob = float(pron.explicacion_shap.get("dias_cobertura_stock", 0.0))
            elif pron:
                dem_diaria = float(pron.cantidad_proyectada)
                dias_cob = round(prod.stock_actual / dem_diaria, 1) if dem_diaria > 0 else 999.0
            else:
                dias_cob = 999.0

            if t_alerta == "QUIEBRE":
                es_critica = cls.es_quiebre_critico(prob_quiebre, dias_cob, prod.stock_actual, prod.punto_reorden, u_cob_quiebre)
                prio = "ALTA" if es_critica else "MEDIA"
                tipo_notif = "quiebre_critico"
            else:
                prio = "MEDIA"
                tipo_notif = "sobrestock_prolongado"

            alertas_resumen.append({
                "sku": prod.sku,
                "nombre_producto": prod.nombre,
                "tipo_alerta": alerta.tipo_alerta,
                "tipo_notif": tipo_notif,
                "prioridad": prio,
                "dias_cobertura": round(dias_cob, 1) if dias_cob is not None else None,
                "probabilidad_quiebre": round(prob_quiebre, 1) if prob_quiebre is not None else None
            })

        return alertas_resumen

    @classmethod
    def list_alertas(
        cls,
        db: Session,
        tipo: Optional[str] = None,
        estado: Optional[str] = None,
        categoria: Optional[str] = None,
        prioridad: Optional[str] = None
    ) -> AlertasResumen:
        umbrales = cls.get_thresholds_dict(db)
        u_cob_quiebre = umbrales["quiebre_dias_cobertura"]
        u_dias_sobre = umbrales["sobrestock_dias"]

        todas_alertas = db.query(Alerta, Producto, Pronostico).join(
            Producto, Alerta.id_producto == Producto.id_producto
        ).outerjoin(
            Pronostico, Alerta.id_pronostico == Pronostico.id_pronostico
        ).all()

        tot_activas = 0
        tot_criticas = 0
        tot_advertencias = 0
        tot_quiebre = 0
        tot_sobrestock = 0
        tot_resueltas = 0
        tot_descartadas = 0

        for alerta, prod, pron in todas_alertas:
            prob_quiebre = 0.0
            dias_cob = None
            if pron and pron.explicacion_shap and isinstance(pron.explicacion_shap, dict):
                prob_quiebre = float(pron.explicacion_shap.get("probabilidad_quiebre", 0.0))
                dias_cob = float(pron.explicacion_shap.get("dias_cobertura_stock", 0.0))
            elif pron:
                dem_diaria = float(pron.cantidad_proyectada)
                dias_cob = round(prod.stock_actual / dem_diaria, 1) if dem_diaria > 0 else 999.0
            else:
                dias_cob = 999.0

            if alerta.tipo_alerta == "QUIEBRE":
                es_critica = cls.es_quiebre_critico(prob_quiebre, dias_cob, prod.stock_actual, prod.punto_reorden, u_cob_quiebre)
                severidad = "CRITICA" if es_critica else "ADVERTENCIA"
                prio = "ALTA" if es_critica else "MEDIA"
            else:
                severidad = "ADVERTENCIA"
                prio = "MEDIA"

            st = (alerta.estado or "").upper()
            if st in ["ACTIVA", "PENDIENTE"]:
                tot_activas += 1
                if alerta.tipo_alerta == "QUIEBRE":
                    tot_quiebre += 1
                elif alerta.tipo_alerta == "SOBRESTOCK":
                    tot_sobrestock += 1

                if prio == "ALTA" or severidad == "CRITICA":
                    tot_criticas += 1
                else:
                    tot_advertencias += 1
            elif st == "RESUELTA":
                tot_resueltas += 1
            elif st == "DESCARTADA":
                tot_descartadas += 1

        query = db.query(Alerta, Producto, Pronostico).join(
            Producto, Alerta.id_producto == Producto.id_producto
        ).outerjoin(
            Pronostico, Alerta.id_pronostico == Pronostico.id_pronostico
        )

        if tipo:
            query = query.filter(Alerta.tipo_alerta == tipo.upper())
        if estado:
            st_filtro = estado.strip().upper()
            if st_filtro in ["ACTIVA", "PENDIENTE"]:
                query = query.filter(func.upper(Alerta.estado).in_(["ACTIVA", "PENDIENTE"]))
            elif st_filtro == "RESUELTA":
                query = query.filter(func.upper(Alerta.estado) == "RESUELTA")
            elif st_filtro == "DESCARTADA":
                query = query.filter(func.upper(Alerta.estado) == "DESCARTADA")
            else:
                query = query.filter(func.upper(Alerta.estado) == st_filtro)
        if categoria:
            query = query.filter(Producto.categoria == categoria)

        results = query.order_by(Alerta.id_alerta.desc()).all()
        items = []

        for alerta, prod, pron in results:
            prob_quiebre = 0.0
            dias_cob = None
            if pron and pron.explicacion_shap and isinstance(pron.explicacion_shap, dict):
                prob_quiebre = float(pron.explicacion_shap.get("probabilidad_quiebre", 0.0))
                dias_cob = float(pron.explicacion_shap.get("dias_cobertura_stock", 0.0))
            elif pron:
                dem_diaria = float(pron.cantidad_proyectada)
                dias_cob = round(prod.stock_actual / dem_diaria, 1) if dem_diaria > 0 else 999.0
            else:
                logger.warning(
                    f"Alerta ID {alerta.id_alerta} (SKU {prod.sku}) no cuenta con pronóstico asociado. "
                    "Tratado como 'sin dato'; no se evalúa severidad crítica por cobertura."
                )
                dias_cob = 999.0

            if alerta.tipo_alerta == "QUIEBRE":
                es_critica = cls.es_quiebre_critico(prob_quiebre, dias_cob, prod.stock_actual, prod.punto_reorden, u_cob_quiebre)
                severidad = "CRITICA" if es_critica else "ADVERTENCIA"
                prio = "ALTA" if es_critica else "MEDIA"
                if severidad == "CRITICA":
                    motivo = f"Riesgo crítico de quiebre (prioridad ALTA): {dias_cob:.1f} días de cobertura (umbral: {u_cob_quiebre:.1f}d), P(quiebre): {prob_quiebre:.1f}%."
                else:
                    motivo = f"Advertencia preventiva de quiebre (prioridad MEDIA): {dias_cob:.1f} días de cobertura (umbral: {u_cob_quiebre:.1f}d)."
            else:
                severidad = "ADVERTENCIA"
                prio = "MEDIA"
                motivo = f"Exceso de inventario inmovilizado (prioridad MEDIA): {dias_cob:.1f} días de cobertura (umbral: {u_dias_sobre:.1f}d)."

            if prioridad and prio != prioridad.upper():
                continue

            st_alerta = (alerta.estado or "ACTIVA").upper()
            if st_alerta == "PENDIENTE":
                st_alerta = "ACTIVA"

            items.append(AlertaItem(
                id_alerta=alerta.id_alerta,
                id_producto=prod.id_producto,
                sku=prod.sku,
                nombre_producto=prod.nombre,
                categoria=prod.categoria,
                tipo_alerta=alerta.tipo_alerta,
                nivel_severidad=severidad,
                prioridad=prio,
                fecha_generacion=alerta.fecha_generacion,
                estado=st_alerta,
                fecha_revision=alerta.fecha_revision,
                stock_actual=prod.stock_actual,
                punto_reorden=prod.punto_reorden,
                dias_cobertura=dias_cob,
                probabilidad_quiebre=prob_quiebre,
                detalle_motivo=motivo
            ))

        from app.schemas.alerts import ConteosAlertas
        conteos = ConteosAlertas(
            activas=tot_activas,
            criticas=tot_criticas,
            advertencias=tot_advertencias,
            quiebre=tot_quiebre,
            sobrestock=tot_sobrestock,
            resueltas=tot_resueltas,
            descartadas=tot_descartadas
        )

        return AlertasResumen(
            activas=tot_activas,
            criticas=tot_criticas,
            advertencias=tot_advertencias,
            quiebre=tot_quiebre,
            sobrestock=tot_sobrestock,
            resueltas=tot_resueltas,
            descartadas=tot_descartadas,
            total_activas=tot_activas,
            total_criticas=tot_criticas,
            total_advertencias=tot_advertencias,
            total_quiebre=tot_quiebre,
            total_sobrestock=tot_sobrestock,
            total_resueltas=tot_resueltas,
            total_descartadas=tot_descartadas,
            conteos=conteos,
            items=items
        )

    @classmethod
    def cambiar_estado_alerta(
        cls,
        db: Session,
        id_alerta: int,
        nuevo_estado: str,
        user_id: int,
        comentario: Optional[str] = None
    ) -> Alerta:
        alerta = db.query(Alerta).filter(Alerta.id_alerta == id_alerta).first()
        if not alerta:
            raise ValueError(f"Alerta con ID {id_alerta} no encontrada.")

        estado_norm = nuevo_estado.strip().upper()
        if estado_norm not in {"ACTIVA", "RESUELTA", "DESCARTADA"}:
            raise ValueError(f"Estado inválido '{nuevo_estado}'. Debe ser 'ACTIVA', 'RESUELTA' o 'DESCARTADA'.")

        prod = db.query(Producto).filter(Producto.id_producto == alerta.id_producto).first()
        sku_val = prod.sku if prod else f"ID_{alerta.id_producto}"
        estado_ant = (alerta.estado or "ACTIVA").upper()
        if estado_ant == "PENDIENTE":
            estado_ant = "ACTIVA"

        alerta.estado = estado_norm
        alerta.fecha_revision = datetime.utcnow()
        db.commit()

        audit = Auditoria(
            id_usuario=user_id,
            accion="ACTUALIZACION_ESTADO_ALERTA",
            modulo_afectado="alertas",
            detalle={
                "id_alerta": alerta.id_alerta,
                "sku": sku_val,
                "tipo_alerta": alerta.tipo_alerta,
                "estado_anterior": estado_ant,
                "nuevo_estado": estado_norm,
                "usuario_id": user_id,
                "comentario": comentario or "Actualización de estado de alerta"
            }
        )
        db.add(audit)
        db.commit()
        return alerta
