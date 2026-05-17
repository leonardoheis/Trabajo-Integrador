from __future__ import annotations

import logging

from config import settings
from models import AzureAnalysisResult

logger = logging.getLogger(__name__)


def check_confidence(azure_result: AzureAnalysisResult) -> tuple[float, bool]:
    """Evaluate the confidence score from an Azure analysis result.

    Returns:
        (confidence_score, is_above_threshold)
    """
    score = azure_result.confidence
    threshold = settings.CONFIDENCE_THRESHOLD
    above = score >= threshold

    if above:
        logger.info(
            "Confidence check PASSED: score=%.4f threshold=%.4f doc_type=%s",
            score,
            threshold,
            azure_result.doc_type,
        )
    else:
        logger.warning(
            "Confidence check FAILED: score=%.4f is below threshold=%.4f "
            "for doc_type=%s — document will be routed to review queue.",
            score,
            threshold,
            azure_result.doc_type,
        )

    return score, above
