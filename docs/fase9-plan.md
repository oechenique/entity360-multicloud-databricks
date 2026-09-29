# Fase 9 — Plan: Snowflake para los modelers

Estado (2026-09-29): **plan y código listos, nada creado.** Sin trial abierto, sin `apply`, sin
recursos en Databricks, AWS ni Snowflake. El Terraform está escrito y pasa `terraform validate`; los
recursos de Databricks y AWS de la fase quedan detrás de variables apagadas por defecto. **Ningún secreto
pasa por un state de Terraform** (ADR 0012): la catalog integration y la base catalog-linked las crea un
script que lee el secreto del SP del llavero.

Fuentes: `reglas/11-snowflake.md`; spike 3b, 3c, 4a–4e y decisiones D7, D8 (`spike/INFORME.md`); ADR 0001
(consumo por principal dedicado) y ADR 0005 (Gold en Iceberg gestionado); documentación de Snowflake
"Configure a catalog integration for Unity Catalog" y "CREATE CATALOG INTEGRATION (Iceberg REST)".

| Pieza | Archivo | Estado |
|---|---|---|
| SP y grants de Databricks | `infra/databricks/snowflake.tf` | escrito, apagado (`fase9_snowflake = false`); `plan` sin cambios de la fase |
| Warehouse, resource monitor, roles, base de marts, external volume (A2) | `infra/snowflake/*.tf` | escrito, validado, sin `apply` |
| Catalog integration, base catalog-linked, grants de lectura de Gold, secreto del SP | `snowflake/integracion.py` (ADR 0012) | escrito, 13 tests con mocks, sin correr |
| Rol IAM de solo lectura para el Camino A2 | `infra/aws/snowflake_a2.tf` | escrito, apagado (`snowflake_a2 = false`) |
| Validación del vending con el SP | `snowflake/validar_vending.py` | escrito, sin correr (necesita el SP) |
| Target `snowflake` y marts | `dbt/profiles.yml.example`, `dbt/models/marts/` | escrito; Gold solo con target Databricks, marts solo con Snowflake |

## Cuándo se hace qué
| # | Paso | Trial abierto | Usa la cuota de Free Edition |
|---|---|---|---|
| 1 | SP + grants en Databricks y **validación del vending con el SP** (§1, §3) | no | no (API de Unity Catalog + S3) |
| 2 | Si §1 pasa: abrir el trial (región **AWS us-east-2**) y anotar la fecha en `manual-steps.md` | **sí** | no |
| 3 | `infra/snowflake` con `camino = "A"` y después `snowflake/integracion.py crear --camino A` (integración, base catalog-linked, grants, `SYSTEM$VERIFY_CATALOG_INTEGRATION`) | sí | no |
| 4 | dbt `--target snowflake`: marts y tests (§4) | sí | no |
| 5 | DAG: tarea de marts después de `dbt_gold` y corrida 25/25 medida | sí | sí (la corrida diaria de siempre) |

## 1. Primer paso: validar el credential vending con el SP (antes del trial)
El spike probó el vending con el token del **usuario** (4e). Snowflake va a usar un **service principal**
con OAuth M2M y grants mínimos, así que la regla 11 exige repetirlo con ese principal antes de abrir
el trial.

1. En `infra/databricks/terraform.tfvars`: `fase9_snowflake = true` (camino `A` por defecto). `plan`
   esperado: 3 recursos nuevos (SP `entity360-snowflake`, grant de catálogo, grant de gold) y nada más.
2. `apply` (con OK) y secreto OAuth del SP, fuera de Terraform (como los demás SP, ADR 0002):
   `.venv\Scripts\python.exe snowflake\integracion.py guardar-secreto --dias 90`. Lo crea con la CLI de
   Databricks y lo guarda en el llavero de Windows (servicio `entity360-snowflake`) con el host y el
   client_id; imprime solo el vencimiento.
3. Chequeos previos: `external_access_enabled = true` en el metastore (`manual-steps.md` §4, activo
   desde el spike) y Gold en el S3 propio (`storage_root` del catálogo, fase 1).
4. Correr con las credenciales de AWS ocultas y el conteo de Databricks:
   ```powershell
   $env:AWS_CONFIG_FILE = "NUL"; $env:AWS_SHARED_CREDENTIALS_FILE = "NUL"
   $env:DATABRICKS_HOST = "https://<WORKSPACE_URL>"
   .venv\Scripts\python.exe snowflake\validar_vending.py --filas-esperadas 1136   # lee el SP del llavero
   ```
   Pasa si: (1) el SP obtiene token; (2) `config` responde; (3) `loadTable` de `gold.dim_entity` trae
   credenciales S3 temporales; (4) el scan con PyIceberg da las mismas filas que Databricks; (5) el SP
   **no** puede cargar `silver.sec_emisor` (mínimo privilegio).
