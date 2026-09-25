variable "aws_profile" {
  description = "Perfil de AWS CLI (regla 00: siempre tesseract)."
  type        = string
  default     = "tesseract"
}

variable "aws_region" {
  description = "Región del productor SEC (regla 05)."
  type        = string
  default     = "us-east-1"
}

variable "sec_user_agent" {
  description = "User-Agent que exige la SEC: nombre y mail (en terraform.tfvars, fuera de git)."
  type        = string
}

variable "schedule_expression" {
  description = "Una vez por día (regla 05), 08:00 de Buenos Aires."
  type        = string
  default     = "cron(0 8 * * ? *)"
}

variable "schedule_timezone" {
  type    = string
  default = "America/Argentina/Buenos_Aires"
}

variable "volume_root" {
  description = "Raíz del landing en Unity Catalog (regla 01)."
  type        = string
  default     = "/Volumes/entity360/landing/raw"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "alert_email" {
  description = "Mail que recibe la alarma de la DLQ (en terraform.tfvars, fuera de git). La suscripción se confirma desde el mail."
  type        = string
}
