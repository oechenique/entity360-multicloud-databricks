# Alarma sobre la DLQ: cualquier mensaje significa que una Lambda agotó sus reintentos.

resource "aws_sns_topic" "alertas" {
  name = "${local.nombre}-alertas"
}

# Queda "PendingConfirmation" hasta que se confirma desde el mail (docs/manual-steps.md).
resource "aws_sns_topic_subscription" "mail" {
  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "dlq" {
  alarm_name          = "${local.nombre}-dlq-con-mensajes"
  alarm_description   = "Hay eventos fallidos en la DLQ del productor SEC EDGAR: revisar logs de las Lambdas."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alertas.arn]
  ok_actions          = [aws_sns_topic.alertas.arn]
}
