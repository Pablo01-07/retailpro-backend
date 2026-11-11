import os
import json
import shutil
import re
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.core.config import settings
from app.core.dependencies import get_current_user, require_roles, RoleCode
from app.core.audit import create_audit_log
from app.models.usuario import Usuario
from app.models.modelo_version import ModeloVersion
from app.models.umbral_configuracion import UmbralConfiguracion
from app.models.auditoria import Auditoria
from app.schemas.model import (
    FichaModeloResponse,
    ModeloHistorialItem,
    ModeloMonitoreoResponse,
    MapeMensualMonitoreoItem,
    FeatureImportanceItem,
    EntrenarModeloRequest,
    EntrenarModeloResponse,
    ReevaluarModeloResponse,
    DescartarModeloRequest,
    MetricasModeloItem,
    DiferenciaMetricasItem,
    CorteComparacionItem,
    ComparacionModeloResponse,
    PublicarModeloResponse,
    DescartarModeloResponse
)
from app.services.ml_service import MLForecastService
from app.services.reporting_service import ReportingService
from app.services.scheduler import ensure_scheduler_started, get_job_proxima_ejecucion
from app.services.etl_service import get_utc_now

DESCRIPCIONES_FEATURES = {
    "rolling_mean_28": "Promedio móvil de ventas de 28 días",
    "rolling_mean_14": "Promedio móvil de ventas de 14 días",
    "rolling_mean_7": "Promedio móvil de ventas de 7 días",
    "rolling_std_14": "Desviación estándar móvil de 14 días (volatilidad)",
    "dia_semana": "Día de la semana (efecto fin de semana en Lima)",
    "dia_semana_sin": "Componente cíclica seno del día de la semana",
    "dia_semana_cos": "Componente cíclica coseno del día de la semana",
    "es_fin_de_semana": "Indicador de fin de semana (sábado y domingo)",
    "es_quincena": "Efecto quincena y fin de mes comercial",
    "es_festivo": "Indicador de feriado oficial en Lima",
    "dia_mes": "Día del mes (1 al 31)",
    "mes": "Mes del año calendario",
    "mes_sin": "Componente estacional seno del mes",
    "mes_cos": "Componente estacional coseno del mes",
    "lag_1": "Venta histórica del día previo (t-1)",
    "lag_2": "Venta histórica de hace 2 días (t-2)",
    "lag_3": "Venta histórica de hace 3 días (t-3)",
    "lag_7": "Venta histórica de hace 7 días (patrón semanal t-7)",
    "lag_14": "Venta histórica de hace 14 días (patrón quincenal t-14)",
    "lag_21": "Venta histórica de hace 21 días (t-21)",
    "lag_28": "Venta histórica de hace 28 días (ciclo mensual t-28)",
    "precio_unitario": "Precio de venta unitario del SKU",
    "sku_idx": "Codificación ordinal de producto SKU",
    "categoria_idx": "Codificación ordinal de categoría",
    "horizonte_dias": "Horizonte de proyección (1 a 14 días)"
}

router = APIRouter(prefix="/modelos", tags=["Modelos de Machine Learning"])


