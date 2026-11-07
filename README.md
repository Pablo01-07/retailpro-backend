# RetailPro Backend

Plataforma web de predicción de volumen de ventas basada en Machine Learning (**XGBoost**) para la optimización de compras y gestión de inventarios en retail (**FasRetail, Lima, Perú**). Desarrollado como proyecto de tesis de Ingeniería de Sistemas de Información (Universidad Peruana de Ciencias Aplicadas - UPC).

---

## 1. Arquitectura y Modelo Relacional de Tesis

La base de datos relacional PostgreSQL consta **EXACTAMENTE de 9 tablas maestros/operativas** más la tabla de control de migraciones `alembic_version`. No existen tablas secundarias ocultas ni columnas fuera de especificación:

1. **`usuario`**: Cuentas de usuario y control de acceso RBAC (`administrador`, `analista`, `jefe_logistica`).
2. **`auditoria`**: Bitácora inmutable de eventos sensibles, logins, exportaciones y ajustes conforme a la Ley N.° 29733 (Protección de Datos Personales).
3. **`umbral_configuracion`**: Parámetros dinámicos y umbrales operativos de quiebre, sobrestock, calidad y nivel de servicio.
4. **`carga_datos`**: Auditoría de ingestas ETL con porcentaje de calidad, conteo de filas válidas/rechazadas y detalle de error.
5. **`producto`**: Catálogo maestro de 60 SKUs en 6 categorías, `stock_actual` y `punto_reorden`.
6. **`venta_historica`**: Serie histórica agregada diaria de ventas por producto (2 años, 43,860 registros limpios).
7. **`modelo_version`**: Registro de versiones del modelo XGBoost con hiperparámetros y métricas fuera de muestra (Walk-Forward).
8. **`pronostico`**: Proyecciones a 14 días con intervalos de confianza calibrados (94.72% de cobertura fuera de muestra), valores SHAP y fecha límite de reposición.
9. **`alerta`**: Alertas automáticas de inventario (`QUIEBRE` y `SOBRESTOCK`) con sincronización idempotente.

---

## 2. Guía de Instalación desde Cero en una Nueva Máquina

### 2.1 Requisitos Previos
- **Python**: Versión 3.11 o 3.12 (compatible con 3.13).
- **PostgreSQL**: Versión 16 o 17 corriendo localmente en el puerto `5432`.
- **Git** y **PowerShell** (o terminal Bash en Linux/macOS).

---

### 2.2 Paso 1: Clonar el Repositorio y Configurar Variables de Entorno
```bash
git clone <URL_DEL_REPOSITORIO>
cd RetailPro_Backend
```

Copia el archivo de plantilla `.env.example` como `.env`:
```powershell
cp .env.example .env
```

Edita `.env` e introduce tu contraseña de PostgreSQL en `POSTGRES_PASSWORD`:
```env
# Configuración de Base de Datos
POSTGRES_SUPERUSER=postgres
POSTGRES_PASSWORD=tu_password_de_postgres_aqui
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=retailpro_db

DATABASE_URL=postgresql+psycopg://retailpro_app:retailpro_app_pwd_2026@localhost:5432/retailpro_db
DATABASE_URL_TEST=postgresql+psycopg://retailpro_app:retailpro_app_pwd_2026@localhost:5432/retailpro_test

# Seguridad JWT
SECRET_KEY=retailpro_secret_key_tesis_upc_2026_super_segura_jwt
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Configuración SMTP y Frontend (Recuperación de Contraseña)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_usuario_smtp
SMTP_PASSWORD=tu_password_smtp
SMTP_FROM=RetailPro <noreply@retailpro.com>
FRONTEND_URL=http://localhost:5173

# Contraseñas Iniciales de Usuarios del Sistema (Seed) - Definir contraseñas seguras en .env
SEED_ADMIN_EMAIL=admin@retailpro.com
SEED_ADMIN_PASSWORD=tu_password_admin_segura

SEED_ANALYST_EMAIL=carlos.lopez@retailpro.com
SEED_ANALYST_PASSWORD=tu_password_analista_segura

SEED_LOGISTICS_EMAIL=roberto.sanchez@retailpro.com
SEED_LOGISTICS_PASSWORD=tu_password_logistica_segura
```

---

### 2.3 Paso 2: Crear el Entorno Virtual e Instalar Dependencias
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

