# ADR 0008 — Consumo y observabilidad: dashboard por Terraform, Genie por script, salud en `ops`

- **Estado:** aceptado (fase 10, 2026-09-29).
- **Relacionado:** regla 12, principio 3 (Terraform desde el día 1), ADR 0005 (Gold en Iceberg con
  contratos), ADR 0007 (principal de Airflow).

## Contexto
La fase 10 entrega un dashboard AI/BI "Entity 360" sobre Gold con un panel de salud de la plataforma, y
un espacio de Genie. Tres cosas no tenían dónde vivir:
- El provider de Databricks (v1.134) tiene `databricks_dashboard`, pero **no tiene recurso para Genie**.
- Los resultados de dbt solo quedaban en `target/` de la máquina que corrió (la PC o el container de
  Airflow).
- Precisión y recall de la resolución estaban en JSON del repo, no en el lakehouse.

## Decisión
- **Dashboard en Terraform** (`infra/databricks/consumo.tf`), desde un JSON generado por
  `databricks/consumo/generar_dashboard.py` y versionado. Publicado con las credenciales del dueño.
- **Genie con un script idempotente** (`databricks/consumo/genie.py`): crea o actualiza el espacio por
  título desde `genie/espacio.json`, con ids deterministas. Las descripciones de columnas salen de
  `gold.yml`: una sola fuente para Unity Catalog y Genie. El destroy lo manda a la papelera a mano
  (`docs/destroy.md`).
- **`ops.dbt_resultado`** (Delta, Terraform): un hook `on-run-end` inserta una fila por nodo de cada
  invocación. Un hook y no un seed ni un modelo: **no agrega tareas al DAG** de Cosmos. El SP del
  orquestador tiene `MODIFY` solo sobre esa tabla. Si la tabla no está, el hook avisa y no falla.
- **`ops.calidad_resolucion`** (Delta, Terraform): `calibrar.py --publicar` carga los
  `resultados_<version>.json`, sin recalibrar.

## Consecuencias
- `dbt build` informa un nodo más (el hook): 25 en vez de 24.
- La frescura del dashboard es la de la última `dbt source freshness` (misma fuente de verdad que los
  umbrales de `sources.yml`); las horas desde el último lote se calculan en vivo.
- Si algún día el provider suma Genie, el script se reemplaza por un recurso con `serialized_space`
  desde el mismo JSON.
