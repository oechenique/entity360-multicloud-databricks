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
| `entity360-producer` (pendiente: `entity360-producer-cdc`) | Extractor CDC (fase 2) | `66ebd68b…` | Administrador de credenciales de Windows, servicio `entity360-cdc-extractor` | 2026-09-25 21:56 | **2026-12-24 21:56** | `producers\cdc_extractor\credenciales.py configurar --dias 90` |
| `entity360-producer-sec-edgar` | Lambda de entrega SEC EDGAR (fase 3) | `871133f2…` | AWS Secrets Manager `entity360/databricks/producer-sec-edgar` (us-east-1) | 2026-09-25 22:14 | **2026-12-24 22:14** | `producers\aws_sec_edgar\credenciales.py cargar --dias 90` |

Mantener esta tabla al día en cada creación, rotación o borrado. Para listar los secretos reales
de un SP (ids y vencimientos, nunca los valores):
```powershell
databricks service-principal-secrets-proxy list <sp_id> -p entity360-free
```

Historial (borrados el 2026-09-25, con OK): `3b3068ef…`, `ba8564c5…`, `a4be27bd…` (smoke tests de
1 h de la fase 1) y `9d1615cb…` (huérfano de un intento fallido de la fase 3: el script creaba el
secreto antes de validar el acceso a AWS; corregido).

Secretos de prueba: `--lifetime 3600s` y borrarlos después del test (ocupan lugar en el límite).
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
