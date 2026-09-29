# Fase 9 (regla 11, docs/fase9-plan.md): Snowflake para los modelers. NO se aplicó: el trial se abre
# recién después de validar el credential vending con el SP de Databricks (snowflake/validar_vending.py).
terraform {
  required_version = ">= 1.6"

  required_providers {
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 2.21"
    }
  }
}

# Auth por perfil de ~/.snowflake/connections.toml (key pair del usuario de Terraform, docs/fase9-plan.md
# paso 2): nunca credenciales en el código ni en tfvars versionados.
provider "snowflake" {
  profile = var.snowflake_profile
  # El external volume (Camino A2) está en preview en el provider 2.21.
  preview_features_enabled = ["snowflake_external_volume_resource"]
}