### 2.4 Paso 3: Inicializar las Bases de Datos y Roles en PostgreSQL
Ejecuta el script que crea las bases de datos `retailpro_db` y `retailpro_test`, así como los usuarios `retailpro_app` y `powerbi_reader`:
```powershell
python scripts/setup_db.py
```

---

### 2.5 Paso 4: Inicialización Automatizada Completa (Un Solo Comando)
Ejecuta el script orquestador maestro para dejar la base de datos completamente lista (migraciones, seed, dataset sintético, entrenamiento y alertas):
```powershell
python scripts/inicializar_sistema_completo.py
```

Este script ejecuta secuencialmente:
1. `alembic upgrade head`: Crea las 9 tablas en `retailpro_db`.
2. `create_views.sql`: Genera las 4 vistas SQL y otorga permisos de solo lectura al usuario `powerbi_reader`.
3. `seed.py`: Registra los 3 usuarios del sistema y los 7 umbrales de configuración iniciales.
4. Genera y procesa a través del pipeline de calidad ETL los archivos de productos (60 SKUs), inventario y 2 años de ventas diarias.
5. Ejecuta la validación Walk-Forward (12 cortes temporales) y entrena el modelo de producción activo.
6. Sincroniza las alertas idempotentes y calcula las fechas límite de reposición considerando el *Lead Time* de proveedores.

---

### 2.6 Paso 5: Iniciar el Servidor de Desarrollo
El comando oficial de arranque del backend es:
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
> [!IMPORTANT]
> Utilizar siempre `--host 127.0.0.1` (sin `0.0.0.0`). Ejecutar directamente en la consola principal de PowerShell para visualizar los registros de acceso en tiempo real (`INFO: GET /api/v1/... 200 OK`) sin procesos en segundo plano.

La API quedará accesible en `http://127.0.0.1:8000`.

---

## 3. Verificación y Pruebas del Sistema

### 3.1 Documentación Interactiva OpenAPI (Swagger)
- **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Healthcheck en vivo:** `GET http://127.0.0.1:8000/health` (verifica conexión activa a PostgreSQL).

### 3.2 Prueba Automatizada de Roles y Endpoints
Ejecuta el script de prueba de flujo completo con `Invoke-RestMethod` para validar la autenticación de los 3 perfiles y la restricción RBAC (HTTP 403 Forbidden para el rol `jefe_logistica`):
```powershell
powershell -ExecutionPolicy Bypass -File scripts/probar_endpoints_roles.ps1
```

### 3.3 Suite Completa de Pruebas Unitarias e Integración (Pytest)
Las pruebas se ejecutan contra la base de datos real de pruebas en PostgreSQL (`retailpro_test`):
```powershell
pytest -v
```
*(45 pruebas unitarias e integrales pasando al 100%).*

---

## 4. Conexión de Power BI (`powerbi_reader`)

Para conectar Power BI Desktop o Servicio a PostgreSQL:
- **Servidor:** `localhost:5432`
- **Base de Datos:** `retailpro_db`
- **Usuario:** `powerbi_reader`
- **Contraseña:** Configurada en `.env` (por defecto `powerbi_reader_pwd_2026`)
- **Vistas Disponibles (Solo Lectura):**
  - `vw_pronosticos`: Predicciones a 14 días con intervalos, P(quiebre), SHAP y fechas límite de compra.
  - `vw_ventas_diarias`: Histórico de demanda diaria consolidada por SKU y categoría.
  - `vw_alertas`: Registro de alertas activas e históricas de quiebre y sobrestock.
  - `vw_nivel_servicio`: Métricas analíticas de Fill Rate y disponibilidad por categoría.

---

## 5. Documentación Adicional en la Carpeta `docs/`
- [`docs/mapa-pantallas-endpoints.md`](docs/mapa-pantallas-endpoints.md): Matriz detallada de las 24 pantallas, endpoints reales, métodos y roles permitidos.
- [`docs/formulas_reposicion_nivel_servicio.md`](docs/formulas_reposicion_nivel_servicio.md): Formulación matemática rigurosa de reposición de inventario, lead time, nivel de servicio estimado y reglas de alerta.
- [`docs/metricas_lineas_base_tesis.md`](docs/metricas_lineas_base_tesis.md): Comparativa de desempeño fuera de muestra (XGBoost vs Naive y Media Móvil de 28 días) en horizontes diario y acumulado a 14 días.