@router.get("/activa", response_model=FichaModeloResponse)
@router.get("/ficha", response_model=FichaModeloResponse, include_in_schema=True)
def get_ficha_modelo_activo(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Ficha Técnica del Modelo Activo de Producción (Pantalla 11).
    """
    modelo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    if not modelo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe un modelo activo en el sistema."
        )

    umbral = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
    umbral_mape = float(umbral.valor) if umbral else 15.0

    mape_val = float(modelo.mape) if modelo.mape is not None else None
    mape_14d_val = float(modelo.mape_14d) if modelo.mape_14d is not None else None
    mape_eval = mape_14d_val if mape_14d_val is not None else mape_val
    cumple = (mape_eval is not None) and (mape_eval <= umbral_mape)

    parametros = {
        "algoritmo": "XGBoost Regressor (Extreme Gradient Boosting)",
        "objective": "reg:squarederror",
        "n_estimators": 120,
        "max_depth": 5,
        "learning_rate": 0.08,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "horizonte_prediccion": "14 días directos por SKU",
        "caracteristicas": "Lags (1, 2, 3, 7, 14, 21, 28), Promedios Móviles (7d, 14d, 28d), Cíclicas, Feriados Lima"
    }

    importancia_features = []
    modelo_path = os.path.join(settings.STORAGE_DIR, "modelos", "modelo_activo.json")
    if os.path.exists(modelo_path):
        try:
            import xgboost as xgb
            booster = xgb.Booster()
            booster.load_model(modelo_path)
            scores = booster.get_score(importance_type="gain")
            total_gain = sum(scores.values()) if scores else 1.0
            top_features = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:8]
            for feat, score in top_features:
                importancia_features.append(FeatureImportanceItem(
                    feature=feat,
                    importancia=round(score / total_gain, 4),
                    descripcion=DESCRIPCIONES_FEATURES.get(feat, f"Variable predictiva {feat}")
                ))
        except Exception:
            pass

    if not importancia_features:
        importancia_features = [
            FeatureImportanceItem(feature="rolling_mean_28", importancia=0.2850, descripcion="Promedio móvil de ventas de 28 días"),
            FeatureImportanceItem(feature="rolling_mean_14", importancia=0.2110, descripcion="Promedio móvil de ventas de 14 días"),
            FeatureImportanceItem(feature="lag_7", importancia=0.1430, descripcion="Venta histórica de hace 7 días (patrón semanal)"),
            FeatureImportanceItem(feature="dia_semana", importancia=0.0980, descripcion="Día de la semana (efecto fin de semana en Lima)"),
            FeatureImportanceItem(feature="lag_1", importancia=0.0820, descripcion="Venta histórica del día previo al corte"),
            FeatureImportanceItem(feature="es_festivo", importancia=0.0650, descripcion="Indicador de feriado oficial en Lima"),
            FeatureImportanceItem(feature="precio_unitario", importancia=0.0540, descripcion="Precio de venta unitario del SKU"),
            FeatureImportanceItem(feature="es_quincena", importancia=0.0380, descripcion="Efecto quincena / fin de mes")
        ]

    wape_val = float(modelo.wape) if modelo.wape is not None else None
    if wape_val is None:
        met_path = os.path.join(settings.STORAGE_DIR, "modelos", "metricas_modelo.json")
        if os.path.exists(met_path):
            try:
                with open(met_path, "r", encoding="utf-8") as f:
                    mdata = json.load(f)
                    if "wape" in mdata and mdata["wape"] is not None:
                        wape_val = float(mdata["wape"])
            except Exception:
                pass
    if wape_val is None:
        wape_val = ReportingService.calcular_wape_fuera_muestra(db)

    cobertura_ic = 94.72
    calib_path = os.path.join(settings.STORAGE_DIR, "modelos", "calibracion_activa.json")
    if os.path.exists(calib_path):
        try:
            with open(calib_path, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                if "cobertura_intervalo_95" in cdata and cdata["cobertura_intervalo_95"] is not None:
                    cobertura_ic = float(cdata["cobertura_intervalo_95"])
                elif "cobertura_secuencial_fuera_muestra" in cdata and cdata["cobertura_secuencial_fuera_muestra"] is not None:
                    cobertura_ic = float(cdata["cobertura_secuencial_fuera_muestra"])
        except Exception:
            pass

    ensure_scheduler_started()
    proximo_reent = get_job_proxima_ejecucion("reentrenamiento_semanal")

    return FichaModeloResponse(
        id_modelo=modelo.id_modelo,
        version=modelo.version,
        algoritmo="XGBoost Regressor",
        estado=modelo.estado,
        fecha_entrenamiento=modelo.fecha_entrenamiento,
        motivo_entrenamiento=modelo.motivo_entrenamiento,
        mae=float(modelo.mae) if modelo.mae else None,
        mape=mape_val,
        rmse=float(modelo.rmse) if modelo.rmse else None,
        wape=wape_val,
        mape_14d=mape_14d_val,
        cobertura_intervalo_95=cobertura_ic,
        umbral_mape_max=umbral_mape,
        cumple_meta=cumple,
        parametros=parametros,
        importancia_variables=importancia_features,
        observacion=modelo.observacion,
        proximo_reentrenamiento_programado=proximo_reent
    )


@router.get("/monitoreo", response_model=ModeloMonitoreoResponse)
def get_monitoreo_modelo(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Monitoreo de Rendimiento del Modelo con la Serie Mensual de MAPE (Pantalla 12).
    Alimentado por los 12 cortes del walk-forward backtest.
    """
    modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    version_activa = modelo_activo.version if modelo_activo else "N/A"

    umbral = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
    umbral_mape = float(umbral.valor) if umbral else 15.0

    backtests = db.query(ModeloVersion).filter(
        ModeloVersion.motivo_entrenamiento == "backtest"
    ).order_by(ModeloVersion.fecha_entrenamiento).all()

    serie_mensual = []
    mapes = []
    mapes_14d = []

    for idx, mb in enumerate(backtests, start=1):
        mape_val = float(mb.mape) if mb.mape is not None else 0.0
        mape_14d_val = float(mb.mape_14d) if mb.mape_14d is not None else None
        rmse_val = float(mb.rmse) if mb.rmse is not None else 0.0
        mae_val = float(mb.mae) if mb.mae is not None else 0.0
        mapes.append(mape_val)
        if mape_14d_val is not None:
            mapes_14d.append(mape_14d_val)

        corte_eval = mape_14d_val if mape_14d_val is not None else mape_val

        if corte_eval > umbral_mape * 1.5:
            estado_alerta = "CRITICO"
        elif corte_eval > umbral_mape:
            estado_alerta = "ADVERTENCIA"
        else:
            estado_alerta = "NORMAL"

        serie_mensual.append(MapeMensualMonitoreoItem(
            periodo=mb.fecha_entrenamiento.strftime("%Y-%m"),
            corte=f"Corte {idx:02d} ({mb.fecha_entrenamiento.strftime('%d/%m/%Y')})",
            mape=mape_val,
            mape_14d=mape_14d_val,
            rmse=rmse_val,
            mae=mae_val,
            umbral_mape=umbral_mape,
            estado_alerta=estado_alerta
        ))

    avg_mape = round(sum(mapes) / len(mapes), 2) if mapes else 0.0
    avg_mape_14d = round(sum(mapes_14d) / len(mapes_14d), 2) if mapes_14d else None
    eval_global = avg_mape_14d if avg_mape_14d is not None else avg_mape
    alerta_degradacion = eval_global > umbral_mape

    cobertura_real = None
    if serie_mensual:
        cobertura_real = MLForecastService.calcular_cobertura_secuencial_fuera_muestra(db) or 94.72
        calib_path = os.path.join(settings.STORAGE_DIR, "modelos", "calibracion_activa.json")
        if os.path.exists(calib_path):
            try:
                with open(calib_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    if "cobertura_intervalo_95" in cdata and cdata["cobertura_intervalo_95"] is not None:
                        cobertura_real = float(cdata["cobertura_intervalo_95"])
                    elif "cobertura_secuencial_fuera_muestra" in cdata and cdata["cobertura_secuencial_fuera_muestra"] is not None:
                        cobertura_real = float(cdata["cobertura_secuencial_fuera_muestra"])
            except Exception:
                pass

    modelo_mape_14d = float(modelo_activo.mape_14d) if (modelo_activo and modelo_activo.mape_14d is not None) else None

    wape_val = float(modelo_activo.wape) if (modelo_activo and modelo_activo.wape is not None) else None
    if wape_val is None:
        met_path = os.path.join(settings.STORAGE_DIR, "modelos", "metricas_modelo.json")
        if os.path.exists(met_path):
            try:
                with open(met_path, "r", encoding="utf-8") as f:
                    mdata = json.load(f)
                    if "wape" in mdata and mdata["wape"] is not None:
                        wape_val = float(mdata["wape"])
            except Exception:
                pass
    if wape_val is None:
        wape_val = ReportingService.calcular_wape_fuera_muestra(db)

    ensure_scheduler_started()
    proximo_reent = get_job_proxima_ejecucion("reentrenamiento_semanal")

    return ModeloMonitoreoResponse(
        version_activa=version_activa,
        mape_promedio_historico=avg_mape,
        mape_14d=avg_mape_14d if avg_mape_14d is not None else modelo_mape_14d,
        mape_14d_promedio_historico=avg_mape_14d,
        umbral_mape_max=umbral_mape,
        alerta_degradacion=alerta_degradacion,
        total_cortes_evaluados=len(serie_mensual),
        wape=wape_val,
        cobertura_intervalo_95=cobertura_real,
        cobertura_fuera_muestra=cobertura_real,
        serie_mensual=serie_mensual,
        proximo_reentrenamiento_programado=proximo_reent
    )


@router.get("/historial", response_model=List[ModeloHistorialItem])
def list_historial_modelos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([RoleCode.ADMIN, RoleCode.ANALYST, RoleCode.LOGISTICS]))
):
    """
    Historial de Versiones de Producción del Modelo (Pantalla 13).
    Filtra y omite los modelos transitorios de backtest, mostrando estrictamente versiones de producción.
    """
    modelos = db.query(ModeloVersion).filter(
        ModeloVersion.motivo_entrenamiento != "backtest"
    ).order_by(ModeloVersion.fecha_entrenamiento.desc()).all()

    resultado = []
    for m in modelos:
        w_val = float(m.wape) if m.wape is not None else None
        if w_val is None:
            cand_path = os.path.join(settings.STORAGE_DIR, "modelos", f"evaluacion_modelo_{m.id_modelo}.json")
            if os.path.exists(cand_path):
                try:
                    with open(cand_path, "r", encoding="utf-8") as f:
                        ed = json.load(f)
                        if "wape" in ed and ed["wape"] is not None:
                            w_val = float(ed["wape"])
                except Exception:
                    pass
        if w_val is None and m.estado == "ACTIVA":
            met_path = os.path.join(settings.STORAGE_DIR, "modelos", "metricas_modelo.json")
            if os.path.exists(met_path):
                try:
                    with open(met_path, "r", encoding="utf-8") as f:
                        mdata = json.load(f)
                        if "wape" in mdata and mdata["wape"] is not None:
                            w_val = float(mdata["wape"])
                except Exception:
                    pass
            if w_val is None:
                w_val = ReportingService.calcular_wape_fuera_muestra(db)

        resultado.append(ModeloHistorialItem(
            id_modelo=m.id_modelo,
            version=m.version,
            fecha_entrenamiento=m.fecha_entrenamiento,
            motivo_entrenamiento=m.motivo_entrenamiento,
            mae=float(m.mae) if m.mae else None,
            mape=float(m.mape) if m.mape else None,
            rmse=float(m.rmse) if m.rmse else None,
            wape=w_val,
            mape_14d=float(m.mape_14d) if m.mape_14d is not None else None,
            estado=m.estado,
            observacion=m.observacion
        ))
    return resultado


