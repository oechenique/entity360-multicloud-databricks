# ADR 0005 — Gold en Iceberg gestionado: qué hace cumplir el contrato y qué queda en tests

- **Estado:** aceptado (fase 7, 2026-09-27).
- **Relacionado:** regla 09 (contratos enforced en Gold), regla 11 (Camino A de Snowflake), ADR 0004.

## Contexto
La regla 09 pide `contract: enforced: true` en todos los modelos Gold. La regla 11 (Camino A) lee Gold
desde Snowflake por el endpoint Iceberg REST de Unity Catalog, y lo que validó el spike (3b, 4e) fueron
**tablas Iceberg gestionadas**, igual que Silver y la resolución.

Lo verificado el 2026-09-27 con dbt-databricks 1.12.5 y el SQL warehouse serverless:

| Qué | Resultado |
|---|---|
| `table_format: iceberg` sin flag | Crea **Delta con UniForm** (`delta.universalFormat.enabledFormats = iceberg`), no Iceberg gestionado |
| Flag `use_managed_iceberg: true` | Crea `USING ICEBERG` (Iceberg gestionado) |
| Restricciones del contrato con Iceberg | dbt no las aplica: "Constraints not supported for file format: parquet" |
| Comentarios de columna con Iceberg | dbt no los aplica: "file format parquet does not support that" |
| `ALTER COLUMN ... SET NOT NULL` a mano | Funciona, y un `INSERT` con nulo falla (`DELTA_NOT_NULL_CONSTRAINT_VIOLATED`) |
| `ADD CONSTRAINT ... PRIMARY KEY` | "Managed Iceberg tables don't support PRIMARY KEY constraint" |
| `ADD CONSTRAINT ... CHECK` | "IcebergWriterCompatV1 is incompatible with feature checkConstraints" |

## Decisión
**Gold en Iceberg gestionado** (`use_managed_iceberg: true`), con el contrato repartido así:

- **dbt:** nombres y tipos de cada columna, antes de crear la tabla (el contrato enforced).
- **El motor:** NOT NULL, que aplica el post-hook `aplicar_contrato_iceberg` y hace cumplir Iceberg.
  El mismo post-hook pone los comentarios de columna (los usa Genie).
- **Tests de dbt:** unicidad (`unique`, `combinacion_unica`), relaciones y rangos (`rango`), que en
  Delta serían PRIMARY KEY (informativa) y CHECK.

## Alternativa descartada: Delta con UniForm
Admite PRIMARY KEY (informativa) y CHECK, y se lee como Iceberg. Se descarta porque el Camino A se
validó con Iceberg gestionado, y porque cambiar de formato solo en Gold deja dos caminos de lectura
para Snowflake. La unicidad como test da la misma garantía que una PRIMARY KEY informativa, que
Databricks tampoco hace cumplir.

## Consecuencias
- Un duplicado o un valor fuera de rango **no frena la escritura**: lo detecta el test y falla el
  `dbt build`, y Airflow (fase 8) no sigue a Snowflake.
- El post-hook es código propio: si una versión de dbt-databricks empieza a aplicar restricciones o
  comentarios sobre Iceberg, se borra.
- **Cómo migrar:** con Delta + UniForm alcanza con sacar el flag y el post-hook; los tests quedan.
