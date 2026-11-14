"""Environment configuration for the SEPA Invoice Processor."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """Immutable configuration loaded from environment variables."""

    aws_region: str = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
    aws_endpoint_url: str = os.getenv("AWS_ENDPOINT_URL", "https://127.0.0.1:9297")
    verify_ssl: bool = os.getenv("AWS_VERIFY_SSL", "false").lower() == "true"

    s3_bucket_name: str = os.getenv("S3_INVOICES_BUCKET", "sepa-fintech-invoices-local")
    sqs_queue_name: str = os.getenv(
        "SQS_INVOICE_QUEUE", "sepa-fintech-invoice-queue-local"
    )
    sqs_dlq_name: str = os.getenv("SQS_INVOICE_DLQ", "sepa-fintech-invoice-dlq-local")
    dynamodb_table_name: str = os.getenv(
        "DYNAMODB_AUDIT_TABLE", "sepa-fintech-audit-ledger-local"
    )
    sns_topic_name: str = os.getenv("SNS_AML_TOPIC", "sepa-fintech-aml-alerts-local")