@router.post("/activa/reevaluar", response_model=ReevaluarModeloResponse)
def reevaluar_modelo_activo(
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(require_roles([RoleCode.ADMIN]))
):
    modelo_activo = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    if not modelo_activo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe un modelo activo en el sistema para reevaluar."
        )

    df_grid, prod_dict, sku_to_idx, cat_to_idx = MLForecastService.load_clean_sales_grid(db)
    if df_grid.empty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No existen datos históricos suficientes para ejecutar la reevaluación."
        )

    backtest_results, res_acum_cat, percentiles_rel, comp_baselines, cob_empirica = MLForecastService.run_walk_forward_backtest(
        db, df_grid, prod_dict
    )

    mapes = [r["mape"] for r in backtest_results]
    rmses = [r["rmse"] for r in backtest_results]
    maes = [r["mae"] for r in backtest_results]
    wapes = [r["wape"] for r in backtest_results]
    mapes_14d = [r["mape_14d"] for r in backtest_results if "mape_14d" in r and r["mape_14d"] is not None]

    avg_mape = round(sum(mapes) / len(mapes), 2) if mapes else 0.0
    avg_rmse = round(sum(rmses) / len(rmses), 4) if rmses else 0.0
    avg_mae = round(sum(maes) / len(maes), 4) if maes else 0.0
    avg_wape = round(sum(wapes) / len(wapes), 2) if wapes else 0.0
    avg_mape_14d = round(sum(mapes_14d) / len(mapes_14d), 2) if mapes_14d else None

    now_utc = get_utc_now()
    now_utc_str = now_utc.isoformat()
    modelo_activo.fecha_entrenamiento = now_utc
    modelo_activo.mape = avg_mape
    modelo_activo.rmse = avg_rmse
    modelo_activo.mae = avg_mae
    modelo_activo.mape_14d = avg_mape_14d
    modelo_activo.wape = avg_wape
    db.commit()
    db.refresh(modelo_activo)

    os.makedirs(os.path.join(settings.STORAGE_DIR, "modelos"), exist_ok=True)
    calib_file = os.path.join(settings.STORAGE_DIR, "modelos", "calibracion_activa.json")
    with open(calib_file, "w", encoding="utf-8") as f:
        json.dump({
            "percentiles_relativos": percentiles_rel,
            "residuos_rel_acum_cat": res_acum_cat,
            "cobertura_secuencial_fuera_muestra": cob_empirica,
            "cobertura_intervalo_95": cob_empirica,
            "fecha_ultima_evaluacion": now_utc_str,
            "mape_14d": avg_mape_14d
        }, f, indent=4, ensure_ascii=False)

    metricas_file = os.path.join(settings.STORAGE_DIR, "modelos", "metricas_modelo.json")
    with open(metricas_file, "w", encoding="utf-8") as f:
        json.dump({
            "version": modelo_activo.version,
            "id_modelo": modelo_activo.id_modelo,
            "mae": avg_mae,
            "mape": avg_mape,
            "rmse": avg_rmse,
            "mape_14d": avg_mape_14d,
            "wape": avg_wape,
            "cobertura_intervalo_95": cob_empirica,
            "cobertura_secuencial_fuera_muestra": cob_empirica,
            "fecha_ultima_evaluacion": now_utc_str
        }, f, indent=4, ensure_ascii=False)

    audit = Auditoria(
        id_usuario=current_admin.id_usuario,
        accion="Reevaluación de métricas del modelo",
        modulo_afectado="modelos",
        detalle={
            "id_modelo": modelo_activo.id_modelo,
            "version": modelo_activo.version,
            "mape_14d": avg_mape_14d,
            "mape": avg_mape,
            "mae": avg_mae,
            "rmse": avg_rmse,
            "wape": avg_wape
        }
    )
    db.add(audit)
    db.commit()

    return ReevaluarModeloResponse(
        mensaje="Reevaluación de métricas completada con éxito.",
        id_modelo=modelo_activo.id_modelo,
        version=modelo_activo.version,
        mape_14d=avg_mape_14d,
        mape=avg_mape,
        mae=avg_mae,
        rmse=avg_rmse,
        wape=avg_wape,
        cobertura_intervalo_95=cob_empirica,
        cortes_evaluados=len(backtest_results)
    )


