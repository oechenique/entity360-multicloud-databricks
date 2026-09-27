# Fase 8 (ADR 0007): levanta Airflow con las credenciales del llavero de Windows.
# Las lee airflow\credenciales.py y quedan solo en el entorno de este proceso y en la configuración
# de los containers: no se escriben en ningún archivo del repo.
#
# Uso (desde la raíz del repo, con Docker Desktop y el legacy creado alguna vez):
#   .\airflow\levantar.ps1              # build + up -d
#   docker compose -f airflow\docker-compose.yml stop     # detener (conserva la base de Airflow)
$ErrorActionPreference = "Stop"
$raiz = Split-Path $PSScriptRoot -Parent

$lineas = & "$raiz\.venv\Scripts\python.exe" "$PSScriptRoot\credenciales.py" entorno
if ($LASTEXITCODE -ne 0) { throw "Faltan credenciales en el llavero: airflow\credenciales.py verificar" }
foreach ($l in $lineas) {
    $k, $v = $l -split "=", 2
    Set-Item -Path "env:$k" -Value $v
}

# Secreto del JWT de la API de Airflow: uno por levantada, compartido por todos los componentes.
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$env:E360_JWT_SECRET = [Convert]::ToBase64String($bytes)

# El extractor CDC ve al SQL Server por la red del legacy.
docker network inspect entity360-legacy_default *> $null
if ($LASTEXITCODE -ne 0) { throw "No existe la red del legacy: docker compose -f legacy\docker-compose.yml up -d" }

# docker escribe el progreso en stderr: con "Stop", PowerShell 5.1 lo toma como error y corta. Se
# decide por el código de salida.
$ErrorActionPreference = "Continue"
docker compose -f "$PSScriptRoot\docker-compose.yml" up -d --build @args 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { throw "docker compose up falló ($LASTEXITCODE)" }