---

## 6. Definición Oficial de Métricas del Modelo Activo (Única Fuente de Verdad)

Para garantizar consistencia y rigor metodológico entre la base de datos, los endpoints de la API y los documentos de tesis, se establece la siguiente política de **fuente única de verdad**:

1. **Definición de las Métricas del Modelo Activo:**
   El modelo en producción se entrena con el 100% de las ventas históricas disponibles (hasta la fecha de corte operativo más reciente). Por definición, un modelo de producción no posee datos futuros no vistos dentro de su propio ajuste sin incurrir en fuga de información (*data leakage*). Por consiguiente, las métricas asociadas a la versión activa (`ModeloVersion.estado == 'ACTIVA'`) representan el **macro-promedio riguroso fuera de muestra de los 12 pliegues temporales mensuales del Walk-Forward Backtesting**:
   - **MAPE Diario ($y > 0$):** **`19.23%`** (macro-promedio de los 12 cortes: entre 16.31% y 24.89%; agregado global: 19.22%).
   - **WAPE Diario Fuera de Muestra:** **`19.93%`** (error absoluto ponderado sobre las 10,080 observaciones out-of-sample).
   - **MAE Diario Fuera de Muestra:** **`7.22`** (7.2205 unidades).
   - **RMSE Diario Fuera de Muestra:** **`10.98`** (10.9802 unidades).
   - **MAPE Acumulado a 14 Días por SKU:** **`10.66%`** (WAPE acumulado: **10.25%**, ciclo de reposición).
   - **Cobertura Real del Intervalo al 95%:** **`94.72%`** estrictamente fuera de muestra (validación secuencial ciega en cortes 2 a 12, 8,752 / 9,240 aciertos). El valor de **`95.42%`** corresponde a la cobertura calibrada retrospectivamente con los mismos residuos (no fuera de muestra).

2. **Paridad Consolidada en Endpoints:**
   Todos los módulos consumen los mismos valores de la tabla `modelo_version`:
   - `GET /api/v1/modelos/activa`: Retorna `mape: 19.23`, `mae: 7.2206`, `rmse: 10.9802`, `wape: 19.93`.
   - `GET /api/v1/modelos/monitoreo`: Lista los 12 cortes históricos de backtest con `mape_promedio_historico: 19.23` y `cobertura_intervalo_95: 94.72`.
   - `GET /api/v1/modelos/historial`: Registra la versión de producción activa (`v1.0.0`) con `mape: 19.23`.
   - `GET /api/v1/pronosticos/{sku}`: Entrega el campo `mape_modelo = 19.23`.
   - `GET /api/v1/dashboard`: Tarjeta de "Precisión Global" muestra `19.23%` (o `null` / `"—"` si no hay modelo activo).
   - `POST /api/v1/reportes/indicadores/export`: Exporta MAPE 19.23%, WAPE 19.93%, RMSE 10.9802 y MAE 7.2206 (o `"—"` si no hay modelo activo).

---

## 7. Intervalos de Confianza y Calibración del Nivel de Incertidumbre

Los intervalos de confianza al 95% se calculan empíricamente a partir de la distribución de errores relativos fuera de muestra obtenida durante el Walk-Forward Backtesting (12 cortes mensuales):

1. **Percentiles Empíricos por Categoría ($p_{2.5}, p_{97.5}$):**
   - Para cada categoría, se determinan los percentiles 2.5% y 97.5% de los residuos relativos acumulados: $e_{rel} = (y_{real} - \hat{y}) / \hat{y}$.
   - Los límites del intervalo para cada SKU y horizonte se escalan proporcionalmente a la proyección puntual:
     $$\text{IC}_{\text{inf}} = \max\left(0, \; \hat{y} \cdot (1 + p_{2.5})\right), \quad \text{IC}_{\text{sup}} = \max\left(0, \; \hat{y} \cdot (1 + p_{97.5})\right)$$
   - Cobertura empírica: **94.72%** fuera de muestra en validación secuencial ciega (8,752 / 9,240 observaciones). La cifra de **95.42%** representa la cobertura calibrada retrospectivamente con los mismos residuos sobre las 10,080 observaciones del catálogo (no fuera de muestra).

> [!NOTE]
> El sistema no aplica ninguna regla arbitraria de "estabilidad temporal con $\sigma \le 2.5\%$". Toda dispersión e incertidumbre se modela de manera objetiva a partir de los percentiles empíricos residuales.

