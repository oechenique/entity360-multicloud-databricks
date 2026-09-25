# Informe del spike (Fase 0)

Estado: **spike cerrado (2026-09-25)**. Las 11 preguntas tienen respuesta con evidencia; B.10 (GDELT)
queda con un resultado preliminar a validar. Pendiente: destroy de los recursos del spike (con
confirmación) antes de la fase 1.

## Resumen ejecutivo
- **La arquitectura de la regla 01 se sostiene.** El push a un UC Volume funciona desde afuera con
  service principal + OAuth M2M (1b), y Free Edition alcanza para medallion, Iceberg, dashboard y
  Genie (3a, 6a, 6b).
- **Snowflake: Camino A viable** (4e). Hace falta sacar Gold del default storage hacia un S3 propio
  y habilitar el acceso externo del metastore; con eso, PyIceberg lee y escribe con credential
  vending. Se valida del lado Snowflake al inicio de la fase 9 (regla 11).
- **El problema de identidad es real y más duro de lo previsto.** La SEC no trae LEI y usa nombres
  en inglés; GLEIF tiene duplicados y homónimos; Wikidata une solo 3–5 de 16 emisores. La
  resolución se apoya en matching por nombre/domicilio dentro de GLEIF AR, con Wikidata y ticker
  como señales extra, y se mide contra un set curado a mano (D11).
- **Los volúmenes son chicos y baratos.** Universo AR de GLEIF: 965 entidades; carga inicial local
  en <1 min con pyarrow; GDELT cuesta ~50 MB por día-consulta con filtro de partición.
- **Dos riesgos de plataforma** dependen de comportamientos de Free Edition que contradicen su
  documentación (storage propio y salida a internet): ver Riesgos.

## Universo recomendado (con cantidades medidas)
| Fuente | Alcance para la fase 2+ | Cantidad | Evidencia |
|---|---|---|---|
| GLEIF LEI2 | Todas las entidades con domicilio legal o jurisdicción AR, **cualquier estado** (el golden record marca vigencia; 531 están LAPSED) | 965 | 8b |
| GLEIF RR | Relaciones con alguna punta AR (matriz/filial, fondos, sucursales) | 336 | 8b |
| GLEIF, conjunto de control | Contrapartes no-AR de esas relaciones (matrices extranjeras): control natural de otros países | a medir en la fase 2 | 8b |
| SEC EDGAR | Emisores AR con CIK (ADRs en NYSE/Nasdaq) | 16 | 9 |
| Wikidata | Ítems AR con LEI + ítems de los 16 emisores por CIK/ticker | 11 + 11 | 11a |
| OpenSanctions | No-personas con país AR (bandera de riesgo) | 46 (3 cruzan con el universo) | 11c |
| GDELT | Menciones diarias de las organizaciones del universo (GKG) | preliminar: 25/día, solo MercadoLibre | 10 |

Se amplía más adelante si el costo y la cuota lo permiten (regla 01); con estos volúmenes, el
límite es la cuota diaria de serverless, no el almacenamiento.

## Camino para Snowflake
**Camino A** (zero-copy con Iceberg REST + `VENDED_CREDENTIALS`), condicionado a:
1. Gold en un catálogo con `MANAGED LOCATION` en un bucket S3 propio **en us-east-2** (la región del
   metastore).
2. `external_access_enabled = true` en el metastore (paso manual, `docs/manual-steps.md` §3).
3. `EXTERNAL_USE_SCHEMA` solo sobre el schema `gold`, otorgado al principal que use Snowflake.
4. Validar al inicio de la fase 9 que el vending funcione con **OAuth del service principal** (el
   spike lo probó con el token del usuario) y del lado Snowflake. Si falla, Camino B sin cambios en
   las fases anteriores.

## Conclusiones
1. Push + manifest + idempotencia en tres capas (D2, D6) es el contrato correcto: el landing solo
   no es idempotente (1c).
2. En Free Edition, lo que vive en default storage no se puede crear por Terraform (catálogos) ni
   exponer a motores externos (3c). El storage propio resuelve las dos cosas (4b, 4e, D7, D8).
