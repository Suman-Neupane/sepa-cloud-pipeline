"""
Pure business logic for German/EU SEPA Invoice & AML Compliance validation.

Validates:
1. Required schema fields.
2. German IBAN format ('DE' + 20 digits = 22 characters).
3. German standard VAT (Mehrwertsteuer / MwSt = 19%).
4. German Anti-Money Laundering Act (Geldwäschegesetz - GwG) threshold (>= 10,000 EUR).
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict

GERMAN_IBAN_REGEX = re.compile(r"^DE\d{20}$")
GERMAN_VAT_RATE = Decimal("0.19")
AML_THRESHOLD_EUR = Decimal("10000.00")

REQUIRED_FIELDS = {
    "invoice_id",
    "sender_iban",
    "recipient_iban",
    "net_amount",
    "vat_amount",
    "gross_amount",
    "currency",
}


class InvoiceValidationError(ValueError):
    """Raised when an invoice payload is malformed, corrupted, or fails SEPA rules."""


def _to_cents(value: Any) -> Decimal:
    """Convert numeric input to a 2-decimal-place Decimal cleanly."""
    try:
        dec = Decimal(str(value))
        return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise InvoiceValidationError(f"Invalid numeric amount: {value}") from exc


def validate_sepa_invoice(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate a SEPA invoice dictionary and return an enriched audit record.

    Raises InvoiceValidationError if the payload is corrupted or violates SEPA/VAT rules,
    which signals the SQS worker to leave the message for retry / Dead-Letter Queue (DLQ).
    """
    if not isinstance(payload, dict):
        raise InvoiceValidationError("Payload must be a JSON object.")

    missing = REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise InvoiceValidationError(
            f"Missing required SEPA fields: {sorted(missing)}"
        )

    invoice_id = str(payload["invoice_id"]).strip()
    if not invoice_id:
        raise InvoiceValidationError("invoice_id cannot be empty.")

    currency = str(payload["currency"]).upper().strip()
    if currency != "EUR":
        raise InvoiceValidationError(
            f"Unsupported SEPA currency '{currency}'. Only 'EUR' is accepted."
        )

    sender_iban = str(payload["sender_iban"]).replace(" ", "").upper()
    recipient_iban = str(payload["recipient_iban"]).replace(" ", "").upper()

    if not GERMAN_IBAN_REGEX.match(sender_iban):
        raise InvoiceValidationError(
            f"Invalid German sender IBAN format: '{sender_iban}'. Expected DE + 20 digits."
        )
    if not GERMAN_IBAN_REGEX.match(recipient_iban):
        raise InvoiceValidationError(
            f"Invalid German recipient IBAN format: '{recipient_iban}'. Expected DE + 20 digits."
        )

    net_amount = _to_cents(payload["net_amount"])
    vat_amount = _to_cents(payload["vat_amount"])
    gross_amount = _to_cents(payload["gross_amount"])

    if net_amount <= Decimal("0.00"):
        raise InvoiceValidationError(
            f"net_amount must be strictly positive, got {net_amount}"
        )

    expected_vat = (net_amount * GERMAN_VAT_RATE).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if vat_amount != expected_vat:
        raise InvoiceValidationError(
            f"VAT (19% MwSt) mismatch: net {net_amount} EUR requires "
            f"{expected_vat} EUR VAT, but got {vat_amount} EUR."
        )

    expected_gross = net_amount + vat_amount
    if gross_amount != expected_gross:
        raise InvoiceValidationError(
            f"Gross amount mismatch: {net_amount} + {vat_amount} != {gross_amount} EUR."
        )

    # German GwG (Anti-Money Laundering) Check: Transactions >= 10,000 EUR require reporting
    is_aml_flagged = gross_amount >= AML_THRESHOLD_EUR
    compliance_status = "FLAGGED_AML" if is_aml_flagged else "APPROVED"

    return {
        "invoice_id": invoice_id,
        "sender_iban": sender_iban,
        "recipient_iban": recipient_iban,
        "net_amount": str(net_amount),
        "vat_amount": str(vat_amount),
        "gross_amount": str(gross_amount),
        "currency": currency,
        "compliance_status": compliance_status,
        "aml_alert_required": is_aml_flagged,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
