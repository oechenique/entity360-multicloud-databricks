# Pasos manuales

Lo que Terraform no puede crear (o no conviene) se documenta acá, con el motivo.

## Antes del primer `terraform apply`

### 1. Perfil de la CLI de Databricks (OAuth U2M)
```powershell
databricks auth login --host <WORKSPACE_URL> --profile entity360-free
```
Motivo: la auth interactiva no se automatiza; Terraform usa ese perfil (`infra/databricks`).

### 2. Credenciales de AWS
```powershell
aws login --profile tesseract
```
Siempre el perfil `tesseract` (regla 00). Las alertas de presupuesto (50 y 100 USD, al 85 % y
100 %) tienen que existir antes de crear recursos (principio 5):
`aws budgets describe-budgets --account-id <AWS_ACCOUNT_ID> --profile tesseract`.

### 3. Variables fuera de git
Copiar cada `terraform.tfvars.example` a `terraform.tfvars` y completar:
- `infra/aws/terraform.tfvars`: `uc_external_id` = ID de la cuenta de Databricks (es el
  `external_id` de cualquier storage credential de la cuenta).
- `infra/databricks/terraform.tfvars`: `aws_account_id`.
- `infra/gcp/terraform.tfvars`: `project_id` (proyecto de GCP en sandbox) y `github_repository`
  (`owner/nombre`, el único repo que acepta el provider de WIF).

### 3b. Credenciales de GCP (ADC del usuario)
```powershell
gcloud auth application-default login
```
Terraform (`infra/gcp`) usa las credenciales por defecto de la aplicación: nunca claves de service
account. El proyecto corre **sin cuenta de facturación** (ADR 0003); verificar antes de cada apply:
`gcloud billing projects describe <GCP_PROJECT_ID> --format="value(billingEnabled)"` → `False`.

## Databricks

### 4. Acceso externo del metastore (Camino A)
Habilita el credential vending por Iceberg REST para motores externos (Snowflake, PyIceberg).
El metastore es de cuenta y Free Edition no expone la consola de cuenta, así que va por CLI.
**Estado: activo desde el spike (2026-09-24).**
```powershell
# Verificar (debe dar True)
databricks metastores summary -p entity360-free -o json   # campo external_access_enabled
# Habilitar
databricks metastores update <METASTORE_ID> --external-access-enabled -p entity360-free
# Revertir (solo si se abandona el Camino A)
databricks metastores update <METASTORE_ID> --external-access-enabled=false -p entity360-free
```
Alcance: todo el metastore. No abre nada solo: cada schema necesita `EXTERNAL_USE_SCHEMA` (ese
grant va por Terraform, solo sobre `gold`, en la fase 9) y solo aplica a storage propio.

### 5. Secretos OAuth de los SP de productores
Un SP por productor (ADR 0002), creados por Terraform. Sus secretos **no** (no quedan en el
state): los crea el script de credenciales de cada productor y los guarda **solo** en el almacén
de secretos de donde corre ese productor. Nunca se imprimen ni se escriben a disco.

**Límite de Databricks: 5 secretos por SP**, y los vencidos cuentan hasta que se borran. Al rotar,
borrar el secreto viejo cuando el nuevo esté en uso.

