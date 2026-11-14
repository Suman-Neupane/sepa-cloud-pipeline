"""
End-to-End Integration Tests against the Official AWS Emulator (https://127.0.0.1:9297).

Tests the real Terraform-provisioned AWS resources:
1. S3 -> SQS -> Worker -> DynamoDB Happy Path (APPROVED).
2. S3 -> SQS -> Worker -> DynamoDB + SNS AML Alert Path (FLAGGED_AML >= 10,000 EUR).
3. Chaos Engineering / Poison-Pill Test: Corrupted invoice fails 3 times and is
   automatically routed by SQS redrive policy to the Dead-Letter Queue (DLQ).
"""

import json
import uuid

import pytest

from src.config import AppConfig
from src.processor import InvoiceEventProcessor


def _drain_queue(sqs_client, queue_url: str) -> None:
    """Drain any leftover messages without triggering SQS PurgeQueue 60-second rate limit."""
    while True:
        resp = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
        )
        messages = resp.get("Messages", [])
        if not messages:
            break
        for msg in messages:
            sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])


@pytest.fixture
def processor() -> InvoiceEventProcessor:
    """Return an initialized InvoiceEventProcessor pointing to the AWS Emulator."""
    config = AppConfig()
    proc = InvoiceEventProcessor(config=config)

    # Clean queues before each test without hitting SQS PurgeQueue rate limits
    main_q = proc._get_queue_url(config.sqs_queue_name)
    dlq_q = proc._get_queue_url(config.sqs_dlq_name)
    _drain_queue(proc.sqs, main_q)
    _drain_queue(proc.sqs, dlq_q)
    return proc


def test_e2e_standard_invoice_stored_in_dynamodb(
    processor: InvoiceEventProcessor,
) -> None:
    """Upload valid SEPA invoice to S3, send SQS event, and verify DynamoDB audit record."""
    invoice_id = f"INV-OK-{uuid.uuid4().hex[:8]}"
    s3_key = f"incoming/{invoice_id}.json"
    invoice_data = {
        "invoice_id": invoice_id,
        "sender_iban": "DE89370400440532013000",
        "recipient_iban": "DE02120300000000202051",
        "net_amount": "500.00",
        "vat_amount": "95.00",
        "gross_amount": "595.00",
        "currency": "EUR",
    }

    # 1. Upload raw JSON to S3
    processor.s3.put_object(
        Bucket=processor.config.s3_bucket_name,
        Key=s3_key,
        Body=json.dumps(invoice_data).encode("utf-8"),
    )

    # 2. Enqueue event in SQS
    queue_url = processor._get_queue_url(processor.config.sqs_queue_name)
    processor.sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(
            {"bucket": processor.config.s3_bucket_name, "s3_key": s3_key}
        ),
    )

    # 3. Run the worker once
    result = processor.process_single_message()
    assert result["status"] == "PROCESSED"

    # 4. Verify record inside DynamoDB
    table = processor.dynamodb.Table(processor.config.dynamodb_table_name)
    db_resp = table.get_item(Key={"invoice_id": invoice_id})
    assert "Item" in db_resp
    assert db_resp["Item"]["compliance_status"] == "APPROVED"
    assert db_resp["Item"]["gross_amount"] == "595.00"


def test_e2e_aml_high_value_invoice_triggers_sns_alert(
    processor: InvoiceEventProcessor,
) -> None:
    """Verify invoices >= 10,000 EUR are flagged in DynamoDB and published to SNS."""
    invoice_id = f"INV-AML-{uuid.uuid4().hex[:8]}"
    s3_key = f"incoming/{invoice_id}.json"
    invoice_data = {
        "invoice_id": invoice_id,
        "sender_iban": "DE89370400440532013000",
        "recipient_iban": "DE02120300000000202051",
        "net_amount": "20000.00",
        "vat_amount": "3800.00",
        "gross_amount": "23800.00",
        "currency": "EUR",
    }

    processor.s3.put_object(
        Bucket=processor.config.s3_bucket_name,
        Key=s3_key,
        Body=json.dumps(invoice_data).encode("utf-8"),
    )

    queue_url = processor._get_queue_url(processor.config.sqs_queue_name)
    processor.sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(
            {"bucket": processor.config.s3_bucket_name, "s3_key": s3_key}
        ),
    )

    result = processor.process_single_message()
    assert result["status"] == "PROCESSED"
    assert result["audit_record"]["compliance_status"] == "FLAGGED_AML"
    assert result["audit_record"]["aml_alert_required"] is True


def test_e2e_poison_pill_message_routes_to_dlq_after_3_retries(
    processor: InvoiceEventProcessor,
) -> None:
    """
    Chaos Test: Upload an invalid invoice (corrupted VAT/IBAN) and verify that after
    maxReceiveCount = 3 failed attempts, SQS routes the message to the Dead-Letter Queue (DLQ).
    """
    invoice_id = f"INV-BAD-{uuid.uuid4().hex[:8]}"
    s3_key = f"incoming/{invoice_id}.json"
    corrupted_data = {
        "invoice_id": invoice_id,
        "sender_iban": "INVALID_IBAN",
        "recipient_iban": "DE02120300000000202051",
        "net_amount": "-999.00",
        "vat_amount": "0.00",
        "gross_amount": "-999.00",
        "currency": "EUR",
    }

    processor.s3.put_object(
        Bucket=processor.config.s3_bucket_name,
        Key=s3_key,
        Body=json.dumps(corrupted_data).encode("utf-8"),
    )

    queue_url = processor._get_queue_url(processor.config.sqs_queue_name)
    dlq_url = processor._get_queue_url(processor.config.sqs_dlq_name)

    processor.sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(
            {"bucket": processor.config.s3_bucket_name, "s3_key": s3_key}
        ),
    )

    # Attempt 1, 2, and 3 should all fail validation
    for attempt in range(1, 4):
        res = processor.process_single_message()
        assert (
            res["status"] == "FAILED_VALIDATION"
        ), f"Expected failure on attempt {attempt}"

    # Attempt 4 on main queue should be EMPTY because SQS moved it to the DLQ!
    empty_res = processor.process_single_message()
    assert empty_res["status"] == "EMPTY"

    # Verify the poison message is now sitting safely inside the Dead-Letter Queue (DLQ)
    dlq_messages = processor.sqs.receive_message(
        QueueUrl=dlq_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=1,
    ).get("Messages", [])

    assert len(dlq_messages) == 1
    dlq_body = json.loads(dlq_messages[0]["Body"])
    assert dlq_body["s3_key"] == s3_key