5. Guardar la salida saneada en `snowflake/evidencia/vending-sp.txt`.

No escribe nada: Databricks sigue siendo el único que escribe Gold (el SP no tiene `MODIFY`). No usa el
SQL warehouse, así que se puede hacer aunque la cuota diaria esté agotada.

## 2. Terraform del lado de Snowflake (`infra/snowflake/`)
Provider `snowflakedb/snowflake` ~> 2.21, auth por perfil de `~/.snowflake/connections.toml` con key pair
(nada en el repo). En Terraform queda **todo lo que no lleva secretos**; la catalog integration y la base
catalog-linked van por `snowflake/integracion.py` (ADR 0012).

| Recurso | Qué | Por qué |
|---|---|---|
| `snowflake_resource_monitor.entity360` | 20 créditos por mes (variable), avisos al 50/75/90 %, suspende al 100 % y corta todo al 110 % | Principio 5 en Snowflake: el tope existe antes que el warehouse |
| `snowflake_warehouse.entity360` | `XSMALL`, `AUTO_SUSPEND = 60`, `auto_resume`, arranca suspendido, un solo cluster, 15 min por statement, con el monitor asignado | Regla 11; una consulta desbocada no quema el mes |
| `snowflake_external_volume.gold` | Solo A2: `s3://entity360-uc-<AWS_ACCOUNT_ID>/catalogs/entity360/`, `allow_writes = false` | Acceso a S3 sin vending |
| `snowflake_database.marts` + `snowflake_schema.marts` | `ENTITY360_MARTS.MARTS` | Lo que construye dbt para los modelers |
| `snowflake_account_role` `ENTITY360_DBT` y `ENTITY360_MODELER` + grants | dbt crea en `MARTS`; los modelers leen (future grants) y usan el warehouse | Mínimo privilegio |
| `snowflake_database.sync` | Solo Camino B: `ENTITY360_SYNC.GOLD` | Destino de la copia |

Por script (`snowflake/integracion.py crear --camino A|A2`), idempotente:

| Objeto | Qué | Idempotencia |
|---|---|---|
| Catalog integration `ENTITY360_UNITY` | `CATALOG_URI = <WORKSPACE_URL>/api/2.1/unity-catalog/iceberg-rest`, catálogo `entity360`, OAuth M2M del SP (`/oidc/v1/token`, scope `all-apis`), `ACCESS_DELEGATION_MODE = VENDED_CREDENTIALS` (A) o `EXTERNAL_VOLUME_CREDENTIALS` (A2), refresco cada 300 s | `CREATE ... IF NOT EXISTS`. Si existe y `DESC` coincide (URI, catálogo, modo, client_id), no la toca; si difiere, falla sin cambiar nada (recrearla es un `DROP`, a mano). `--rotar-secreto`: solo `ALTER ... SET REST_AUTHENTICATION` |
| Base catalog-linked `ENTITY360_UC` | `CREATE DATABASE IF NOT EXISTS ENTITY360_UC LINKED_CATALOG = (CATALOG = 'ENTITY360_UNITY' [, EXTERNAL_VOLUME = 'ENTITY360_GOLD_VOL'])` | `IF NOT EXISTS`; el provider tampoco tiene `LINKED_CATALOG` en `snowflake_database` |
| Grants de lectura | `USAGE` en la base y sus schemas, `SELECT` en las tablas Iceberg actuales y futuras, para `ENTITY360_DBT` y `ENTITY360_MODELER` | Solo cuando la base es nueva o con `--reaplicar-grants` |
| Verificación | `SYSTEM$VERIFY_CATALOG_INTEGRATION('ENTITY360_UNITY')` | Siempre |

El secreto sale del llavero, no se imprime ni se loguea (el logger del conector queda en WARNING, que no
muestra el SQL), y si Snowflake devuelve un error que cita el statement, el script lo propaga con el
secreto reemplazado por `***` (también en su forma escapada). Tests: `tests/snowflake/test_integracion.py`.
**A verificar en el primer uso:** si `QUERY_HISTORY` guarda el texto del `CREATE CATALOG INTEGRATION`
con el secreto a la vista o enmascarado. Si lo guarda a la vista, rotar no lo resuelve (el `ALTER` también
lo lleva): se deja anotado en el ADR 0012 como exposición residual, visible solo para quien lee el
historial de la cuenta (ACCOUNTADMIN por defecto), y el secreto vence a los 90 días.

