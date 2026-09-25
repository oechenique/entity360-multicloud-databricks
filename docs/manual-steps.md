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

### 5. Secreto OAuth del SP de productores
El SP `entity360-producer` lo crea Terraform; su secreto no, para que no quede en el state.
Se crea cuando un productor lo necesita y se guarda **solo** en el secret manager de la nube
que lo usa (Secrets Manager en AWS, Secret Manager en GCP, GitHub Secrets para Actions).
```powershell
# producer_sp_id: output de infra/databricks
databricks service-principal-secrets-proxy create <producer_sp_id> --lifetime <segundos>s -p entity360-free
```
Nunca se imprime ni se escribe a disco. Para pruebas, `--lifetime 3600s` (vence solo); para
productores, definir la vida útil y la rotación en su fase.

Verificación: `python tests/smoke_producer_push.py` con `DATABRICKS_HOST`,
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
