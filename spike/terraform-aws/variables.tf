variable "aws_profile" {
  type    = string
  default = "tesseract"
}

variable "aws_region" {
  description = "Región del metastore de Unity Catalog (us-east-2)."
  type        = string
  default     = "us-east-2"
}

variable "uc_master_role_arn" {
  description = "Rol de Databricks que asume el rol propio (sale de la storage credential)."
  type        = string
  default     = "arn:aws:iam::414351767826:role/unity-catalog-prod-UCMasterRole-14S5ZJVKOTYTL"
}

variable "uc_external_id" {
  description = "external_id de la storage credential entity360-spike-s3."
  type        = string
  default     = "171da3f6-c865-458c-b614-c71d9267e2cb"
}
