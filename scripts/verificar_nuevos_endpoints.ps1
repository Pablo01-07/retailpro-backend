$ErrorActionPreference = "Stop"

$adminPwd = $env:SEED_ADMIN_PASSWORD
$logisticsPwd = $env:SEED_LOGISTICS_PASSWORD

if (-not $adminPwd -or -not $logisticsPwd) {
    if (Test-Path ".env") {
        Get-Content ".env" | ForEach-Object {
            $line = $_.Trim()
            if ($line -match '^SEED_ADMIN_PASSWORD="?([^"]+)"?') { if (-not $adminPwd) { $adminPwd = $matches[1] } }
            if ($line -match '^SEED_LOGISTICS_PASSWORD="?([^"]+)"?') { if (-not $logisticsPwd) { $logisticsPwd = $matches[1] } }
        }
    }
}

if (-not $adminPwd) {
    $sec = Read-Host "Ingrese contraseña de Administrador" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $adminPwd = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
}
if (-not $logisticsPwd) {
    $sec = Read-Host "Ingrese contraseña de Jefe de Logística" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $logisticsPwd = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
}

$loginAdminBody = @{ email = "admin@retailpro.com"; password = $adminPwd } | ConvertTo-Json
$loginAdmin = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/auth/login' -Method Post -ContentType 'application/json' -Body $loginAdminBody
$tokenAdmin = $loginAdmin.access_token
Write-Host "[OK] Autenticación de Administrador exitosa."

$loginLogBody = @{ email = "roberto.sanchez@retailpro.com"; password = $logisticsPwd } | ConvertTo-Json
$loginLog = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/auth/login' -Method Post -ContentType 'application/json' -Body $loginLogBody
$tokenLog = $loginLog.access_token
Write-Host "[OK] Autenticación de Jefe de Logística exitosa."

$hist = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/reportes/historial?page=1&limit=5' -Method Get -Headers @{Authorization="Bearer $tokenLog"}
Write-Host "1. GET /reportes/historial: $($hist.total_reportes) reportes disponibles en storage"

$repInv = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/reportes/inventario/export' -Method Post -Headers @{Authorization="Bearer $tokenAdmin"} -ContentType 'application/json' -Body '{"formato": "xlsx", "categoria": "Abarrotes"}'
Write-Host "2. POST /reportes/inventario/export: $($repInv.nombre_archivo) -> $($repInv.url_descarga)"

$repVen = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/reportes/ventas/export' -Method Post -Headers @{Authorization="Bearer $tokenAdmin"} -ContentType 'application/json' -Body '{"formato": "csv"}'
Write-Host "3. POST /reportes/ventas/export: $($repVen.nombre_archivo) -> $($repVen.url_descarga)"

$repInd = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/reportes/indicadores/export' -Method Post -Headers @{Authorization="Bearer $tokenAdmin"} -ContentType 'application/json' -Body '{"formato": "pdf"}'
Write-Host "4. POST /reportes/indicadores/export: $($repInd.nombre_archivo) -> $($repInd.url_descarga)"

$repRep = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/reposicion/exportar' -Method Post -Headers @{Authorization="Bearer $tokenAdmin"} -ContentType 'application/json' -Body '{"formato": "xlsx", "prioridad": "ALTA"}'
Write-Host "5. POST /reposicion/exportar: $($repRep.nombre_archivo) -> $($repRep.url_descarga)"

$ns = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/dashboard/nivel-servicio?categoria=Abarrotes&almacen=Principal' -Method Get -Headers @{Authorization="Bearer $tokenLog"}
Write-Host "6. GET /dashboard/nivel-servicio: Fill Rate: $($ns.nivel_servicio_global_pct)% | Almacenes: $($ns.almacenes -join ', ') | Seleccionado: $($ns.almacen_seleccionado)"

$repList = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/reposicion?sku=ABA-001' -Method Get -Headers @{Authorization="Bearer $tokenLog"}
Write-Host "7. GET /reposicion (sku=ABA-001): $($repList.total_recomendaciones) recomendaciones"

$tend = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/pronosticos/tendencias?categoria=Abarrotes' -Method Get -Headers @{Authorization="Bearer $tokenLog"}
Write-Host "8. GET /pronosticos/tendencias (categoria=Abarrotes): $($tend.total_meses) meses evaluados"

$cal = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/datos/calidad?tipo_informacion=ventas' -Method Get -Headers @{Authorization="Bearer $tokenAdmin"}
Write-Host "9. GET /datos/calidad (tipo=ventas): $($cal.total_cargas) cargas encontradas"

$act = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/modelos/13/activar' -Method Patch -Headers @{Authorization="Bearer $tokenAdmin"}
Write-Host "10. PATCH /modelos/13/activar: Versión $($act.version) activada con estado '$($act.estado)'"

$proc = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/procesos/ejecutar/pronostico' -Method Post -Headers @{Authorization="Bearer $tokenAdmin"}
Write-Host "11. POST /procesos/ejecutar/pronostico: $($proc.mensaje) (Carga ID: $($proc.id_carga))"
