# Estado del proyecto

Última actualización: **2026-09-29, 20:40 UTC**. Se actualiza al cerrar cada sesión.

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
- **Fase 9 preparada, nada creado (2026-09-29):** `docs/fase9-plan.md` (validación del vending con el SP
  primero, Terraform de Snowflake, grants de Databricks, target y marts de dbt, Caminos A2 y B con el
  criterio para pasar de uno a otro, consumo estimado ~13–15 créditos al mes). Terraform escrito y
  validado en `infra/snowflake`, `infra/databricks/snowflake.tf` e `infra/aws/snowflake_a2.tf` (los dos
  últimos apagados por variable: el `plan` de Databricks no suma nada de la fase). Marts en
  `dbt/models/marts` (solo target snowflake; Gold y el DAG no cambian). Sin trial y sin `apply`.
  La catalog integration y la base catalog-linked van por `snowflake/integracion.py` (secreto del
  llavero, nunca en un state; ADR 0012), con 13 tests con mocks en `tests/snowflake`.
- **Fase 9, paso 1: vending validado con el SP (2026-09-29).** SP `entity360-snowflake` y sus grants
  creados (`apply` con `-target`, camino A: `USE_CATALOG`; `USE_SCHEMA`, `SELECT` y `EXTERNAL_USE_SCHEMA`
  en gold); `fase9_snowflake = true` en `terraform.tfvars` para que un `plan` normal no lo destruya.
  Secreto en el llavero (`entity360-snowflake`, vence 2026-12-28 18:41 UTC). `validar_vending.py` 5/5:
  token del SP, `config`, credenciales S3 temporales en `loadTable` de `gold.dim_entity`, scan de 1136
  filas (igual que la última resolución) y 403 en `silver.sec_emisor`. **Camino A.** Evidencia:
  `snowflake/evidencia/vending-sp.txt`. El trial sigue sin abrir (espera OK).
- **Fase 9, preparación del trial (2026-09-29):** Gastón abre el trial (Enterprise, AWS us-east-2).
  `snowflake/cuenta.py claves` ya generó los key pairs de `ENTITY360_TF` y `ENTITY360_DBT_SVC` en
  `~/.snowflake/keys` (fuera del repo, acceso solo del usuario de Windows); la clave pública de dbt está
  en `infra/snowflake/terraform.tfvars` (ignorado). Orden exacto en `manual-steps.md` §14–15: Gastón corre
  un solo SQL en Snowsight (usuario `ENTITY360_TF` con la clave pública); después, con OK en cada paso,
  `cuenta.py conexiones`, `terraform plan`/`apply` de `infra/snowflake`, `integracion.py crear --camino A`
  y dbt de los marts.
- **Trial de Snowflake abierto el 2026-09-29** (Enterprise, AWS us-east-2; vence a los 30 días o al
  agotar el crédito). Account identifier solo en archivos locales (`~/.snowflake/`), `<ORG>-<CUENTA>` en el
  repo. `ENTITY360_TF` creado por Gastón en Snowsight (servicio, sin contraseña, key pair; fingerprint
  verificado contra la clave local). Conexión probada: `ENTITY360_TF`, `ACCOUNTADMIN`, `AWS_US_EAST_2`.
  Usuario de servicio con ACCOUNTADMIN solo durante el proyecto (ADR 0013).
  - **Otro trial, abierto por error en sa-east-1** (otra organización, sin tarjeta): no se usa y no se
    toca; vence solo. Sin recursos del proyecto.
- **`infra/snowflake` aplicado (2026-09-29, con OK):** 18 recursos (`ENTITY360_MONITOR` 20 créditos,
  `ENTITY360_WH` XSMALL suspendido, roles, `ENTITY360_MARTS.MARTS`, `ENTITY360_DBT_SVC`). Pendientes de OK:
  un segundo plan de 3 recursos (monitor de cuenta `ENTITY360_CUENTA` de 25 créditos asignado con
  `ALTER ACCOUNT`, y `COMPUTE_WH` con `AUTO_SUSPEND = 60`) y `integracion.py crear --camino A` (simulado
  con `--simular`). Medición diaria de lo que no frenan los monitores (serverless, catalog-linked) en
  `snowflake/evidencia/consumo.md`.
- **Monitor de cuenta y `COMPUTE_WH` aplicados** (3 recursos): `ENTITY360_CUENTA` a nivel `ACCOUNT` (25
  créditos), `COMPUTE_WH` con `AUTO_SUSPEND = 60`.
- **Catalog integration y base catalog-linked creadas (2026-09-29, Camino A):** `integracion.py crear`
  (segunda corrida: sin cambios), `SYSTEM$VERIFY_CATALOG_INTEGRATION` OK, solo `gold` con sus 5 tablas y
  conteos iguales a Gold (1136 / 1268 / 52 / 10 / 4036) leyendo con `ENTITY360_DBT` en `ENTITY360_WH`.
  Refresh y descubrimiento cada 3600 s; `SYNC_INTERVAL_SECONDS` se cambia con `ALTER` sin recrear.
  Evidencia: `snowflake/evidencia/catalog-linked.txt`.
- **Solo lectura probado:** `CREATE ICEBERG TABLE` en la base falla con `ENTITY360_DBT` y con
  ACCOUNTADMIN (`allowed write operations: 'NONE'`); no se creó nada.
- **Marts de dbt en Snowflake (2026-09-29):** `dbt build --target snowflake --select marts` 13/13 (3
  modelos: `mart_empresa` 1136, `mart_noticias_diarias` 10, `mart_riesgo` 52; 9 tests) en 15,6 s, con
  `ENTITY360_DBT_SVC`. Antes, dos arreglos: grants reaplicados (los de después del `CREATE` solo cubrieron
  la tabla ya descubierta y los `FUTURE` no se aplicaron) y `::array` en `mart_riesgo`. Corrección: los
  conteos del paso 3 "con `ENTITY360_DBT`" no probaban los grants (roles secundarios); repetidos sin
  roles secundarios, iguales. Créditos: 0,036 en la hora de dbt; monitores en 0,07 de 20 y de 25.
  `ENTITY360_WH` y `COMPUTE_WH` suspendidos. Evidencia: `snowflake/evidencia/marts-dbt.txt`.
  **A verificar tras la próxima corrida del DAG:** si los grants sobreviven al `CREATE OR REPLACE` de Gold.
  - **Incidente:** la primera corrida imprimió el token OAuth del SP (1 h de vida, solo lectura de gold):
    el paso 1 devolvía el token y `Pasos` imprimía el resultado. Corregido (el paso devuelve una
    descripción y `Pasos` oculta el secreto y el token en todo lo que imprime), con 5 tests que fallan
    con la versión vieja. **El token vence a las 19:41 UTC del 2026-09-29** (una hora
    después de emitido). **No se rota el secreto del SP:** rotarlo no invalida un token ya emitido, que
    vive hasta su `exp`; solo cortaría tokens nuevos, y no hay indicio de que el secreto se haya
    expuesto. Verificado (`git log -p --all`, 68 commits, y el working tree): el token nunca entró a un
    commit. Fuera del repo quedó en el transcript local de la sesión de Claude Code; los archivos de
    salida del scratchpad, borrados.
- Tests: 3 en `tests/airflow`, 120 en `tests/medallion`, 25 en `tests/snowflake`, 38 en `tests/gcp_gdelt`, 19 en `tests/contracts` (entorno
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