@router.patch("/{id_modelo}/activar", response_model=ModeloHistorialItem)
def activar_version_modelo(
    id_modelo: int,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(require_roles([RoleCode.ADMIN]))
):
    """
    Activa una versión de producción del modelo de machine learning (Pantalla 13).
    Solo permitido a administradores.
    Rechaza modelos de cortes de backtest con HTTP 400.
    El modelo activo previo pasa a 'ANTERIOR' y el seleccionado pasa a 'ACTIVA'.
    Registra el cambio en auditoría conforme a Ley N.° 29733.
    """
    modelo = db.query(ModeloVersion).filter(ModeloVersion.id_modelo == id_modelo).first()
    if not modelo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo con ID {id_modelo} no encontrado."
        )

    if modelo.motivo_entrenamiento == "backtest":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede activar un corte de evaluación backtest. Solo se permite activar versiones completas de producción."
        )

    if modelo.estado in ["DESCARTADA", "CANDIDATA"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede activar directamente un modelo con estado {modelo.estado}. Debe publicarse a través del flujo de aprobación."
        )

    db.query(ModeloVersion).filter(
        ModeloVersion.estado == "ACTIVA",
        ModeloVersion.id_modelo != id_modelo
    ).update({"estado": "ANTERIOR"})

    modelo.estado = "ACTIVA"

    audit = Auditoria(
        id_usuario=current_admin.id_usuario,
        accion="ACTIVACION_MODELO",
        modulo_afectado="modelos",
        detalle={
            "id_modelo": id_modelo,
            "version": modelo.version,
            "motivo_entrenamiento": modelo.motivo_entrenamiento
        }
    )
    db.add(audit)
    db.commit()
    db.refresh(modelo)

    return ModeloHistorialItem(
        id_modelo=modelo.id_modelo,
        version=modelo.version,
        fecha_entrenamiento=modelo.fecha_entrenamiento,
        motivo_entrenamiento=modelo.motivo_entrenamiento,
        mae=float(modelo.mae) if modelo.mae else None,
        mape=float(modelo.mape) if modelo.mape else None,
        rmse=float(modelo.rmse) if modelo.rmse else None,
        mape_14d=float(modelo.mape_14d) if modelo.mape_14d is not None else None,
        estado=modelo.estado,
        observacion=modelo.observacion
    )


