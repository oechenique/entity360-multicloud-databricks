# Storage propio del catálogo (regla 03, D7/D8): bucket y rol en infra/aws/.

locals {
  bucket   = "entity360-uc-${var.aws_account_id}"
  role_arn = "arn:aws:iam::${var.aws_account_id}:role/entity360-uc"
}

resource "databricks_storage_credential" "uc" {
  name    = "entity360-uc"
  comment = "Rol IAM entity360-uc (infra/aws) para el storage del catálogo entity360."

  aws_iam_role {
    role_arn = local.role_arn
  }
}

# Sin force_destroy (regla 03): si quedan tablas (incluidas las retenidas para UNDROP), el
# destroy falla y se resuelve a mano, con confirmación (docs/destroy.md).
resource "databricks_external_location" "uc" {
  name            = "entity360-uc"
  url             = "s3://${local.bucket}/"
  credential_name = databricks_storage_credential.uc.name
  comment         = "Bucket propio del catálogo entity360 (fuera del default storage)."
}

# force_destroy a propósito (regla 03, aprendizaje del proyecto anterior): el destroy del
# catálogo borra schemas y tablas. Documentado en docs/destroy.md.
resource "databricks_catalog" "entity360" {
  name          = "entity360"
  storage_root  = "s3://${local.bucket}/catalogs/entity360"
  comment       = "entity360: golden record de empresas a partir de GLEIF, SEC, Wikidata, OpenSanctions y GDELT."
  force_destroy = true

  depends_on = [databricks_external_location.uc]
}
