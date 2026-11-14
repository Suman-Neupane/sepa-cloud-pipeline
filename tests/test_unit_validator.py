"""Fast unit tests for German SEPA IBAN, 19% MwSt (VAT), and AML validation rules."""

import pytest

from src.validator import InvoiceValidationError, validate_sepa_invoice


def test_valid_standard_sepa_invoice_approved() -> None:
    """A valid invoice under 10,000 EUR with correct 19% VAT should be APPROVED."""
    payload = {
        "invoice_id": "INV-2026-0001",
        "sender_iban": "DE89 3704 0044 0532 0130 00",
        "recipient_iban": "DE02120300000000202051",
        "net_amount": "1000.00",
        "vat_amount": "190.00",
        "gross_amount": "1190.00",
        "currency": "EUR",
    }

    result = validate_sepa_invoice(payload)

    assert result["invoice_id"] == "INV-2026-0001"
    assert result["sender_iban"] == "DE89370400440532013000"
    assert result["compliance_status"] == "APPROVED"
    assert result["aml_alert_required"] is False


def test_high_value_sepa_invoice_flagged_for_aml() -> None:
    """An invoice >= 10,000 EUR gross must be flagged as FLAGGED_AML under German GwG."""
    payload = {
        "invoice_id": "INV-2026-9999",
        "sender_iban": "DE89370400440532013000",
        "recipient_iban": "DE02120300000000202051",
        "net_amount": "10000.00",
        "vat_amount": "1900.00",
        "gross_amount": "11900.00",
        "currency": "EUR",
    }

    result = validate_sepa_invoice(payload)

    assert result["compliance_status"] == "FLAGGED_AML"
    assert result["aml_alert_required"] is True


def test_invalid_german_iban_raises_error() -> None:
    """Non-German or malformed IBANs must raise InvoiceValidationError."""
    payload = {
        "invoice_id": "INV-2026-0002",
        "sender_iban": "INVALID_IBAN_123",
        "recipient_iban": "DE02120300000000202051",
        "net_amount": "100.00",
        "vat_amount": "19.00",
        "gross_amount": "119.00",
        "currency": "EUR",
    }

    with pytest.raises(InvoiceValidationError, match="Invalid German sender IBAN"):
        validate_sepa_invoice(payload)


def test_wrong_vat_calculation_raises_error() -> None:
    """Incorrect 19% MwSt calculation must raise InvoiceValidationError."""
    payload = {
        "invoice_id": "INV-2026-0003",
        "sender_iban": "DE89370400440532013000",
        "recipient_iban": "DE02120300000000202051",
        "net_amount": "100.00",
        "vat_amount": "7.00",  # Wrong VAT rate
        "gross_amount": "107.00",
        "currency": "EUR",
    }

    with pytest.raises(InvoiceValidationError, match="VAT \\(19% MwSt\\) mismatch"):
        validate_sepa_invoice(payload)
