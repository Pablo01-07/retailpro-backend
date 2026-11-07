import os
import csv
import random
import datetime

random.seed(42)

BASE_CATALOGO_SKUS = [
    {"sku": "ABA-001", "nombre": "Arroz Costeño Extra 1kg", "categoria": "Abarrotes", "precio_base": 4.50, "vol_base": 45},
    {"sku": "ABA-002", "nombre": "Azúcar Rubia Cartavio 1kg", "categoria": "Abarrotes", "precio_base": 3.80, "vol_base": 40},
    {"sku": "ABA-003", "nombre": "Aceite Vegetal Primor Clásico 1L", "categoria": "Abarrotes", "precio_base": 9.20, "vol_base": 35},
    {"sku": "ABA-004", "nombre": "Fideos Spaghetti Don Vittorio 450g", "categoria": "Abarrotes", "precio_base": 2.90, "vol_base": 50},
    {"sku": "ABA-005", "nombre": "Leche Gloria Evaporada Entera 400g", "categoria": "Abarrotes", "precio_base": 4.20, "vol_base": 65},
    {"sku": "ABA-006", "nombre": "Atún Primor Lomitos en Aceite 170g", "categoria": "Abarrotes", "precio_base": 5.90, "vol_base": 30},
    {"sku": "ABA-007", "nombre": "Avena 3 Ositos Tradicional 500g", "categoria": "Abarrotes", "precio_base": 3.50, "vol_base": 25},
    {"sku": "ABA-008", "nombre": "Harina Blanca Flor sin Preparar 1kg", "categoria": "Abarrotes", "precio_base": 4.80, "vol_base": 20},
    {"sku": "ABA-009", "nombre": "Sal de Mesa Marina Emsal 1kg", "categoria": "Abarrotes", "precio_base": 1.50, "vol_base": 35},
    {"sku": "ABA-010", "nombre": "Café Soluble Nescafé Tradición 200g", "categoria": "Abarrotes", "precio_base": 22.50, "vol_base": 15},

    {"sku": "BEB-001", "nombre": "Gaseosa Inca Kola 1.5L", "categoria": "Bebidas", "precio_base": 7.50, "vol_base": 55},
    {"sku": "BEB-002", "nombre": "Gaseosa Coca Cola 1.5L", "categoria": "Bebidas", "precio_base": 7.50, "vol_base": 50},
    {"sku": "BEB-003", "nombre": "Agua San Luis sin Gas 1L", "categoria": "Bebidas", "precio_base": 2.20, "vol_base": 40},
    {"sku": "BEB-004", "nombre": "Cerveza Cusqueña Dorada 330ml", "categoria": "Bebidas", "precio_base": 5.50, "vol_base": 35},
    {"sku": "BEB-005", "nombre": "Cerveza Pilsen Callao 355ml", "categoria": "Bebidas", "precio_base": 4.80, "vol_base": 45},
    {"sku": "BEB-006", "nombre": "Jugo Frugos del Valle Durazno 1L", "categoria": "Bebidas", "precio_base": 4.90, "vol_base": 30},
    {"sku": "BEB-007", "nombre": "Bebida Hidratante Sporade Mora 500ml", "categoria": "Bebidas", "precio_base": 2.50, "vol_base": 25},
    {"sku": "BEB-008", "nombre": "Té Helado Free Tea Limón 500ml", "categoria": "Bebidas", "precio_base": 2.80, "vol_base": 22},
    {"sku": "BEB-009", "nombre": "Vino Tacama Selección Especial 750ml", "categoria": "Bebidas", "precio_base": 36.90, "vol_base": 8},
    {"sku": "BEB-010", "nombre": "Pisco Quebranta Santiago Queirolo 750ml", "categoria": "Bebidas", "precio_base": 38.50, "vol_base": 6},

    {"sku": "LAC-001", "nombre": "Yogurt Gloria Fresa 1kg", "categoria": "Lácteos", "precio_base": 6.80, "vol_base": 38},
    {"sku": "LAC-002", "nombre": "Queso Edam Bonlé Tajado 200g", "categoria": "Lácteos", "precio_base": 11.20, "vol_base": 20},
    {"sku": "LAC-003", "nombre": "Queso Fresco Laive 250g", "categoria": "Lácteos", "precio_base": 9.50, "vol_base": 22},
    {"sku": "LAC-004", "nombre": "Mantequilla Gloria con Sal 200g", "categoria": "Lácteos", "precio_base": 8.90, "vol_base": 18},
    {"sku": "LAC-005", "nombre": "Margarina Dorina 225g", "categoria": "Lácteos", "precio_base": 4.50, "vol_base": 24},
    {"sku": "LAC-006", "nombre": "Crema de Leche Nestlé 290g", "categoria": "Lácteos", "precio_base": 7.20, "vol_base": 14},
    {"sku": "LAC-007", "nombre": "Leche Chocolatada Gloria UHT 1L", "categoria": "Lácteos", "precio_base": 5.90, "vol_base": 28},
    {"sku": "LAC-008", "nombre": "Manjarblanco Nestlé Pote 500g", "categoria": "Lácteos", "precio_base": 8.20, "vol_base": 12},
    {"sku": "LAC-009", "nombre": "Huevo de Gallina La Calera x 15", "categoria": "Lácteos", "precio_base": 9.80, "vol_base": 42},
    {"sku": "LAC-010", "nombre": "Jamónada Especial San Fernando 200g", "categoria": "Lácteos", "precio_base": 5.40, "vol_base": 26},

    {"sku": "PER-001", "nombre": "Shampoo Head & Shoulders Limpieza 375ml", "categoria": "Cuidado Personal", "precio_base": 19.90, "vol_base": 16},
    {"sku": "PER-002", "nombre": "Jabón de Tocador Dove Original 90g", "categoria": "Cuidado Personal", "precio_base": 4.20, "vol_base": 32},
    {"sku": "PER-003", "nombre": "Crema Dental Kolynos Triple Limpieza 90g", "categoria": "Cuidado Personal", "precio_base": 3.90, "vol_base": 35},
    {"sku": "PER-004", "nombre": "Cepillo Dental Colgate 360 Medio", "categoria": "Cuidado Personal", "precio_base": 7.90, "vol_base": 14},
    {"sku": "PER-005", "nombre": "Desodorante Rexona Men Cobalt Roll-on 50ml", "categoria": "Cuidado Personal", "precio_base": 10.50, "vol_base": 20},
    {"sku": "PER-006", "nombre": "Papel Higiénico Suave Rindemax x 4", "categoria": "Cuidado Personal", "precio_base": 6.90, "vol_base": 45},
    {"sku": "PER-007", "nombre": "Toallas Femeninas Nosotras Invisible x 10", "categoria": "Cuidado Personal", "precio_base": 5.80, "vol_base": 25},
    {"sku": "PER-008", "nombre": "Afeitadora Gillette Prestobarba 3 x 2", "categoria": "Cuidado Personal", "precio_base": 12.90, "vol_base": 15},
    {"sku": "PER-009", "nombre": "Enjuague Bucal Listerine Cool Mint 250ml", "categoria": "Cuidado Personal", "precio_base": 14.50, "vol_base": 12},
    {"sku": "PER-010", "nombre": "Crema Corporal Nivea Milk Nutritiva 250ml", "categoria": "Cuidado Personal", "precio_base": 18.20, "vol_base": 10},

    {"sku": "LIM-001", "nombre": "Detergente en Polvo Bolívar Floral 800g", "categoria": "Limpieza", "precio_base": 8.50, "vol_base": 38},
    {"sku": "LIM-002", "nombre": "Detergente en Polvo Ace Blanco 800g", "categoria": "Limpieza", "precio_base": 7.90, "vol_base": 34},
    {"sku": "LIM-003", "nombre": "Lejía Clorox Tradicional 1L", "categoria": "Limpieza", "precio_base": 3.80, "vol_base": 42},
    {"sku": "LIM-004", "nombre": "Lavavajillas en Pasta Ayudín Limón 450g", "categoria": "Limpieza", "precio_base": 4.50, "vol_base": 36},
    {"sku": "LIM-005", "nombre": "Suavizante Suavitel Fresca Primavera 1L", "categoria": "Limpieza", "precio_base": 9.90, "vol_base": 22},
    {"sku": "LIM-006", "nombre": "Limpiador Líquido Poett Lavanda 900ml", "categoria": "Limpieza", "precio_base": 5.20, "vol_base": 28},
    {"sku": "LIM-007", "nombre": "Esponja Scotch-Brite Clásica x 2", "categoria": "Limpieza", "precio_base": 4.20, "vol_base": 25},
    {"sku": "LIM-008", "nombre": "Bolsas de Basura Ekono 50L x 10", "categoria": "Limpieza", "precio_base": 5.90, "vol_base": 30},
    {"sku": "LIM-009", "nombre": "Limpiavidrios Sapolio Antiestático 500ml", "categoria": "Limpieza", "precio_base": 6.20, "vol_base": 16},
    {"sku": "LIM-010", "nombre": "Desinfectante Pinesol Pino 1L", "categoria": "Limpieza", "precio_base": 11.50, "vol_base": 14},

    {"sku": "SNA-001", "nombre": "Papas Fritas Lay's Clásicas 160g", "categoria": "Snacks", "precio_base": 6.50, "vol_base": 40},
    {"sku": "SNA-002", "nombre": "Galletas Casino Menta Paquete x 6", "categoria": "Snacks", "precio_base": 4.20, "vol_base": 36},
    {"sku": "SNA-003", "nombre": "Galletas Soda San Jorge x 6", "categoria": "Snacks", "precio_base": 3.20, "vol_base": 45},
    {"sku": "SNA-004", "nombre": "Chocolate Sublime Barra 30g", "categoria": "Snacks", "precio_base": 2.00, "vol_base": 60},
    {"sku": "SNA-005", "nombre": "Chocolate Triángulo D'Onofrio 30g", "categoria": "Snacks", "precio_base": 2.20, "vol_base": 50},
    {"sku": "SNA-006", "nombre": "Chizitos Pascualillo Queso 120g", "categoria": "Snacks", "precio_base": 3.80, "vol_base": 32},
    {"sku": "SNA-007", "nombre": "Tortees Picante Choclo Dulce 150g", "categoria": "Snacks", "precio_base": 4.50, "vol_base": 28},
    {"sku": "SNA-008", "nombre": "Caramelos Chicho Limón Bolsa 100g", "categoria": "Snacks", "precio_base": 2.50, "vol_base": 30},
    {"sku": "SNA-009", "nombre": "Galleta Oreo Original 108g", "categoria": "Snacks", "precio_base": 3.50, "vol_base": 38},
    {"sku": "SNA-010", "nombre": "Maní Salado Karinto 100g", "categoria": "Snacks", "precio_base": 3.20, "vol_base": 24},
]


