# Informe del spike (Fase 0)

Estado: **en curso** (parte A).

## Resultados
| # | Pregunta | Resultado | Evidencia | Impacto en el diseño |
|---|---|---|---|---|
| 1a | Push a UC Volume desde afuera con PAT + lectura con Spark | ✅ | `evidencia/a1-push-pat.txt`, `evidencia/a1-read-spark.txt` | El modelo push de la regla 01 funciona tal cual. |
| 1a' | Crear el catálogo con Terraform sobre default storage | ❌ | `evidencia/a1-catalogo-default-storage.txt` | Catálogo por SQL + `terraform import`; paso manual en `docs/manual-steps.md`. |
| 1b | Push con service principal (OAuth M2M) | ✅ | `evidencia/a1-push-oauth-m2m.txt`, `evidencia/a1-push-oauth-m2m-403.txt` | Los productores usan SP + OAuth M2M, sin PAT. El SP necesita `workspace_access` además de los grants de UC (sin eso, 403). |
| 1c | ¿Reenviar el mismo lote duplica datos? | ⚠️ sí | `evidencia/a1-read-spark-2-lotes.txt` (20 filas, 10 LEI) | Principio 6: la idempotencia no la da el landing. Tres capas (D6): el productor no empuja si no hubo cambios, Bronze deduplica por `sha256` y Silver por clave natural. |
| 3a | Tabla `USING ICEBERG` gestionada en Free Edition | ✅ | `evidencia/a3-tabla-iceberg.txt` (MANAGED, ICEBERG, 10 filas) | Se puede crear y consultar Iceberg gestionado desde Databricks. |
| 3b | Metadata por Iceberg REST (config, loadTable, schema, snapshot) con PyIceberg | ✅ | `evidencia/a3-iceberg-rest.txt` pasos 1–3 | El catálogo REST responde y expone la tabla. |
| 3c | Credential vending sobre default storage | ❌ (confirmado) | `evidencia/a3-iceberg-rest.txt` paso 2: `config` vacío, 0 `storage-credentials`; `evidencia/a3-external-use-schema.txt`: `EXTERNAL USE SCHEMA` no aplica a `SCHEMA_DB_STORAGE` | Sin credenciales, ningún motor externo (Snowflake incluido) puede leer datos del default storage. |
| 3d | Lectura y escritura de datos con PyIceberg | ❌ | `evidencia/a3-iceberg-rest.txt` pasos 4–5: `HeadObject` 400 en `dbstorage-prod-…` | Consecuencia de 3c. Iceberg externo depende del punto 4 (S3 propio). |
| 4 | Salir del default storage (S3 propio) | ⏳ | | |
| 5 | Salida a internet de Free Edition | ⏳ | | |
| 6 | Dashboard AI/BI y Genie | ⏳ | | |
| 7–11 | Parte B | ⏳ | | GDELT (10) pendiente: no existe proyecto GCP. |

## Decisiones
| ID | Decisión | Motivo |
|---|---|---|
| D1 | El catálogo `entity360` se crea por SQL y se importa a Terraform (paso manual documentado). | La API de UC no acepta default storage en Free Edition. |
| D2 | Manifest por lote como `_manifest_<timestamp_utc>.json` (regla 01 actualizada). | Con un `_manifest.json` fijo, dos lotes del mismo día en la misma partición se pisan. |
| D3 | Los archivos de datos se suben en JSON Lines (`.jsonl`) cuando la fuente es JSON. | `read_files` los lee directo, un registro por fila. |
| D4 | Productores autenticados con service principal + OAuth M2M; secreto en el secret manager de cada nube. PAT solo para pruebas manuales. | Sin claves estáticas de usuario (principio 4); el token M2M dura 1 h. |
| D5 | El SP productor lleva `workspace_access` y solo `USE_CATALOG`/`USE_SCHEMA`/`READ_VOLUME`/`WRITE_VOLUME` sobre landing. | Mínimo privilegio; el entitlement es obligatorio para la Files API. |
| D6 | Idempotencia en tres capas: (1) cada productor compara el `sha256` del lote con el del último manifest de su fuente y no empuja si no cambió; (2) Bronze descarta lotes con `sha256` ya ingerido; (3) Silver deduplica por clave natural (LEI, CIK, etc.). | Hallazgo 1c: dos lotes idénticos en landing duplican filas. Cortar en el productor ahorra cuota y ruido; Bronze y Silver cubren reenvíos y solapamientos parciales. |