#### Tabla de secretos vigentes
| SP | Productor | Secreto (id) | Dónde se guarda | Creado (UTC) | **Vence (UTC)** | Cómo se rota |
|---|---|---|---|---|---|---|
| `entity360-producer` (recurso `producer_cdc`; nombre heredado, ADR 0002) | Extractor CDC (fase 2) | `66ebd68b…` | Administrador de credenciales de Windows, servicio `entity360-cdc-extractor` | 2026-09-25 21:56 | **2026-12-24 21:56** | `producers\cdc_extractor\credenciales.py configurar --dias 90` |
| `entity360-producer-sec-edgar` | Lambda de entrega SEC EDGAR (fase 3) | `871133f2…` | AWS Secrets Manager `entity360/databricks/producer-sec-edgar` (us-east-1) | 2026-09-25 22:14 | **2026-12-24 22:14** | `producers\aws_sec_edgar\credenciales.py cargar --dias 90` |
| `entity360-producer-enrichment` | Container de enriquecimiento (fase 5) | `88a521b9…` | GitHub Secrets del repo (`DATABRICKS_CLIENT_SECRET`, junto con `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` y `USER_AGENT`) | 2026-09-26 22:57 | **2026-12-25 22:57** | `producers\container_enrichment\credenciales.py cargar --dias 90` |
| `entity360-producer-gdelt` | Productor GDELT en GitHub Actions (fase 4) | `88a530ee…` | GitHub Secrets del repo (`GDELT_DATABRICKS_CLIENT_SECRET`, junto con `GDELT_DATABRICKS_CLIENT_ID`; `DATABRICKS_HOST` es compartido) | 2026-09-26 23:33 | **2026-12-25 23:33** | `producers\gcp_gdelt\credenciales.py cargar --dias 90` |
| `entity360-snowflake` | Catalog integration de Snowflake y validación del vending (fase 9, ADR 0012) | `c61a7428…` | Administrador de credenciales de Windows, servicio `entity360-snowflake` (con `databricks_host` y `client_id`) | 2026-09-29 18:41 | **2026-12-28 18:41** | `snowflake\integracion.py guardar-secreto --dias 90` y, si la integración ya existe, `crear --camino A --rotar-secreto` |
| Usuario de Snowflake `ENTITY360_TF` (ACCOUNTADMIN, ADR 0013) | Terraform `infra/snowflake` y `snowflake/integracion.py` (fase 9) | key pair RSA 2048, fingerprint `SHA256:/O7a+qlk…` | `~/.snowflake/keys/entity360_tf.p8` y perfil `[entity360]` de `~/.snowflake/config` (icacls: solo el usuario de Windows) | 2026-09-29 | **no vence** | a mano: `ALTER USER ENTITY360_TF SET RSA_PUBLIC_KEY_2 = '<nueva>'`, cambiar la clave local, `UNSET RSA_PUBLIC_KEY` |
| Usuario de Snowflake `ENTITY360_DBT_SVC` (rol `ENTITY360_DBT`) | dbt, target `snowflake` (fase 9) | key pair RSA 2048 | `~/.snowflake/keys/entity360_dbt_svc.p8` (icacls); la pública en `infra/snowflake/terraform.tfvars` | 2026-09-29 | **no vence** | a mano: nueva clave con `cuenta.py`, `dbt_rsa_public_key` y `terraform apply` |

Mantener esta tabla al día en cada creación, rotación o borrado. Para listar los secretos reales
de un SP (ids y vencimientos, nunca los valores):
```powershell
databricks service-principal-secrets-proxy list <sp_id> -p entity360-free
```

Historial (borrados el 2026-09-25, con OK): `3b3068ef…`, `ba8564c5…`, `a4be27bd…` (smoke tests de
1 h de la fase 1) y `9d1615cb…` (huérfano de un intento fallido de la fase 3: el script creaba el
secreto antes de validar el acceso a AWS; corregido).

Secretos de prueba: `--lifetime 3600s` y borrarlos después del test (ocupan lugar en el límite).
Historial: `f94cb459…` de `entity360-producer-enrichment` (prueba de push de la fase 5, 1 h), borrado el
2026-09-26 con OK.
Verificación del SP de productores: `python tests/smoke_producer_push.py` con `DATABRICKS_HOST`,
`DATABRICKS_CLIENT_ID` y `DATABRICKS_CLIENT_SECRET` en el entorno.

