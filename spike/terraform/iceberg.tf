# Spike A.3: Iceberg gestionado en Free Edition, leído/escrito desde afuera por el
# endpoint Iceberg REST de Unity Catalog. La tabla se crea por SQL (CTAS) dentro de este
# schema y se borra con él (force_destroy).

resource "databricks_schema" "spike" {
  catalog_name  = databricks_catalog.entity360.name
  name          = "spike"
  comment       = "Pruebas del spike (Iceberg), aparte de landing."
  force_destroy = true
}

# EXTERNAL_USE_SCHEMA no se puede otorgar sobre default storage (SCHEMA_DB_STORAGE):
# ver spike/evidencia/a3-external-use-schema.txt. Por eso no hay grant acá.
