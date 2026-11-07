import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import xgboost as xgb
from datetime import date, timedelta
from app.core.database import SessionLocal
from app.services.ml_service import MLForecastService, get_12_monthly_cutoffs


def evaluar_configuracion(df_grid, cuts, params, prod_dict):
    mapes, wapes, rmses, maes = [], [], [], []
    all_y_true = []
    all_y_pred = []
    
    all_acum_true = []
    all_acum_pred = []

    residuos_rel_por_corte = []

    for idx, c in enumerate(cuts):
        df_train = MLForecastService.generate_training_matrix(df_grid, end_date=c, sample_step_days=7)
        X_tr = df_train[MLForecastService.FEATURE_COLS]
        y_tr = df_train["y_real"]

        model = xgb.XGBRegressor(
            max_depth=params["max_depth"],
            learning_rate=params["learning_rate"],
            n_estimators=params["n_estimators"],
            subsample=params["subsample"],
            colsample_bytree=params["colsample_bytree"],
            random_state=42,
            n_jobs=-1
        )
        model.fit(X_tr, y_tr)

        df_val = MLForecastService.extract_features_at_cutoff(df_grid, cutoff_date=c, horizon_days=14, include_target=True)
        X_val = df_val[MLForecastService.FEATURE_COLS]
        y_val_real = df_val["y_real"].values
        preds = np.maximum(0.0, model.predict(X_val))
        df_val["y_pred"] = preds

        met = MLForecastService.calculate_metrics(y_val_real, preds)
        mapes.append(met["mape"])
        wapes.append(met["wape"])
        rmses.append(met["rmse"])
        maes.append(met["mae"])

        all_y_true.extend(y_val_real)
        all_y_pred.extend(preds)

        rel_corte = ((y_val_real - preds) / np.maximum(1.0, preds)).tolist()
        residuos_rel_por_corte.append(rel_corte)

        for pid, pgroup in df_val.groupby("id_producto"):
            all_acum_true.append(float(np.sum(pgroup["y_real"].values)))
            all_acum_pred.append(float(np.sum(pgroup["y_pred"].values)))

    aciertos_oos = 0
    total_oos = 0
    for k in range(1, len(cuts)):
        residuos_previos = [r for prev in residuos_rel_por_corte[:k] for r in prev]
        p25 = float(np.percentile(residuos_previos, 2.5))
        p975 = float(np.percentile(residuos_previos, 97.5))

        start_idx = k * 60 * 14
        end_idx = (k + 1) * 60 * 14
        y_k_true = all_y_true[start_idx:end_idx]
        y_k_pred = all_y_pred[start_idx:end_idx]

        for yt, yp in zip(y_k_true, y_k_pred):
            inf = max(0.0, yp * (1.0 + p25))
            sup = max(0.0, yp * (1.0 + p975))
            if inf <= yt <= sup:
                aciertos_oos += 1
            total_oos += 1

    cobertura_oos = round((aciertos_oos / total_oos) * 100.0, 2) if total_oos > 0 else 0.0

    met_acum = MLForecastService.calculate_metrics(np.array(all_acum_true), np.array(all_acum_pred))

    return {
        "mape": round(float(np.mean(mapes)), 2),
        "wape": round(float(np.mean(wapes)), 2),
        "rmse": round(float(np.mean(rmses)), 4),
        "mae": round(float(np.mean(maes)), 4),
        "cobertura_oos": cobertura_oos,
        "acum_mape": met_acum["mape"],
        "acum_wape": met_acum["wape"],
        "acum_rmse": met_acum["rmse"],
        "acum_mae": met_acum["mae"],
        "all_y_true": all_y_true,
        "all_y_pred": all_y_pred
    }


def evaluar_lineas_base(df_grid, cuts):
    all_y_true = []
    all_y_naive = []
    all_y_ma28 = []

    all_acum_true = []
    all_acum_naive = []
    all_acum_ma28 = []

    for c in cuts:
        df_val = MLForecastService.extract_features_at_cutoff(df_grid, cutoff_date=c, horizon_days=14, include_target=True)
        preds_naive = []
        preds_ma28 = []

        for _, r in df_val.iterrows():
            h = int(r["horizonte_dias"])
            val_n = float(r["lag_7"]) if h <= 7 else float(r["lag_14"])
            preds_naive.append(max(0.0, val_n))
            preds_ma28.append(max(0.0, float(r["rolling_mean_28"])))

        y_real = df_val["y_real"].values
        preds_naive = np.array(preds_naive)
        preds_ma28 = np.array(preds_ma28)

        df_val["p_naive"] = preds_naive
        df_val["p_ma28"] = preds_ma28

        all_y_true.extend(y_real)
        all_y_naive.extend(preds_naive)
        all_y_ma28.extend(preds_ma28)

        for pid, pgroup in df_val.groupby("id_producto"):
            all_acum_true.append(float(np.sum(pgroup["y_real"].values)))
            all_acum_naive.append(float(np.sum(pgroup["p_naive"].values)))
            all_acum_ma28.append(float(np.sum(pgroup["p_ma28"].values)))

    met_naive_dia = MLForecastService.calculate_metrics(np.array(all_y_true), np.array(all_y_naive))
    met_ma28_dia = MLForecastService.calculate_metrics(np.array(all_y_true), np.array(all_y_ma28))

    met_naive_acum = MLForecastService.calculate_metrics(np.array(all_acum_true), np.array(all_acum_naive))
    met_ma28_acum = MLForecastService.calculate_metrics(np.array(all_acum_true), np.array(all_acum_ma28))

    return {
        "naive_dia": met_naive_dia,
        "ma28_dia": met_ma28_dia,
        "naive_acum": met_naive_acum,
        "ma28_acum": met_ma28_acum
    }


