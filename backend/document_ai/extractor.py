"""Regex-based field extractor for Spanish municipal documents."""
from __future__ import annotations

import re
from typing import Any

from models import DocumentType

# ── Shared patterns ────────────────────────────────────────────────────────────

_DATE = re.compile(
    r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
    r"|\d{1,2}\s+de\s+\w+\s+de\s+\d{4})\b",
    re.IGNORECASE,
)
_AMOUNT = re.compile(r"\$\s*([\d.,]+)|\b([\d.,]+)\s*pesos\b", re.IGNORECASE)
_CUIT = re.compile(r"\b(\d{2}-\d{7,8}-\d)\b")

# ── Invoice patterns ───────────────────────────────────────────────────────────

_VENDOR = re.compile(r"(?:vendedor|proveedor|razón social)[:\s]+([^\n]+)", re.IGNORECASE)
_INVOICE_NUM = re.compile(r"\bn[°º]?\s*([\d]{3,}[-\d]*)\b", re.IGNORECASE)
_CUSTOMER = re.compile(r"(?:cliente|comprador|destinatario)[:\s]+([^\n]+)", re.IGNORECASE)

# ── Contract patterns ──────────────────────────────────────────────────────────

_PARTY_A = re.compile(r"(?:primera parte|parte a|contratante)[:\s]+([^\n]+)", re.IGNORECASE)
_PARTY_B = re.compile(r"(?:segunda parte|parte b|contratado)[:\s]+([^\n]+)", re.IGNORECASE)
_GOV_LAW = re.compile(r"(?:ley aplicable|derecho aplicable|legislación)[:\s]+([^\n]+)", re.IGNORECASE)

# ── Tax form patterns ──────────────────────────────────────────────────────────

_TAXPAYER = re.compile(r"(?:contribuyente|denominación|razón social)\s*:\s*([^\n]+)", re.IGNORECASE)
_TAX_YEAR = re.compile(
    r"(?:período\s+fiscal|ejercicio\s+fiscal|período|ejercicio|año)\s*:\s*(\d{4})",
    re.IGNORECASE,
)

# ── Report patterns ────────────────────────────────────────────────────────────

_TITLE = re.compile(r"(?:informe|reporte)[:\s]+([^\n]+)", re.IGNORECASE)
_AUTHOR = re.compile(r"(?:autor|elaborado por|preparado por)\s*:\s*([^\n]+)", re.IGNORECASE)
_DEPT = re.compile(r"(?:área|departamento|secretaría|dirección)\s*:\s*([^\n]+)", re.IGNORECASE)


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_fields(text: str, doc_type: DocumentType) -> dict[str, Any]:
    """Extract raw fields from text according to document type.

    Returns an empty dict for UNKNOWN documents.
    Field names match the Azure alias map in agents/field_extractor.py so
    existing normalization continues to work unchanged.
    """
    if doc_type == DocumentType.UNKNOWN:
        return {}

    dates = [m for m in _DATE.findall(text)]
    flat_amounts = [m[0] or m[1] for m in _AMOUNT.findall(text)]

    if doc_type == DocumentType.INVOICE:
        return _invoice(text, dates, flat_amounts)
    if doc_type == DocumentType.CONTRACT:
        return _contract(text, dates, flat_amounts)
    if doc_type == DocumentType.TAX_FORM:
        return _tax_form(text, dates, flat_amounts)
    if doc_type == DocumentType.REPORT:
        return _report(text, dates)
    return {}  # pragma: no cover


def _first_match(pattern: re.Pattern[str], text: str, group: int = 1) -> str | None:
    m = pattern.search(text)
    return m.group(group).strip() if m else None


def _invoice(text: str, dates: list[str], amounts: list[str]) -> dict[str, Any]:
    return {
        "VendorName": _first_match(_VENDOR, text),
        "CustomerName": _first_match(_CUSTOMER, text),
        "InvoiceId": _first_match(_INVOICE_NUM, text),
        "InvoiceDate": dates[0] if dates else None,
        "DueDate": dates[1] if len(dates) > 1 else None,
        "AmountDue": amounts[-1] if amounts else None,
        "SubTotal": amounts[0] if amounts else None,
        "CurrencyCode": "ARS",
        "TaxpayerId": _first_match(_CUIT, text),
    }


def _contract(text: str, dates: list[str], amounts: list[str]) -> dict[str, Any]:
    return {
        "party_a": _first_match(_PARTY_A, text),
        "party_b": _first_match(_PARTY_B, text),
        "effective_date": dates[0] if dates else None,
        "expiration_date": dates[1] if len(dates) > 1 else None,
        "contract_value": amounts[0] if amounts else None,
        "governing_law": _first_match(_GOV_LAW, text),
    }


def _tax_form(text: str, dates: list[str], amounts: list[str]) -> dict[str, Any]:
    return {
        "taxpayer_name": _first_match(_TAXPAYER, text),
        "taxpayer_id": _first_match(_CUIT, text),
        "tax_year": _first_match(_TAX_YEAR, text),
        "filing_status": dates[0] if dates else None,
        "tax_owed": amounts[-1] if amounts else None,
        "refund_amount": None,
    }


def _report(text: str, dates: list[str]) -> dict[str, Any]:
    return {
        "title": _first_match(_TITLE, text),
        "author": _first_match(_AUTHOR, text),
        "date": dates[0] if dates else None,
        "department": _first_match(_DEPT, text),
    }
