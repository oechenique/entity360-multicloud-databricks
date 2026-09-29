# Destroy

Principio 7: el destroy se escribe junto con la infra. **Todo con confirmación explícita**
(regla 00): nada de esto se corre sin OK de Gastón.

## Estado: qué se probó
- **Probado de punta a punta:** el destroy del spike (Databricks, AWS y SQL Server local; `spike/INFORME.md`,
  "Estado final"), con verificación después de cada paso. De ahí salen el orden y los aprendizajes de
  este documento (`force_destroy` en la external location, Genie a la papelera).
- **Escrito junto con cada stack, sin ejecutar todavía sobre el proyecto:** todo lo de abajo. Ejecutarlo
  es el último paso del cierre (regla 12) y necesita OK explícito.

## Orden completo
Primero lo que usa las identidades de Databricks (los SP), después Databricks, después las nubes y al
final lo local. Cada paso tiene su sección más abajo.

| # | Qué | Sección |
|---|---|---|
| 1 | Airflow: detener el DAG y los containers | [Airflow](#airflow-fase-8) |
| 2 | Productores: GDELT (`infra/gcp`), enriquecimiento (GitHub Actions + GHCR), SEC EDGAR (`infra/aws/sec_edgar`) | [GDELT](#productor-gdelt-fase-4-infragcp), [enriquecimiento](#container-de-enriquecimiento-fase-5), [SEC EDGAR](#productor-sec-edgar-fase-3-us-east-1) |
| 3 | Snowflake (fase 9), cuando exista | [Snowflake](#snowflake-fase-9) |
| 4 | Genie a la papelera y `infra/databricks` (catálogo, job, SP, dashboard, tablas de `ops`) | [1. Databricks](#1-databricks) |
| 5 | Vaciar el bucket del catálogo a propósito | [2. Vaciar el bucket](#2-vaciar-el-bucket-a-propósito) |
| 6 | `infra/aws`: bucket y rol IAM del catálogo | [3. AWS](#3-aws) |
| 7 | Legacy: SQL Server, credenciales y checkpoint del extractor | [Legacy](#legacy-fase-2) |
| 8 | Limpieza local | [Limpieza local](#limpieza-local) |

No se toca (a propósito):
- El flag del metastore `external_access_enabled` (`manual-steps.md` §4): se revierte solo si se
  abandona el Camino A de Snowflake.
- Los presupuestos de AWS (50 y 100 USD, `manual-steps.md` §2): son de la cuenta, no del proyecto.
- El proyecto de GCP (sandbox, sin facturación): lo crea y lo borra el dueño de la cuenta.
- Los secretos OAuth de los SP: se borran con los SP (y los M2M vencen a la hora).

## 1. Databricks
El espacio de Genie (fase 10) no es de Terraform: se manda a la papelera antes, por su título.
```powershell
$sid = (databricks genie list-spaces -p entity360-free -o json | ConvertFrom-Json).spaces |
  Where-Object { $_.title -eq 'Entity 360' } | Select-Object -ExpandProperty space_id
$sid                                               # revisar que sea uno solo
databricks genie trash-space $sid -p entity360-free
```
El dashboard "Entity 360" y las tablas `ops.dbt_resultado` y `ops.calidad_resolucion` sí caen con el
destroy (`infra/databricks/consumo.tf`).
```powershell
cd infra\databricks
terraform plan -destroy        # revisar la lista
terraform destroy
```
Qué pasa con cada `force_destroy` (regla 03, decidido a propósito):
- **Catálogo y schemas: `force_destroy = true`.** El destroy borra tablas y volumes aunque tengan
  datos. Las tablas gestionadas quedan retenidas unos días para `UNDROP`.
- **External location: sin `force_destroy`.** Si todavía hay tablas que dependen de ella (por
  ejemplo, las retenidas para `UNDROP`), el destroy **falla**. No se resuelve con `--force` por
  defecto: primero se revisa qué queda (`SHOW TABLES DROPPED IN entity360.<schema>`) y se decide.
  Si hay que forzarlo, se muestra el comando y se ejecuta solo con OK:
  ```powershell
  databricks external-locations delete entity360-uc --force -p entity360-free
  terraform state rm databricks_external_location.uc
  terraform destroy
  ```

## 2. Vaciar el bucket a propósito
El bucket `entity360-uc-<AWS_ACCOUNT_ID>` **no** tiene `force_destroy`: el `terraform destroy` de
AWS falla si quedan objetos. Es a propósito, para que borrar datos sea un paso consciente.

Después del destroy de Databricks, revisar qué quedó y recién ahí vaciar:
```powershell
$acc = aws sts get-caller-identity --profile tesseract --query Account --output text
$bucket = "entity360-uc-$acc"

# 1) Ver qué hay (cantidad y tamaño); no borra nada.
aws s3 ls "s3://$bucket/" --recursive --summarize --profile tesseract

# 2) Simular el borrado; no borra nada.
aws s3 rm "s3://$bucket/" --recursive --dryrun --profile tesseract

# 3) Con OK: borrar.
aws s3 rm "s3://$bucket/" --recursive --profile tesseract

# 4) Confirmar que quedó vacío (Total Objects: 0).
aws s3 ls "s3://$bucket/" --recursive --summarize --profile tesseract
```
El bucket no tiene versionado, así que `aws s3 rm` alcanza (no hay versiones viejas que borrar).

## 3. AWS
```powershell
cd infra\aws
terraform plan -destroy
terraform destroy              # bucket (ya vacío) y rol IAM entity360-uc
```

## Verificación
- `databricks catalogs list -p entity360-free` sin `entity360`; `storage-credentials list` y
  `external-locations list` sin `entity360-uc`.
- `aws s3api head-bucket --bucket <bucket> --profile tesseract` → 404.
- `aws iam get-role --role-name entity360-uc --profile tesseract` → `NoSuchEntity`.
- `terraform state list` vacío en los dos stacks.

## Legacy (fase 2)
Independiente de la nube; con confirmación.
```powershell
# SQL Server: contenedor, red y volumen con la base (incluido el historial del CDC)
docker compose -f legacy\docker-compose.yml down -v

# Credenciales del extractor en el Administrador de credenciales de Windows
.venv\Scripts\python.exe -c "import keyring; [keyring.delete_password('entity360-cdc-extractor', k) for k in ('databricks_host','databricks_client_id','databricks_secret','sql_password')]"

# Checkpoint local del extractor
Remove-Item producers\cdc_extractor\state\checkpoint.json
```
Los secretos OAuth del SP se borran con el SP (destroy de `infra/databricks`) o vencen solos.
Los archivos ya empujados al volume se borran con el catálogo.

## Productor SEC EDGAR (fase 3, us-east-1)
Antes que `infra/databricks` (la Lambda de entrega usa el SP `entity360-producer-sec-edgar`).
```powershell
$acc = aws sts get-caller-identity --profile tesseract --query Account --output text
$bucket = "entity360-sec-edgar-$acc"

# 1) Vaciar el respaldo crudo a propósito (el bucket no tiene force_destroy): listar, simular, borrar, confirmar.
aws s3 ls "s3://$bucket/" --recursive --summarize --profile tesseract
aws s3 rm "s3://$bucket/" --recursive --dryrun --profile tesseract
aws s3 rm "s3://$bucket/" --recursive --profile tesseract          # con OK
aws s3 ls "s3://$bucket/" --recursive --summarize --profile tesseract   # Total Objects: 0

# 2) Destroy (borra también el schedule diario, las Lambdas, la DLQ y la alarma)
cd infra\aws\sec_edgar
terraform plan -destroy
terraform destroy
```
- El secreto de Secrets Manager queda **7 días** en recuperación (`recovery_window_in_days`) y
  después se borra solo. Para borrarlo ya: `aws secretsmanager delete-secret --secret-id
  entity360/databricks/producer-sec-edgar --force-delete-without-recovery` (con OK).
- La suscripción de SNS se borra con el tópico.
- El secreto OAuth del SP se borra con el SP (destroy de `infra/databricks`) o vence solo.
- Los lotes ya entregados al volume se borran con el catálogo.

## Container de enriquecimiento (fase 5)
Antes que `infra/databricks` (el workflow usa el SP `entity360-producer-enrichment`). Con OK:
```powershell
# 1) Cortar la ejecución diaria (o borrar .github/workflows/enriquecimiento-*.yml y pushear)
gh workflow disable enriquecimiento-diario.yml
# 2) Secretos del repo
foreach ($s in 'DATABRICKS_HOST','DATABRICKS_CLIENT_ID','DATABRICKS_CLIENT_SECRET','USER_AGENT') { gh secret delete $s }
# 3) Paquete de GHCR (todas sus versiones)
gh api -X DELETE /user/packages/container/entity360-enrichment
# 4) Imagen local
docker image rm entity360-enrichment:local
```
- El borrado del paquete necesita el scope `delete:packages` (`gh auth refresh -s delete:packages`).
- El secreto OAuth del SP se borra con el SP (destroy de `infra/databricks`) o vence solo.
- Los lotes ya empujados al volume se borran con el catálogo.

## Productor GDELT (fase 4, `infra/gcp`)
Antes que `infra/databricks` (el workflow usa el SP `entity360-producer-gdelt`). Independiente de
AWS. Sin cuenta de facturación no hay nada que cueste mientras exista (ADR 0003). Con OK:
```powershell
# 1) Cortar la corrida horaria (o borrar .github/workflows/gdelt-*.yml y pushear)
gh workflow disable gdelt-horario.yml

# 2) Secretos del repo propios de GDELT (DATABRICKS_HOST es compartido con enriquecimiento: se borra ahí)
foreach ($s in 'GDELT_DATABRICKS_CLIENT_ID','GDELT_DATABRICKS_CLIENT_SECRET','GCP_WIF_PROVIDER','GCP_SERVICE_ACCOUNT','GCP_PROJECT_ID') { gh secret delete $s }

# 3) Paquete de GHCR (todas sus versiones) e imagen local, si se construyó
gh api -X DELETE /user/packages/container/entity360-gdelt
docker image rm entity360-gdelt

# 4) Vaciar el respaldo a propósito: el dataset tiene delete_contents_on_destroy = false y el
#    destroy falla si quedan tablas. Ver qué hay, y recién ahí borrar la tabla.
$proyecto = (Select-String -Path infra\gcp\terraform.tfvars -Pattern 'project_id\s*=\s*"(.+)"').Matches.Groups[1].Value
bq ls --project_id=$proyecto entity360_gdelt
bq show --format=prettyjson "${proyecto}:entity360_gdelt.menciones"   # numRows, numBytes
bq rm -t -f "${proyecto}:entity360_gdelt.menciones"                   # con OK

# 5) Destroy: dataset, bindings, SA, provider y pool de WIF
cd infra\gcp
terraform plan -destroy
terraform destroy
```
- **WIF queda 30 días en borrado lógico.** El pool y el provider pasan a `DELETED` y su ID no se
  puede reusar hasta que se purgan. Un `apply` dentro de esos 30 días falla con "already exists":
  restaurarlos (`gcloud iam workload-identity-pools undelete entity360-github --location=global`,
  y lo mismo con `providers undelete github-oidc`) e importarlos, o cambiar los IDs.
- **La SA** también se puede recuperar durante 30 días (`gcloud iam service-accounts undelete
  <unique_id>`). No tiene claves que revocar.
- **Las APIs quedan habilitadas** (`disable_on_destroy = false`: BigQuery lo usa también el spike, y
  habilitadas sin facturación no cuestan). Para deshabilitar las de WIF a mano, con OK:
  `gcloud services disable sts.googleapis.com iamcredentials.googleapis.com --project $proyecto`.
- El secreto OAuth del SP se borra con el SP (destroy de `infra/databricks`) o vence solo.
- Los lotes ya empujados al volume se borran con el catálogo.

Verificación: `gcloud iam workload-identity-pools list --location=global --project $proyecto` sin
pools activos (`--show-deleted` los muestra en `DELETED`), `gcloud iam service-accounts list
--project $proyecto` sin `entity360-gdelt`, `bq ls --project_id=$proyecto` sin `entity360_gdelt` y
`terraform state list` vacío en `infra/gcp`.

## Medallion (fase 6)
Todo en `infra/databricks`: el `terraform destroy` del paso 1 borra el job `entity360-medallion`,
el código en `/Shared/entity360/medallion` y el volume `ops.checkpoints`. Las tablas de `bronze`,
`silver` y `resolution` (Iceberg gestionadas) se borran con los schemas (`force_destroy = true`).
Si el schedule está activo, pausarlo antes (`pause_status = "PAUSED"` en `medallion.tf` y
`terraform apply`), para que no arranque una corrida a mitad del destroy.

Las tablas de `gold` (fase 7) las crea dbt, no Terraform: se borran con el schema (`force_destroy`).
Los veredictos de los contratos (`_contrato_*.json`) viven en el volume `landing.raw` y se borran con él.

Para reprocesar una fuente desde cero sin destruir
nada: borrar su checkpoint (`databricks fs rm -r dbfs:/Volumes/entity360/ops/checkpoints/<fuente>`);
la capa 2 evita filas duplicadas en Bronze.

## Airflow (fase 8)
```powershell
docker compose -p entity360-airflow down -v   # containers, red y base de Airflow (volumen postgres-db)
docker image rm entity360-airflow:3.3.2
```
El SP `entity360-orquestador`, sus grants y el permiso sobre el job se borran con el `terraform destroy`
de `infra/databricks`. Borrar también las credenciales del llavero de Windows (servicio
`entity360-airflow`, en el Administrador de credenciales) y revocar su secreto si no se destruye el SP.

## Snowflake (fase 9)
La fase 9 está planificada (`docs/fase9-plan.md`) y su Terraform escrito, pero **no hay recursos**: ni
trial abierto ni `apply`. Cuando existan, antes que `infra/databricks` (Snowflake lee Gold con el SP de
Databricks), con OK.

Primero lo que no es de Terraform (ADR 0012): la base catalog-linked y la catalog integration, en ese
orden (la base depende de la integración). En Snowsight, con ACCOUNTADMIN:
```sql
SHOW DATABASES LIKE 'ENTITY360_UC';                 -- revisar que sea la catalog-linked
DROP DATABASE IF EXISTS ENTITY360_UC;               -- Gold no se toca: el SP no tiene MODIFY en Unity Catalog
SHOW CATALOG INTEGRATIONS LIKE 'ENTITY360_UNITY';
DROP CATALOG INTEGRATION IF EXISTS ENTITY360_UNITY;
```
Después Terraform:
```powershell
cd infra\snowflake
terraform plan -destroy        # monitor, warehouse, roles, base de marts, external volume (A2)
terraform destroy
```
Después, en `infra/databricks`, `fase9_snowflake = false` y `apply` (SP `entity360-snowflake` y sus
grants) y, si se usó el Camino A2, `snowflake_a2 = false` y `apply` en `infra/aws`. Borrar el secreto del
SP del llavero (servicio `entity360-snowflake`) y la clave privada del usuario de Terraform de Snowflake.
El trial se suspende solo al vencer.

## Limpieza local
Lo que queda en la PC después de los destroy. Nada está en git (`.gitignore`). Con OK:
```powershell
# Entornos de Python
Remove-Item -Recurse -Force .venv, contracts\.venv, dbt\.venv, spike\.venv
# Datos descargados por el spike (~950 MB) y artefactos de dbt
Remove-Item -Recurse -Force spike\data, dbt\target, dbt\logs, airflow\logs
# Imágenes de Docker del proyecto
docker image rm entity360-airflow:3.3.2 entity360-enrichment:local entity360-gdelt
# Variables y states locales (revisar antes: el state vacío confirma el destroy)
Get-ChildItem -Recurse -Include terraform.tfvars, *.tfstate*, *.tfplan, .env, profiles.yml -File |
  Where-Object { $_.FullName -notmatch '\.venv\' } | Select-Object FullName
```
- **Llavero de Windows:** servicios `entity360-cdc-extractor` y `entity360-airflow` (Administrador de
  credenciales) y el perfil `entity360-free` de `~/.databrickscfg` con su token OAuth
  (`databricks auth logout -p entity360-free`, o borrar la sección a mano).
- **`.wslconfig`** (fase 8, `airflow/wslconfig.propuesto`): es de la PC, no del proyecto. Si ya no se
  quiere el techo de WSL, borrar `%UserProfile%\.wslconfig` y correr `wsl --shutdown`.

## Verificación final
- `terraform state list` vacío en `infra/databricks`, `infra/aws`, `infra/aws/sec_edgar` e `infra/gcp`.
- `databricks catalogs list -p entity360-free` sin `entity360`; `databricks service-principals list` sin
  `entity360-*`; `databricks genie list-spaces` sin "Entity 360"; el dashboard no figura en
  `/Shared/entity360`.
- `aws s3 ls --profile tesseract` sin buckets `entity360-*`; `aws lambda list-functions` sin
  `entity360-*`.
- `gh workflow list` con los workflows de GDELT y enriquecimiento deshabilitados (o borrados) y
  `gh secret list` sin los secretos del proyecto.
- `docker ps -a` y `docker volume ls` sin `entity360-*`.
