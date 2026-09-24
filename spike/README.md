# Spike (Fase 0)

Todo lo de esta carpeta es efímero salvo `INFORME.md` y `evidencia/`.

## Recursos creados
| Recurso | Cómo | Estado |
|---|---|---|
| Catálogo `entity360` | SQL `CREATE CATALOG` + `terraform import` (la API no acepta default storage) | creado |
| Schema `entity360.landing` | Terraform | creado |
| Volume `entity360.landing.raw` | Terraform | creado |
| PAT `spike-a1-files-api` | CLI, 1 h de vida, solo en memoria | expira solo |

## Paso manual (A.1)
1. `databricks auth login --host https://dbc-26f27eaf-626f.cloud.databricks.com --profile entity360-free`
2. Crear el catálogo por SQL en un warehouse (ver `evidencia/a1-catalogo-default-storage.txt`)
   y después `terraform import databricks_catalog.entity360 entity360`.

## Destroy (con confirmación, antes de la fase 1)
```powershell
cd spike\terraform
terraform plan -destroy    # revisar
terraform destroy          # borra volume (con archivos), schema y catálogo (force_destroy)
```
