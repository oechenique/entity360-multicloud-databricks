# Contraparte de levantar.ps1: detiene Airflow sin borrar nada (la base de Airflow y los volúmenes quedan).
# Va por nombre de proyecto y no por el archivo: docker-compose.yml exige las credenciales (${...:?}) y
# acá no hacen falta.
#
# Uso (desde la raíz del repo):
#   .\airflow\apagar.ps1              # solo Airflow
#   .\airflow\apagar.ps1 -ConLegacy   # también el SQL Server del legacy
#   .\airflow\levantar.ps1            # volver a levantar (con el legacy: docker compose -f legacy\docker-compose.yml start)
param([switch]$ConLegacy)
$ErrorActionPreference = "Continue"   # docker escribe el progreso en stderr (ver levantar.ps1)

$proyectos = @("entity360-airflow")
if ($ConLegacy) { $proyectos += "entity360-legacy" }
foreach ($p in $proyectos) {
    docker compose -p $p stop 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "docker compose -p $p stop falló ($LASTEXITCODE)" }
}
docker ps --filter "name=entity360" --format "{{.Names}}: {{.Status}}"
