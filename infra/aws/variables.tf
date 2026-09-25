variable "aws_profile" {
  description = "Perfil de AWS CLI (regla 00: siempre tesseract)."
  type        = string
  default     = "tesseract"
}

variable "aws_region" {
  description = "Región del storage de Unity Catalog: la del metastore de Free Edition (regla 00)."
  type        = string
  default     = "us-east-2"
}

variable "uc_master_role_arn" {
  description = "Rol de Unity Catalog (cuenta de Databricks) que asume el rol del catálogo."
  type        = string
  default     = "arn:aws:iam::414351767826:role/unity-catalog-prod-UCMasterRole-14S5ZJVKOTYTL"
}

variable "uc_external_id" {
  description = "external_id de las storage credentials de la cuenta de Databricks (en terraform.tfvars, fuera de git)."
  type        = string
}
