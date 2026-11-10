import pytest
from datetime import date, timedelta, datetime
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session

from app.models.producto import Producto
from app.models.venta_historica import VentaHistorica
from app.models.modelo_version import ModeloVersion
from app.models.pronostico import Pronostico
from app.services.ml_service import MLForecastService


def test_zero_data_leakage_guarantee():
    cutoff_date = date(2025, 6, 1)

    fechas = [cutoff_date - timedelta(days=i) for i in range(60, 0, -1)] + [cutoff_date] + [cutoff_date + timedelta(days=i) for i in range(1, 15)]
    fechas = sorted(fechas)

    df_base = pd.DataFrame({
        "fecha": fechas,
        "id_producto": 1,
        "sku": "PRD-001",
        "categoria": "Bebidas",
        "sku_idx": 0,
        "categoria_idx": 0,
        "cantidad_vendida": [10 + (i % 7) * 2 for i in range(len(fechas))],
        "precio_unitario": 5.50
    })

    features_orig = MLForecastService.extract_features_at_cutoff(df_base, cutoff_date=cutoff_date, horizon_days=14, include_target=False)

    df_altered = df_base.copy()
    mask_future = df_altered["fecha"] > cutoff_date
    df_altered.loc[mask_future, "cantidad_vendida"] = 99999
    df_altered.loc[mask_future, "precio_unitario"] = 500.0

    features_altered = MLForecastService.extract_features_at_cutoff(df_altered, cutoff_date=cutoff_date, horizon_days=14, include_target=False)

    feature_cols = MLForecastService.FEATURE_COLS
    for col in feature_cols:
        val_orig = features_orig[col].values
        val_alt = features_altered[col].values
        assert np.array_equal(val_orig, val_alt), f"Fuga de datos detectada en la característica '{col}': cambió con datos del futuro."

    assert features_orig["cutoff_date"].max() <= cutoff_date
    assert features_orig["horizonte_dias"].min() == 1
    assert features_orig["horizonte_dias"].max() == 14


def test_empirical_confidence_intervals_and_uncertainty():
    p25_rel = -0.25
    p975_rel = 0.30

    y_alto = 80.0
    inf_alto = max(0.0, round(y_alto * (1.0 + p25_rel), 2))
    sup_alto = max(0.0, round(y_alto * (1.0 + p975_rel), 2))
    assert inf_alto == 60.0
    assert sup_alto == 104.0
    assert inf_alto <= y_alto <= sup_alto

    y_bajo = 10.0
    inf_bajo = max(0.0, round(y_bajo * (1.0 + p25_rel), 2))
    sup_bajo = max(0.0, round(y_bajo * (1.0 + p975_rel), 2))
    assert inf_bajo == 7.5
    assert sup_bajo == 13.0
    assert inf_bajo <= y_bajo <= sup_bajo

    assert (sup_alto - inf_alto) > (sup_bajo - inf_bajo)


def test_empirical_coverage_95_percent():
    np.random.seed(42)
    bloques = 6
    n_por_bloque = 300
    residuos_bloques = [np.random.normal(0.0, 0.15, size=n_por_bloque) for _ in range(bloques)]

    aciertos_oos = 0
    total_oos = 0

    for k in range(1, bloques):
        previos = np.concatenate(residuos_bloques[:k])
        p25 = float(np.percentile(previos, 2.5))
        p975 = float(np.percentile(previos, 97.5))

        y_pred = np.random.uniform(20, 80, size=n_por_bloque)
        y_true = np.maximum(0.0, y_pred * (1.0 + residuos_bloques[k]))

        inf = np.maximum(0.0, y_pred * (1.0 + p25))
        sup = np.maximum(0.0, y_pred * (1.0 + p975))

        aciertos_oos += int(np.sum((inf <= y_true) & (y_true <= sup)))
        total_oos += n_por_bloque

    cobertura_oos = (aciertos_oos / total_oos) * 100.0
    assert 91.0 <= cobertura_oos <= 97.5, f"Cobertura OOS obtenida: {cobertura_oos}%"


def test_empirical_stockout_probability_logic():
    residuos_rel = [-0.15, -0.05, 0.0, 0.03, 0.08, 0.12, 0.15, -0.10, 0.04, 0.06]
    demanda_proy_14d = 100.0

    stock_cero = 0
    prob_cero = 100.0 if stock_cero <= 0 else 0.0
    assert prob_cero == 100.0

    stock_alto = 200
    demandas_sim = [max(0.0, demanda_proy_14d * (1.0 + r)) for r in residuos_rel]
    quiebres_alto = sum(1 for d in demandas_sim if d > stock_alto)
    prob_alto = (quiebres_alto / len(demandas_sim)) * 100.0
    assert prob_alto == 0.0

    stock_inter = 105
    quiebres_inter = sum(1 for d in demandas_sim if d > stock_inter)
    prob_inter = (quiebres_inter / len(demandas_sim)) * 100.0
    assert prob_inter == 40.0


