# Spike (Fase 0)

Todo lo de esta carpeta es efímero salvo `INFORME.md` y `evidencia/`.

## Recursos creados
| Recurso | Cómo | Estado |
|---|---|---|
| Catálogo `entity360` | SQL `CREATE CATALOG` + `terraform import` (la API no acepta default storage) | creado |
| Schema `entity360.landing` | Terraform | creado |
| Volume `entity360.landing.raw` | Terraform | creado |
| PAT `spike-a1-files-api` | CLI, 1 h de vida, solo en memoria | expira solo |
| SP `entity360-spike-producer` (+ `workspace_access`) | Terraform | creado |
| Grants del SP en catálogo, schema y volume | Terraform (`databricks_grant`) | creados |
| 2 secretos OAuth del SP | CLI, 1 h de vida, solo en memoria | expiran solos; se borran con el SP |
| Schema `entity360.spike` (`force_destroy`) | Terraform | creado |
| Tabla `entity360.spike.gleif_iceberg` (Iceberg gestionada) | SQL CTAS | creada; se borra con el schema |
| venv `spike/.venv` (pyiceberg 0.12.0, pyarrow 25.0.1) | local | ignorado por git |
| AWS (us-east-2): bucket `entity360-spike-uc-887793660259`, rol IAM `entity360-spike-uc` + policy | Terraform (`spike/terraform-aws/`) | creado |
| Storage credential `entity360-spike-s3` | API (A.4a) + `terraform import` | creada |
| External location `entity360-spike-s3`, catálogo `entity360_ext` (MANAGED LOCATION S3), schema `spike` | Terraform | creados |
| Grant `EXTERNAL_USE_SCHEMA` en `entity360_ext.spike` | Terraform | creado |
| Tablas `entity360_ext.spike.gleif_delta` y `gleif_iceberg` | SQL CTAS (+ 1 append externo con PyIceberg) | creadas; se borran con el catálogo |
| **Flag del metastore `external_access_enabled` = true** | CLI (`databricks metastores update`) | **activo; afecta a todo el metastore** |

## Paso manual (A.1)
1. `databricks auth login --host https://dbc-26f27eaf-626f.cloud.databricks.com --profile entity360-free`
2. Catálogo por SQL + `terraform import`: ver `docs/manual-steps.md`.
3. Secreto OAuth del SP (fuera de Terraform para que no quede en el state):
   `databricks service-principal-secrets-proxy create <sp_id> --lifetime 3600s -p entity360-free`

## Destroy (con confirmación, antes de la fase 1)
Orden: primero Databricks (suelta la external location), después AWS.
Si el Camino A no sigue en la fase 1, revertir también el flag del metastore:
`databricks metastores update 9997da73-5c41-4468-bbe7-feb64349cca3 --external-access-enabled=false -p entity360-free`
```powershell
cd spike\terraform
terraform plan -destroy    # revisar
terraform destroy          # borra grants, SP (y sus secretos), external location, credential, volume, schemas y catálogos
cd ..\terraform-aws
terraform plan -destroy
terraform destroy          # bucket (force_destroy) y rol IAM
```
