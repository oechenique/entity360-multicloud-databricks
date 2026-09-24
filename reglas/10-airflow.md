# 10 — Fase 8: Airflow como plano de control

- Airflow local con Docker (última versión estable; verificar compatibilidad de
  providers).
- DAG principal de convergencia:
  1. Disparar el extractor de CDC del legacy.
  2. Sensores por fuente sobre los manifests del volume, con timeout y política de
     "fuente atrasada".
  3. Checks de Soda Core por lote.
  4. Job de Databricks (Bronze → Silver → resolución).
  5. dbt con Astronomer Cosmos (un task por modelo, lineage visible en la UI).
  6. Sincronización con Snowflake según el camino elegido.
  7. Checks finales y alertas.
- Conexiones y secretos en connections/variables de entorno, nunca en los DAGs.
- Documentado: Airflow corre local por decisión de costo.
