# ==============================================================================
# 1. AMAZON S3: Encrypted & Private Raw SEPA Invoice Storage
# ==============================================================================
resource "aws_s3_bucket" "invoices" {
  bucket        = "${var.project_name}-invoices-${var.environment}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "invoices_versioning" {
  bucket = aws_s3_bucket.invoices.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "invoices_encryption" {
  bucket = aws_s3_bucket.invoices.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Security Best Practice (Checked by Trivy/Checkov): Block all public access
resource "aws_s3_bucket_public_access_block" "invoices_public_block" {
  bucket = aws_s3_bucket.invoices.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ==============================================================================
# 2. AMAZON SQS: Main Event Queue + Dead-Letter Queue (DLQ) for Fault Tolerance
# ==============================================================================
resource "aws_sqs_queue" "invoice_dlq" {
  name                      = "${var.project_name}-invoice-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days retention for failed messages
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "invoice_queue" {
  name                       = "${var.project_name}-invoice-queue-${var.environment}"
  visibility_timeout_seconds = 30
  sqs_managed_sse_enabled    = true

  # Redrive Policy: Move poison-pill messages to DLQ after 3 failed processing attempts
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.invoice_dlq.arn
    maxReceiveCount     = 3
  })
}

# ==============================================================================
# 3. AMAZON DYNAMODB: Immutable SEPA Compliance & Audit Ledger
# ==============================================================================
resource "aws_dynamodb_table" "invoice_audit" {
  name         = "${var.project_name}-audit-ledger-${var.environment}"
  billing_mode = "PAY_PER_REQUEST" # Serverless on-demand pricing (€0 when idle)
  hash_key     = "invoice_id"

  attribute {
    name = "invoice_id"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ==============================================================================
# 4. AMAZON SNS: Real-Time Anti-Money Laundering (AML > 10,000 EUR) Alerts
# ==============================================================================
resource "aws_sns_topic" "aml_alerts" {
  name              = "${var.project_name}-aml-alerts-${var.environment}"
  kms_master_key_id = "alias/aws/sns"
}

# ==============================================================================
# 5. AWS IAM: Strict Least-Privilege Execution Role for Worker
# ==============================================================================
data "aws_iam_policy_document" "worker_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com", "ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "processor_worker_role" {
  name               = "${var.project_name}-worker-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.worker_assume_role.json
}

data "aws_iam_policy_document" "worker_least_privilege" {
  statement {
    sid     = "ReadInvoiceObjectsFromS3"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.invoices.arn,
      "${aws_s3_bucket.invoices.arn}/*"
    ]
  }

  statement {
    sid    = "ConsumeInvoiceQueueMessages"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility"
    ]
    resources = [aws_sqs_queue.invoice_queue.arn]
  }

  statement {
    sid       = "WriteComplianceAuditToDynamoDB"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.invoice_audit.arn]
  }

  statement {
    sid       = "PublishAMLAlertsToSNS"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.aml_alerts.arn]
  }
}

resource "aws_iam_role_policy" "processor_worker_policy" {
  name   = "${var.project_name}-worker-least-privilege-policy"
  role   = aws_iam_role.processor_worker_role.id
  policy = data.aws_iam_policy_document.worker_least_privilege.json
}