def main():
    db = SessionLocal()
    try:
        df_grid, prod_dict, _, _ = MLForecastService.load_clean_sales_grid(db)
        max_date = df_grid["fecha"].max()
        cuts = get_12_monthly_cutoffs(max_date)

        params_default = {
            "max_depth": 5, "learning_rate": 0.08, "n_estimators": 100,
            "subsample": 0.85, "colsample_bytree": 0.85
        }
        params_adjusted = {
            "max_depth": 6, "learning_rate": 0.05, "n_estimators": 140,
            "subsample": 0.85, "colsample_bytree": 0.85
        }

        print("1. Evaluando parámetros por defecto sobre los 12 cortes...")
        res_def = evaluar_configuracion(df_grid, cuts, params_default, prod_dict)

        print("2. Evaluando parámetros ajustados sobre los mismos 12 cortes...")
        res_adj = evaluar_configuracion(df_grid, cuts, params_adjusted, prod_dict)

        print("3. Evaluando líneas base sobre los mismos 12 cortes...")
        res_baselines = evaluar_lineas_base(df_grid, cuts)

        print("\n" + "=" * 80)
        print("TABLA 1: COMPARACIÓN DE PARÁMETROS SOBRE LOS MISMOS 12 CORTES")
        print("=" * 80)
        print(f"{'Configuración':<25} | {'MAPE':<8} | {'WAPE':<8} | {'RMSE':<10} | {'MAE':<8}")
        print("-" * 80)
        print(f"{'Parámetros por Defecto':<25} | {res_def['mape']:>6.2f}% | {res_def['wape']:>6.2f}% | {res_def['rmse']:>10.4f} | {res_def['mae']:>8.4f}")
        print(f"{'Parámetros Ajustados':<25} | {res_adj['mape']:>6.2f}% | {res_adj['wape']:>6.2f}% | {res_adj['rmse']:>10.4f} | {res_adj['mae']:>8.4f}")

        if res_def["rmse"] <= res_adj["rmse"] and res_def["mae"] <= res_adj["mae"]:
            elegida = "default"
            res_final = res_def
            params_final = params_default
            print("\n[+] DECISIÓN: Se mantienen los PARÁMETROS POR DEFECTO por ser más consistentes en RMSE/MAE.")
        else:
            elegida = "adjusted"
            res_final = res_adj
            params_final = params_adjusted
            print("\n[+] DECISIÓN: Se seleccionan los PARÁMETROS AJUSTADOS.")

        print("\n" + "=" * 80)
        print("TABLA 2: COBERTURA FUERA DE MUESTRA DEL IC 95% (CALIBRACIÓN CORTES 1..k-1 -> k)")
        print("=" * 80)
        print(f"Cobertura Empírica Fuera de Muestra (OOS): {res_final['cobertura_oos']}% (Rango meta: 90% - 97%)")
        print(f"Cortes evaluados: 11 pliegues out-of-sample (cortes 02 a 12)")

        print("\n" + "=" * 80)
        print("TABLA 3: MÉTRICA DIARIA (PRINCIPAL) VS DEMANDA ACUMULADA 14D (ADICIONAL)")
        print("=" * 80)
        print(f"{'Modelo / Estrategia':<28} | {'MAPE Diario':<12} | {'WAPE Diario':<12} | {'MAPE Acum 14d':<14} | {'WAPE Acum 14d':<14}")
        print("-" * 80)
        print(f"{'XGBoost (Modelo Final)':<28} | {res_final['mape']:>10.2f}% | {res_final['wape']:>10.2f}% | {res_final['acum_mape']:>12.2f}% | {res_final['acum_wape']:>12.2f}%")
        print(f"{'Naive Estacional (Lag 7d)':<28} | {res_baselines['naive_dia']['mape']:>10.2f}% | {res_baselines['naive_dia']['wape']:>10.2f}% | {res_baselines['naive_acum']['mape']:>12.2f}% | {res_baselines['naive_acum']['wape']:>12.2f}%")
        print(f"{'Media Móvil 28 Días':<28} | {res_baselines['ma28_dia']['mape']:>10.2f}% | {res_baselines['ma28_dia']['wape']:>10.2f}% | {res_baselines['ma28_acum']['mape']:>12.2f}% | {res_baselines['ma28_acum']['wape']:>12.2f}%")

    finally:
        db.close()


if __name__ == "__main__":
    main()
