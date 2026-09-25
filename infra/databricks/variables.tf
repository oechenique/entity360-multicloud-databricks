variable "databricks_profile" {
  description = "Perfil de ~/.databrickscfg del workspace Free Edition."
  type        = string
  default     = "entity360-free"
}

variable "aws_account_id" {
  description = "Cuenta AWS del bucket del catálogo (en terraform.tfvars, fuera de git)."
  type        = string
}

variable "warehouse_name" {
  description = "SQL warehouse para crear tablas (Free Edition trae uno solo)."
  type        = string
  default     = "Serverless Starter Warehouse"
}
