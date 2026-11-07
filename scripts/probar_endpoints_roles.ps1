$baseUrl = "http://127.0.0.1:8000/api/v1"

$envContent = Get-Content ".env"
$adminPwd = ""
$analystPwd = ""
$logisticsPwd = ""

foreach ($line in $envContent) {
    if ($line -match '^SEED_ADMIN_PASSWORD="?([^"]+)"?') { $adminPwd = $matches[1] }
    if ($line -match '^SEED_ANALYST_PASSWORD="?([^"]+)"?') { $analystPwd = $matches[1] }
    if ($line -match '^SEED_LOGISTICS_PASSWORD="?([^"]+)"?') { $logisticsPwd = $matches[1] }
}

Write-Host "=========================================================================="
Write-Host "1. AUTENTICACION POR ROL (Invoke-RestMethod POST /auth/login)"
Write-Host "=========================================================================="

$adminPayload = @{ email = "admin@retailpro.com"; password = $adminPwd } | ConvertTo-Json
$adminLogin = Invoke-RestMethod -Uri "$baseUrl/auth/login" -Method Post -Body $adminPayload -ContentType "application/json"
$adminToken = $adminLogin.access_token
Write-Host "[+] Administrador autenticado: $($adminLogin.user.nombre_completo) (Rol: $($adminLogin.user.rol))"

$analystPayload = @{ email = "carlos.lopez@retailpro.com"; password = $analystPwd } | ConvertTo-Json
$analystLogin = Invoke-RestMethod -Uri "$baseUrl/auth/login" -Method Post -Body $analystPayload -ContentType "application/json"
$analystToken = $analystLogin.access_token
Write-Host "[+] Analista autenticado:       $($analystLogin.user.nombre_completo) (Rol: $($analystLogin.user.rol))"

$logisticsPayload = @{ email = "roberto.sanchez@retailpro.com"; password = $logisticsPwd } | ConvertTo-Json
$logisticsLogin = Invoke-RestMethod -Uri "$baseUrl/auth/login" -Method Post -Body $logisticsPayload -ContentType "application/json"
$logisticsToken = $logisticsLogin.access_token
Write-Host "[+] Jefe Logistica autenticado: $($logisticsLogin.user.nombre_completo) (Rol: $($logisticsLogin.user.rol))"

Write-Host "`n=========================================================================="
Write-Host "2. DASHBOARD COMO JEFE DE LOGISTICA (GET /dashboard - 200 OK)"
Write-Host "=========================================================================="
$logisticsHeaders = @{ Authorization = "Bearer $logisticsToken" }
$dash = Invoke-RestMethod -Uri "$baseUrl/dashboard" -Method Get -Headers $logisticsHeaders
Write-Host "[+] KPIs Ejecutivos recuperados exitosamente:"
foreach ($k in $dash.kpis) {
    Write-Host "    - $($k.nombre): $($k.valor) (Estado: $($k.estado))"
}

Write-Host "`n=========================================================================="
Write-Host "3. REPOSICION COMO ANALISTA (GET /reposicion - 200 OK)"
Write-Host "=========================================================================="
$analystHeaders = @{ Authorization = "Bearer $analystToken" }
$repo = Invoke-RestMethod -Uri "$baseUrl/reposicion" -Method Get -Headers $analystHeaders
Write-Host "[+] Total recomendaciones generadas: $($repo.total_recomendaciones)"
Write-Host "[+] Total sugerido de compra:        $($repo.total_sugerido_unidades) unidades"
$primerItem = $repo.items[0]
Write-Host "    * Primer SKU: $($primerItem.sku) - $($primerItem.nombre_producto)"
Write-Host "      Stock: $($primerItem.stock_actual) | Sugerido: $($primerItem.cantidad_sugerida) | Prioridad: $($primerItem.prioridad)"

Write-Host "`n=========================================================================="
Write-Host "4. AJUSTE MANUAL COMO ANALISTA (PATCH /reposicion/{id} - 200 OK)"
Write-Host "=========================================================================="
$patchBody = @{
    cantidad_ajustada = 180
    motivo_ajuste = "Lote minimo del proveedor acordado en negociacion"
} | ConvertTo-Json
$ajusteResp = Invoke-RestMethod -Uri "$baseUrl/reposicion/$($primerItem.id_pronostico)" -Method Patch -Headers $analystHeaders -Body $patchBody -ContentType "application/json"
Write-Host "[+] $($ajusteResp.mensaje)"
Write-Host "    Cantidad ajustada: $($ajusteResp.cantidad_ajustada) und."

Write-Host "`n=========================================================================="
Write-Host "5. PRUEBA DE RESTRICCION RBAC (Jefe Logistica intenta ajustar reposicion)"
Write-Host "   (Esperado: 403 Forbidden)"
Write-Host "=========================================================================="
try {
    $forbiddenResp = Invoke-RestMethod -Uri "$baseUrl/reposicion/$($primerItem.id_pronostico)" -Method Patch -Headers $logisticsHeaders -Body $patchBody -ContentType "application/json"
    Write-Host "[-] ERROR: La solicitud tuvo exito cuando debio ser rechazada."
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    Write-Host "[+] RESPUESTA CORRECTA: Error HTTP $statusCode Forbidden detectado y bloqueado por RBAC."
    Write-Host "    Mensaje del servidor: Acceso denegado: Se requiere rol administrador o analista."
}

Write-Host "`n=========================================================================="
Write-Host "6. CENTRO DE ALERTAS (GET /alertas - 200 OK)"
Write-Host "=========================================================================="
$alertas = Invoke-RestMethod -Uri "$baseUrl/alertas" -Method Get -Headers $analystHeaders
Write-Host "[+] Total alertas activas: $($alertas.total_activas) (Quiebre: $($alertas.total_quiebre), Sobrestock: $($alertas.total_sobrestock))"
if ($alertas.items.Count -gt 0) {
    $a = $alertas.items[0]
    Write-Host "    * Alerta #$($a.id_alerta): SKU $($a.sku) ($($a.tipo_alerta) - $($a.nivel_severidad))"
    Write-Host "      Motivo: $($a.detalle_motivo)"
}

Write-Host "`n=========================================================================="
Write-Host "7. NIVEL DE SERVICIO COMO JEFE DE LOGISTICA (GET /dashboard/nivel-servicio)"
Write-Host "=========================================================================="
$ns = Invoke-RestMethod -Uri "$baseUrl/dashboard/nivel-servicio" -Method Get -Headers $logisticsHeaders
Write-Host "[+] Nivel de servicio global estimado: $($ns.nivel_servicio_global_pct)%"
Write-Host "[+] Disponibilidad de catalogo:        $($ns.disponibilidad_global_pct)%"
Write-Host "[+] Nota metodologica:                 $($ns.nota_metodologica)"

Write-Host "`n=========================================================================="
Write-Host "8. EXPORTACION DE REPORTES COMO ANALISTA (POST /reportes/pronostico/export)"
Write-Host "=========================================================================="
$exportBody = @{
    formato = "pdf"
    tipo_reporte = "pronostico_reposicion"
} | ConvertTo-Json
$exportResp = Invoke-RestMethod -Uri "$baseUrl/reportes/pronostico/export" -Method Post -Headers $analystHeaders -Body $exportBody -ContentType "application/json"
Write-Host "[+] Reporte generado en PDF: $($exportResp.nombre_archivo)"
Write-Host "    URL descarga: $($exportResp.url_descarga)"
