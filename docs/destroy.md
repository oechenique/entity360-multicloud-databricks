# Destroy

Principio 7: el destroy se escribe junto con la infra. **Todo con confirmación explícita**
(regla 00): nada de esto se corre sin OK de Gastón.

## Orden
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
