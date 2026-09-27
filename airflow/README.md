# Airflow: el plano de control (regla 10)

Airflow 3.3 local en Docker, **por decisión de costo**: orquesta lo que vive fuera de Databricks. Si
todo estuviera adentro, alcanzarían los Jobs de Databricks; acá hay un SQL Server en la PC, contratos
de llegada y dbt.

## DAG `entity360_convergencia` (todos los días, 08:45 Buenos Aires)

```text
extraer_cdc ─► llegada_sqlserver_cdc ─┐
               llegada_sec_edgar     ─┤
               llegada_gdelt         ─┼─► contratos ─► medallion ─► dbt_gold (Cosmos) ─► frescura
               llegada_opensanctions ─┤
               llegada_wikidata      ─┘
```

| Tarea | Qué hace |
|---|---|
| `extraer_cdc` | Extractor CDC del legacy (`producers/cdc_extractor`): cambios del SQL Server al landing. Usa su propio SP (ADR 0002) y el mismo checkpoint que cuando corre a mano. |
| `llegada_<fuente>` | Sensor sobre los manifests del landing. Pasa si el último lote es más nuevo que el `warn_after` de la frescura de esa fuente en dbt (`dbt/models/sources.yml`). Si no, reintenta cada 5 min; a los 30 min la fuente queda **atrasada** (`skipped`), se alerta y el DAG sigue. |
| `contratos` | Soda Core sobre los lotes sin veredicto (`contracts/verificar.py --pendientes`). Un lote en cuarentena se alerta y queda afuera; no frena el DAG. |
| `medallion` | Dispara el job `entity360-medallion` (bronze → silver → resolucion) y espera. Bronze exige el veredicto de cada lote (ADR 0006): por eso el job ya no tiene schedule propio. |
| `dbt_gold` | Cosmos: un task por modelo Gold y sus tests después de cada uno (lineage en la UI). |
| `frescura` | `dbt source freshness`. Un `error` falla la tarea y alerta. |

Cualquier tarea que falla alerta por Telegram (`contracts/alertas.py`; sin bot, a stderr y al log). La
sincronización con Snowflake se suma en la fase 9.

## Identidad y secretos (ADR 0007)

Airflow usa el SP `entity360-orquestador` (OAuth M2M, grants mínimos) y el extractor CDC el suyo. Los
secretos viven en el llavero de Windows; `levantar.ps1` los pasa a `docker compose` como variables de
entorno. Nada en los DAGs ni en archivos del repo. `config/profiles.yml` es el perfil de dbt dentro del
container: sin secretos, todo por variables de entorno.

## Levantar

Requisitos: Docker Desktop, el legacy creado alguna vez (su red `entity360-legacy_default`) y las
credenciales en el llavero (`docs/manual-steps.md` §12).

```powershell
docker compose -f legacy\docker-compose.yml start     # el SQL Server que lee el extractor CDC
.\airflow\levantar.ps1                                  # build + up -d; UI en http://localhost:8080
docker compose -p entity360-airflow stop       # detener (conserva la base de Airflow)
```

La UI escucha solo en `localhost` y todos los usuarios son admin (uso local).

Para detener o bajar se usa el **nombre del proyecto** (`-p entity360-airflow`), no el archivo: el
compose exige las credenciales (`${...:?}`) hasta para interpolar un `stop`, y fuera de `levantar.ps1`
no están en el entorno.

**Con la PC apagada no se procesa nada nuevo** (ADR 0006): los productores siguen aterrizando lotes y
la primera corrida de Airflow los toma todos. No se pierde nada.
