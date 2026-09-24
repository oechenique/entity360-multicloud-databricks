# Pasos manuales

Lo que Terraform no puede crear (o no conviene) se documenta acá, con el motivo.

## Databricks

### 1. Perfil de la CLI (OAuth U2M)
```powershell
databricks auth login --host https://dbc-26f27eaf-626f.cloud.databricks.com --profile entity360-free
```
Motivo: la auth interactiva no se automatiza; Terraform usa ese perfil.

### 2. Catálogo `entity360` sobre default storage
En Free Edition la API de Unity Catalog (y por eso `databricks_catalog` de Terraform) no
crea catálogos sobre default storage: responde `Metastore storage root URL does not exist`
(evidencia: `spike/evidencia/a1-catalogo-default-storage.txt`). Por SQL sí funciona.

1. En un SQL warehouse (o el SQL editor):
   ```sql
   CREATE CATALOG IF NOT EXISTS entity360 COMMENT '...';
   ```
2. Traerlo al state de Terraform:
   ```powershell
   terraform import databricks_catalog.entity360 entity360
   ```
3. El recurso lleva `lifecycle { ignore_changes = [storage_root] }`; sin eso el plan fuerza
   un replace que vuelve a fallar.

Schemas, volumes y grants sí van por Terraform.
