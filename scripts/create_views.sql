
CREATE OR REPLACE VIEW vw_pronosticos AS
SELECT 
    pr.id_pronostico,
    pr.fecha_generacion,
    pr.horizonte_dias,
    pr.cantidad_proyectada,
    pr.intervalo_confianza_inf,
    pr.intervalo_confianza_sup,
    pr.nivel_incertidumbre,
    pr.cantidad_sugerida_reposicion,
    pr.cantidad_ajustada_reposicion,
    pr.fecha_limite_reposicion,
    p.sku,
    p.nombre AS nombre_producto,
    p.categoria,
    p.stock_actual,
    p.punto_reorden,
    m.version AS version_modelo,
    m.mape,
    m.rmse,
    m.mae,
    m.estado AS estado_modelo
FROM pronostico pr
JOIN producto p ON pr.id_producto = p.id_producto
JOIN modelo_version m ON pr.id_modelo = m.id_modelo;

CREATE OR REPLACE VIEW vw_ventas_diarias AS
SELECT 
    v.fecha,
    p.sku,
    p.nombre AS nombre_producto,
    p.categoria,
    SUM(v.cantidad_vendida) AS total_cantidad_vendida,
    SUM(v.cantidad_vendida * v.precio_unitario) AS total_ingresos,
    ROUND(AVG(v.precio_unitario), 2) AS precio_promedio
FROM venta_historica v
JOIN producto p ON v.id_producto = p.id_producto
GROUP BY v.fecha, p.sku, p.nombre, p.categoria;

CREATE OR REPLACE VIEW vw_alertas AS
SELECT 
    a.id_alerta,
    a.tipo_alerta,
    a.fecha_generacion,
    a.estado,
    a.fecha_revision,
    p.sku,
    p.nombre AS nombre_producto,
    p.categoria,
    p.stock_actual,
    p.punto_reorden,
    pr.cantidad_proyectada,
    pr.fecha_limite_reposicion
FROM alerta a
JOIN producto p ON a.id_producto = p.id_producto
LEFT JOIN pronostico pr ON a.id_pronostico = pr.id_pronostico;

CREATE OR REPLACE VIEW vw_nivel_servicio AS
SELECT 
    p.categoria,
    COUNT(DISTINCT p.id_producto) AS total_skus,
    SUM(p.stock_actual) AS stock_total,
    ROUND(
        CASE 
            WHEN COUNT(DISTINCT p.id_producto) = 0 THEN 100.00
            ELSE 100.00 - (COUNT(DISTINCT CASE WHEN p.stock_actual <= p.punto_reorden THEN p.id_producto END)::decimal / COUNT(DISTINCT p.id_producto)::decimal * 100.00)
        END, 2
    ) AS nivel_servicio_estimado_pct,
    COUNT(DISTINCT CASE WHEN p.stock_actual <= p.punto_reorden THEN p.id_producto END) AS skus_en_riesgo
FROM producto p
GROUP BY p.categoria;

GRANT SELECT ON vw_pronosticos TO powerbi_reader;
GRANT SELECT ON vw_ventas_diarias TO powerbi_reader;
GRANT SELECT ON vw_alertas TO powerbi_reader;
GRANT SELECT ON vw_nivel_servicio TO powerbi_reader;
