output "bucket_url" {
  value = "s3://${aws_s3_bucket.uc.bucket}/"
}

output "role_arn" {
  value = aws_iam_role.uc.arn
}
