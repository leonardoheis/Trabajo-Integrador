from __future__ import annotations

import logging
from typing import Any

from models import AzureAnalysisResult, DocumentType

logger = logging.getLogger(__name__)

# Expected fields per document type
_FIELD_SCHEMA: dict[DocumentType, list[str]] = {
    DocumentType.INVOICE: [
        "vendor_name",
        "vendor_address",
        "customer_name",
        "invoice_number",
        "invoice_date",
        "due_date",
        "amount_due",
        "sub_total",
        "tax_amount",
        "currency",
    ],
    DocumentType.CONTRACT: [
        "party_a",
        "party_b",
        "effective_date",
        "expiration_date",
        "contract_value",
        "governing_law",
        "jurisdiction",
    ],
    DocumentType.TAX_FORM: [
        "taxpayer_name",
        "taxpayer_id",
        "tax_year",
        "filing_status",
        "gross_income",
        "taxable_income",
        "tax_owed",
        "refund_amount",
    ],
    DocumentType.REPORT: [
        "title",
        "author",
        "date",
        "department",
        "summary",
        "period_covered",
    ],
    DocumentType.UNKNOWN: [],
}

# Azure field name aliases → normalized field names
_ALIAS_MAP: dict[str, str] = {
    "VendorName": "vendor_name",
    "VendorAddress": "vendor_address",
    "CustomerName": "customer_name",
    "InvoiceId": "invoice_number",
    "InvoiceDate": "invoice_date",
    "DueDate": "due_date",
    "AmountDue": "amount_due",
    "SubTotal": "sub_total",
    "TotalTax": "tax_amount",
    "CurrencyCode": "currency",
}


def extract_fields(
    azure_result: AzureAnalysisResult, doc_type: DocumentType
) -> dict[str, Any]:
    """Extract and normalize fields from an Azure analysis result.

    Missing expected fields are included with None and logged as WARNING.
    """
    raw_fields = azure_result.fields or {}
    expected = _FIELD_SCHEMA.get(doc_type, [])
    normalized: dict[str, Any] = {}

    # Normalize raw field names via alias map first
    for raw_key, value in raw_fields.items():
        norm_key = _ALIAS_MAP.get(raw_key, raw_key.lower())
        normalized[norm_key] = value

    # Ensure all expected fields are present
    output: dict[str, Any] = {}
    for field in expected:
        if field in normalized:
            output[field] = normalized[field]
        else:
            logger.warning(
                "Expected field '%s' not found for doc_type='%s'.",
                field,
                doc_type,
            )
            output[field] = None

    # Include any extra fields that were not in the schema
    for key, value in normalized.items():
        if key not in output:
            output[key] = value

    logger.info(
        "Field extraction complete for doc_type='%s': %d/%d expected fields found.",
        doc_type,
        sum(1 for v in output.values() if v is not None),
        len(expected),
    )
    return output
