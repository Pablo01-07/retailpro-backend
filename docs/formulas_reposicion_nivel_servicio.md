# Fórmulas Metodológicas: Reposición de Inventarios, Nivel de Servicio y Alertas

Este documento describe formalmente las formulaciones matemáticas e hipótesis de negocio implementadas en la plataforma **RetailPro** para la optimización de compras, prevención de quiebres y control de sobrestock en FasRetail (Lima, Perú), conforme a los requerimientos de la tesis.

---

## 1. Motor de Recomendaciones de Reposición (Pantalla 16)

### 1.1 Variables y Parámetros
- $S_i$: `producto.stock_actual` del producto $i$.
- $SS_i$: Stock de Seguridad (`producto.punto_reorden`). Representa el colchón de inventario requerido para amortiguar variaciones de demanda durante el ciclo.
- $L_i$: Tiempo de entrega del proveedor (*Lead Time*), configurado globalmente mediante `DEFAULT_LEAD_TIME_DAYS = 3` días para proveedores de retail en Lima Metropolitana.
- $T_{\text{cobertura}}$: Horizonte de cobertura operativa (14 días).
- $\hat{y}_{i, h}$: Demanda proyectada para el producto $i$ en el día $h \in [1, 14]$ generada por el modelo XGBoost activo.
- $D_{\text{proyectada}, i}$: Demanda acumulada proyectada durante el horizonte de 14 días:
  $$D_{\text{proyectada}, i} = \sum_{h=1}^{14} \hat{y}_{i, h}$$
- $d_{\text{prom}, i}$: Demanda promedio diaria proyectada:
  $$d_{\text{prom}, i} = \frac{D_{\text{proyectada}, i}}{14}$$
- $\text{dias\_cobertura}_i$: Días de inventario disponible hasta agotar el stock actual:
  $$\text{dias\_cobertura}_i = \frac{S_i}{d_{\text{prom}, i}}$$

### 1.2 Cantidad Sugerida de Reposición (`cantidad_sugerida_reposicion`)
La política de abastecimiento busca cubrir la demanda proyectada de la quincena restableciendo el stock de seguridad al finalizar el ciclo:

$$\text{cantidad\_sugerida\_reposicion}_i = \max\left(0, \lceil D_{\text{proyectada}, i} + SS_i - S_i \rceil\right)$$

- Si el stock actual $S_i$ es suficiente para cubrir la demanda y mantener el stock de seguridad ($S_i \ge D_{\text{proyectada}, i} + SS_i$), la cantidad sugerida es **0**.
- Si el stock actual es insuficiente, el sistema sugiere la cantidad entera mínima a ordenar para restablecer el stock meta.

### 1.3 Fecha Límite de Reposición (`fecha_limite_reposicion`)
Representa el último día en que una orden de compra debe emitirse al proveedor para que el pedido arribe antes de que ocurra el quiebre de stock físico, considerando el *Lead Time* ($L = 3$ días):

1. **Fecha Estimada de Quiebre:**
   $$\text{Fecha Quiebre}_i = \text{Fecha Generación} + \lfloor \text{dias\_cobertura}_i \rfloor \text{ días}$$

2. **Fecha Límite de Emisión de Orden:**
   $$\text{Fecha Límite}_i = \max\left( \text{Fecha Generación}, \, \text{Fecha Quiebre}_i - L \right)$$

- **Regla de urgencia:** Si $\text{Fecha Quiebre}_i - L \le \text{Fecha Generación}$ (es decir, el stock se agotará antes o durante el plazo de entrega del proveedor), la orden es urgente y la fecha límite es **la fecha de hoy** (emisión inmediata).

### 1.4 Prioridad Dinámica de Reposición (Calculada en Consulta)
La prioridad en la pantalla 16 se evalúa dinámicamente utilizando los umbrales vigentes en `umbral_configuracion`:
- **ALTA:** $\text{dias\_cobertura}_i \le \text{quiebre\_dias\_cobertura} \lor P(\text{quiebre})_i \ge (\text{quiebre\_prob\_min} \times 5) \lor S_i \le SS_i$.
- **MEDIA:** $\text{dias\_cobertura}_i \le (\text{quiebre\_dias\_cobertura} \times 2)$.
- **BAJA:** Cobertura holgada por encima de dos semanas.

### 1.5 Ajuste Manual (`cantidad_ajustada_reposicion`)
El analista de inventarios puede ingresar una cantidad ajustada (`PATCH /api/v1/reposicion/{id_pronostico}`) para considerar restricciones comerciales (múltiplos de caja, lotes mínimos de compra o restricciones presupuestales). La operación queda registrada de forma inmutable en `auditoria`.

---

## 2. Nivel de Servicio y Disponibilidad de Catálogo (Pantalla 14 y 17)

### 2.1 Limitación de Datos en FasRetail
FasRetail no registra en su base de datos transaccional una serie de saldos de inventario físico diario histórico (únicamente dispone del `stock_actual` en `producto` y de las transacciones de `venta_historica`). Por ello, las métricas de nivel de servicio son **estimaciones analíticas proyectadas**.

### 2.2 Unificación de Métricas