Pasos, con el trial abierto:
1. **Bootstrap** (`manual-steps.md` §14): `snowflake/cuenta.py claves` genera los key pairs en
   `~/.snowflake/keys` e imprime el único SQL que se corre en Snowsight (crea `ENTITY360_TF`, usuario de
   servicio con la clave pública); `cuenta.py conexiones` arma los perfiles locales con el account
   identifier. `ENTITY360_DBT_SVC` lo crea Terraform con su clave pública. Anotar la fecha de alta del trial.
2. `terraform.tfvars` desde el `.example` (sin secretos: perfil, camino, créditos, clave pública de dbt)
   → `terraform plan` → revisar → `apply` con OK. Crea monitor, warehouse, roles, la base de marts y el
   usuario de dbt.
3. `pip install -r snowflake\requirements.txt` en el `.venv` y
   `.venv\Scripts\python.exe snowflake\integracion.py crear --camino A`: integración, base
   catalog-linked, grants de lectura y `SYSTEM$VERIFY_CATALOG_INTEGRATION`. Correrlo dos veces tiene que
   decir "sin cambios" la segunda.
4. `SHOW TABLES IN DATABASE ENTITY360_UC;`: tienen que aparecer las 5 tablas de `gold` y ninguna otra.
   Conteos iguales a Databricks en las 5 tablas.
   **Hecho el 2026-09-29** (`snowflake/evidencia/catalog-linked.txt`): solo el schema `gold`, las 5
   tablas, conteos iguales, array y map legibles, nombres en minúscula entre comillas.

**Parámetros de la sincronización (2026-09-29):**
- Integración: `REFRESH_INTERVAL_SECONDS = 3600` (metadata de las tablas). Gold solo cambia con el DAG,
  una vez por día, y la sincronización no la frena ningún resource monitor.
- Base: `ALLOWED_NAMESPACES = ('gold')` (no intenta `silver`, `bronze` ni `landing`, donde el SP recibe
  403), `SYNC_INTERVAL_SECONDS = 3600` (descubrimiento de schemas y tablas; el default de Snowflake es
  30 s) y `ALLOWED_WRITE_OPERATIONS = NONE`.
- **`SYNC_INTERVAL_SECONDS` se puede cambiar sin recrear la base:**
  `ALTER DATABASE ENTITY360_UC UPDATE LINKED_CATALOG SET SYNC_INTERVAL_SECONDS = <n>;` (probado con el
  mismo valor). También existen `SUSPEND DISCOVERY` / `RESUME DISCOVERY` y `ADD/REMOVE ... ALLOWED_NAMESPACES`.
- **Refresh manual después de una corrida del DAG:** `.venv\Scripts\python.exe snowflake\integracion.py
  refrescar` (`ALTER ICEBERG TABLE ENTITY360_UC."gold"."<tabla>" REFRESH` por tabla; probado). Estado de
  la sincronización: `SELECT SYSTEM$CATALOG_LINK_STATUS('ENTITY360_UC');`.
- **Solo lectura del lado de Snowflake, no demostrado:** un `INSERT` de cero filas no hace commit y pasó,
  así que no prueba `ALLOWED_WRITE_OPERATIONS = NONE`. La barrera probada es la de Unity Catalog (el SP
  no tiene `MODIFY`); Gold quedó en el mismo snapshot. La prueba concluyente (un `INSERT` de una fila que
  tiene que fallar) se hace solo con OK.
5. Tipos a verificar en la primera sincronización: `fuentes` (array), `procedencia` (map) y la
   capitalización de los nombres (los marts asumen minúscula entre comillas).

## 3. SP y grants de Databricks (`infra/databricks/snowflake.tf`)
| Objeto | Privilegios | Camino |
|---|---|---|
| SP `entity360-snowflake` | `workspace_access` (la API de Iceberg REST es del workspace, D5) | A, A2 |
| catálogo `entity360` | `USE_CATALOG` | A, A2 |
| schema `gold` | `USE_SCHEMA`, `SELECT` | A, A2 |
| schema `gold` | `EXTERNAL_USE_SCHEMA` | **solo A** |

