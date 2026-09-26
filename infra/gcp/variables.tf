variable "project_id" {
  description = "Proyecto de GCP en modo sandbox (en terraform.tfvars, fuera de git)."
  type        = string
}

variable "github_repository" {
  description = "Repo de GitHub (owner/nombre) que puede autenticarse por Workload Identity Federation."
  type        = string
}

variable "bq_location" {
  description = "Ubicación del dataset de respaldo: la misma que gdelt-bq (US), para que la consulta y el load job corran juntos."
  type        = string
  default     = "US"
}