3. El CDC de SQL Server Developer funciona como lo pide la regla 04; el extractor tiene que leer por
   rango de LSN y tolerar el retraso asíncrono del capture job (7).
4. GLEIF es la columna vertebral del universo: completo, CC0, con deltas diarios de 2 MB (8).
5. **La calidad del matching se mide contra un set de validación curado a mano**, con Wikidata y
   el ticker bursátil como señales extra, no como verdad de referencia (D11). Wikidata cubre 3–5 de
   16 emisores y el 1 % del universo (11a, 11b).
6. OpenSanctions aporta pocas coincidencias (3) pero de alto valor para "riesgo" (11c).
7. GDELT es barato con filtro de partición, pero la señal para empresas AR parece escasa; antes de
   construir el productor GCP (fase 4) hay que confirmar que no es un falso negativo (10).

## Recomendaciones para la fase 1 (regla 03)
1. **Catálogo `entity360` con `MANAGED LOCATION` en un bucket S3 propio (us-east-2)**, creado por
   Terraform (D8). El bucket y el rol IAM van en `infra/aws/` (tomar como base `spike/terraform-aws`),
   con la storage credential y la external location en `infra/databricks/`.
2. Mantener `external_access_enabled` (Camino A) y documentarlo como paso manual; otorgar
   `EXTERNAL_USE_SCHEMA` solo sobre `gold`.
3. SP de productores como en el spike: `workspace_access` + `USE_CATALOG`/`USE_SCHEMA`/`READ_VOLUME`/
   `WRITE_VOLUME` sobre `landing.raw` (D4, D5). Secretos OAuth fuera del state de Terraform.
4. Contrato de landing con `_manifest_<ts>.json` (D2) y `ops.ingestion_log` con el `sha256` del
   manifest, que es la base del dedup de Bronze (D6).
5. Crear el dashboard y el Genie space por API a partir de archivos versionados (`.lvdash.json`),
   no a mano (6a).
6. Separar desde el inicio el set de validación curado (D11): un archivo versionado con pares
   resueltos a mano y su evidencia, que alimenta la evaluación de la fase 6.
7. Terraform con variables en `terraform.tfvars` (fuera de git) y `.tfvars.example` versionado;
   placeholders en toda la documentación.

## Pendientes y decisiones abiertas
- **Destroy del spike** (con confirmación): orden y comandos en `README.md`. Decidir si el flag
  `external_access_enabled` se mantiene (recomendado, Camino A) o se revierte.
- **B.10:** query de diagnóstico de GDELT (dry run + OK) para descartar falso negativo del regex.
- **Regla 08, punto 6** ("evaluación contra Wikidata como verdad de referencia") contradice D11:
  actualizarla con OK de Gastón.
- **Regla 11, Camino A:** agregar la validación del vending con el service principal (hoy probado
  con el usuario).
- **Historial de git** (mail en el autor de los primeros commits, datos identificatorios en commits
  viejos): decidir antes de hacer público el repo.

## Recursos activos al cierre (a destruir antes de la fase 1; detalle en `README.md`)
| Dónde | Recurso | Costo / nota |
|---|---|---|
| AWS us-east-2 | Bucket `entity360-spike-uc-<AWS_ACCOUNT_ID>` (~44 KB) y rol IAM `entity360-spike-uc` | centavos; alertas de 50/100 USD activas |
| Databricks | Catálogos `entity360` y `entity360_ext` (schemas, volume, tablas), SP `entity360-spike-producer`, storage credential + external location, grants | Free Edition |
| Databricks | **Flag del metastore `external_access_enabled = true`** (afecta a todo el metastore) | mantener para el Camino A o revertir |
| Databricks | Carpeta `/Users/<DATABRICKS_USER_EMAIL>/entity360-spike/` (notebook, dashboard publicado), Genie space | fuera de Terraform |
| GCP | Proyecto `<GCP_PROJECT_ID>` en sandbox de BigQuery, sin billing; sin datasets creados | 0 (no se destruye: lo usa la fase 4) |
| Local | Contenedor `entity360-spike-mssql` **parado** + volumen `entity360-spike-mssql` | 0 |
| Local | `spike/data/` (GLEIF 506 MB, OpenSanctions 441 MB, ignorado por git), `spike/.venv` | 0 |