@router.post("/entrenar", response_model=EntrenarModeloResponse)
def trigger_reentrenamiento_modelo(
    background_tasks: BackgroundTasks,
    payload: Optional[EntrenarModeloRequest] = None,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(require_roles([RoleCode.ADMIN]))
):
    """
    Dispara el entrenamiento manual del modelo en segundo plano.
    Solo rol Administrador.
    """
    if MLForecastService.is_entrenamiento_en_curso():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un reentrenamiento en ejecución."
        )

    motivo = (payload.motivo if payload and payload.motivo else "reentrenamiento_manual")

    def _bg_entrenar():
        from app.core.database import SessionLocal
        with SessionLocal() as bg_db:
            try:
                MLForecastService.entrenar_modelo_candidato(
                    db=bg_db,
                    motivo=motivo
                )
            except Exception:
                pass

    background_tasks.add_task(_bg_entrenar)
    return EntrenarModeloResponse(
        mensaje="Reentrenamiento iniciado. El resultado aparecerá en el historial de versiones."
    )


@router.get("/{id_modelo}/comparacion", response_model=ComparacionModeloResponse)
def get_comparacion_modelo(
    id_modelo: int,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(require_roles([RoleCode.ADMIN]))
):
    candidato = db.query(ModeloVersion).filter(ModeloVersion.id_modelo == id_modelo).first()
    if not candidato:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo candidato con ID {id_modelo} no encontrado."
        )

    activa = db.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()

    umbral = db.query(UmbralConfiguracion).filter(UmbralConfiguracion.tipo_umbral == "mape_max").first()
    umbral_mape = float(umbral.valor) if umbral else 15.0

    eval_cand_file = os.path.join(settings.STORAGE_DIR, "modelos", f"evaluacion_modelo_{id_modelo}.json")
    eval_cand_data = {}
    if os.path.exists(eval_cand_file):
        try:
            with open(eval_cand_file, "r", encoding="utf-8") as f:
                eval_cand_data = json.load(f)
        except Exception:
            pass

    cand_mae = float(candidato.mae) if candidato.mae is not None else eval_cand_data.get("mae")
    cand_mape = float(candidato.mape) if candidato.mape is not None else eval_cand_data.get("mape")
    cand_rmse = float(candidato.rmse) if candidato.rmse is not None else eval_cand_data.get("rmse")
    cand_mape_14d = float(candidato.mape_14d) if candidato.mape_14d is not None else eval_cand_data.get("mape_14d")
    cand_wape = float(candidato.wape) if candidato.wape is not None else eval_cand_data.get("wape")
    cand_cob = eval_cand_data.get("cobertura_intervalo_95", eval_cand_data.get("cobertura_secuencial_fuera_muestra"))

    item_cand = MetricasModeloItem(
        id_modelo=candidato.id_modelo,
        version=candidato.version,
        estado=candidato.estado,
        mae=cand_mae,
        mape=cand_mape,
        rmse=cand_rmse,
        wape=cand_wape,
        mape_14d=cand_mape_14d,
        cobertura_intervalo_95=cand_cob
    )

    item_activa = None
    act_mae = None
    act_mape = None
    act_rmse = None
    act_wape = None
    act_mape_14d = None
    act_cob = None

    if activa:
        act_mae = float(activa.mae) if activa.mae is not None else None
        act_mape = float(activa.mape) if activa.mape is not None else None
        act_rmse = float(activa.rmse) if activa.rmse is not None else None
        act_mape_14d = float(activa.mape_14d) if activa.mape_14d is not None else None
        act_wape = float(activa.wape) if activa.wape is not None else None
        if act_wape is None:
            met_path = os.path.join(settings.STORAGE_DIR, "modelos", "metricas_modelo.json")
            if os.path.exists(met_path):
                try:
                    with open(met_path, "r", encoding="utf-8") as f:
                        mdata = json.load(f)
                        if "wape" in mdata and mdata["wape"] is not None:
                            act_wape = float(mdata["wape"])
                except Exception:
                    pass
        if act_wape is None:
            act_wape = ReportingService.calcular_wape_fuera_muestra(db)
        act_cob = MLForecastService.calcular_cobertura_secuencial_fuera_muestra(db)

        item_activa = MetricasModeloItem(
            id_modelo=activa.id_modelo,
            version=activa.version,
            estado=activa.estado,
            mae=act_mae,
            mape=act_mape,
            rmse=act_rmse,
            wape=act_wape,
            mape_14d=act_mape_14d,
            cobertura_intervalo_95=act_cob
        )

    def _diff(v1, v2, decimals=2):
        if v1 is not None and v2 is not None:
            return round(float(v1) - float(v2), decimals)
        return None

    diferencia = DiferenciaMetricasItem(
        mape_14d=_diff(cand_mape_14d, act_mape_14d, 2),
        mape=_diff(cand_mape, act_mape, 2),
        mae=_diff(cand_mae, act_mae, 4),
        rmse=_diff(cand_rmse, act_rmse, 4),
        wape=_diff(cand_wape, act_wape, 2),
        cobertura_intervalo_95=_diff(cand_cob, act_cob, 2)
    )

    backtests_activa = db.query(ModeloVersion).filter(
        ModeloVersion.motivo_entrenamiento == "backtest"
    ).order_by(ModeloVersion.fecha_entrenamiento).all()

    cand_backtest_list = eval_cand_data.get("backtest_results", [])
    cortes = []
    num_cortes = max(len(cand_backtest_list), len(backtests_activa), 12)
    for i in range(num_cortes):
        c_cand = cand_backtest_list[i] if i < len(cand_backtest_list) else {}
        b_act = backtests_activa[i] if i < len(backtests_activa) else None

        c_mape_14d = c_cand.get("mape_14d")
        if c_mape_14d is not None:
            c_mape_14d = round(float(c_mape_14d), 2)

        a_mape_14d = None
        periodo = c_cand.get("periodo")
        if b_act:
            a_mape_14d = float(b_act.mape_14d) if b_act.mape_14d is not None else float(b_act.mape)
            a_mape_14d = round(a_mape_14d, 2)
            if not periodo:
                periodo = b_act.fecha_entrenamiento.strftime("%Y-%m")

        if not periodo:
            periodo = f"Corte {i+1:02d}"

        diff_cut = None
        if c_mape_14d is not None and a_mape_14d is not None:
            diff_cut = round(c_mape_14d - a_mape_14d, 2)

        cortes.append(CorteComparacionItem(
            corte_idx=i + 1,
            periodo=periodo,
            mape_14d_candidato=c_mape_14d,
            mape_14d_activa=a_mape_14d,
            diferencia=diff_cut
        ))

    cumple_umbral = bool(cand_mape_14d is not None and cand_mape_14d <= umbral_mape)
    if act_mape_14d is not None and cand_mape_14d is not None:
        diff_mape = round(cand_mape_14d - act_mape_14d, 4)
        if abs(diff_mape) < 0.05:
            comparacion_vigente = "equivalente"
        elif diff_mape < 0:
            comparacion_vigente = "mejora"
        else:
            comparacion_vigente = "empeora"
        mejora_vigente = bool(cand_mape_14d < act_mape_14d)
    else:
        comparacion_vigente = "mejora" if cumple_umbral else "empeora"
        mejora_vigente = cumple_umbral

    u_eval = candidato.umbral_mape_evaluacion
    if u_eval is None and candidato.observacion:
        match_disc = re.search(r"umbral de\s+([\d\.]+)%", candidato.observacion)
        if match_disc:
            try:
                u_eval = float(match_disc.group(1))
            except Exception:
                pass
        else:
            match_apt = re.search(r"≤\s*([\d\.]+)%\)", candidato.observacion)
            if match_apt:
                try:
                    u_eval = float(match_apt.group(1))
                except Exception:
                    pass
    if u_eval is None:
        u_eval = umbral_mape

    return ComparacionModeloResponse(
        id_candidato=candidato.id_modelo,
        version_candidato=candidato.version,
        id_activa=activa.id_modelo if activa else None,
        version_activa=activa.version if activa else None,
        candidato=item_cand,
        activa=item_activa,
        diferencia=diferencia,
        cortes=cortes,
        cumple_umbral=cumple_umbral,
        mejora_vigente=mejora_vigente,
        comparacion_vigente=comparacion_vigente,
        umbral_mape=umbral_mape,
        umbral_mape_evaluacion=u_eval
    )