2. **Clasificación del `nivel_incertidumbre` (Relativa al Catálogo):**
   - El nivel de incertidumbre asignado a cada proyección (`BAJO`, `MEDIO`, `ALTO`) mide la **amplitud relativa del intervalo de predicción** respecto a la escala del producto:
     $$\text{Ancho Relativo} = \frac{\text{IC}_{\text{sup}} - \text{IC}_{\text{inf}}}{\max(1, \; \hat{y})}$$
   - Umbrales centralizados en [`app/core/config.py`](app/core/config.py):
     - $\text{Ancho Relativo} \le 0.95 \implies$ **`BAJO`** (`UNCERTAINTY_THRESHOLD_LOW = 0.95`)
     - $0.95 < \text{Ancho Relativo} \le 1.10 \implies$ **`MEDIO`** (`UNCERTAINTY_THRESHOLD_MEDIUM = 1.10`)
     - $\text{Ancho Relativo} > 1.10 \implies$ **`ALTO`**
   - **Interpretación operativa de negocio:** El indicador `nivel_incertidumbre` es una métrica comparativa dentro del catálogo de FasRetail que refleja la **volatilidad intrínseca y dispersión empírica de la categoría** (como productos de alta rotación y demanda estable: Abarrotes y Bebidas vs categorías con mayor varianza semanal), y **no** un fallo o error absoluto del modelo predictivo.

---

## 8. Ciclo de Vida de Alertas de Inventario y Regla Anti-Reapertura

El Centro de Alertas gestiona de forma determinista el ciclo de vida de incidencias de inventario (`QUIEBRE` y `SOBRESTOCK`) conforme a la siguiente especificación:

1. **Estados Operativos Válidos:**
   - **`ACTIVA`**: Alerta vigente que requiere atención operativa o emisión de orden de compra.
   - **`RESUELTA`**: Alerta atendida por el analista (como la colocación de orden de reposición) o resuelta automáticamente al cesar la condición de riesgo.
   - **`DESCARTADA`**: Alerta desestimada justificadamente por el usuario con comentario de auditoría.

2. **Transiciones y Auditoría:**
   - Las transiciones de estado se ejecutan mediante el endpoint `PATCH /api/v1/alertas/{id_alerta}` (restringido a roles `administrador` y `analista`).
   - Cada transición registra un evento inmutable en la tabla `auditoria` con el ID de usuario, ID de alerta, SKU, tipo de alerta, `estado_anterior`, `nuevo_estado` y comentario justificativo.

3. **Regla Anti-Reapertura (Idempotencia Operativa):**
   - Durante la regeneración de pronósticos (`POST /procesos/ejecutar/pronostico`) o la actualización dinámica de umbrales (`PUT /umbrales`), el motor de sincronización (`sincronizar_alertas`) evalúa las condiciones de quiebre y sobrestock.
   - **Garantía anti-reapertura:** Si para un SKU y tipo de alerta existe una alerta previa en estado `RESUELTA` o `DESCARTADA`, el sistema **NO reabre ni duplica** la alerta mientras la proyección pertenezca a la misma fecha base del pronóstico ($t_{\text{base}}$) y la condición sea idéntica.
   - **Generación legítima:** Únicamente se genera una nueva alerta si la fecha base del pronóstico avanza a un nuevo día operativo ($t_{\text{base, nuevo}} > t_{\text{base, anterior}}$) o si la condición de riesgo surge tras un período sin alerta.
   - **Reactivación manual:** Un usuario puede devolver una alerta resuelta o descartada al estado `ACTIVA` en cualquier momento mediante `PATCH /api/v1/alertas/{id_alerta}` con `nuevo_estado="ACTIVA"`.

4. **Agregación de Conteos:**
   - La respuesta de `GET /api/v1/alertas` segrega estrictamente las alertas: los contadores operativos `activas`, `criticas`, `advertencias`, `quiebre` y `sobrestock` excluyen en su totalidad a las alertas en estado `RESUELTA` y `DESCARTADA`.
   - Las alertas inactivas se reportan exclusivamente en los contadores `resueltas` y `descartadas`.

---

## 9. Servicio de Correo Electrónico (SMTP) y Recuperación de Contraseña

