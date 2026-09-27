# Estado del proyecto

Última actualización: **2026-09-27, 23:55 UTC**. Se actualiza al cerrar cada sesión.

## Dónde estamos
**Fases 6 a 8 cerradas. Sigue la fase 9 (Snowflake): espera el OK de Gastón (abre el trial de 30 días).**

## Hecho
- **Fases 0 a 5** cerradas (spike, base de Databricks, legacy con CDC, SEC EDGAR, GDELT, enriquecimiento).
  - GDELT: el cron de Actions saltea horas (3 corridas en 20 h el 2026-09-27); la ventana pasó a
    24 h para no perder menciones (ADR 0003).
- **Fase 6 (regla 08):**
  - Job `entity360-medallion`: bronze → silver → resolucion, schedule diario 08:45 (Buenos Aires).
    Consumo: 0,6–1,2 DBU por corrida (`databricks/evidencia/pasos1-3-primeras-corridas.txt`).
  - Resolución de identidades (`databricks/medallion/identidades.py`, v2): 1268 registros → 1137
    entidades; 51 casos a revisar y 11 conflictos en `resolution.revision`.
  - Set de validación etiquetado: parte A (59 registros) y parte B (60 pares), en
    `databricks/resolucion/validacion/`. Resolución v2: 1137 entidades.
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
2. ~~Calibración~~ **v2 aplicada al job (2026-09-27).** Las 4 correcciones (GDELT sin país, alias
   genéricos y ≥ 2 tokens, gemelo de LEI y empates a revisión, Wikidata como señal) con los mismos pesos
   (umbral 70). Evaluación: v1 ciega 0,913/0,955; v2 1,000/1,000 (no ciega). Restricciones de integridad
   verificadas y Gold refrescado. **Queda por decidir:** la v2 perdió Cresud (A006) y Banco Galicia
   (A059) en la mitad de calibración; hay dos ajustes propuestos en
   `databricks/resolucion/calibracion/INFORME.md`, sin aplicar.
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
- **Airflow detenido** y **SQL Server del legacy detenido** (`docker compose stop`, volúmenes intactos).
  El DAG queda activo en la base de Airflow: con Airflow prendido corre a las 08:45. Para retomar:
  `docker compose -f legacy\docker-compose.yml start` y `.\airflow\levantar.ps1`.
- El job de Databricks no corre solo (schedule pausado, ADR 0006): sin Airflow no se procesa nada nuevo
  (los productores siguen aterrizando lotes).
- Entornos locales: `.venv` (fase 6), `contracts\.venv` (Soda), `dbt\.venv` (dbt), todos ignorados.