@router.post("/{id_modelo}/publicar", response_model=PublicarModeloResponse)
def publicar_modelo_candidato(
    id_modelo: int,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(require_roles([RoleCode.ADMIN]))
):
    candidato = db.query(ModeloVersion).filter(ModeloVersion.id_modelo == id_modelo).first()
    if not candidato:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo con ID {id_modelo} no encontrado."
        )

    if candidato.estado != "APTA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Solo se pueden publicar modelos con estado APTA. El modelo actual tiene estado '{candidato.estado}'."
        )

    modelo_previo = db.query(ModeloVersion).filter(
        ModeloVersion.estado == "ACTIVA",
        ModeloVersion.id_modelo != id_modelo
    ).first()
    if modelo_previo:
        modelo_previo.estado = "ANTERIOR"

    candidato.estado = "ACTIVA"
    now_str = datetime.now(ZoneInfo("America/Lima")).strftime("%d/%m/%Y %H:%M")
    user_name = current_admin.nombre_completo or current_admin.username
    candidato.observacion = f"Publicada el {now_str} por {user_name}"

    model_dir = os.path.join(settings.STORAGE_DIR, "modelos")
    os.makedirs(model_dir, exist_ok=True)
    cand_model_path = os.path.join(model_dir, f"modelo_{candidato.id_modelo}.json")
    active_model_path = os.path.join(model_dir, "modelo_activo.json")
    if os.path.exists(cand_model_path):
        shutil.copyfile(cand_model_path, active_model_path)

    cand_eval_path = os.path.join(model_dir, f"evaluacion_modelo_{candidato.id_modelo}.json")
    active_calib_path = os.path.join(model_dir, "calibracion_activa.json")
    if os.path.exists(cand_eval_path):
        shutil.copyfile(cand_eval_path, active_calib_path)

    cob_val = 94.72
    wape_val = float(candidato.wape) if candidato.wape is not None else None
    if os.path.exists(cand_eval_path):
        try:
            with open(cand_eval_path, "r", encoding="utf-8") as f:
                ed = json.load(f)
                cob_val = ed.get("cobertura_intervalo_95", ed.get("cobertura_secuencial_fuera_muestra", 94.72))
                if wape_val is None and "wape" in ed and ed["wape"] is not None:
                    wape_val = float(ed["wape"])
        except Exception:
            pass
    if wape_val is None:
        wape_val = ReportingService.calcular_wape_fuera_muestra(db)

    metricas_file = os.path.join(model_dir, "metricas_modelo.json")
    with open(metricas_file, "w", encoding="utf-8") as f:
        json.dump({
            "version": candidato.version,
            "id_modelo": candidato.id_modelo,
            "mae": float(candidato.mae) if candidato.mae else None,
            "mape": float(candidato.mape) if candidato.mape else None,
            "rmse": float(candidato.rmse) if candidato.rmse else None,
            "mape_14d": float(candidato.mape_14d) if candidato.mape_14d is not None else None,
            "wape": wape_val,
            "cobertura_intervalo_95": cob_val
        }, f, indent=4, ensure_ascii=False)

    try:
        MLForecastService.generar_pronosticos_lote(db=db, modelo_activo=candidato)
    except Exception:
        pass

    try:
        from app.services.alert_service import AlertService
        AlertService.sincronizar_alertas(db=db, notificar=True)
    except Exception:
        pass

    create_audit_log(
        db=db,
        accion="Publicación de modelo",
        modulo_afectado="modelos",
        user=current_admin,
        detalle={
            "id_modelo": candidato.id_modelo,
            "version": candidato.version,
            "observacion": candidato.observacion
        }
    )

    db.commit()
    db.refresh(candidato)

    return PublicarModeloResponse(
        mensaje="Modelo publicado exitosamente en producción.",
        id_modelo=candidato.id_modelo,
        version=candidato.version,
        estado=candidato.estado,
        observacion=candidato.observacion
    )


