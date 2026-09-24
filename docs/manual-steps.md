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

Schemas, volumes y grants sí van por Terraform. Si el catálogo vive en un bucket S3 propio
(`storage_root`), Terraform lo crea sin este paso (spike 4b).

### 3. Acceso externo del metastore (Camino A)
Habilita credential vending por Iceberg REST para motores externos (Snowflake, PyIceberg).
El metastore es de cuenta y Free Edition no expone la consola de cuenta; se hace por CLI:
```powershell
databricks metastores update 9997da73-5c41-4468-bbe7-feb64349cca3 --external-access-enabled -p entity360-free
```
Alcance: todo el metastore. No abre nada solo: cada schema necesita `EXTERNAL_USE_SCHEMA`
(ese grant sí va por Terraform) y solo aplica a storage propio, no a default storage.
Revertir: el mismo comando con `--external-access-enabled=false`.
