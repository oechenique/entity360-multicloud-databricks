# Informe del spike (Fase 0)

Estado: **parte A respondida**. Snowflake (Camino A, catalog integration `ICEBERG_REST` + `VENDED_CREDENTIALS`) se valida al inicio de la fase 9, no en el spike. Parte B en curso.

## Estado al cierre de hoy (2026-09-24)

**Hecho**
- Parte A completa: 1 (push con PAT y con SP + OAuth M2M), 3 (Iceberg gestionado + REST), 4 (S3
  propio, flag de acceso externo y credential vending: Camino A viable), 5 (salida a internet)
  y 6 (dashboard AI/BI y Genie).
- Parte B: 7 (SQL Server Developer con CDC), 8 (GLEIF golden copy completo, universo AR y
  tiempos) y 9 (SEC EDGAR).
- Decisiones D1–D9 registradas abajo. Datos identificatorios reemplazados por placeholders.
  Falso positivo de GitGuardian resuelto (sin contraseñas en el historial).

**Pendiente**
- B.10 GDELT: espera el proyecto de GCP (con alertas de presupuesto antes de crear nada).
- B.11 OpenSanctions y Wikidata: próxima sesión. Wikidata es el puente LEI↔CIK que mostró
  faltar el punto 9.
- Cerrar el informe (universo recomendado con cantidades y camino para Snowflake) y destruir
  los recursos del spike, con confirmación, antes de la fase 1.
- Decidir si se reescribe el historial (mail en el autor de los primeros commits, datos
  identificatorios en commits viejos) antes de hacer público el repo.

**Recursos activos** (detalle y destroy en `README.md`)
| Dónde | Recurso | Costo / nota |
|---|---|---|
| AWS us-east-2 | Bucket `entity360-spike-uc-<AWS_ACCOUNT_ID>` (~44 KB) y rol IAM `entity360-spike-uc` | centavos; alertas de 50/100 USD activas |
| Databricks | Catálogos `entity360` y `entity360_ext` (schemas, volume, tablas), SP `entity360-spike-producer`, storage credential + external location, grants | Free Edition |
| Databricks | **Flag del metastore `external_access_enabled = true`** (afecta a todo el metastore) | revertir si el Camino A no sigue |
| Databricks | Carpeta `/Users/<DATABRICKS_USER_EMAIL>/entity360-spike/` (notebook, dashboard publicado), Genie space | fuera de Terraform |
| Local | Contenedor `entity360-spike-mssql` **parado** + volumen `entity360-spike-mssql` con la base CDC | 0 |
| Local | `spike/data/gleif` (506 MB, ignorado por git), `spike/.venv` | 0 |

Sin jobs ni schedules activos. El PAT y los secretos OAuth del SP ya vencieron (1 h).

## Riesgos
| Riesgo | Evidencia | Mitigación |
|---|---|---|
| La doc de Free Edition lista "custom workspace storage locations" como no soportado, pero 4b–4e funcionan. Databricks podría cerrarlo. | 4b–4e vs. free-edition-limitations | Todo por Terraform e idempotente; si se cierra, se cae al Camino B sin rediseñar productores ni medallion. |
| La salida a internet está abierta **sin** verificación de LinkedIn, contra lo que dice la doc. Databricks puede aplicar la restricción en cualquier momento. | 5 (cuenta sin verificar: botón "Verify identity" en la UI) | D9: push desde los productores; nada del pipeline depende de la salida de Databricks. |
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
| 5 | Salida a internet desde serverless | ✅ abierta **sin** verificación de LinkedIn | `evidencia/a5-salida-internet.txt`: 13/13 hosts (GLEIF, SEC, OpenSanctions, Wikidata, GDELT, PyPI, GitHub, S3 y hosts no populares); IP de salida 3.145.247.171 | La doc dice que la salida está restringida salvo verificación con LinkedIn; la cuenta **no** está verificada (la UI muestra "Verify identity", confirmado por Gastón el 2026-09-24). El modelo push (regla 01) ya no es obligatorio por red, pero se mantiene (D9). |
| 6a | Dashboard AI/BI sobre tablas del catálogo (creado y publicado por API) | ✅ | `evidencia/a6-consumo.txt` | Se puede versionar como `.lvdash.json` y desplegar por API/Terraform. |
| 6b | Genie space sobre Delta **e Iceberg**, pregunta en español por API | ✅ | `evidencia/a6-consumo.txt`: SQL correcto, 10 LEI, top 3 | Genie funciona sobre Gold en Iceberg: no hace falta duplicar en Delta para consumo. |
| 6c | Límites de Free Edition | 📄 doc | `evidencia/a6-consumo.txt` | 1 warehouse 2X-Small, máx. 5 tareas concurrentes, cuota diaria de serverless con corte. Dashboards y Genie sin límites publicados. |
| 7 | SQL Server Developer en Docker con CDC: inserts, updates y deletes leídos con `cdc.fn_cdc_get_all_changes_*` | ✅ | `evidencia/b7-sqlserver-cdc.txt`: SQL Server 2022 CU27, Agent Running, 16 cambios (11 insert, 2+2 update antes/después, 1 delete) con LSN | El extractor de la fase 2 lee por rango de LSN (`fn_cdc_get_min_lsn` / checkpoint → `fn_cdc_get_max_lsn`) y guarda el último LSN procesado. El capture job es asíncrono (~5 s): el extractor tiene que tolerar ese retraso. Net changes disponible (`supports_net_changes=1`). |
| 8a | GLEIF golden copy completo (LEI2 + RR), tamaño y registros | ✅ | `evidencia/b8-gleif-golden-copy.txt` (publish 2026-09-24 16:00) | LEI2: 482 MB zip / 4,77 GB CSV / 3.441.120 registros / 338 columnas. RR: 23 MB / 488.850. Delta LastDay: 14.0k LEI2 (2 MB) y 2,6k RR. Licencia CC0. |
| 8b | Universo AR en GLEIF | ✅ | ídem | 965 entidades AR (964 por domicilio legal, 955 por jurisdicción). EntityStatus: 881 ACTIVE, 14 INACTIVE, 70 NULL. RegistrationStatus: 350 ISSUED, **531 LAPSED**, 69 ANNULLED, 14 RETIRED, 1 DUPLICATE. 336 relaciones RR con punta AR (154 consolidación directa, 159 última). Universo chico: entra entero en SQL Server y en Free Edition. |
| 8c | Tiempo de procesar el archivo entero en streaming (PC local) | ✅ | ídem | Descarga 38 s. Pasada completa: **csv stdlib 66,9 s (51k filas/s)** vs **pyarrow 12,7 s (272k filas/s, 3 columnas)**, mismos conteos. RR: 2 s. La carga inicial de la fase 2 se puede hacer local filtrando en streaming con pyarrow (sin descomprimir a disco) y aplicar después el delta diario. |
| 9 | SEC EDGAR: submissions de 3 empresas AR, con User-Agent y ≤5 req/s | ✅ | `evidencia/b9-sec-edgar.txt` | 16/17 tickers AR con CIK. JSON de 128–164 KB por empresa, <0,5 s. **Sin LEI** (`lei=null` en los 3) y nombres en inglés ("Pampa Energy Inc.", "Macro Bank Inc."): la búsqueda literal en GLEIF da 0. GLEIF tiene duplicados (Banco Macro: 2 LEI) y homónimos parciales (YPF). El puente es Wikidata (punto 11). |
| 10 | GDELT | ⏳ | | Pendiente: no existe proyecto GCP. |
| 11 | OpenSanctions y Wikidata | ⏳ | | |

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