def construir_catalogo_con_inventario_realista():
    indices_sobrestock = {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
    indices_quiebre = {2, 8, 14, 22, 28, 36, 42, 48, 56}

    catalogo = []
    for i, item in enumerate(BASE_CATALOGO_SKUS):
        p = item.copy()
        vol = p["vol_base"]

        p["reorden"] = max(10, int(round(vol * 7.0)))

        if i in indices_sobrestock:
            dias_cob = 75 + (i * 2) % 25
            p["stock"] = int(round(vol * dias_cob))
        elif i in indices_quiebre:
            dias_cob = 3 + (i % 4)
            p["stock"] = int(round(vol * dias_cob))
        else:
            dias_cob = 18 + (i * 2) % 16
            p["stock"] = int(round(vol * dias_cob))

        catalogo.append(p)
    return catalogo


CATALOGO_SKUS = construir_catalogo_con_inventario_realista()


def generar_productos_csv(output_path: str):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sku", "nombre", "categoria", "stock_actual", "punto_reorden"])
        for p in CATALOGO_SKUS:
            writer.writerow([p["sku"], p["nombre"], p["categoria"], p["stock"], p["reorden"]])
    print(f"[+] Generado catálogo de productos: {output_path} ({len(CATALOGO_SKUS)} registros)")


def generar_inventario_csv(output_path: str):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sku", "stock_actual", "punto_reorden"])
        for p in CATALOGO_SKUS:
            writer.writerow([p["sku"], p["stock"], p["reorden"]])
    print(f"[+] Generado archivo de inventario: {output_path} ({len(CATALOGO_SKUS)} registros)")


def generar_ventas_csv(output_path: str, end_date: datetime.date = None, days: int = 731):
    if end_date is None:
        end_date = datetime.date.today() - datetime.timedelta(days=1)

    start_date = end_date - datetime.timedelta(days=days - 1)
    filas = []
    quiebre_tracker = {p["sku"]: 0 for p in CATALOGO_SKUS}

    for d in range(days):
        current_date = start_date + datetime.timedelta(days=d)
        is_weekend = current_date.weekday() in [4, 5, 6]
        mes = current_date.month
        dia = current_date.day

        factor_fecha = 1.0
        if mes == 7 and 15 <= dia <= 31:
            factor_fecha *= 1.45
        elif (mes == 5 and 15 <= dia <= 20) or (mes == 11 and 18 <= dia <= 24):
            factor_fecha *= 1.30
        elif mes == 12 and dia >= 10:
            factor_fecha *= 1.65

        for p in CATALOGO_SKUS:
            sku = p["sku"]
            cat = p["categoria"]
            base_vol = p["vol_base"]
            precio = p["precio_base"]

            if quiebre_tracker[sku] > 0:
                quiebre_tracker[sku] -= 1
                cantidad = 0
                filas.append([current_date.strftime("%Y-%m-%d"), sku, cantidad, round(precio, 2)])
                continue

            factor_cat = 1.0
            if cat in ["Bebidas", "Snacks"] and mes in [1, 2, 3]:
                factor_cat = 1.35
            elif cat == "Abarrotes" and mes in [6, 7, 8]:
                factor_cat = 1.20

            factor_finde = 1.30 if is_weekend else 0.95

            factor_quincena = 1.15 if (dia in [14, 15, 16, 29, 30, 31]) else 1.0

            es_promo = random.random() < 0.05
            factor_promo = 1.35 if es_promo else 1.0
            precio_final = round(precio * 0.85 if es_promo else precio, 2)

            media_diaria = base_vol * factor_fecha * factor_cat * factor_finde * factor_quincena * factor_promo
            cantidad = max(0, int(round(random.gauss(media_diaria, media_diaria * 0.18))))

            if cantidad > base_vol * 1.5 and random.random() < 0.03:
                quiebre_tracker[sku] = random.randint(2, 5)

            filas.append([current_date.strftime("%Y-%m-%d"), sku, cantidad, precio_final])

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fecha", "sku", "cantidad_vendida", "precio_unitario"])
        writer.writerows(filas)

    print(f"[+] Generadas ventas históricas: {output_path} ({len(filas)} filas, {days} días desde {start_date} hasta {end_date})")


def generar_ventas_defectuosas(output_path_ok: str, output_path_fail: str, end_date: datetime.date = None):
    if end_date is None:
        end_date = datetime.date.today() - datetime.timedelta(days=1)

    fecha_base = end_date - datetime.timedelta(days=45)

    pares_unicos = []
    for d in range(20):
        f_str = (fecha_base + datetime.timedelta(days=d)).strftime("%Y-%m-%d")
        for p in CATALOGO_SKUS[:50]:
            pares_unicos.append([f_str, p["sku"], p["vol_base"], p["precio_base"]])

    filas_ok = [fila.copy() for fila in pares_unicos[:1000]]
    filas_ok[10][0] = ""
    filas_ok[20][1] = ""
    filas_ok[30][2] = ""
    filas_ok[40][0] = "2026-13-45"
    filas_ok[50][2] = -15
    filas_ok[60][3] = -8.50
    filas_ok[70][2] = "no_numerico"
    filas_ok[80][1] = "SKU_FANTASMA_999"
    filas_ok[90] = filas_ok[0].copy()
    filas_ok[91] = filas_ok[1].copy()
    filas_ok[92] = filas_ok[2].copy()
    filas_ok[93] = filas_ok[3].copy()

    with open(output_path_ok, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fecha", "sku", "cantidad_vendida", "precio_unitario"])
        writer.writerows(filas_ok)
    print(f"[+] Generado dataset de advertencia (>98% calidad): {output_path_ok} (1000 filas, 12 defectuosas, 98.8% válidas)")

    filas_fail = [fila.copy() for fila in pares_unicos[:1000]]
    for i in range(100):
        if i < 20:
            filas_fail[i][0] = ""
        elif i < 40:
            filas_fail[i][1] = ""
        elif i < 60:
            filas_fail[i][2] = -random.randint(5, 50)
        elif i < 80:
            filas_fail[i][0] = "fecha_erronea_xxx"
        else:
            filas_fail[i][1] = f"SKU_INEXISTENTE_{i}"

    with open(output_path_fail, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fecha", "sku", "cantidad_vendida", "precio_unitario"])
        writer.writerows(filas_fail)
    print(f"[+] Generado dataset rechazable (<98% calidad): {output_path_fail} (1000 filas, 100 defectuosas, 90.0% válidas)")


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dir = os.path.join(base_dir, "datos_carga")
    os.makedirs(target_dir, exist_ok=True)

    ayer = datetime.date.today() - datetime.timedelta(days=1)
    print(f"[*] Generando datasets sintéticos en {target_dir} con fecha final AYER ({ayer.isoformat()})...")
    generar_productos_csv(os.path.join(target_dir, "productos_fasretail.csv"))
    generar_inventario_csv(os.path.join(target_dir, "inventario_fasretail.csv"))
    generar_ventas_csv(os.path.join(target_dir, "ventas_fasretail.csv"), end_date=ayer, days=731)
    generar_ventas_defectuosas(
        os.path.join(target_dir, "ventas_defectuoso_advertencia.csv"),
        os.path.join(target_dir, "ventas_defectuoso_rechazado.csv"),
        end_date=ayer
    )
    print("[+] Todos los datasets sintéticos se generaron exitosamente.")


if __name__ == "__main__":
    main()
