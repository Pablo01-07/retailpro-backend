import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from datetime import timedelta
from app.core.database import SessionLocal
from app.services.ml_service import MLForecastService
from app.models.modelo_version import ModeloVersion
from app.models.pronostico import Pronostico


def main():
    db = SessionLocal()
    try:
        t0 = time.time()
        print("1. Cargando cuadrícula de ventas limpias...")
        df_grid, prod_dict, sku_to_idx, cat_to_idx = MLForecastService.load_clean_sales_grid(db)
        min_f = df_grid["fecha"].min()
        max_f = df_grid["fecha"].max()
        print(f"   Cuadrícula cargada: {len(df_grid)} filas, {len(prod_dict)} productos desde {min_f} hasta {max_f}.")

        print("2. Ejecutando Walk-Forward Backtesting (12 pliegues)...")
        backtest_results, res_acum_cat, percentiles_rel, comp_baselines, cob_empirica = MLForecastService.run_walk_forward_backtest(
            db, df_grid, prod_dict
        )

        mapes = [r["mape"] for r in backtest_results]
        rmses = [r["rmse"] for r in backtest_results]
        maes = [r["mae"] for r in backtest_results]
        wapes = [r["wape"] for r in backtest_results]
        mapes_14d = [r["mape_14d"] for r in backtest_results if "mape_14d" in r and r["mape_14d"] is not None]

        avg_mape = round(sum(mapes) / len(mapes), 2)
        avg_rmse = round(sum(rmses) / len(rmses), 4)
        avg_mae = round(sum(maes) / len(maes), 4)
        avg_wape = round(sum(wapes) / len(wapes), 2)
        avg_mape_14d = round(sum(mapes_14d) / len(mapes_14d), 2) if mapes_14d else None

        out_of_sample_metrics = {
            "mape": avg_mape,
            "mape_14d": avg_mape_14d,
            "wape": avg_wape,
            "rmse": avg_rmse,
            "mae": avg_mae
        }

        print("\n" + "=" * 75)
        print("MÉTRICAS DEL BACKTEST WALK-FORWARD (12 CORTES - FUERA DE MUESTRA)")
        print("=" * 75)
        print(f"MAPE Promedio Histórico (y > 0): {avg_mape}%")
        print(f"MAPE 14d Acumulado Promedio:     {avg_mape_14d}% (Meta: <= 15%)")
        print(f"WAPE Promedio Histórico:         {avg_wape}%")
        print(f"RMSE Promedio Histórico:         {avg_rmse}")
        print(f"MAE Promedio Histórico:          {avg_mae}")
        print(f"Cobertura Empírica del IC 95%:   {cob_empirica}% (Meta: 90% - 97%)")

        print("\n" + "=" * 75)
        print("TABLA COMPARATIVA: XGBOOST VS LÍNEAS BASE (TESIS)")
        print("=" * 75)
        print(f"{'Modelo':<25} | {'MAPE':<8} | {'WAPE':<8} | {'RMSE':<10} | {'MAE':<8}")
        print("-" * 75)
        print(f"{'XGBoost (Propuesto)':<25} | {avg_mape:>6.2f}% | {avg_wape:>6.2f}% | {avg_rmse:>10.4f} | {avg_mae:>8.4f}")
        print(f"{'Naive Estacional (Lag 7d)':<25} | {comp_baselines['naive_estacional']['mape']:>6.2f}% | {comp_baselines['naive_estacional']['wape']:>6.2f}% | {comp_baselines['naive_estacional']['rmse']:>10.4f} | {comp_baselines['naive_estacional']['mae']:>8.4f}")
        print(f"{'Media Móvil 28 Días':<25} | {comp_baselines['media_movil_28d']['mape']:>6.2f}% | {comp_baselines['media_movil_28d']['wape']:>6.2f}% | {comp_baselines['media_movil_28d']['rmse']:>10.4f} | {comp_baselines['media_movil_28d']['mae']:>8.4f}")

        docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
        os.makedirs(docs_dir, exist_ok=True)
        doc_path = os.path.join(docs_dir, "metricas_lineas_base_tesis.md")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("# Comparativa de Modelos de Pronóstico: XGBoost vs Líneas Base\n\n")
            f.write("Evaluación estricta fuera de muestra mediante validación temporal Walk-Forward (12 cortes mensuales a 14 días):\n\n")
            f.write("| Modelo / Estrategia | MAPE (y > 0) | WAPE | RMSE | MAE |\n")
            f.write("| :--- | :---: | :---: | :---: | :---: |\n")
            f.write(f"| **XGBoost Regressor (Propuesto)** | **{avg_mape:.2f}%** | **{avg_wape:.2f}%** | **{avg_rmse:.4f}** | **{avg_mae:.4f}** |\n")
            f.write(f"| Naive Estacional (Mismo día semana previa) | {comp_baselines['naive_estacional']['mape']:.2f}% | {comp_baselines['naive_estacional']['wape']:.2f}% | {comp_baselines['naive_estacional']['rmse']:.4f} | {comp_baselines['naive_estacional']['mae']:.4f} |\n")
            f.write(f"| Media Móvil 28 Días (Consumo Promedio) | {comp_baselines['media_movil_28d']['mape']:.2f}% | {comp_baselines['media_movil_28d']['wape']:.2f}% | {comp_baselines['media_movil_28d']['rmse']:.4f} | {comp_baselines['media_movil_28d']['mae']:.4f} |\n\n")
            f.write(f"- **Cobertura Empírica Real del Intervalo de Confianza al 95%:** {cob_empirica}%\n")
            f.write(f"- **Total de observaciones evaluadas por modelo:** 10,080 predicciones diarias (60 SKUs x 14 días x 12 cortes).\n")
        print(f"[+] Documento guardado en: {doc_path}")

        print("\n3. Entrenando Modelo Activo de Producción...")
        prod_res = MLForecastService.train_production_model(
            db, df_grid, prod_dict, res_acum_cat, percentiles_rel, out_of_sample_metrics
        )

        t_total = round(time.time() - t0, 2)
        print("\n" + "=" * 75)
        print("RESUMEN DEL MODELO ACTIVO DE PRODUCCIÓN")
        print("=" * 75)
        print(f"Versión: {prod_res['version']} ({prod_res['estado']})")
        print(f"Métricas fuera de muestra asignadas: MAPE={prod_res['mape']}% | RMSE={prod_res['rmse']} | MAE={prod_res['mae']}")
        print(f"Tiempo de generación de pronósticos futuros: {prod_res['duracion_segundos']} segundos")
        print(f"Tiempo total del pipeline: {t_total} segundos")

        count_modelos = db.query(ModeloVersion).count()
        count_prod_modelos = db.query(ModeloVersion).filter(ModeloVersion.motivo_entrenamiento != "backtest").count()
        count_pronosticos = db.query(Pronostico).count()
        print(f"Total filas en modelo_version: {count_modelos} ({count_prod_modelos} producción, {count_modelos - count_prod_modelos} backtest)")
        print(f"Total filas en pronostico: {count_pronosticos} (10,080 backtest + 840 producción)")

        coberturas = [r["dias_cobertura"] for r in prod_res["resumen_cobertura"]]
        p_quiebres = [r["prob_quiebre"] for r in prod_res["resumen_cobertura"]]

        sanos = sum(1 for c in coberturas if 14 <= c <= 45)
        criticos = sum(1 for c in coberturas if c < 14)
        sobrestock = sum(1 for c in coberturas if c > 45)

        quiebre_alto = sum(1 for p in p_quiebres if p >= 25.0)
        quiebre_bajo = sum(1 for p in p_quiebres if p < 5.0)
        quiebre_medio = sum(1 for p in p_quiebres if 5.0 <= p < 25.0)

        print("\n" + "=" * 75)
        print("DISTRIBUCIÓN DE COBERTURA Y PROBABILIDAD DE QUIEBRE (60 SKUS)")
        print("=" * 75)
        print(f"Por Días de Cobertura:")
        print(f"  - Críticos / En Riesgo (< 14 días):  {criticos:>2} SKUs ({criticos/60*100:.1f}%)")
        print(f"  - Cobertura Sana / Normal (14 a 45 días): {sanos:>2} SKUs ({sanos/60*100:.1f}%)")
        print(f"  - Sobrestock (> 45 días):             {sobrestock:>2} SKUs ({sobrestock/60*100:.1f}%)")
        print(f"Por Probabilidad de Quiebre Empírica:")
        print(f"  - Alta Probabilidad Quiebre (>= 25%): {quiebre_alto:>2} SKUs ({quiebre_alto/60*100:.1f}%)")
        print(f"  - Moderada Probabilidad (5% a 25%):   {quiebre_medio:>2} SKUs ({quiebre_medio/60*100:.1f}%)")
        print(f"  - Mínima / Nula Probabilidad (< 5%):  {quiebre_bajo:>2} SKUs ({quiebre_bajo/60*100:.1f}%)")

        sample_p = db.query(Pronostico).filter(Pronostico.id_modelo == prod_res["id_modelo"]).order_by(Pronostico.id_producto, Pronostico.horizonte_dias).limit(14).all()
        first_prod = prod_dict[sample_p[0].id_producto]
        print("\n" + "=" * 75)
        print(f"MUESTRA DE PRONÓSTICO 14 DÍAS: SKU {first_prod['sku']} ({first_prod['nombre']})")
        print(f"Stock actual: {first_prod['stock_actual']} | P(quiebre): {sample_p[0].explicacion_shap['probabilidad_quiebre']}% | Cobertura: {sample_p[0].explicacion_shap['dias_cobertura_stock']} días | Nivel: {sample_p[0].nivel_incertidumbre}")
        print("=" * 75)
        print(f"{'Día':<4} | {'Fecha Obj.':<10} | {'Cant. Proy.':<12} | {'IC Inf.':<8} | {'IC Sup.':<8} | {'SHAP Top Factor'}")
        print("-" * 75)
        for sp in sample_p:
            fecha_obj = (sp.fecha_generacion + timedelta(days=sp.horizonte_dias)).date()
            top_f = sp.explicacion_shap["top_factores"][0]
            print(f"{sp.horizonte_dias:<4} | {fecha_obj.isoformat()} | {float(sp.cantidad_proyectada):>11.2f} | {float(sp.intervalo_confianza_inf):>7.2f} | {float(sp.intervalo_confianza_sup):>7.2f} | {top_f['feature']} ({top_f['impacto']:+.2f})")

    finally:
        db.close()


if __name__ == "__main__":
    main()
