# Estado del proyecto

Última actualización: **2026-09-29, 15:45 UTC**. Se actualiza al cerrar cada sesión.

## Dónde estamos
**Fases 6 a 8 cerradas; resolución v2.1 aplicada. Fase 10: consumo y observabilidad hechos (adelantada a pedido de Gastón); sigue aligerar Airflow. La fase 9 (Snowflake) espera su OK (abre el trial de 30 días).**

## Hecho
- **Fases 0 a 5** cerradas (spike, base de Databricks, legacy con CDC, SEC EDGAR, GDELT, enriquecimiento).
  - GDELT: el cron de Actions saltea horas (3 corridas en 20 h el 2026-09-27); la ventana pasó a
    24 h para no perder menciones (ADR 0003).
- **Fase 6 (regla 08):**
  - Job `entity360-medallion`: bronze → silver → resolucion, schedule diario 08:45 (Buenos Aires).
    Consumo: 0,6–1,2 DBU por corrida (`databricks/evidencia/pasos1-3-primeras-corridas.txt`).
  - Resolución de identidades (`databricks/medallion/identidades.py`, v2.1): 1268 registros → 1136
    entidades; 20 casos a revisar, 11 conflictos y 8 empates en `resolution.revision`. Integridad:
    `databricks/resolucion/integridad.py` (7 chequeos).
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
- **Fase 10 (regla 12), consumo y observabilidad:** dashboard AI/BI "Entity 360" (3 páginas: empresa,
  panorama, salud de la plataforma) por Terraform; espacio de Genie "Entity 360" por
  `databricks/consumo/genie.py`; resultados de dbt en `ops.dbt_resultado` (hook) y precisión/recall en
  `ops.calidad_resolucion` (ADR 0008). 5 preguntas reales probadas: 5/5 correctas tras documentar el JSON
  del CDC (la primera corrida falló la 4). Detalle: `databricks/consumo/README.md`. Falta del cierre:
  README completo, capturas y video, destroy probado.
- Tests: 3 en `tests/airflow`, 114 en `tests/medallion`, 38 en `tests/gcp_gdelt`, 19 en `tests/contracts` (entorno
  `contracts\.venv`).

## Pendiente
1. ~~Etiquetar la parte B~~ **hecho** (60 pares, 2026-09-27).
2. ~~Calibración~~ **v2 aplicada al job (2026-09-27).** Las 4 correcciones (GDELT sin país, alias
   genéricos y ≥ 2 tokens, gemelo de LEI y empates a revisión, Wikidata como señal) con los mismos pesos
   (umbral 70). Evaluación: v1 ciega 0,913/0,955; v2 1,000/1,000 (no ciega). Restricciones de integridad
   verificadas y Gold refrescado. **v2.1 aplicada (2026-09-29):** token único raro por idf (≥ 5,7) y
   país heredado en GDELT por CIK/LEI. Recupera Cresud (A006); Banco Galicia (A059) queda en revisión
   por decisión (sin identificador no hereda país): error conocido en el `README.md`. Set completo
   45/0/1 (P 1,000, R 0,978), no ciega.
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
- `dbt source freshness` (2026-09-29 15:32 UTC): GDELT (43 h) y OpenSanctions (49 h) en warn. No es un
  productor caído: Airflow está apagado desde el 27, Bronze no corrió y `ops.ingestion_log` no registró
  los lotes nuevos del landing.
- `main` = `origin/main`.
- **Airflow detenido** (`docker compose -p entity360-airflow stop`) y **SQL Server del legacy
  detenido** (`docker compose -f legacy\docker-compose.yml stop`), con los volúmenes intactos.
  El DAG queda activo en la base de Airflow: con Airflow prendido corre a las 08:45. Para retomar:
  `docker compose -f legacy\docker-compose.yml start` y `.\airflow\levantar.ps1`.
- El job de Databricks no corre solo (schedule pausado, ADR 0006): sin Airflow no se procesa nada nuevo
  (los productores siguen aterrizando lotes).
- Entornos locales: `.venv` (fase 6), `contracts\.venv` (Soda), `dbt\.venv` (dbt), todos ignorados.
