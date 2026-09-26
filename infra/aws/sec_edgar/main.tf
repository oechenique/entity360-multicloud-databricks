# Fase 3 (regla 05): productor AWS de SEC EDGAR.
# Scheduler -> Lambda extractor -> S3 (respaldo crudo) -> notificación -> Lambda entrega -> UC Volume.

data "aws_caller_identity" "current" {}

locals {
  nombre = "entity360-sec-edgar"
  bucket = "${local.nombre}-${data.aws_caller_identity.current.account_id}"
  codigo = "${path.module}/../../../producers/aws_sec_edgar"
}

# --------------------------------------------------------------------------- S3 (respaldo crudo)

# Sin force_destroy: el respaldo se vacía a propósito antes del destroy (docs/destroy.md).
resource "aws_s3_bucket" "raw" {
  bucket = local.bucket
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# --------------------------------------------------------------------------- DLQ y secreto

resource "aws_sqs_queue" "dlq" {
  name                      = "${local.nombre}-dlq"
  message_retention_seconds = 1209600 # 14 días (máximo de SQS)
  sqs_managed_sse_enabled   = true
}

# El valor (host, client_id, client_secret del SP) se carga fuera de Terraform con
# producers/aws_sec_edgar/credenciales.py, para que no quede en el state.
resource "aws_secretsmanager_secret" "databricks" {
  name                    = "entity360/databricks/producer-sec-edgar"
  description             = "OAuth M2M del SP entity360-producer-sec-edgar para la Lambda de entrega (SEC EDGAR)."
  recovery_window_in_days = 7
}

# --------------------------------------------------------------------------- IAM

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "extractor" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.extractor.arn}:*"]
  }
  statement {
    sid       = "Lotes"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/lotes/*"]
  }
  statement {
    sid       = "Estado"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/estado/*"]
  }
  statement {
    sid       = "EstadoInexistente" # sin ListBucket, un GetObject de algo que no existe da 403 y no NoSuchKey
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.raw.arn]
  }
  statement {
    sid       = "DLQ"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

data "aws_iam_policy_document" "entrega" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.entrega.arn}:*"]
  }
  statement {
    sid       = "LeerLotes"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.raw.arn}/lotes/*"]
  }
  statement {
    sid       = "Secreto"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.databricks.arn]
  }
  statement {
    sid       = "DLQ"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role" "extractor" {
  name               = "${local.nombre}-extractor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "extractor" {
  name   = "extractor"
  role   = aws_iam_role.extractor.id
  policy = data.aws_iam_policy_document.extractor.json
}

resource "aws_iam_role" "entrega" {
  name               = "${local.nombre}-entrega"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "entrega" {
  name   = "entrega"
  role   = aws_iam_role.entrega.id
  policy = data.aws_iam_policy_document.entrega.json
}

# --------------------------------------------------------------------------- Lambdas

data "archive_file" "extractor" {
  type        = "zip"
  output_path = "${path.module}/build/extractor.zip"
  source {
    content  = file("${local.codigo}/extractor.py")
    filename = "extractor.py"
  }
  source {
    content  = file("${local.codigo}/universo.json")
    filename = "universo.json"
  }
}

data "archive_file" "entrega" {
  type        = "zip"
  output_path = "${path.module}/build/entrega.zip"
  source {
    content  = file("${local.codigo}/entrega.py")
    filename = "entrega.py"
  }
}

resource "aws_cloudwatch_log_group" "extractor" {
  name              = "/aws/lambda/${local.nombre}-extractor"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "entrega" {
  name              = "/aws/lambda/${local.nombre}-entrega"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "extractor" {
  function_name    = "${local.nombre}-extractor"
  role             = aws_iam_role.extractor.arn
  runtime          = "python3.13"
  handler          = "extractor.lambda_handler"
  filename         = data.archive_file.extractor.output_path
  source_code_hash = data.archive_file.extractor.output_base64sha256
  timeout          = 120
  memory_size      = 256
  environment {
    variables = {
      BUCKET         = aws_s3_bucket.raw.bucket
      SEC_USER_AGENT = var.sec_user_agent
    }
  }
  depends_on = [aws_cloudwatch_log_group.extractor]
}

resource "aws_lambda_function" "entrega" {
  function_name    = "${local.nombre}-entrega"
  role             = aws_iam_role.entrega.arn
  runtime          = "python3.13"
  handler          = "entrega.lambda_handler"
  filename         = data.archive_file.entrega.output_path
  source_code_hash = data.archive_file.entrega.output_base64sha256
  timeout          = 120
  memory_size      = 256
  environment {
    variables = {
      SECRET_ID   = aws_secretsmanager_secret.databricks.arn
      VOLUME_ROOT = var.volume_root
    }
  }
  depends_on = [aws_cloudwatch_log_group.entrega]
}

# Invocaciones asíncronas (Scheduler y S3): 2 reintentos y, si fallan, a la DLQ.
resource "aws_lambda_function_event_invoke_config" "extractor" {
  function_name          = aws_lambda_function.extractor.function_name
  maximum_retry_attempts = 2
  destination_config {
    on_failure {
      destination = aws_sqs_queue.dlq.arn
    }
  }
}

resource "aws_lambda_function_event_invoke_config" "entrega" {
  function_name          = aws_lambda_function.entrega.function_name
  maximum_retry_attempts = 2
  destination_config {
    on_failure {
      destination = aws_sqs_queue.dlq.arn
    }
  }
}

# --------------------------------------------------------------------------- disparadores

# La creación de un manifest en lotes/ dispara la entrega (los .jsonl no terminan en ".json").
resource "aws_lambda_permission" "s3_entrega" {
  statement_id  = "s3-invoca-entrega"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.entrega.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.raw.arn
}

resource "aws_s3_bucket_notification" "manifest" {
  bucket = aws_s3_bucket.raw.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.entrega.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "lotes/"
    filter_suffix       = ".json"
  }
  depends_on = [aws_lambda_permission.s3_entrega]
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.extractor.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.nombre}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "scheduler"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "diario" {
  name                         = "${local.nombre}-diario"
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.extractor.arn
    role_arn = aws_iam_role.scheduler.arn
    retry_policy {
      maximum_retry_attempts = 2
    }
    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }
}
