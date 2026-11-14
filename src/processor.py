"""
Event-Driven AWS Worker for processing SEPA Invoices.

Connects to AWS (or Official AWS Emulator on port 9297):
1. Polls SQS queue for new invoice event messages.
2. Fetches raw invoice JSON from S3.
3. Validates German IBAN, 19% MwSt (VAT), and GwG AML rules (>= 10,000 EUR).
4. Writes immutable audit record to DynamoDB.
5. Publishes high-value AML alerts to SNS.
6. Leaves corrupted messages unacknowledged (visibility timeout = 0) so SQS
   automatically moves them to the Dead-Letter Queue (DLQ) after 3 attempts.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
import urllib3

from src.config import AppConfig
from src.validator import InvoiceValidationError, validate_sepa_invoice

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


class InvoiceEventProcessor:
    """Processes incoming SEPA invoice events across S3, SQS, DynamoDB, and SNS."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()

        client_kwargs: dict[str, Any] = {
            "region_name": self.config.aws_region,
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        }
        if self.config.aws_endpoint_url:
            client_kwargs["endpoint_url"] = self.config.aws_endpoint_url
            client_kwargs["verify"] = self.config.verify_ssl

        self.s3 = boto3.client("s3", **client_kwargs)
        self.sqs = boto3.client("sqs", **client_kwargs)
        self.dynamodb = boto3.resource("dynamodb", **client_kwargs)
        self.sns = boto3.client("sns", **client_kwargs)

    def _get_queue_url(self, queue_name: str) -> str:
        response = self.sqs.get_queue_url(QueueName=queue_name)
        return response["QueueUrl"]

    def _get_topic_arn(self, topic_name: str) -> str:
        response = self.sns.create_topic(Name=topic_name)
        return response["TopicArn"]

    def process_single_message(self) -> dict[str, Any]:
        """
        Poll one message from the primary SQS queue and process it end-to-end.

        Returns a status dictionary describing what happened:
        - {"status": "EMPTY"} if no message is in the queue.
        - {"status": "PROCESSED", "audit_record": ...} if valid.
        - {"status": "FAILED_VALIDATION", "error": ...} if invalid (triggers retry / DLQ).
        """
        queue_url = self._get_queue_url(self.config.sqs_queue_name)

        response = self.sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=1,
            AttributeNames=["ApproximateReceiveCount"],
        )

        messages = response.get("Messages", [])
        if not messages:
            return {"status": "EMPTY"}

        msg = messages[0]
        receipt_handle = msg["ReceiptHandle"]

        try:
            body = json.loads(msg["Body"])
            bucket = body.get("bucket", self.config.s3_bucket_name)
            s3_key = body["s3_key"]

            # 1. Fetch raw invoice JSON from Amazon S3
            s3_obj = self.s3.get_object(Bucket=bucket, Key=s3_key)
            raw_content = s3_obj["Body"].read().decode("utf-8")
            invoice_payload = json.loads(raw_content)

            # 2. Validate SEPA IBAN, 19% VAT, and AML threshold
            audit_record = validate_sepa_invoice(invoice_payload)
            audit_record["s3_key"] = s3_key

            # 3. Store immutable compliance record in Amazon DynamoDB
            table = self.dynamodb.Table(self.config.dynamodb_table_name)
            table.put_item(Item=audit_record)

            # 4. If invoice >= 10,000 EUR, publish alert to Amazon SNS
            if audit_record["aml_alert_required"]:
                topic_arn = self._get_topic_arn(self.config.sns_topic_name)
                self.sns.publish(
                    TopicArn=topic_arn,
                    Subject=f"AML Compliance Alert: Invoice {audit_record['invoice_id']}",
                    Message=json.dumps(audit_record),
                )

            # 5. Acknowledge & delete message from SQS upon successful processing
            self.sqs.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
            )

            return {
                "status": "PROCESSED",
                "audit_record": audit_record,
            }

        except (InvoiceValidationError, KeyError, json.JSONDecodeError) as exc:
            logger.warning("Invoice validation failed (Poison Pill): %s", exc)
            # Set VisibilityTimeout=0 so SQS immediately increments receive count
            # and moves the message to the Dead-Letter Queue (DLQ) after 3 failures
            self.sqs.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=0,
            )
            return {
                "status": "FAILED_VALIDATION",
                "error": str(exc),
            }