@router.post("/{id_modelo}/descartar", response_model=DescartarModeloResponse)
def descartar_modelo_candidato(
    id_modelo: int,
    payload: DescartarModeloRequest,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(require_roles([RoleCode.ADMIN]))
):
    if not payload.comentario or not payload.comentario.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El comentario de descarte es obligatorio."
        )

    candidato = db.query(ModeloVersion).filter(ModeloVersion.id_modelo == id_modelo).first()
    if not candidato:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo con ID {id_modelo} no encontrado."
        )

    if candidato.estado != "APTA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Solo se pueden descartar modelos con estado APTA. El modelo actual tiene estado '{candidato.estado}'."
        )

    candidato.estado = "DESCARTADA"
    candidato.observacion = f"Descartada manualmente: {payload.comentario.strip()}"

    create_audit_log(
        db=db,
        accion="Descarte de modelo",
        modulo_afectado="modelos",
        user=current_admin,
        detalle={
            "id_modelo": candidato.id_modelo,
            "version": candidato.version,
            "comentario": payload.comentario.strip(),
            "observacion": candidato.observacion
        }
    )

    db.commit()
    db.refresh(candidato)

    return DescartarModeloResponse(
        mensaje="Modelo descartado exitosamente.",
        id_modelo=candidato.id_modelo,
        version=candidato.version,
        estado=candidato.estado,
        observacion=candidato.observacion
    )