### 9.1 Flujo de Recuperación de Contraseña (100% Implementado con Envío Real)
El sistema cuenta con envío real de correo electrónico a través del protocolo SMTP con cifrado seguro STARTTLS (`timeout=10s`) implementado en [`app/services/email_service.py`](app/services/email_service.py):

1. **Solicitud de Recuperación (`POST /api/v1/auth/recuperar` o `/password-recovery`):**
   - Acepta `{ "correo": "usuario@empresa.com" }` (o `{ "email": "..." }`).
   - **Rate Limiting previo y universal:** Aplica un límite estricto de **5 solicitudes por correo por hora** (HTTP 429 Too Many Requests ante excesos) trazado en la tabla `auditoria`. Este límite se valida y consume de forma previa e indistinta para **todos los casos** (exista o no la cuenta), retornando HTTP 429 antes de consultar la existencia del usuario en la base de datos para mitigar ataques de fuerza bruta o abuso de la API.
   - **Política de Mensajería Explícita:** Por tratarse de una plataforma corporativa e interna sin auto-registro público de usuarios, se adoptó el retorno de mensajes y códigos de estado HTTP explícitos (en lugar de respuestas ambiguas anti-enumeración), optimizando el soporte operativo y la claridad para los colaboradores:
     - **Correo no registrado:** Responde `HTTP 404 Not Found` con `{"detail": "No existe una cuenta registrada con ese correo electrónico."}`.
     - **Cuenta inactiva:** Responde `HTTP 403 Forbidden` con `{"detail": "La cuenta está inactiva. Comunícate con el administrador."}`.
     - **Cuenta existente y activa:** Envía el correo real vía SMTP y responde `HTTP 200 OK` con `{"success": true, "message": "Te enviamos las instrucciones al correo indicado. Revisa tu bandeja de entrada y spam."}`.
   - **Generación de Token Criptográfico Seguro:** Para usuarios activos, genera un JWT criptográfico con:
     - Claim `propósito`: `"reset"`.
     - Expiración: 30 minutos (`settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`).
     - Claim `huella`: Primeros 16 caracteres hexadecimales del hash SHA-256 de la contraseña actual del usuario (`user.clave_hash`).
   - Envía un correo con plantilla HTML y texto plano en español conteniendo el enlace de acceso:
     `{FRONTEND_URL}/restablecer-contrasena?token={token}`
   - **Auditoría segura:** Registra el evento en `auditoria` (IP y correo destino) omitiendo cualquier token, credencial o secreto.

2. **Restablecimiento Seguro (`POST /api/v1/auth/restablecer` o `/reset-password`):**
   - Acepta `{ "token": "...", "nueva_contrasena": "..." }` (o `{ "token": "...", "new_password": "..." }`).
   - Valida criptográficamente la firma del JWT, expiración temporal, claim de propósito (`"reset"`) y correspondencia exacta de la `huella` con la clave actual en BD.
   - **Garantía de un solo uso:** Al actualizar la contraseña (`user.clave_hash`), la huella del usuario cambia de inmediato, invalidando de forma automática y definitiva el token ante cualquier intento de reutilización.
   - Aplica validación de robustez de contraseña (mínimo 8 caracteres, combinación de letras y números) devolviendo errores genéricos HTTP 400 Bad Request.