Sin jobs ni schedules activos. PAT y secretos OAuth del SP vencidos.

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
| 9 | SEC EDGAR: submissions de 3 empresas AR, con User-Agent y ≤5 req/s | ✅ | `evidencia/b9-sec-edgar.txt` | 16/17 tickers AR con CIK. JSON de 128–164 KB por empresa, <0,5 s. **Sin LEI** (`lei=null` en los 3) y nombres en inglés ("Pampa Energy Inc.", "Macro Bank Inc."): la búsqueda literal en GLEIF da 0. GLEIF tiene duplicados (Banco Macro: 2 LEI) y homónimos parciales (YPF). Wikidata resultó un puente parcial (11a). |
| 10 | GDELT en BigQuery (sandbox), con filtro de partición y dry run | ⚠️ preliminar | `evidencia/b10-gdelt.txt` | Costo: por día GKG (`V2Organizations`, `V2Tone`) **0,05 GiB**, Events **0,005 GiB**; sin filtro de partición serían **285 GiB**. Consumo real ~60 MB con tope de 1 GiB (D12). Menciones en 1 día: **solo MercadoLibre (25, tono −0,38)**; Events: 0. Señal muy escasa para el universo AR; no se descarta falso negativo del regex (nombres normalizados en inglés): validar antes de diseñar el productor GCP (fase 4). |
| 11a | Wikidata une SEC (CIK) con GLEIF (LEI) en los 16 emisores AR | ⚠️ parcial | `evidencia/b11-wikidata-opensanctions.txt` | Por CIK (P5531): **3/16 con LEI** (YPF, Edenor, MercadoLibre), los 3 verificados en GLEIF. Por ticker (P414+P249): **5/16** (suma Banco Macro, con el LEI ACTIVE que desempata el duplicado de B.9, y Telecom). Pampa Energía: sin ítem; solo se resuelve por nombre en castellano en GLEIF. Wikidata es **una señal más**, no el puente principal. |
| 11b | Wikidata como verdad de referencia del matching | ❌ insuficiente | ídem | Solo 11 ítems AR con LEI; 10 caen en el universo GLEIF AR (965) = **1,0 %**. No alcanza para medir calidad: hace falta un conjunto de validación curado (ver recomendaciones). |
| 11c | OpenSanctions: descarga, licencia y cruce con el universo | ✅ | ídem | `targets.simple.csv` 441 MB (1,23 M targets, 4,07 M entidades en total), lectura 4,6 s. AR: 46 no-personas y 2.162 personas. Cruce con el universo: 1 por LEI (PlusPetrol) y 2 por nombre normalizado (PlusPetrol, Telecom Argentina), en registros de riesgo. Licencia **CC BY-NC 4.0**, uso no comercial válido (`docs/fuentes.md`). La señal de riesgo es rara: sirve como bandera, no como volumen. |

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
| D10 | Principio 5 en GCP: el proyecto de BigQuery corre en **modo sandbox, sin cuenta de facturación** (`billingEnabled=False`, verificado). Sin billing no hay costo posible, y tampoco se pueden crear alertas de presupuesto (requieren cuenta de facturación). Si en la fase 4 se habilita billing (Cloud Run, Scheduler, GCS), las alertas se crean **antes** que cualquier recurso. | Acordado con Gastón (2026-09-25). |
| D11 | La calidad de la resolución de identidades se mide contra un **set de validación curado a mano** (pares CIK↔LEI y fuente↔LEI resueltos manualmente, con evidencia de cada decisión). Wikidata (CIK/P5531, LEI/P1278) y el ticker (P414+P249) se usan como **señales extra** de matching, no como verdad de referencia. | B.11: Wikidata cubre 3–5 de 16 emisores y el 1 % del universo. Acordado con Gastón (2026-09-25). |
| D12 | El guardarraíl de BigQuery va **cerca del consumo esperado**, no del máximo de la cuota: tope de dry run y `maximum_bytes_billed` = 1 GiB por query cuando lo esperado es ~50 MB. | Si una query supera 20× lo esperado, algo cambió (falta el filtro de partición, otra tabla, otra columna) y tiene que cortarse. Acordado con Gastón (2026-09-25). |