- **Nada fuera de `gold`** (ADR 0001): ni `silver`, ni `resolution`, ni `ops`. El paso 1 lo verifica.
- **Sin `MODIFY` ni `ALL PRIVILEGES`**, aunque la documentación de Snowflake los liste para bases
  catalog-linked con escritura: acá Snowflake solo lee y Databricks sigue siendo el dueño de Gold (el SP
  del orquestador, ADR 0007). Sin `MODIFY`, Unity Catalog rechaza cualquier escritura que intente
  Snowflake por la base catalog-linked (a confirmar en el paso 3 con un `INSERT` que tiene que fallar).
- `external_access_enabled` del metastore ya está activo (spike 4d); el A2 no lo necesita.
- El Camino B no usa este SP: la extracción la hace Airflow con el SP del orquestador, que ya lee `gold`.

## 4. dbt: target `snowflake` y marts
- **Un proyecto, dos plataformas.** `dbt_project.yml`: `gold` se habilita solo con target Databricks y
  `marts` solo con Snowflake. Cosmos renderiza con el target `airflow` (Databricks): el DAG no cambia
  hasta que se sume la tarea de marts. El hook `registrar_resultados` solo corre en Databricks.
- **Target** en `dbt/profiles.yml.example`: `type: snowflake`, key pair del usuario `ENTITY360_DBT_SVC`
  por variables de entorno, rol `ENTITY360_DBT`, warehouse `ENTITY360_WH`, base `ENTITY360_MARTS`,
  schema `MARTS`. Adapter: `dbt-snowflake==1.12.1` (compatible con `dbt-core` 1.12.3), en un
  `requirements-snowflake.txt` aparte para no engordar la imagen de Airflow hasta que haga falta.
- **Fuente** `gold_uc` (`models/marts/fuentes_snowflake.yml`): base `ENTITY360_UC` (A/A2) o
  `ENTITY360_SYNC` (B) por la variable `snowflake_gold_database`.
- **Marts** (`models/marts/`):

  | Mart | Grano | Para qué |
  |---|---|---|
  | `mart_empresa` | una fila por empresa | identidad, cantidad de fuentes, noticias de 30 días (tono ponderado), riesgo, cambios del legacy de 90 días |
  | `mart_noticias_diarias` | empresa × día | menciones, tono y media móvil de 7 días (picos para marketing y riesgo) |
  | `mart_riesgo` | empresa × aparición en lista | lista, sanción, vínculo por LEI o por nombre, cobertura reciente |

  Tests: unicidad y no nulos, rangos, claves compuestas y relaciones con `mart_empresa` (los mismos
  tests genéricos del proyecto, que son SQL estándar).
- **DAG:** una tarea `snowflake_marts` (`dbt build --target snowflake --select marts`) después de
  `dbt_gold` y antes de `resultado`. En el Camino B, antes va `sync_snowflake`.

## 5. Caminos de respaldo y cuándo pasar de uno a otro
| Camino | Metadata | Datos | Copia | Requisitos |
|---|---|---|---|---|
| **A** | Iceberg REST de Unity Catalog | credenciales S3 temporales que emite Unity Catalog (vending) | no | `external_access_enabled`, `EXTERNAL_USE_SCHEMA` en gold, storage propio |
| **A2** | Iceberg REST de Unity Catalog | `EXTERNAL VOLUME` de Snowflake con un rol IAM propio de solo lectura sobre el bucket (`ACCESS_DELEGATION_MODE = EXTERNAL_VOLUME_CREDENTIALS`) | no | rol `entity360-snowflake-a2` (`infra/aws/snowflake_a2.tf`, dos `apply` para la confianza) |
| **B** | — | Airflow extrae Gold por el SQL warehouse de Databricks y carga con stage interno + `COPY INTO` | **sí** | nada del lado Unity Catalog; usa la cuota de Free Edition |

"Camino A2" es la variante documentada por Snowflake para Unity Catalog cuando no se usa el vending. No
estaba en la regla 11: se agrega como paso intermedio porque sigue siendo zero-copy y solo cambia quién
da las credenciales de S3. En el A2, `integracion.py crear --camino A2 --external-volume
ENTITY360_GOLD_VOL` usa el volume de Terraform.

**Alternativa descartada para el A2:** external volume propio + catalog integration `OBJECT_STORE`
(Snowflake lee los `metadata.json` de Iceberg directo de S3) con un refresh disparado desde Airflow. Se
descarta porque no usa el catálogo de Unity Catalog (se pierden sus grants y el descubrimiento de
tablas) y obliga a mantener un refresh por tabla después de cada `dbt build`.