def test_api_forecasts_and_models(client, admin_token, db_session):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    prod = db_session.query(Producto).filter(Producto.sku == "TEST-SKU-01").first()
    if not prod:
        prod = Producto(
            sku="TEST-SKU-01",
            nombre="Producto Test Pronóstico",
            categoria="Bebidas",
            stock_actual=150,
            punto_reorden=30,
            estado="activo"
        )
        db_session.add(prod)
        db_session.commit()
        db_session.refresh(prod)

    mv_prod = db_session.query(ModeloVersion).filter(ModeloVersion.version == "v1.0.0").first()
    if not mv_prod:
        mv_prod = ModeloVersion(
            version="v1.0.0",
            motivo_entrenamiento="inicial_produccion",
            mae=5.2,
            mape=14.5,
            rmse=7.8,
            estado="ACTIVA"
        )
        db_session.add(mv_prod)
        db_session.commit()
        db_session.refresh(mv_prod)

    mv_backtest = db_session.query(ModeloVersion).filter(ModeloVersion.version == "v0.backtest.01").first()
    if not mv_backtest:
        mv_backtest = ModeloVersion(
            version="v0.backtest.01",
            motivo_entrenamiento="backtest",
            mae=6.1,
            mape=18.2,
            rmse=9.0,
            estado="DESCARTADA"
        )
        db_session.add(mv_backtest)
        db_session.commit()
        db_session.refresh(mv_backtest)

    fecha_base = datetime.utcnow()
    for h in range(1, 15):
        pron = Pronostico(
            id_producto=prod.id_producto,
            id_modelo=mv_prod.id_modelo,
            fecha_generacion=fecha_base,
            horizonte_dias=h,
            cantidad_proyectada=25.0 + h,
            intervalo_confianza_inf=max(0.0, 20.0 + h),
            intervalo_confianza_sup=30.0 + h,
            nivel_incertidumbre="BAJO",
            explicacion_shap={
                "probabilidad_quiebre": 12.5,
                "top_factores": [{"feature": "rolling_mean_7", "impacto": 2.5}]
            },
            cantidad_sugerida_reposicion=50,
            fecha_limite_reposicion=(fecha_base + timedelta(days=7)).date()
        )
        db_session.add(pron)
    db_session.commit()

    resp = client.get("/api/v1/pronosticos", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_skus"] >= 1
    assert data["version_modelo"] == "v1.0.0"

    resp_sku = client.get(f"/api/v1/pronosticos/{prod.sku}", headers=admin_headers)
    assert resp_sku.status_code == 200
    data_sku = resp_sku.json()
    assert data_sku["sku"] == prod.sku
    assert len(data_sku["serie_14_dias"]) == 14
    assert data_sku["probabilidad_quiebre"] == 12.5
    assert data_sku["serie_14_dias"][0]["horizonte_dias"] == 1
    assert data_sku["serie_14_dias"][13]["horizonte_dias"] == 14

    resp_act = client.get("/api/v1/modelos/activa", headers=admin_headers)
    assert resp_act.status_code == 200
    data_act = resp_act.json()
    assert data_act["version"] == "v1.0.0"
    assert data_act["estado"] == "ACTIVA"
    assert len(data_act["importancia_variables"]) > 0

    resp_hist = client.get("/api/v1/modelos/historial", headers=admin_headers)
    assert resp_hist.status_code == 200
    data_hist = resp_hist.json()
    versiones = [m["version"] for m in data_hist]
    assert "v1.0.0" in versiones
    assert "v0.backtest.01" not in versiones, "El historial de la pantalla 13 no debe mostrar modelos de backtest."

    resp_mon = client.get("/api/v1/modelos/monitoreo", headers=admin_headers)
    assert resp_mon.status_code == 200
    data_mon = resp_mon.json()
    assert "serie_mensual" in data_mon
    assert "mape_promedio_historico" in data_mon


def test_pronostico_sku_sin_pronostico_vigente_cp044(client, admin_token, db_session):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    modelo = db_session.query(ModeloVersion).filter(ModeloVersion.estado == "ACTIVA").first()
    if not modelo:
        modelo = ModeloVersion(
            version="v1.0.0",
            fecha_entrenamiento=datetime.utcnow(),
            motivo_entrenamiento="INICIAL",
            mape=15.0,
            estado="ACTIVA"
        )
        db_session.add(modelo)
        db_session.commit()

    prod_sin_pron = Producto(
        sku="SKU-SIN-PRON",
        nombre="Producto Sin Pronostico",
        categoria="Abarrotes",
        stock_actual=40,
        punto_reorden=15,
        estado="activo"
    )
    db_session.add(prod_sin_pron)
    db_session.commit()

    resp = client.get(f"/api/v1/pronosticos/{prod_sin_pron.sku}", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["sku"] == "SKU-SIN-PRON"
    assert data["pronostico_disponible"] is False
    assert data["serie_14_dias"] == []
    assert data["demanda_total_proyectada_14d"] == 0.0
    assert data["probabilidad_quiebre"] == 0.0
    assert data["nivel_incertidumbre"] == "N/D"
    assert data["fecha_generacion"] is None

    resp_404 = client.get("/api/v1/pronosticos/SKU-NO-EXISTE-XYZ", headers=admin_headers)
    assert resp_404.status_code == 404


def test_nivel_incertidumbre_por_sku_cp027(db_session):
    from app.services.ml_service import calcular_niveles_incertidumbre_por_sku
    from app.core.config import settings

    assert hasattr(settings, "UNCERTAINTY_CV_PERCENTILE_LOW")
    assert hasattr(settings, "UNCERTAINTY_CV_PERCENTILE_HIGH")
    assert settings.UNCERTAINTY_CV_PERCENTILE_LOW == 40
    assert settings.UNCERTAINTY_CV_PERCENTILE_HIGH == 80

    niveles = calcular_niveles_incertidumbre_por_sku(db=db_session)
    if niveles:
        sample_info = next(iter(niveles.values()))
        assert "nivel" in sample_info
        assert sample_info["nivel"] in ["BAJO", "MEDIO", "ALTO"]
        assert "cv" in sample_info
