# Destroy

Principio 7: el destroy se escribe junto con la infra. **Todo con confirmación explícita**
(regla 00): nada de esto se corre sin OK de Gastón.

## Orden
0. Productores que usan los SP (por ejemplo `infra/aws/sec_edgar`, ver su sección).
1. Databricks (`infra/databricks`): suelta la external location, que depende del bucket.
2. Vaciar el bucket del catálogo a propósito (ver abajo).
3. AWS (`infra/aws`): bucket y rol IAM.

No se toca:
- El flag del metastore `external_access_enabled` (ver `manual-steps.md` §3): se revierte solo
  si se abandona el Camino A.
- Los secretos OAuth del SP: se borran solos con el SP (y vencen a la hora).

## 1. Databricks
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
