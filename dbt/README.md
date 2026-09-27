# dbt: Gold con contratos enforced (regla 09)

Cinco modelos en `entity360.gold`, tablas **Iceberg gestionadas** (las lee Snowflake en la fase 9):

| Modelo | Grano | Sale de |
|---|---|---|
| `dim_entity` | una fila por empresa (golden record) | `resolution.golden_record` |
| `bridge_entity_source` | un registro de una fuente | `resolution.entidad_registro` + `registro` |
| `fct_news_signal` | entidad y día | `silver.gdelt_mencion` |
| `fct_risk_flags` | entidad y registro de OpenSanctions | `silver.opensanctions_entidad` |
| `fct_entity_changes` | versión de una fila del legacy (CDC) | `silver.gleif_*_hist` |

## Contratos en Iceberg gestionado (ADR 0005)

- `contract: enforced: true` en todo Gold: dbt compara nombres y tipos de cada columna con el YAML
  antes de crear la tabla, y falla si no coinciden.
- **NOT NULL:** dbt-databricks 1.12 no aplica restricciones sobre Iceberg (lo trata como parquet), pero
  Iceberg gestionado sí las admite. El post-hook `aplicar_contrato_iceberg` las aplica y el motor las
  hace cumplir. También pone las descripciones como comentarios de columna, que usa Genie.
- **PRIMARY KEY y CHECK** no existen en Iceberg gestionado: la unicidad (`unique`,
  `combinacion_unica`) y los rangos (`rango`) son tests de dbt.

## Tests y frescura

- 19 tests: unicidad, relaciones con `dim_entity`, valores aceptados y rangos.
- `dbt source freshness`: el último lote de cada productor (`ops.ingestion_log`), con umbrales según su
  cadencia real, y la última corrida de la resolución.

## Correr

```powershell
python -m venv dbt\.venv
dbt\.venv\Scripts\python.exe -m pip install -r dbt\requirements.txt
copy dbt\profiles.yml.example dbt\profiles.yml     # ignorado por git; lee todo de variables de entorno
$env:DATABRICKS_HOST = "<WORKSPACE_URL>"            # sin https://
$env:DATABRICKS_HTTP_PATH = "/sql/1.0/warehouses/<WAREHOUSE_ID>"
$env:DATABRICKS_TOKEN = (databricks auth token -p entity360-free | ConvertFrom-Json).access_token   # OAuth, 1 h
cd dbt
$env:DBT_PROFILES_DIR = "."
..\dbt\.venv\Scripts\dbt build               # modelos + tests
..\dbt\.venv\Scripts\dbt source freshness
..\dbt\.venv\Scripts\dbt docs generate; ..\dbt\.venv\Scripts\dbt docs serve   # documentación y lineage
```

Primera corrida (2026-09-27): `dbt build` 24/24 (5 modelos, 19 tests) y frescura 7/7 en verde.
