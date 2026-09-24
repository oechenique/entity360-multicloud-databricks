terraform {
  required_version = ">= 1.6"

  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.90"
    }
  }
}

# Auth por perfil OAuth de ~/.databrickscfg (nunca claves en el repo).
provider "databricks" {
  profile = var.databricks_profile
}
