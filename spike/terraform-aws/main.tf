# Spike A.4b: bucket propio para salir del default storage de Free Edition.

data "aws_caller_identity" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  bucket_name = "entity360-spike-uc-${local.account_id}"
  role_name   = "entity360-spike-uc"
  role_arn    = "arn:aws:iam::${local.account_id}:role/${local.role_name}"
}

resource "aws_s3_bucket" "uc" {
  bucket        = local.bucket_name
  force_destroy = true # bucket del spike: el destroy vacía y borra
}

resource "aws_s3_bucket_public_access_block" "uc" {
  bucket                  = aws_s3_bucket.uc.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uc" {
  bucket = aws_s3_bucket.uc.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "uc" {
  bucket = aws_s3_bucket.uc.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Trust: el UCMasterRole de Databricks con external_id, y el propio rol (Databricks exige
# que pueda asumirse a sí mismo). El self-trust va por condición sobre la cuenta, porque
# IAM rechaza un principal que todavía no existe al crear el rol.
data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "UnityCatalogMaster"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.uc_master_role_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.uc_external_id]
    }
  }

  statement {
    sid     = "SelfAssume"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [local.role_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.uc_external_id]
    }
  }
}

resource "aws_iam_role" "uc" {
  name               = local.role_name
  assume_role_policy = data.aws_iam_policy_document.trust.json
  description        = "Unity Catalog (Free Edition) -> bucket del spike entity360"
}

data "aws_iam_policy_document" "access" {
  statement {
    sid = "BucketObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.uc.arn}/*"]
  }

  statement {
    sid = "Bucket"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
      "s3:GetLifecycleConfiguration",
      "s3:PutLifecycleConfiguration",
    ]
    resources = [aws_s3_bucket.uc.arn]
  }

  statement {
    sid       = "SelfAssume"
    actions   = ["sts:AssumeRole"]
    resources = [local.role_arn]
  }
}

resource "aws_iam_role_policy" "uc" {
  name   = "entity360-spike-uc-s3"
  role   = aws_iam_role.uc.id
  policy = data.aws_iam_policy_document.access.json
}
