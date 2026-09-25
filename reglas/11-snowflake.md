# 11 — Fase 9: Snowflake para los modelers

**Recién acá se abre el trial de Snowflake** (30 días o el saldo de crédito, lo que ocurra
primero; al vencer se suspende). Anotar la fecha de alta en `docs/manual-steps.md`.

## Camino A — Zero-copy con Iceberg REST (solo si el spike lo validó)
- **Primer paso de la fase, antes de abrir el trial:** validar el credential vending con
  el **service principal** (OAuth M2M) que va a usar Snowflake. El spike lo probó con el
  token del usuario (4e). Con PyIceberg y credenciales locales de AWS ocultas: `loadTable`
  devuelve credenciales S3 temporales y el scan de una tabla de `gold` funciona. El SP
  necesita `USE_CATALOG`, `USE_SCHEMA`, `SELECT` y `EXTERNAL_USE_SCHEMA` sobre `gold`.
  Si falla, Camino B sin abrir el trial para el Camino A.
- Catalog integration `ICEBERG_REST` contra el endpoint de Unity Catalog, con
  `VENDED_CREDENTIALS` y OAuth del service principal.
- Snowflake lee las tablas Gold; Databricks sigue siendo el dueño de la escritura.

## Camino B — Sync explícito
- Tarea de Airflow que extrae Gold por el SQL warehouse de Databricks y carga en Snowflake
  (stage interno + `COPY INTO`), incremental.
- ADR explicando por qué no fue zero-copy.

## En ambos
- Warehouse `X-SMALL` con `AUTO_SUSPEND = 60` y resource monitor.
- dbt target `snowflake` con marts para los modelers.
- Terraform en `infra/snowflake/`.