### Histórico: catálogo sobre default storage (ya no se usa)
En Free Edition la API de Unity Catalog no crea catálogos sobre default storage
(`Metastore storage root URL does not exist`, spike 1a'). Desde la fase 1 el catálogo vive en
un bucket propio y lo crea Terraform (D8), así que este paso ya no aplica. Si alguna vez hiciera
falta un catálogo en default storage: `CREATE CATALOG` por SQL + `terraform import` +
`lifecycle { ignore_changes = [storage_root] }`.

## Legacy (fase 2)

### 6. SQL Server local y credenciales del extractor CDC
```powershell
cd legacy
Copy-Item .env.example .env      # y poner una contraseña de sa (no se versiona)
docker compose up -d --wait
# modelo y CDC: ver legacy/README.md
cd ..
.venv\Scripts\python.exe legacy\gleif_erp.py carga-inicial
.venv\Scripts\python.exe producers\cdc_extractor\credenciales.py configurar --dias 90
```
`credenciales.py` crea el secreto OAuth del SP y el login de solo lectura `cdc_extractor`, y
guarda todo en el Administrador de credenciales de Windows (`keyring`, servicio
`entity360-cdc-extractor`). Motivo de la excepción al principio 4: un sistema on-prem no tiene
secret manager de nube; el almacén de credenciales del sistema operativo cumple ese rol. Rotar
antes del vencimiento (el primero vence el 2026-12-24).

## Productor SEC EDGAR (fase 3)

### 7. Variables, secreto y suscripción a la alarma
1. `infra/aws/sec_edgar/terraform.tfvars` (fuera de git, ver `.example`): `sec_user_agent` (la SEC
   exige nombre y mail) y `alert_email`.
2. `terraform apply` en `infra/aws/sec_edgar` (antes, `infra/databricks` con el SP
   `entity360-producer-sec-edgar`).
3. Cargar el secreto del SP en Secrets Manager (valida el acceso a AWS antes de crear el secreto):
   ```powershell
   .venv\Scripts\python.exe producers\aws_sec_edgar\credenciales.py cargar --dias 90
   ```
   Requiere `boto3` y `botocore[crt]` en el venv (el `aws login` usa el proveedor de credenciales
   que necesita CRT).
4. **Confirmar la suscripción al tópico SNS** desde el mail "AWS Notification - Subscription
   Confirmation". Hasta entonces la alarma de la DLQ no avisa. Verificar:
   ```powershell
   aws sns list-subscriptions-by-topic --topic-arn arn:aws:sns:us-east-1:<AWS_ACCOUNT_ID>:entity360-sec-edgar-alertas --profile tesseract --region us-east-1
   ```
   (`SubscriptionArn` deja de decir `PendingConfirmation`).

## Container de enriquecimiento (fase 5)

### 8. CLI de GitHub y secretos del repo
1. `terraform apply` en `infra/databricks` (SP `entity360-producer-enrichment`).
2. CLI de GitHub, una vez: `winget install GitHub.cli` y `gh auth login`.
3. Cargar los secretos del repo (valida `gh` antes de crear el secreto del SP):
   ```powershell
   $env:ENRIQUECIMIENTO_USER_AGENT = "entity360 (portfolio) <CONTACT_EMAIL>"
   .venv\Scripts\python.exe producers\container_enrichment\credenciales.py cargar --dias 90
   ```
4. La imagen se publica sola con el push a `main` (`enriquecimiento-imagen.yml`). La primera
   corrida diaria se puede disparar a mano: Actions → `enriquecimiento-diario` → Run workflow
   (o `gh workflow run enriquecimiento-diario.yml`).
5. Anotar el secreto en la tabla de secretos vigentes (§5).

Hasta que existan los secretos, el workflow diario falla con "Falta el secreto …" (y GitHub avisa
por mail).

## Productor GDELT (fase 4, sin facturación en GCP)

### 9. WIF, secretos del repo y primera corrida
Todo en el proyecto de GCP en sandbox (ADR 0003). Si algún paso pide una cuenta de facturación, se
frena (regla 06).
1. `terraform apply` en `infra/gcp` (APIs de WIF, pool `entity360-github`, provider `github-oidc`,
   SA `entity360-gdelt` sin claves, dataset `entity360_gdelt`). Requiere §3 y §3b.
2. Secretos de WIF en el repo, directo de los outputs a `gh` por stdin (identifican el proyecto:
   principio 9, no se imprimen ni van al código del workflow):
   ```powershell
   cd infra\gcp
   terraform output -raw wif_provider          | gh secret set GCP_WIF_PROVIDER
   terraform output -raw service_account_email | gh secret set GCP_SERVICE_ACCOUNT
   (Select-String -Path terraform.tfvars -Pattern 'project_id\s*=\s*"(.+)"').Matches.Groups[1].Value | gh secret set GCP_PROJECT_ID
   cd ..\..
   ```
3. `terraform apply` en `infra/databricks` (SP `entity360-producer-gdelt` y sus grants).
4. Secreto OAuth del SP (valida `gh` y que exista `DATABRICKS_HOST`, que carga el §8, antes de
   crear el secreto):
   ```powershell
   .venv\Scripts\python.exe producers\gcp_gdelt\credenciales.py cargar --dias 90
   ```
5. La imagen se publica sola con el push a `main` (`gdelt-imagen.yml`). Primera corrida a mano
   (la ventana por defecto es de 24 horas, el máximo; ADR 0003):
   `gh workflow run gdelt-horario.yml`. Después corre sola con el cron (minuto 23
   de cada hora).
6. Anotar el secreto en la tabla de secretos vigentes (§5).

Hasta que existan los secretos, el workflow horario falla con "Falta el secreto …" (y GitHub avisa
por mail). Si falla el paso de auth a GCP, revisar que el workflow corra desde `main` y se llame
`gdelt-*`: el provider rechaza cualquier otro token.

Tests del productor (sin nube; los de BigQuery se saltean sin credenciales):
`.venv\Scripts\python.exe -m pytest tests\gcp_gdelt`.

## Contratos y Gold (fase 7)

### 10. Canal de alertas (Telegram)
Las cuarentenas de los contratos (y, desde la fase 8, las fuentes atrasadas) se avisan por Telegram.
1. En Telegram, hablar con `@BotFather`, `/newbot`, y guardar el token.
2. Mandarle un mensaje cualquiera al bot y leer el `chat.id` en
   `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. Variables de entorno (en Airflow, en `airflow/.env`, fuera de git): `TELEGRAM_BOT_TOKEN` y
   `TELEGRAM_CHAT_ID`. Sin ellas, las alertas van a stderr y nada se frena.

### 11. dbt
`dbt/profiles.yml` (ignorado por git) sale de `dbt/profiles.yml.example`: host, warehouse y token por
variables de entorno; el token es el OAuth de vida corta de la CLI. Ver `dbt/README.md`.

## Airflow (fase 8)

### 12. Principal de Airflow y credenciales (ADR 0007)
1. `terraform apply` en `infra/databricks` (SP `entity360-orquestador`, grants y permiso sobre el job).
2. Pasar al SP las tablas de Gold que ya existan (dbt las recrea y hace falta ser dueño; una sola vez,
   con el perfil del usuario, en el SQL editor o con la Statement Execution API):
   ```sql
   ALTER TABLE entity360.gold.<tabla> OWNER TO `<application_id del SP>`;   -- las 5 tablas de gold
   ```
3. Secreto OAuth del SP (90 días) al llavero de Windows:
   ```powershell
   .venv\Scripts\python.exe airflow\credenciales.py configurar --dias 90
   .venv\Scripts\python.exe airflow\credenciales.py verificar   # también mira las del extractor CDC (§6)
   ```
4. `.\airflow\levantar.ps1` (ver `airflow/README.md`). Anotar el secreto en la tabla de secretos
   vigentes (§5). Rotarlo: volver a correr el paso 3 y `levantar.ps1`.

## Snowflake (fase 9, `docs/fase9-plan.md`)
Orden: §13 (antes del trial) → abrir el trial → §14 → `terraform apply` en `infra/snowflake` → §15.
Ningún secreto pasa por un state de Terraform (ADR 0012).

### 13. SP de Snowflake y validación del vending (antes del trial)
**Hecho el 2026-09-29:** SP creado (`apply` con `-target` del SP y sus grants; `fase9_snowflake = true` y
`snowflake_camino = "A"` en `terraform.tfvars`), secreto en el llavero y vending validado 5/5
(`snowflake/evidencia/vending-sp.txt`). Camino A.
1. `fase9_snowflake = true` en `infra/databricks/terraform.tfvars`, `plan` (3 recursos: SP y dos grants) y
   `apply` con OK.
2. Secreto OAuth del SP (90 días) al llavero de Windows (servicio `entity360-snowflake`, con el host y el
   client_id); imprime solo el vencimiento:
   ```powershell
   .venv\Scripts\python.exe -m pip install -r snowflake\requirements.txt
   .venv\Scripts\python.exe snowflake\integracion.py guardar-secreto --dias 90
   ```
   Anotarlo en la tabla de secretos vigentes (§5).
3. Validación del vending (`docs/fase9-plan.md` §1): si falla, ver el criterio del §5 del plan antes de
   abrir el trial.

### 14. Trial, usuarios de servicio y conexiones
Cada paso que crea algo en Snowflake se muestra antes y corre con OK.

**Gastón (UI, lo mínimo):**
1. Abrir el trial: **Enterprise, AWS us-east-2** (la región del bucket del catálogo). **Fecha de alta:
   2026-09-29** (vence a los 30 días o al agotar el crédito). Pasar el account identifier `<ORG>-<CUENTA>`.
2. Snowsight → hoja SQL nueva, rol ACCOUNTADMIN → pegar, **una sentencia por línea** (un bloque de
   varias líneas no corre), el SQL que imprimió
   `snowflake\cuenta.py claves` (crea `ENTITY360_TF`, `TYPE = SERVICE`, solo con la clave **pública**, sin
   contraseña) y verificar con `DESC USER ENTITY360_TF` (`HAS_PASSWORD = false`).
3. Verificar el mail del perfil (Snowsight → perfil): los avisos del resource monitor van a los
   ACCOUNTADMIN con mail verificado.

**Claude (PC):**
- `snowflake\cuenta.py claves` (ya hecho el 2026-09-29): pares RSA de `ENTITY360_TF` y
  `ENTITY360_DBT_SVC` en `~/.snowflake/keys`, acceso solo del usuario de Windows. La clave pública de dbt
  va en `infra/snowflake/terraform.tfvars` (ignorado por git; una clave pública no es un secreto).
- Con el account identifier: `snowflake\cuenta.py conexiones --cuenta <ORG>-<CUENTA>` (perfil
  `entity360` de `~/.snowflake/config` para Terraform y de `connections.toml` para el conector) y prueba
  de conexión con `SELECT CURRENT_USER(), CURRENT_ROLE()` (no usa warehouse).

`ENTITY360_TF` usa ACCOUNTADMIN: crear un resource monitor y una catalog integration lo exigen. Es un
usuario de servicio sin contraseña, solo en esta PC; en una cuenta de empresa serían roles separados.

### 15. Terraform, catalog integration y marts (cada paso con OK)
1. `terraform init` y `terraform plan -out` en `infra/snowflake` → Gastón revisa el plan → `apply`:
   resource monitor, warehouse (arranca suspendido), roles, base de marts y el usuario `ENTITY360_DBT_SVC`.
2. Mostrar qué va a crear `integracion.py` (integración `ENTITY360_UNITY`, base `ENTITY360_UC`, grants de
   lectura) → OK → `snowflake\integracion.py crear --camino A` y una segunda vez, que tiene que decir
   "sin cambios". `SYSTEM$VERIFY_CATALOG_INTEGRATION` en la salida.
3. `SHOW TABLES IN DATABASE ENTITY360_UC`: las 5 tablas de `gold` y ninguna otra. Conteos contra los de
   Gold del 2026-09-29 (Gold no cambió desde el `dbt build` de las 15:48 UTC: `dim_entity` 1136,
   `bridge_entity_source` 1268, `fct_risk_flags` 52, `fct_news_signal` 10, `fct_entity_changes` 4036), sin
   usar el warehouse de Databricks.
4. dbt de los marts (OK): `dbt\.venv` con `requirements-snowflake.txt`, variables `SNOWFLAKE_ACCOUNT`,
   `SNOWFLAKE_USER = ENTITY360_DBT_SVC`, `SNOWFLAKE_PRIVATE_KEY_PATH`, y
   `dbt build --target snowflake --select marts --vars "{snowflake_gold_database: ENTITY360_UC}"`.
5. Consumo del día en `WAREHOUSE_METERING_HISTORY` (llega con demora) en `snowflake/evidencia/consumo.md`.

Rotar el secreto del SP: `integracion.py guardar-secreto` y `crear --camino A --rotar-secreto`.
