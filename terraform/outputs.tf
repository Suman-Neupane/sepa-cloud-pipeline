output "s3_invoices_bucket_name" {
  description = "Name of the S3 bucket storing raw SEPA invoice payloads"
  value       = aws_s3_bucket.invoices.id
}

output "sqs_invoice_queue_url" {
  description = "URL of the primary SQS invoice processing queue"
  value       = aws_sqs_queue.invoice_queue.url
}

output "sqs_invoice_dlq_url" {
  description = "URL of the SQS Dead-Letter Queue (DLQ) for failed/poison messages"
  value       = aws_sqs_queue.invoice_dlq.url
}

output "dynamodb_audit_table_name" {
  description = "Name of the DynamoDB table storing SEPA compliance audit records"
  value       = aws_dynamodb_table.invoice_audit.name
}

output "sns_aml_alerts_topic_arn" {
  description = "ARN of the SNS topic for German GwG/AML high-value transaction alerts"
  value       = aws_sns_topic.aml_alerts.arn
}

output "worker_iam_role_arn" {
  description = "ARN of the least-privilege IAM role for the invoice processor worker"
  value       = aws_iam_role.processor_worker_role.arn
}

output "kms_cmk_arn" {
  description = "ARN of the Customer Managed Key (CMK) for GDPR/FinTech encryption"
  value       = aws_kms_key.fintech_kms_key.arn
}
