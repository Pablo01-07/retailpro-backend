# Comparativa de Modelos de Pronóstico: XGBoost vs Líneas Base

Este documento consolida la evaluación rigurosa fuera de muestra (*out-of-sample*) realizada mediante validación temporal **Walk-Forward con 12 cortes mensuales a 14 días** (10,080 predicciones individuales por modelo):

---

### 1. Métricas Principales (Demanda Diaria por SKU a 14 Días)

| Modelo / Estrategia | MAPE (y > 0) | WAPE | RMSE | MAE | Reducción Error vs Naive |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **XGBoost Regressor (Propuesto)** | **19.23%** | **19.93%** | **10.9802** | **7.2205** | **-40.1%** |
| Media Móvil 28 Días (Consumo Promedio) | 27.25% | 27.45% | 14.5959 | 9.9439 | -17.5% |
| Naive Estacional (Mismo día semana previa) | 32.98% | 33.26% | 18.2917 | 12.0493 | Referencia |

*Nota:* MAPE (19.23%), RMSE (10.9802) y MAE (7.2205) corresponden al macro-promedio riguroso no ponderado de los 12 pliegues temporales; WAPE (19.93%) representa el error ponderado global out-of-sample sobre las 10,080 observaciones.

---

### 2. Métrica Adicional (Demanda Acumulada a 14 Días por SKU)

Para la gestión de compras y abastecimiento de inventarios, el error sobre la demanda acumulada durante todo el ciclo de reposición (14 días) es determinante para prevenir quiebres de stock y sobrecostos:

| Modelo / Estrategia | MAPE Acumulado 14d | WAPE Acumulado 14d | MAE Acumulado 14d | RMSE Acumulado 14d |
| :--- | :---: | :---: | :---: | :---: |
| **XGBoost Regressor (Propuesto)** | **10.66%** | **10.25%** | **52.00** | **72.73** |
| Media Móvil 28 Días (Consumo Promedio) | 13.28% | 13.30% | 67.45 | 105.68 |
| Naive Estacional (Mismo día semana previa) | 17.72% | 17.82% | 90.38 | 142.42 |

---

### 3. Hiperparámetros y Fuente de Verdad del Modelo

El modelo de producción activo adopta la arquitectura XGBoost optimizada por validación temporal secuencial:
- Parámetros: `n_estimators=120, max_depth=5, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85`.
- **Definición de Fuente de Verdad:** Las métricas publicadas en `GET /modelos/activa`, `/modelos/monitoreo`, `/modelos/historial`, `/pronosticos/{sku}` y en los reportes provienen de la tabla `modelo_version` (`estado == 'ACTIVA'`), calculadas como el agregado de los 12 cortes out-of-sample de walk-forward backtesting.

---

### 4. Calibración de Intervalos de Confianza al 95%

- **Método fuera de muestra:** Percentiles calculados secuencialmente utilizando únicamente los residuos out-of-sample de los cortes previos $1 \dots k-1$ y evaluados en el corte $k$ (11 pliegues out-of-sample sin fuga temporal previa).
- **Cobertura Fuera de Muestra (Estricta):** **94.72%** en validación secuencial ciega (8,752 / 9,240 observaciones dentro del intervalo al 95%).
- **Cobertura Calibrada con los Mismos Residuos:** **95.42%** evaluada retrospectivamente sobre el total de 10,080 observaciones del catálogo (**no fuera de muestra**).
- **Estabilidad temporal:** El modelo no aplica ninguna regla arbitraria de estabilidad temporal con $\sigma \le 2.5\%$; la dispersión y la incertidumbre se obtienen de manera puramente empírica de los residuos del backtest.
