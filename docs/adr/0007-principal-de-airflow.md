# ADR 0007 — Airflow usa su propio service principal (`entity360-orquestador`)

- **Estado:** aceptado (fase 8, 2026-09-27).
- **Relacionado:** regla 10 (Airflow local; conexiones y secretos en variables de entorno), ADR 0001
  (grants por rol), ADR 0002 (un SP por productor), ADR 0006 (el job lo dispara Airflow).

## Contexto
Airflow corre local, en Docker (regla 10), y necesita hablar con Databricks para:
verificar lotes (leer el landing y escribir los veredictos de los contratos), disparar el job
`entity360-medallion` y correr dbt (leer Silver, la resolución y `ops`; escribir Gold).

La identidad del usuario no sirve adentro de un container: el perfil de la CLI
(`auth_type = databricks-cli`) guarda sus tokens OAuth en el llavero de Windows, que un container Linux
no ve. La alternativa, un token personal (PAT), es una clave estática de la identidad dueña de todo el
catálogo (principio 4).

## Decisión
- **SP `entity360-orquestador`** (Terraform, `infra/databricks/orquestador.tf`), con OAuth M2M y
  entitlements `workspace_access` y `databricks_sql_access`. Grants mínimos:

  | Objeto | Privilegios | Para qué |
  |---|---|---|
  | catálogo `entity360` | `USE_CATALOG` | |
  | `landing`, volume `raw` | `USE_SCHEMA`; `READ_VOLUME`, `WRITE_VOLUME` | contratos: leer lotes, escribir veredictos |
  | `silver`, `resolution`, `ops` | `USE_SCHEMA`, `SELECT` | fuentes de dbt y frescura |
  | `gold` | `USE_SCHEMA`, `SELECT`, `MODIFY`, `CREATE_TABLE` | dbt escribe Gold |
  | job `entity360-medallion` | `CAN_MANAGE_RUN` | disparar el job y seguirlo |

  No lee `bronze` (verificado: `INSUFFICIENT_PERMISSIONS`). El job corre con la identidad de su dueño,
  no con la del SP.
- **El SP es dueño de las tablas de Gold**: dbt las recrea con `CREATE OR REPLACE TABLE`, que exige ser
  dueño. Las cinco que había creado el usuario en la fase 7 se pasaron al SP con `ALTER TABLE ... OWNER
  TO` (reversible). El usuario sigue controlando todo como dueño del catálogo.
- **Secretos:** el secreto OAuth del SP (90 días) vive en el llavero de Windows (`airflow/credenciales.py`,
  servicio `entity360-airflow`), igual que el del extractor CDC. `airflow/levantar.ps1` los lee y se los
  pasa a `docker compose` como variables de entorno del proceso (regla 10). No se escriben en ningún
  archivo del repo.
- El extractor CDC sigue con **su** SP (ADR 0002): dentro de Airflow recibe sus credenciales como
  `CDC_*` en vez de leerlas del llavero.

## Consecuencias
- Airflow no puede hacer nada fuera de su rol: ni leer Bronze, ni tocar el volume de checkpoints, ni
  cambiar el job.
- Las variables de entorno quedan en la configuración de los containers (visible con `docker inspect`
  en la PC). Es el costo de la regla 10 ("conexiones y secretos en variables de entorno") en una PC
  personal; el secreto vence a los 90 días y se rota con `credenciales.py configurar`.
- Rotar el secreto implica volver a levantar Airflow (`levantar.ps1`).
- **En un workspace pago:** el mismo SP, con los grants a través de un grupo de cuenta
  `entity360-orquestacion`, y el secreto en el secret manager de la nube donde corra Airflow
  (por ejemplo, MWAA con AWS Secrets Manager).
