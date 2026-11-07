# Resumen Ejecutivo de Resultados del Sistema: RetailPro

**Proyecto de Tesis:** Plataforma web de predicción de volumen de ventas mediante Machine Learning (XGBoost) para la optimización de la gestión de inventarios en empresas de retail. Caso de estudio: FasRetail (Lima Metropolitana, Perú).  
**Institución:** Universidad Peruana de Ciencias Aplicadas (UPC).  
**Fecha de Consolidación:** Octubre de 2026.

---

> [!NOTE]
> ### Declaración de Datos Sintéticos (*Synthetic Data Disclaimer*)
> Todos los datos procesados en la plataforma (`productos_fasretail.csv`, `inventario_fasretail.csv`, `ventas_fasretail.csv`, `ventas_defectuoso_advertencia.csv` y `ventas_defectuoso_rechazo.csv`) han sido generados mediante el script algorítmico [`scripts/generar_datos_carga.py`](file:///C:/UPC/CICLO%2010/TP1/P20262014_Codigo/RetailPro_Backend/scripts/generar_datos_carga.py). El generador modela de manera realista el comportamiento transaccional del retail supermercadista de Lima Metropolitana (Fiestas Patrias, Cyber Days, Navidad, variaciones estacionales, quiebres de inventario inducidos y elasticidad promocional) con fines exclusivos de validación del pipeline ETL, evaluación del modelo predictivo y sustentación académica de tesis.

---

## 1. Conteo de Datos y Estructura Relacional Estricta

El sistema respeta con fidelidad absoluta la arquitectura de **exactamente 9 tablas relacionales** (+ `alembic_version`):

| Tabla de la Base de Datos | Tipo de Entidad | Registros Reales | Descripción Funcional |
| :--- | :--- | :---: | :--- |
| `alembic_version` | Control de Esquema | 1 | Versión de migración activa de Alembic. |
| `usuario` | Seguridad y RBAC | 3 | Cuentas base (`administrador`, `analista`, `jefe_logistica`). |
| `auditoria` | Bitácora Inmutable | Variable (22+) | Registro de transacciones según Ley N.° 29733 (logins, cargas, ajustes, reportes). |
| `umbral_configuracion` | Parámetros Dinámicos | 7 | Umbrales de quiebre, sobrestock, calidad ETL, MAPE y nivel de servicio. |
| `carga_datos` | Historial ETL | 5 | 3 cargas limpias procesadas y 2 defectuosas para auditoría. |
| `producto` | Catálogo Maestro | 60 | 60 SKUs en 6 categorías (Abarrotes, Bebidas, Lácteos, Limpieza, Cuidado Personal, Snacks). |
| `venta_historica` | Serie Transaccional | 43,860 | 2 años completos de ventas diarias (731 días $\times$ 60 SKUs) sin duplicados. |
| `modelo_version` | Modelos Machine Learning | 13 | 1 modelo activo de producción + 12 versiones de validación temporal backtest. |
| `pronostico` | Inferencia Predictiva | 10,920 | 840 pronósticos quincenales del modelo activo + 10,080 del backtest walk-forward. |
| `alerta` | Operaciones de Inventario | 13 | 13 alertas de quiebre activas legítimas (0 falsos positivos de sobrestock). |

---

## 2. Resultados de Calidad del Pipeline ETL

Las cargas de datos ejecutadas a través de los endpoints `/api/v1/datos/upload` y `/api/v1/datos/procesar-validos` arrojaron los siguientes resultados de validación:

| Archivo / Tipo de Carga | Registros Procesados | Registros Rechazados | Porcentaje de Calidad | Estado Final Asignado | Observaciones Operativas |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `productos_fasretail.csv` | 60 | 0 | 100.00% | `COMPLETADO` | Catálogo íntegro con precios, costos y categorías. |
| `inventario_fasretail.csv` | 60 | 0 | 100.00% | `COMPLETADO` | Actualización de `stock_actual` y `punto_reorden`. |
| `ventas_fasretail.csv` | 43,860 | 0 | 100.00% | `COMPLETADO` | 2 años de historia sin solapamientos. Idempotencia verificada. |
| `ventas_defectuoso_advertencia.csv` | 2,000 | 20 | 99.01% | `CON_ADVERTENCIAS` | Calidad $\ge 98\%$. Registra advertencias sintácticas sin alterar el histórico. |
| `ventas_defectuoso_rechazo.csv` | 0 | 100 | 0.00% | `FALLIDO` | Calidad $< 98\%$. Archivo descartado automáticamente por control de calidad. |

---

## 3. Desempeño del Modelo Fuera de Muestra (*Walk-Forward Backtesting*)

La validación temporal rigurosa se ejecutó mediante **12 pliegues walk-forward mensuales a 14 días** (10,080 observaciones evaluadas exclusivamente fuera de muestra):

### 3.1 Métrica Principal: Demanda Diaria por SKU a 14 Días
| Estrategia Predictiva | MAPE ($y > 0$) | WAPE | RMSE | MAE | Reducción Error vs Naive |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **XGBoost Regressor (RetailPro)** | **19.23%** | **19.93%** | **10.9802** | **7.2205** | **-40.1%** |
| Media Móvil 28 Días (Consumo Promedio) | 27.25% | 27.45% | 14.5959 | 9.9439 | -17.5% |
| Naive Estacional (Mismo día semana previa) | 32.98% | 33.26% | 18.2917 | 12.0493 | Referencia |

*Nota:* MAPE (19.23%), RMSE (10.9802) y MAE (7.2205) son el promedio no ponderado de los 12 pliegues; WAPE (19.93%) es el ponderado global de las 10,080 observaciones.

### 3.2 Métrica Adicional: Demanda Acumulada a 14 Días por SKU (Ciclo de Abastecimiento)
Para la emisión de órdenes de compra, el error acumulado a lo largo de todo el ciclo de 14 días es crítico:
| Estrategia Predictiva | MAPE Acumulado 14d | WAPE Acumulado 14d | MAE Acumulado 14d | RMSE Acumulado 14d |
| :--- | :---: | :---: | :---: | :---: |
| **XGBoost Regressor (RetailPro)** | **10.66%** | **10.25%** | **52.00** | **72.73** |
| Media Móvil 28 Días (Consumo Promedio) | 13.28% | 13.30% | 67.45 | 105.68 |
| Naive Estacional (Mismo día semana previa) | 17.72% | 17.82% | 90.38 | 142.42 |

### 3.3 Hiperparámetros y Fuente de Verdad
- Configuración adoptada: `n_estimators=120, max_depth=5, learning_rate=0.08, subsample=0.85, colsample_bytree=0.85`.
- *Definición de Fuente de Verdad:* Las métricas del modelo activo en producción reportadas por la API (`GET /modelos/activa`, `/pronosticos/{sku}`) corresponden al promedio riguroso out-of-sample de los 12 cortes de backtesting temporal registrados en `modelo_version`.

---

## 4. Calibración de Intervalos de Confianza (95%)

- **Metodología de Calibración:** Los percentiles empíricos ($P_{2.5}, P_{97.5}$) se calcularon secuencialmente utilizando únicamente los residuos out-of-sample acumulados de los cortes previos $1 \dots k-1$ para evaluar la cobertura en el corte $k$ (11 pliegues temporalmente ciegos).
- **Cobertura Fuera de Muestra (Estricta):** **94.72%** en validación secuencial fuera de muestra (8,752 / 9,240 observaciones dentro del intervalo).
- **Cobertura Calibrada con los Mismos Residuos:** **95.42%** evaluada retrospectivamente sobre el total de 10,080 observaciones del catálogo (**no fuera de muestra**).
- **Estabilidad temporal:** El modelo no aplica ninguna regla arbitraria de estabilidad temporal con $\sigma \le 2.5\%$; la varianza e incertidumbre se calibran puramente mediante los residuos del backtest.
- **Ancho Relativo del Intervalo:** Promedio de $\pm 24.3\%$, reescalado dinámicamente según la categoría y el nivel de demanda de cada SKU.

---

## 5. Tiempos de Ejecución y Eficiencia Computacional

Mediciones realizadas en entorno local estándar (Python 3.13 / PostgreSQL 17 / CPU):
- **Carga de Cuadrícula de Ventas (43,860 registros):** ~0.24 segundos.
- **Validación Walk-Forward Completa (12 modelos entrenados y evaluados):** 14.16 segundos (~1.18 s por pliegue).
- **Entrenamiento del Modelo de Producción y 840 Pronósticos Quincenales:** **1.52 segundos**.
- **Generación de Reportes Multiformato (PDF, XLSX, CSV):** < 0.15 segundos por reporte.

---

## 6. Lógica de Alertas y Severidad

### 6.1 Regla Coherente de SOBRESTOCK (Operador AND)
$$\text{Alerta SOBRESTOCK} = (\text{dias\_cobertura} > \text{sobrestock\_dias}) \land \left(\frac{\text{stock\_actual}}{\text{punto\_reorden}} \times 100\% \ge \text{sobrestock\_pct}\right)$$
- Al exigir **AND**, se evita que productos de rotación normal (como SNA-010 con 21.9 días) generen alertas falsas.
- Con `sobrestock_dias = 90.0` y una cobertura máxima en catálogo de 88.2 días, se generan **0 alertas de sobrestock espurias**.

### 6.2 Regla de QUIEBRE y Severidad Centralizada
$$\text{Alerta QUIEBRE} = P(\text{quiebre}) \ge \text{quiebre\_prob\_min} \, (5.0\%) \lor \text{dias\_cobertura} \le \text{quiebre\_dias\_cobertura} \, (7.0\text{d}) \lor S_i \le SS_i$$

- **Criterio de Severidad CRÍTICA (Centralizado en `app/core/config.py`):**
  $$P(\text{quiebre}) \ge 50.0\% \lor \text{dias\_cobertura} \le 3.5\text{d} \, (7.0 \times 0.5) \lor \text{stock\_actual} \le (SS_i \times 0.5)$$
- **Conteo Actual:** **9 Alertas Críticas** y **4 Advertencias Preventivas** (Total: 13 alertas activas).

---

## 7. Fórmulas de Reposición y Nivel de Servicio

### 7.1 Reposición de Inventarios
- **Cantidad Sugerida de Compra:**
  $$\text{cantidad\_sugerida}_i = \max\left(0, \lceil D_{\text{proyectada}, i} + \text{punto\_reorden}_i - \text{stock\_actual}_i \rceil\right)$$
- **Fecha Límite de Compra (*Lead Time* = 3 días):**
  $$\text{Fecha Quiebre} = \text{Fecha Generación} + \lfloor \text{dias\_cobertura} \rfloor \text{ días}$$
  $$\text{Fecha Límite} = \max\left(\text{Fecha Generación (Hoy)}, \, \text{Fecha Quiebre} - 3 \text{ días}\right)$$

### 7.2 Métricas Unificadas de Nivel de Servicio
- **Métrica Principal: "Nivel de Servicio Estimado (Fill Rate)":**
  $$\text{Nivel de Servicio Estimado} = \frac{\sum_{i=1}^{N} \min\left(S_i, D_{\text{proyectada}, i}\right)}{\sum_{i=1}^{N} D_{\text{proyectada}, i}} \times 100\% = \mathbf{88.06\%}$$
- **Métrica Secundaria: "Disponibilidad de Catálogo":**
  $$\text{Disponibilidad de Catálogo} = \frac{\text{SKUs con } S_i > SS_i}{\text{Total SKUs Activos}} \times 100\% = \frac{51}{60} \times 100\% = \mathbf{85.0\%}$$