#### A. Métrica Principal: "Nivel de Servicio Estimado (Fill Rate)"
Representa el porcentaje ponderado de la demanda de clientes proyectada a 14 días que la empresa está en capacidad de satisfacer con sus inventarios disponibles actuales:

$$\text{Nivel de Servicio Estimado (Fill Rate)} = \frac{\sum_{i=1}^{N} \min\left(S_i, D_{\text{proyectada}, i}\right)}{\sum_{i=1}^{N} D_{\text{proyectada}, i}} \times 100\%$$

- **Valor en FasRetail:** **88.06%** (Meta referencial: 95.0%).
- Esta métrica única es la que se reporta tanto en la tarjeta KPI del **Dashboard Ejecutivo** (Pantalla 14) como en el encabezado del **Módulo de Nivel de Servicio** (Pantalla 17).

#### B. Métrica Secundaria: "Disponibilidad de Catálogo"
Indicador operativo que mide la proporción de SKUs del surtido activo cuyo stock físico supera su respectivo punto de reorden:

$$\text{Disponibilidad de Catálogo} = \frac{\text{Total SKUs con } S_i > SS_i}{\text{Total SKUs Activos en Catálogo}} \times 100\%$$

- **Valor en FasRetail:** $\frac{51}{60} \times 100\% =$ **85.0%**.
- Se reporta con su denominación específica y diferenciada ("Disponibilidad de Catálogo") en el dashboard y en las tablas de categoría.

---

## 3. Centro de Alertas de Inventario (Pantalla 18 y 19)

### 3.1 Umbrales Dinámicos (`umbral_configuracion`)
Todos los umbrales se leen dinámicamente de la tabla `umbral_configuracion` (sin constantes fijas en el código):
1. `quiebre_dias_cobertura`: Días críticos de cobertura mínima (sembrado en 7.00 días).
2. `quiebre_prob_min`: Probabilidad mínima calculada de quiebre (sembrado en 5.00%).
3. `sobrestock_dias`: Días máximos de cobertura tolerables (sembrado en 90.00 días).
4. `sobrestock_pct`: Ratio porcentual de stock sobre punto de reorden (sembrado en 150.00%).

### 3.2 Reglas de Disparo y Justificación Técnica

#### A. Alerta de QUIEBRE
Se activa si se cumple cualquiera de las siguientes condiciones de riesgo:
$$P(\text{quiebre})_i \ge \text{quiebre\_prob\_min} \quad \lor \quad \text{dias\_cobertura}_i \le \text{quiebre\_dias\_cobertura} \quad \lor \quad S_i \le SS_i$$

- **Severidad CRÍTICA (Parámetros Centralizados en Configuración):**
  Una alerta de quiebre califica como **CRÍTICA** si cumple cualquiera de las siguientes condiciones gobernadas por los parámetros centralizados en `app/core/config.py`:
  $$P(\text{quiebre})_i \ge \text{ALERT\_CRITICAL\_STOCKOUT\_PROB\_MIN} \, (50.0\%)$$
  $$\lor \quad \text{dias\_cobertura}_i \le (\text{quiebre\_dias\_cobertura} \times \text{ALERT\_CRITICAL\_COVERAGE\_FACTOR} \, [0.5])$$
  $$\lor \quad S_i \le (SS_i \times \text{ALERT\_CRITICAL\_REORDER\_POINT\_FACTOR} \, [0.5])$$
- **Severidad ADVERTENCIA:** Si el riesgo está en el rango preventivo (supera los umbrales mínimos pero no alcanza los criterios críticos).

#### B. Alerta de SOBRESTOCK
Se activa mediante una regla coherente con operador **AND**:
$$\text{dias\_cobertura}_i > \text{sobrestock\_dias} \quad \land \quad \left(\frac{S_i}{SS_i} \times 100\% \ge \text{sobrestock\_pct}\right)$$

- **Justificación del operador AND frente al OR:**
  1. La cobertura en días ($\text{dias\_cobertura}_i > \text{sobrestock\_dias}$) mide la *velocidad de rotación temporal* y es la condición primaria obligatoria para calificar la inmovilización de capital. En retail de abarrotes y perecibles, coberturas menores a 90 días corresponden a inventarios cíclicos y de presentación normales.
  2. El porcentaje sobre punto de reorden ($\frac{S_i}{SS_i} \ge \text{sobrestock\_pct}$) mide el *volumen físico excedente*.
  3. El uso anterior de un operador OR provocaba falsos positivos masivos (como SNA-010 con apenas 21.9 días de inventario), catalogando erróneamente rotaciones regulares como sobrestock.
  4. La regla **AND** garantiza que un producto solo sea alertado si tanto su tiempo de liquidación como su volumen físico superan simultáneamente los umbrales tolerables fijados por la gerencia.

### 3.3 Visualización en Dashboard (Pantalla 14)
El Dashboard Ejecutivo separa estrictamente:
- **"Alertas Críticas (Quiebre Inminente)":** SKUs con riesgo inminente de desabastecimiento.
- **"Advertencias de Inventario":** SKUs en monitoreo preventivo de quiebre o sobrestock.
