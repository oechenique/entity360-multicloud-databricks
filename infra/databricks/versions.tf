terraform {
  required_version = ">= 1.6"

  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.90"
    }
  }
}

# Auth por perfil OAuth de ~/.databrickscfg (regla 03): nunca credenciales en el código.
provider "databricks" {
  profile = var.databricks_profile
}
