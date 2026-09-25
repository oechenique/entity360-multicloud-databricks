output "bucket" {
  value = aws_s3_bucket.raw.bucket
}

output "extractor_function" {
  value = aws_lambda_function.extractor.function_name
}

output "entrega_function" {
  value = aws_lambda_function.entrega.function_name
}

output "secret_id" {
  value = aws_secretsmanager_secret.databricks.name
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}
