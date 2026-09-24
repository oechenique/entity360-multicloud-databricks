# Informe del spike (Fase 0)

Estado: **parte A respondida** (pendiente: confirmar la verificación con LinkedIn y probar Snowflake en el Camino A). Parte B sin empezar.

## Riesgos
| Riesgo | Evidencia | Mitigación |
|---|---|---|
| La doc de Free Edition lista "custom workspace storage locations" como no soportado, pero 4b–4e funcionan. Databricks podría cerrarlo. | 4b–4e vs. free-edition-limitations | Todo por Terraform e idempotente; si se cierra, se cae al Camino B sin rediseñar productores ni medallion. |
| La salida a internet medida contradice la doc (restringida sin LinkedIn). | 5 | Mantener el push (D9): los productores no dependen de la salida de Databricks. |
| Cuota diaria de serverless con corte del workspace. | 6c | Universo acotado, jobs chicos, sin schedules agresivos. |

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
| 4a | ¿Free Edition permite crear una storage credential propia? | ✅ (inesperado) | `evidencia/a4-storage-credential.txt`; `evidencia/a4-privilegios-metastore.txt` (el listado de grants no lo mostraba) | Camino A sigue abierto. Falta probar con S3 real. |
| 4b | External location + catálogo con `MANAGED LOCATION` en S3 propio, lectura/escritura desde serverless | ✅ | `evidencia/a4-external-location-apply.txt`, `evidencia/a4-serverless-s3-propio.txt` (Delta e Iceberg, 10 filas c/u, 17 objetos en S3) | Se puede salir del default storage. Con S3 propio el catálogo sí se crea por Terraform (no hace falta el paso manual de D1). |
| 4c | Credential vending a motores externos sobre S3 propio (flag apagado) | ❌ | `evidencia/a4-iceberg-rest-s3-propio.txt`, `evidencia/a4-vending-diagnostico.txt` | Causa: `external_access_enabled=False` en el metastore. |
| 4d | Habilitar `external_access_enabled` desde el workspace | ✅ (inesperado) | `evidencia/a4-flag-external-access.txt` | El usuario de Free Edition puede cambiarlo aunque el owner sea "System user". Afecta a todo el metastore; cada schema igual necesita `EXTERNAL_USE_SCHEMA`. |
| 4e | Credential vending + lectura y escritura con PyIceberg sobre S3 propio | ✅ | `evidencia/a4-iceberg-rest-s3-propio-flag-on.txt`: credenciales S3 temporales emitidas, scan de 10 filas, append externo, Databricks ve 11 filas / 10 LEI | **Camino A viable** para Snowflake (catalog integration `ICEBERG_REST` + `VENDED_CREDENTIALS`), pendiente de probar del lado Snowflake. |
| 5 | Salida a internet desde serverless | ✅ abierta | `evidencia/a5-salida-internet.txt`: 13/13 hosts (GLEIF, SEC, OpenSanctions, Wikidata, GDELT, PyPI, GitHub, S3 y hosts no populares); IP de salida 3.145.247.171 | La doc dice que la salida está restringida salvo verificación con LinkedIn. Hay que confirmar en la UI si la cuenta está verificada. El modelo push (regla 01) ya no es obligatorio por red, pero se mantiene (D9). |
| 6a | Dashboard AI/BI sobre tablas del catálogo (creado y publicado por API) | ✅ | `evidencia/a6-consumo.txt` | Se puede versionar como `.lvdash.json` y desplegar por API/Terraform. |
| 6b | Genie space sobre Delta **e Iceberg**, pregunta en español por API | ✅ | `evidencia/a6-consumo.txt`: SQL correcto, 10 LEI, top 3 | Genie funciona sobre Gold en Iceberg: no hace falta duplicar en Delta para consumo. |
| 6c | Límites de Free Edition | 📄 doc | `evidencia/a6-consumo.txt` | 1 warehouse 2X-Small, máx. 5 tareas concurrentes, cuota diaria de serverless con corte. Dashboards y Genie sin límites publicados. |
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
| D7 | Camino A para Snowflake: Gold en un catálogo con `MANAGED LOCATION` en S3 propio + `external_access_enabled` + `EXTERNAL_USE_SCHEMA` solo en los schemas que se exponen. | 4b–4e: es la única combinación que da credential vending en Free Edition. |
| D8 | D1 se revisa: si los catálogos viven en S3 propio, se crean por Terraform; el paso manual queda solo para catálogos en default storage. | 4b: `databricks_catalog` con `storage_root` funciona. |
| D9 | Se mantiene el modelo push aunque la salida a internet esté abierta. | Cada nube guarda su respaldo y actúa como "otro sistema"; no depender de una salida que la doc dice restringida. |
