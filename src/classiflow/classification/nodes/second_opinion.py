import asyncio
from functools import lru_cache
from typing import Protocol, cast, runtime_checkable

from classiflow.classification.bert.classifier import BertClassifier
from classiflow.classification.config_classification import (
    ClassificationConfig,
    get_classification_config,
)
from classiflow.classification.domain.results import SecondOpinionResult
from classiflow.database.repositories.audit import AuditDetail
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.model_cache import evict_lru_cache
from classiflow.pipeline.base import BaseNode
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService
from classiflow.settings import PROJECT_ROOT


@runtime_checkable
class _Classifier(Protocol):
    def predict(self, text: str) -> SecondOpinionResult: ...


@lru_cache(maxsize=1)
def _load_bert_classifier(model_path: str) -> BertClassifier:
    # Same cached-singleton-loader shape as node4_duplicate_control.py's
    # get_sentence_model() -- the BETO weights + OOD/SVM artifacts are expensive to load
    # (~425MB) and are read fresh from config only on the first call.
    return BertClassifier(model_path, get_classification_config())


def unload_bert() -> None:
    # BETO moves itself onto CUDA and would otherwise stay resident for the process
    # lifetime. On an 8GB card that permanently shrinks the budget below what the next
    # job's ~4.8GB GGUF needs, so job 1 succeeds and job 2 fails to load its model.
    evict_lru_cache(_load_bert_classifier)


class SecondOpinionNode(BaseNode):
    @property
    def name(self) -> str:
        return "classification_second_opinion"

    def __init__(
        self,
        audit: AuditService,
        broadcaster: EventBroadcaster,
        *,
        classifier: _Classifier | None = None,
        config: ClassificationConfig | None = None,
    ) -> None:
        super().__init__(audit, broadcaster)
        self.classifier: _Classifier | None = classifier
        self.config: ClassificationConfig = (
            config if config is not None else get_classification_config()
        )

    async def run(self, ctx: JobContext, cleaned_text: str) -> SecondOpinionResult | None:
        if not self.config.second_opinion_enabled:
            return None
        start = await self._emit_started(ctx)
        result = await asyncio.to_thread(self._predict, cleaned_text)
        await self._emit_and_audit(
            ctx,
            start,
            passed=True,
            detail=AuditDetail.model_validate({
                "filename": ctx.filename,
                "label": result.label,
                "confidence": result.confidence,
                "svm_agrees_with_prediction": result.svm_agrees_with_prediction,
            }),
        )
        return result

    def _predict(self, cleaned_text: str) -> SecondOpinionResult:
        classifier: _Classifier
        if self.classifier is not None:
            classifier = self.classifier
        else:
            classifier = cast(
                "_Classifier",
                _load_bert_classifier(str(PROJECT_ROOT / self.config.bert_model_path)),
            )
        return classifier.predict(cleaned_text)
