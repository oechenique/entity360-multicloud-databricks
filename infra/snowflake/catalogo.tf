# Gold de Unity Catalog en Snowflake, sin copiar (Caminos A y A2, docs/fase9-plan.md §2).
#
# La catalog integration ICEBERG_REST y la base catalog-linked ENTITY360_UC NO están en Terraform
# (ADR 0012): la integración lleva el secreto OAuth del SP de Databricks y todo lo que un recurso
# recibe termina en el state. Las crea snowflake/integracion.py, idempotente, con el secreto leído del
# llavero de Windows.
#
# Acá queda lo que no tiene secretos: el external volume del Camino A2 (Snowflake lee S3 con un rol IAM
# propio de solo lectura, infra/aws/snowflake_a2.tf). El script lo referencia por nombre.

locals {
  a2 = var.camino == "A2" ? 1 : 0
}

resource "snowflake_external_volume" "gold" {
  count        = local.a2
  name         = "ENTITY360_GOLD_VOL"
  allow_writes = "false" # Databricks es el único que escribe Gold
  comment      = "Camino A2: lectura de Gold en S3 con un rol propio de Snowflake."

  storage_location {
    storage_location_name = "entity360-uc-gold"
    storage_provider      = "S3"
    storage_base_url      = var.a2_bucket_url
    storage_aws_role_arn  = var.a2_role_arn
  }
}

output "external_volume" {
  description = "Nombre del external volume (Camino A2), para snowflake/integracion.py --camino A2."
  value       = local.a2 == 1 ? snowflake_external_volume.gold[0].name : null
}
