variable "snowflake_profile" {
  description = "Conexión de ~/.snowflake/connections.toml (usuario de Terraform con key pair)."
  type        = string
  default     = "entity360"
}

variable "camino" {
  description = "A (Iceberg REST + vended credentials), A2 (Iceberg REST + external volume) o B (sync)."
  type        = string
  default     = "A"

  validation {
    condition     = contains(["A", "A2", "B"], var.camino)
    error_message = "camino tiene que ser A, A2 o B."
  }
}

variable "creditos_mensuales" {
  description = "Tope del resource monitor, en créditos por mes (docs/fase9-plan.md §6)."
  type        = number
  default     = 20
}

# --- Caminos A y A2: catalog integration contra Unity Catalog ---------------------------------

variable "databricks_workspace_url" {
  description = "URL del workspace, con https:// (en terraform.tfvars, fuera de git): <WORKSPACE_URL>."
  type        = string
  default     = ""
}

variable "uc_sp_client_id" {
  description = "application_id del SP entity360-snowflake (output de infra/databricks)."
  type        = string
  default     = ""
}

variable "uc_sp_client_secret" {
  description = "Secreto OAuth del SP. Solo por TF_VAR_uc_sp_client_secret, nunca en tfvars (termina en el state local)."
  type        = string
  default     = ""
  sensitive   = true
}

# --- Camino A2: external volume sobre el bucket del catálogo ----------------------------------

variable "a2_bucket_url" {
  description = "Raíz de Gold en S3: s3://entity360-uc-<AWS_ACCOUNT_ID>/catalogs/entity360/."
  type        = string
  default     = ""
}

variable "a2_role_arn" {
  description = "Rol IAM de solo lectura que asume Snowflake (infra/aws/snowflake_a2.tf)."
  type        = string
  default     = ""
}
