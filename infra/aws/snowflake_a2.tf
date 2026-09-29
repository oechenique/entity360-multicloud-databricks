# Fase 9, Camino A2 (docs/fase9-plan.md §5): Snowflake lee Gold en S3 con un rol propio, de solo
# lectura, en vez de credenciales emitidas por Unity Catalog. Apagado por defecto: solo si el Camino A
# falla del lado de Snowflake.
#
# Dos pasos, como toda confianza con Snowflake: (1) crear el external volume en infra/snowflake con el
# ARN de este rol; (2) DESC EXTERNAL VOLUME da STORAGE_AWS_IAM_USER_ARN y STORAGE_AWS_EXTERNAL_ID, que
# van a estas variables, y un segundo apply fija la confianza.

variable "snowflake_a2" {
  description = "Crea el rol de solo lectura de Snowflake sobre Gold (Camino A2)."
  type        = bool
  default     = false
}

variable "snowflake_iam_user_arn" {
  description = "STORAGE_AWS_IAM_USER_ARN de DESC EXTERNAL VOLUME ENTITY360_GOLD_VOL."
  type        = string
  default     = ""
}

variable "snowflake_external_id" {
  description = "STORAGE_AWS_EXTERNAL_ID de DESC EXTERNAL VOLUME ENTITY360_GOLD_VOL."
  type        = string
  default     = ""
}

locals {
  a2_prefijo = "catalogs/entity360/"
}

data "aws_iam_policy_document" "snowflake_a2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type = "AWS"
      # Antes del paso 2 no hay usuario de Snowflake: la cuenta propia, así el rol se puede crear.
      identifiers = [var.snowflake_iam_user_arn != "" ? var.snowflake_iam_user_arn : "arn:aws:iam::${local.account_id}:root"]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.snowflake_external_id != "" ? var.snowflake_external_id : "pendiente-de-snowflake"]
    }
  }
}

resource "aws_iam_role" "snowflake_a2" {
  count              = var.snowflake_a2 ? 1 : 0
  name               = "entity360-snowflake-a2"
  assume_role_policy = data.aws_iam_policy_document.snowflake_a2_trust.json
  description        = "Snowflake lee Gold (Iceberg) del bucket del catálogo. Solo lectura. Camino A2."
}

data "aws_iam_policy_document" "snowflake_a2_lectura" {
  statement {
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.uc.arn}/${local.a2_prefijo}*"]
  }
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.uc.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.a2_prefijo}*"]
    }
  }
}

resource "aws_iam_role_policy" "snowflake_a2" {
  count  = var.snowflake_a2 ? 1 : 0
  name   = "gold-solo-lectura"
  role   = aws_iam_role.snowflake_a2[0].id
  policy = data.aws_iam_policy_document.snowflake_a2_lectura.json
}

output "snowflake_a2_role_arn" {
  value = var.snowflake_a2 ? aws_iam_role.snowflake_a2[0].arn : null
}
