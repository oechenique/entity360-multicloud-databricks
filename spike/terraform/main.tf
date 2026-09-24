# Spike A.1: destino del modelo push (regla 01, "Contrato común de landing").
# Recursos efímeros del spike: se destruyen antes de la fase 1 (ver spike/README.md).

# Free Edition: la API no crea catálogos sobre default storage ("Metastore storage root
# URL does not exist"). Se crea con SQL y se importa (ver spike/README.md). El
# storage_root lo asigna el default storage, por eso se ignora.
resource "databricks_catalog" "entity360" {
  name          = "entity360"
  comment       = "Spike entity360: catálogo de prueba sobre default storage."
  force_destroy = true

  lifecycle {
    ignore_changes = [storage_root]
  }
}

resource "databricks_schema" "landing" {
  catalog_name = databricks_catalog.entity360.name
  name         = "landing"
  comment      = "Zona de llegada de los productores (push)."
}

resource "databricks_volume" "raw" {
  catalog_name = databricks_catalog.entity360.name
  schema_name  = databricks_schema.landing.name
  name         = "raw"
  volume_type  = "MANAGED"
  comment      = "Archivos crudos empujados por los productores con la Files API."
}
