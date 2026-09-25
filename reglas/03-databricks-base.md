# 03 — Fase 1: Base en Databricks (Terraform)

- Provider `databricks` apuntando al workspace de Free Edition. Auth por perfil de la CLI,
  nunca hardcodeada.
- Catálogo `entity360` con **`MANAGED LOCATION` en un bucket S3 propio (`us-east-2`)**,
  creado por Terraform (D7, D8 del spike). El bucket y el rol IAM van en `infra/aws/`; la
  storage credential y la external location, en `infra/databricks/`. Sobre default storage
  la API no crea catálogos ni permite acceso externo: no se usa.
- **Flag del metastore `external_access_enabled = true`** (Camino A de la regla 11). Ya está
  activo desde el spike; no lo maneja Terraform: se documenta en `docs/manual-steps.md` con
  su verificación y su reversión. `EXTERNAL_USE_SCHEMA` se otorga solo sobre `gold`.
- Schemas: `landing`, `bronze`, `silver`, `resolution`, `gold`, `ops`.
- Volume `landing.raw`.
- Principal técnico para los productores: **SP con OAuth M2M** (validado en el spike). Lleva
  el entitlement **`workspace_access`** (sin él, la Files API responde 403 aunque los grants
  de UC estén bien) y solo `USE_CATALOG`, `USE_SCHEMA`, `READ_VOLUME` y `WRITE_VOLUME` sobre
  `landing.raw`. Los secretos OAuth se crean fuera de Terraform (no quedan en el state) y
  van a los secret managers.
- Grants por rol: productores, ingeniería, consumo (lectura de `gold`).
- Tags y comentarios en tablas y columnas desde el inicio: son parte de la gobernanza y
  lo que después usa Genie.
- **`force_destroy` solo a propósito y documentado.** En catálogo y schemas sí (aprendizaje
  del proyecto anterior), con `delete_recursive` en directorios. En la external location,
  `force_destroy = true` hace que el provider borre con force y pase por encima de tablas
  retenidas para UNDROP sin avisar: no se pone salvo decisión explícita, anotada en
  `docs/destroy.md`.
- **Idempotencia en tres capas** (D6 del spike):
  1. El productor compara el `sha256` del lote con el del último manifest de su fuente y no
     empuja si no cambió.
  2. Bronze descarta lotes con un `sha256` ya ingerido.
  3. Silver deduplica por clave natural (LEI, CIK, etc.).
- Contrato de landing con `_manifest_<timestamp_utc>.json` por lote (regla 01).
- `ops.ingestion_log`: una fila por lote aterrizado, con el `sha256` del manifest (base de la
  capa 2 de idempotencia).

Límites de la Free Edition: solo serverless, un SQL warehouse chico, pocas tareas de job
concurrentes, cuota diaria de cómputo. Los jobs tienen que tolerar reintentos.
