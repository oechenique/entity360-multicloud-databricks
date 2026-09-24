# Spike A.4b: salir del default storage hacia un bucket S3 propio
# (bucket y rol en spike/terraform-aws/).

variable "spike_bucket" {
  description = "Bucket creado por spike/terraform-aws."
  type        = string
  default     = "entity360-spike-uc-887793660259"
}

# Creada por API en A.4a (prueba de permiso) e importada: su external_id está en la
# trust policy del rol IAM.
resource "databricks_storage_credential" "spike_s3" {
  name    = "entity360-spike-s3"
  comment = "Spike A.4: prueba de permiso"

  aws_iam_role {
    role_arn = "arn:aws:iam::887793660259:role/entity360-spike-uc"
  }
}

resource "databricks_external_location" "spike_s3" {
  name            = "entity360-spike-s3"
  url             = "s3://${var.spike_bucket}/"
  credential_name = databricks_storage_credential.spike_s3.name
  comment         = "Bucket propio del spike (fuera del default storage)."
  force_destroy   = true
}

resource "databricks_catalog" "ext" {
  name          = "entity360_ext"
  storage_root  = "s3://${var.spike_bucket}/catalogs/entity360_ext"
  comment       = "Spike A.4b: catálogo con MANAGED LOCATION en S3 propio."
  force_destroy = true

  depends_on = [databricks_external_location.spike_s3]
}

resource "databricks_schema" "ext_spike" {
  catalog_name  = databricks_catalog.ext.name
  name          = "spike"
  force_destroy = true
}

data "databricks_current_user" "me" {}

# Acceso de motores externos (Iceberg REST + credential vending). En default storage no
# aplica (A.3); sobre S3 propio es la prueba del Camino A.
resource "databricks_grant" "ext_spike_external_use" {
  schema     = databricks_schema.ext_spike.id
  principal  = data.databricks_current_user.me.user_name
  privileges = ["EXTERNAL_USE_SCHEMA"]
}
