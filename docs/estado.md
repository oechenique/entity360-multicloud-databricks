# Estado del proyecto

Última actualización: **2026-09-27, 01:20 UTC** (cierre del día). Se actualiza al cerrar cada sesión.

## Dónde estamos
**Fase 6 (regla 08), paso 4: esperando el etiquetado de la parte A del set de validación.**

## Hecho
- **Fase 4 (GDELT)** cerrada salvo la verificación del cron (ver "Pendiente"):
  - WIF, SA sin claves, respaldo en BigQuery sandbox y SP `entity360-producer-gdelt`.
  - Tests del match de alias y de la idempotencia (`tests/gcp_gdelt`, 38 tests, uno contra BigQuery).
  - Docs: `manual-steps.md` §9, `destroy.md` y la licencia en `fuentes.md`.
- **Fase 6, pasos 0 a 3:**
  - Paso 0 verificado en serverless (`databricks/evidencia/paso0-verificaciones.txt`) y ADR 0004
    (job de PySpark, no Lakeflow Declarative Pipelines).
  - Job `entity360-medallion` (`infra/databricks/medallion.tf`): Bronze (Auto Loader, capa 2 por
    sha256) → Silver (SCD2 del CDC, normalización, cuarentena), todo en Iceberg gestionado.
    **Schedule diario 08:45 (Buenos Aires), activo desde el 2026-09-27.**
  - Dos corridas manuales verificadas (`databricks/evidencia/pasos1-3-primeras-corridas.txt`),
    incluido un reenvío idéntico que quedó como `duplicado` sin sumar filas.
  - 71 tests locales (`tests/medallion`).
- **Fase 6, paso 4 (parte A):** `databricks/resolucion/validacion/parte_a.csv` generado.

## Pendiente
1. **Etiquetar la parte A (Gastón).** Son 59 registros:
   - Archivo: `databricks/resolucion/validacion/parte_a.csv` (separado por `;`, se abre en Excel).
   - Instrucciones: `databricks/resolucion/validacion/README.md`.
   - Por registro: `respuesta` (`1`–`5`, `ninguno`, `otro` + `lei_otro`, o `incierto`),
     `evidencia` (obligatoria) y `fecha`.
   - **No regenerar el CSV** después de empezar: el script lo pisa.
2. **Cron de `gdelt-horario`: todavía no corrió solo.**
   - El `schedule` llegó a `main` el 2026-09-26 a las 23:25 UTC.
   - El slot de las 00:23 UTC pasó sin corrida `schedule`; a las 01:20 UTC seguía sin ninguna (solo
     las 4 manuales del 2026-09-26). El workflow figura activo y `enriquecimiento-diario` (también
     nuevo) tampoco corrió todavía: parece la demora de GitHub con schedules nuevos.
   - Verificar:
     `gh run list --workflow gdelt-horario.yml --event schedule --limit 5 --json createdAt,startedAt,updatedAt,conclusion`.
     Cada corrida tiene que durar menos de 60 s (ADR 0003).
   - Si al día siguiente sigue sin correr, revisar la pestaña Actions (GitHub puede desactivar schedules).
3. **Consumo en DBU por corrida del job: falta medirlo.** `system.billing.usage` llega con ~12 h de
   retraso. Consulta (SQL warehouse):
   ```sql
   SELECT usage_metadata.job_run_id, sku_name, round(sum(usage_quantity), 4) AS dbu
   FROM system.billing.usage
   WHERE usage_metadata.job_id = '<terraform output medallion_job_id>'
   GROUP BY ALL
   ```
   Anotar el resultado en `databricks/evidencia/pasos1-3-primeras-corridas.txt`, junto con la primera
   corrida programada (08:45).

## Qué sigue (después del etiquetado)
1. Parte B del set de validación (~60 pares: fáciles, positivos difíciles, negativos difíciles y
   dudosos), en `parte_b.csv`.
2. Paso 5: resolución (blocking, score, umbrales, clusters, golden record), calibración con la mitad
   del set, y precisión y recall con intervalo de Wilson al 95 % sobre la otra mitad.

## Estado del entorno al cerrar
- `main` = `origin/main`, sin cambios locales.
- SQL Server del legacy: contenedor **detenido** (`docker compose stop`), con el volumen intacto.
  Para levantarlo: `docker compose -f legacy\docker-compose.yml start`.
- Sin procesos ni watchers corriendo. Ningún job de Databricks en ejecución; la próxima corrida es
  el schedule de las 08:45.
