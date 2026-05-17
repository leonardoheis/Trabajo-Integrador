"""Keyword-based document classifier for Spanish municipal documents."""
from __future__ import annotations

from models import DocumentType

# Spanish keyword lists per document type.
# Confidence is computed as: min(1.0, hit_ratio * 2) so that matching
# ≥ 50% of a type's keywords yields confidence ≥ 0.90.
_KEYWORDS: dict[DocumentType, list[str]] = {
    DocumentType.INVOICE: [
        "factura",
        "remito",
        "comprobante",
        "importe",
        "subtotal",
        "total",
        "vendedor",
        "proveedor",
        "cliente",
        "iva",
        "neto",
        "condición de pago",
        "precio unitario",
        "cantidad",
    ],
    DocumentType.CONTRACT: [
        "contrato",
        "acuerdo",
        "convenio",
        "cláusula",
        "obligación",
        "vigencia",
        "plazo",
        "rescisión",
        "parte contratante",
        "locación",
        "municipalidad",
        "servicio",
        "obra pública",
    ],
    DocumentType.TAX_FORM: [
        "declaración jurada",
        "ddjj",
        "afip",
        "impuesto",
        "contribuyente",
        "cuit",
        "gravado",
        "exento",
        "retención",
        "percepción",
        "tributo",
        "base imponible",
        "alícuota",
    ],
    DocumentType.REPORT: [
        "informe",
        "reporte",
        "análisis",
        "conclusión",
        "resumen ejecutivo",
        "diagnóstico",
        "resultados",
        "antecedentes",
        "recomendaciones",
        "período",
        "ejercicio",
        "gestión",
    ],
}


def classify(text: str) -> tuple[DocumentType, float]:
    """Return the most likely DocumentType and a confidence score in [0, 1].

    Returns (UNKNOWN, 0.0) when the text is empty or no keywords match.
    """
    if not text.strip():
        return DocumentType.UNKNOWN, 0.0

    lower = text.lower()
    scores: dict[DocumentType, float] = {
        doc_type: sum(1 for kw in keywords if kw in lower) / len(keywords)
        for doc_type, keywords in _KEYWORDS.items()
    }

    best_type = max(scores, key=lambda t: scores[t])
    best_score = scores[best_type]

    if best_score == 0.0:
        return DocumentType.UNKNOWN, 0.0

    confidence = round(min(1.0, best_score * 2.0), 4)
    return best_type, confidence
