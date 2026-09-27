# Estado del proyecto

Última actualización: **2026-09-27, 23:15 UTC**. Se actualiza al cerrar cada sesión.

## Dónde estamos
**Fase 8 (regla 10) cerrada: Airflow local orquesta todo. Sigue la fase 9 (Snowflake), y en paralelo
el etiquetado de la parte B.**

## Hecho
- **Fases 0 a 5** cerradas (spike, base de Databricks, legacy con CDC, SEC EDGAR, GDELT, enriquecimiento).
  - GDELT: el cron de Actions saltea horas (3 corridas en 20 h el 2026-09-27); la ventana pasó a
    24 h para no perder menciones (ADR 0003).
- **Fase 6 (regla 08):**
  - Job `entity360-medallion`: bronze → silver → resolucion, schedule diario 08:45 (Buenos Aires).
    Consumo: 0,6–1,2 DBU por corrida (`databricks/evidencia/pasos1-3-primeras-corridas.txt`).
  - Resolución de identidades (`databricks/medallion/identidades.py`, pesos **sin calibrar**): 1268
    registros → 1132 entidades; 17 casos a revisar y 16 conflictos en `resolution.revision`.
  - Set de validación: **parte A etiquetada** (59 registros) y **parte B generada** (60 pares, sin
    etiquetar), en `databricks/resolucion/validacion/`.
- **Fase 7 (regla 09):**
  - Contratos de llegada con Soda Core 4 (`contracts/`): 5 fuentes, veredicto `_contrato_<ts>.json`
    por lote, cuarentena en Bronze (`cuarentena_contrato`) y alerta por Telegram. Los 10 lotes del
    landing, aprobados.
  - dbt (`dbt/`): 5 modelos Gold en Iceberg gestionado con contratos enforced (ADR 0005); `dbt build`
    24/24 y `dbt source freshness` 7/7.
- **Fase 8 (regla 10):** Airflow 3.3 local en Docker (`airflow/`), DAG `entity360_convergencia` a las
  08:45: extractor CDC → sensores de llegada por fuente → contratos → job de Databricks → dbt con
  Cosmos → frescura. SP propio `entity360-orquestador` (ADR 0007). Primera corrida completa en verde.
- Tests: 3 en `tests/airflow`, 99 en `tests/medallion`, 38 en `tests/gcp_gdelt`, 19 en `tests/contracts` (entorno
  `contracts\.venv`).

## Pendiente
1. ~~Etiquetar la parte B~~ **hecho** (60 pares, 2026-09-27).
2. **Calibración (paso 5 de la fase 6): números listos, sin aplicar.** La grilla no cambia los pesos
   (los iniciales empatan en el máximo). Evaluación: precisión 0,913 [0,732–0,976], recall 0,955
   [0,782–0,992], recall del blocking 11/11. Quedan 7 errores con causas estructurales (país supuesto de
   GDELT, alias genéricos de OpenSanctions, gemelos de LEI anulados, un identificador de marca): ver
   `databricks/resolucion/calibracion/INFORME.md`. Decisión de Gastón pendiente: qué causas corregir y
   cómo evaluar después (la mitad de evaluación ya se miró).
3. ~~Lotes sin veredicto~~ **resuelto (ADR 0006):** Bronze exige el veredicto y el schedule de las
   08:45 está **pausado**: el job lo dispara Airflow (fase 8). Cuarentena probada de punta a punta
   (`contracts/evidencia/cuarentena-punta-a-punta.txt`).
4. ~~Borrar `gold.prueba_contrato`~~ **hecho** (2026-09-27).
5. **Aligerar el stack de Airflow:** la corrida del DAG saturó la CPU de la PC. Más adelante: seguir
   con LocalExecutor, límites de CPU y memoria por contenedor en `airflow/docker-compose.yml` y un techo
   para WSL2 en `.wslconfig` (`processors`, `memory`).
6. **Canal de alertas:** crear el bot de Telegram (`docs/manual-steps.md` §10). Sin él, las alertas van
   a stderr.

## Estado del entorno al cerrar
- `main` = `origin/main`.
- **Airflow levantado** (`.\airflow\levantar.ps1`, UI en http://localhost:8080) y el SQL Server del
  legacy **prendido** (lo lee el extractor CDC). El job de Databricks lo dispara Airflow (ADR 0006).
  Para apagar: `docker compose -f airflow\docker-compose.yml stop` y
  `docker compose -f legacy\docker-compose.yml stop`.
- Entornos locales: `.venv` (fase 6), `contracts\.venv` (Soda), `dbt\.venv` (dbt), todos ignorados.
