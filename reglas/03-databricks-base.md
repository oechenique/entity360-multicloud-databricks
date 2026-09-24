# 03 — Fase 1: Base en Databricks (Terraform)

- Provider `databricks` apuntando al workspace de Free Edition. Auth por perfil de la CLI,
  nunca hardcodeada.
- Catálogo `entity360` (con `MANAGED LOCATION` propia si el spike habilitó el Camino A).
- Schemas: `landing`, `bronze`, `silver`, `resolution`, `gold`, `ops`.
- Volume `landing.raw`.
- Principal técnico para los productores (SP con OAuth M2M si el spike lo permitió; si no,
  PAT de alcance mínimo en los secret managers). Solo puede escribir en el volume.
- Grants por rol: productores, ingeniería, consumo (lectura de `gold`).
- Tags y comentarios en tablas y columnas desde el inicio: son parte de la gobernanza y
  lo que después usa Genie.
- `force_destroy = true` en catálogo y schemas, `delete_recursive` en directorios
  (aprendizaje del proyecto anterior).
- `ops.ingestion_log`: una fila por lote aterrizado.

Límites de la Free Edition: solo serverless, un SQL warehouse chico, pocas tareas de job
concurrentes, cuota diaria de cómputo. Los jobs tienen que tolerar reintentos.
