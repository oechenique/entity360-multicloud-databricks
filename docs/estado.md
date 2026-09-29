# Estado del proyecto

Última actualización: **2026-09-29, 19:00 UTC**. Se actualiza al cerrar cada sesión.

## Dónde estamos
**Fases 6 a 8 cerradas; resolución v2.1 aplicada. Fase 10: consumo y observabilidad hechos (adelantada a pedido de Gastón). Aligerar Airflow a medias: falta la corrida 24/24 medida, bloqueada por la cuota diaria de Free Edition. La fase 9 (Snowflake) espera su OK (abre el trial de 30 días).**

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
  del CDC (la primera corrida falló la 4). Detalle: `databricks/consumo/README.md`.
- **Cierre del repo (2026-09-29):** `README.md` completo (problema, historia, diagrama Mermaid, porqué de
  cada pieza, métricas v1 y v2.1 con IC, errores conocidos, limitaciones de Free Edition, cómo
  levantarlo); ADR 0009 (push al landing), 0010 (resolución por reglas), 0011 (Silver incremental) y la
  actualización del 0007; `docs/destroy.md` con el orden completo, Snowflake, limpieza local y
  verificación final. Falta del cierre: capturas y video, y **ejecutar** el destroy (solo con OK).
- **Aligerar Airflow (parcial, 2026-09-29):** stack liviano en `airflow/docker-compose.yml` (4 tareas a
  la vez, parseo cada 5 min, techo de CPU y memoria por container, sin triggerer porque no hay tareas
  diferibles) y `.wslconfig` aplicado (6 procesadores, 5,8 GB, 2 GB de swap). En reposo: 7,6 % de CPU y
  2,1 GB contra 10,1 % y 2,4 GB (`airflow/evidencia/consumo.md`). dbt deja Gold a nombre del SP del
  orquestador (`dbt/macros/duenio_gold.sql`, variable `E360_GOLD_OWNER`) y el DAG tiene la tarea final
  `resultado`: una corrida con dbt caído ya no figura `success` (24 tareas).
- **Silver incremental (código, 2026-09-29):** cada fuente procesa solo los lotes de Bronze que Silver no
  procesó (`silver._lotes_procesados`); capa 3 por MERGE si el registro nuevo no es más viejo; tablas de
  nombres reemplazadas por padre; SCD2 sin cambios. Tests de equivalencia con el recálculo completo en
  `tests/medallion/test_incremental.py`. **Sin desplegar:** la validación en el workspace está en
  `databricks/evidencia/silver-incremental-validacion.md`.
- Tests: 3 en `tests/airflow`, 120 en `tests/medallion`, 38 en `tests/gcp_gdelt`, 19 en `tests/contracts` (entorno
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
5. **Aligerar Airflow, lo que falta (cuando vuelva el warehouse):**
   1. **Devolver Gold al SP** (OK de Gastón ya dado): dos `dbt build` locales del 2026-09-29 dejaron las
      5 tablas a nombre del usuario y la corrida del DAG de ese día falló en dbt con `PERMISSION_DENIED`.
      ``ALTER TABLE entity360.gold.<tabla> OWNER TO `<application_id del SP>` `` en `dim_entity`,
      `bridge_entity_source`, `fct_news_signal`, `fct_risk_flags`, `fct_entity_changes`.
   2. Reactivar el DAG (`airflow dags unpause entity360_convergencia`), correrlo y medirlo:
      `python airflow\medir.py --minutos 90 --run-id <run_id> --salida airflow\evidencia\corrida-liviano.csv`.
      Esperado: 24/24.
   3. Techo de 2 GB al SQL Server del legacy (`legacy/docker-compose.yml`) si aprieta la memoria durante
      la corrida. En reposo usa 1,25 GB.
   4. Informe de consumo final en `airflow/evidencia/consumo.md`.
6. **Silver incremental:** desplegar y validar con las huellas de
   `databricks/evidencia/silver-incremental-validacion.md` (pasos 1 a 5), cuando vuelva la cuota.
7. **Canal de alertas:** crear el bot de Telegram (`docs/manual-steps.md` §10). Sin él, las alertas van
   a stderr.

## Restricciones del proyecto
- **Cuota diaria de cómputo serverless de Free Edition.** Cuando se agota, el SQL warehouse no arranca
  (`Cannot create the resource, please try again later`) y no corren ni dbt, ni el dashboard, ni Genie, ni
  el job. Pasó el 2026-09-29 ~17:10 UTC, después de un día con varias corridas de la resolución,
  `dbt build`, validación del dashboard, pruebas de Genie y una corrida del DAG. Plan: agrupar el trabajo
  que usa el warehouse, no validar consulta por consulta si alcanza con una pasada, y dejar la corrida
  diaria del DAG como el consumo principal. Silver incremental (reprocesa todo aunque Bronze no traiga
  nada) es la primera optimización.

## Estado del entorno al cerrar
- `dbt source freshness` (2026-09-29 15:32 UTC): GDELT (43 h) y OpenSanctions (49 h) en warn. No es un
  productor caído: Airflow está apagado desde el 27, Bronze no corrió y `ops.ingestion_log` no registró
  los lotes nuevos del landing.
- `main` = `origin/main`.
- **Airflow detenido** (`docker compose -p entity360-airflow stop`) y **SQL Server del legacy
  detenido** (`docker compose -f legacy\docker-compose.yml stop`), con los volúmenes intactos.
  **El DAG queda pausado** (2026-09-29): con Gold a nombre del usuario, la corrida de las 08:45 fallaría.
  Para retomar: `docker compose -f legacy\docker-compose.yml start`, `.\airflow\levantar.ps1` y, después
  de devolver Gold al SP, `airflow dags unpause entity360_convergencia`.
- El warehouse no arrancaba al cerrar (cuota diaria de Free Edition).
- El job de Databricks no corre solo (schedule pausado, ADR 0006): sin Airflow no se procesa nada nuevo
  (los productores siguen aterrizando lotes).
- Entornos locales: `.venv` (fase 6), `contracts\.venv` (Soda), `dbt\.venv` (dbt), todos ignorados.