**Criterio para pasar de uno a otro:**
1. **§1 falla en el paso 1 o 2** (el SP no obtiene token o el endpoint REST no responde): el problema es
   Unity Catalog, no el vending → **Camino B**, sin abrir el trial para A ni A2.
2. **§1 falla en el paso 3** (sin credenciales S3) o **en el 4** con un error de acceso a S3, y la
   metadata sí se lee: el vending no funciona con el SP → **Camino A2** (no depende del vending). Se abre
   el trial igual.
3. **§1 falla en el paso 5** (el SP ve Silver): no es un camino, es un grant de más. Se corrige y se repite.
4. **Con el trial abierto, en A:** si `SYSTEM$VERIFY_CATALOG_INTEGRATION` falla o la base catalog-linked
   no descubre las tablas → **A2**, cambiando `camino` en los dos stacks.
5. **En A o A2:** si las 5 tablas no aparecen, si los conteos no coinciden con Databricks, si algún tipo
   (`map`, `array`) no se puede leer, o si Snowflake no ve un snapshot nuevo después de
   `refresh_interval_seconds` → **B**.
6. **Tope de tiempo:** 3 días de trial para A/A2. Si no está andando, B, con el ADR que explica por qué
   no fue zero-copy (regla 11).

**Camino B, diseño:** tarea de Airflow `sync_snowflake` con el SP del orquestador. Por tabla de Gold,
lee por el SQL warehouse de Databricks, escribe Parquet, `PUT` al stage interno de `ENTITY360_SYNC.GOLD`
y `COPY INTO` con `MATCH_BY_COLUMN_NAME`. Incremental: los hechos por `fecha` o `valido_desde` posteriores
a la última carga y reemplazo completo de `dim_entity` y `bridge_entity_source` (1.136 y 1.268 filas).
Costo que se asume: una copia de Gold (MB) y consultas diarias contra la cuota de Free Edition.

## 6. Estimación del consumo del trial
Supuestos a confirmar al abrirlo: crédito de prueba de **USD 400** por 30 días; edición Standard (≈ USD 2
por crédito) o Enterprise (≈ USD 3), en AWS us-east-2. Un X-SMALL consume 1 crédito por hora, facturado
por segundo con un mínimo de 60 s cada vez que arranca; los cloud services son gratis hasta el 10 % del
cómputo diario.

| Uso | Supuesto | Créditos por mes |
|---|---|---|
| Puesta a punto (verificación, conteos, primeras corridas de dbt) | 2 h de warehouse en total | ~2 |
| dbt de los marts, diario | < 1 min de cómputo + 60 s de auto-suspend ≈ 2 min por día | ~1 |
| Consultas de los modelers y demo | ~10 h en el mes | ~10 |
| Sincronización de la base catalog-linked | cada 300 s; cómputo de Snowflake **a medir** la primera semana (`METERING_HISTORY`) | ? |
| Camino B (si hace falta) | `COPY INTO` diario, ~1 min | +1 |
| **Total estimado** | | **~13 a 15** |

- **En dinero:** USD 26 a 45 en el mes, entre el 7 % y el 11 % del crédito de prueba. El resource
  monitor corta a los 20 créditos (USD 40 a 60): aunque la estimación falle por el doble, el trial no
  se agota.
- **Almacenamiento:** A y A2, ~0 (Gold queda en el S3 del proyecto); los marts son MB. En B, la copia de
  Gold, también MB.
- **AWS:** lecturas de S3 desde Snowflake (centavos). Por eso el trial va en **us-east-2**, la región del
  bucket: otra región sumaría transferencia entre regiones.
- **Databricks:** A y A2 no usan el SQL warehouse (Unity Catalog responde por API): la fase 9 no compite
  con la cuota diaria de Free Edition. B sí.
- Medición real: `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY` y `METERING_DAILY_HISTORY` al final
  de la primera semana, en `snowflake/evidencia/consumo.md`.

## Destroy
`docs/destroy.md`, sección Snowflake. Orden: primero, con SQL y OK, `DROP DATABASE ENTITY360_UC` y
`DROP CATALOG INTEGRATION ENTITY360_UNITY` (no son de Terraform); después `terraform destroy` en
`infra/snowflake` (monitor, warehouse, roles, base de marts, external volume); después
`fase9_snowflake = false` y `apply` en `infra/databricks` (SP y grants) y, si se usó A2,
`snowflake_a2 = false` en `infra/aws`. Por último, borrar el servicio `entity360-snowflake` del llavero.
El trial se suspende solo al vencer.