### 9.2 Notificaciones de Alertas por Correo (Pantalla 09)
El subsistema de alertas operativas se encuentra completamente integrado con el motor de notificaciones SMTP saliente en [`app/services/email_service.py`](file:///C:/UPC/CICLO%2010/TP1/P20262014_Codigo/RetailPro_Backend/app/services/email_service.py):

1. **Configuración de Destinatarios y Filtros de Alertas (`GET` / `PUT /api/v1/procesos/configuracion`):**
   - **Destinatarios (`correo_alertas`):** Admite de 1 a 5 direcciones de correo electrónico válidas separadas por coma. Valida formato estricto y retorna HTTP 422 ante correos no válidos o listas que superen 5 destinatarios.
   - **Filtros por Tipo de Alerta:** Permite activar o desactivar selectivamente el envío de notificaciones para:
     - `quiebre_critico` (`notificar_quiebre`): Quiebres de stock inminentes o con alta probabilidad.
     - `calidad_bajo_umbral` (`notificar_calidad_baja`): Archivos de datos con calidad por debajo del umbral mínimo exigido.
     - `sobrestock_prolongado` (`notificar_sobrestock`): Días de cobertura excesivos y stock superior al ratio de reorden.
   - **Umbral de Calidad Mínima (`umbral_calidad` / `calidad_min`):** Rango permitido entre 50.0% y 100.0% (HTTP 422 ante valores fuera de rango). Al modificarse mediante `PUT`, sincroniza de forma inmediata y persistente el valor de `calidad_min` en la tabla `umbral_configuracion` de PostgreSQL.
   - **Verificación SMTP (`smtp_configurado`):** El endpoint `GET` expone un booleano que indica si las credenciales mínimas (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`) se encuentran cargadas en el entorno sin exponer secretos.

2. **Despacho Consolidado ante Nuevas Alertas de Inventario:**
   - Durante la generación de pronósticos (`POST /procesos/ejecutar/pronostico`), ETL o sincronización, cuando se **crean alertas nuevas** en la base de datos pertenecientes a los tipos habilitados, se envía **un único correo resumen** en español a todos los destinatarios configurados.
   - El correo incluye una tabla HTML estructurada con: SKU, Producto, Tipo de alerta (`QUIEBRE`, `SOBRESTOCK`), Prioridad (`ALTA`, `MEDIA`), Cobertura (días), Probabilidad de quiebre y el enlace directo al Centro de Alertas (`{FRONTEND_URL}/alertas`).
   - **Regla anti-spam y anti-reapertura:** Únicamente se notifican alertas recién creadas. Alertas preexistentes o bloqueadas por la regla de no reapertura no disparan nuevos correos.
   - **Tolerancia a Fallos:** Si el servidor SMTP no se encuentra disponible o no está configurado, el error se registra en logs de forma sanitizada (sin credenciales) y el proceso batch continúa sin interrupciones.

3. **Notificación por Calidad Insuficiente de Archivos ETL:**
   - Cuando se valida la carga de un archivo (`POST /api/v1/datos/upload` o ETL local) y el índice de calidad obtenido es inferior a `calidad_min`, se despacha un correo de advertencia con el nombre del archivo, calidad obtenida (%), umbral exigido (%) y enlace a la consola de datos (`{FRONTEND_URL}/datos`).

4. **Despacho Manual de Resumen de Alertas Activas (`POST /api/v1/notificaciones/resumen-alertas` y alias `/prueba`):**
   - Exclusivo para rol `administrador` (HTTP 403 Forbidden para analista y logística).
   - Envía a los destinatarios configurados el mismo correo resumen que se genera ante nuevas alertas, consolidando las alertas **ACTIVAS** actuales de los tipos habilitados (`quiebre_critico`, `sobrestock_prolongado`) con asunto `"Resumen de alertas – RetailPro"`, sin la palabra "prueba" en asunto, cuerpo ni mensajes.
   - Si no existen alertas activas de los tipos habilitados, no despacha correo y responde:
     `{"success": true, "enviado": false, "message": "No hay alertas activas de los tipos seleccionados."}`
   - Si se envía exitosamente, responde:
     `{"success": true, "enviado": true, "cantidad_alertas": n, "destinatarios": [...], "message": "Resumen enviado a ..."}`
   - Ante errores de conexión SMTP, devuelve mensaje sanitizado sin exponer credenciales.

5. **Trazabilidad y Auditoría:**
   - El despacho manual de resumen se audita en la tabla `auditoria` bajo la acción `"Notificación de alertas enviada"` y módulo `"notificaciones"`, registrando en `detalle` el tipo `"manual"`, la cantidad de alertas, la cantidad de destinatarios y los correos destino, preservando la confidencialidad según la Ley N.° 29733 (sin cuerpo de correo ni credenciales).
   - Los despachos automáticos batch se auditan con acción `"Notificación de alerta enviada"` (o `"Notificación de alertas enviada"`).
   - Cualquier modificación en la configuración de procesos y alertas se registra con `accion="Configuración de proceso modificada"` y descripción legible (ej: `"ETL: hora 03:00 → 02:00"`).

6. **Salvaguarda de Pruebas:**
   - La suite automatizada de pruebas y el script de inicialización (`scripts/inicializar_sistema_completo.py`) incorporan mocks automáticos de `smtplib.SMTP` y la bandera `SKIP_EMAIL_NOTIFICATIONS=true` para garantizar que ningún entorno de prueba o inicialización remita correos reales.
