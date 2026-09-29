variable "snowflake_profile" {
  description = "Conexión de ~/.snowflake/connections.toml (usuario de Terraform con key pair)."
  type        = string
  default     = "entity360"
}

variable "camino" {
  description = "A (Iceberg REST + vended credentials), A2 (Iceberg REST + external volume) o B (sync). La integración la crea snowflake/integracion.py (ADR 0012)."
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
