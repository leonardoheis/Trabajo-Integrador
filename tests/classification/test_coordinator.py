from pathlib import Path
from typing import TYPE_CHECKING

from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.coordinator import build_classification_coordinator
from classiflow.classification.domain.results import SecondOpinionResult
from classiflow.classification.nodes import (
    ConfidenceGateNode,
    ForeignMunicipalityNode,
    LlmJudgeNode,
    PrimaryClassifierNode,
    RoutingNode,
    SecondOpinionNode,
    SmellsRiskNode,
)
from classiflow.classification.prompts.llm_judge import build_judge_chain
from classiflow.classification.prompts.primary_classification import build_classification_chain
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.database.repositories.classification_record import (
    InMemoryClassificationRecordRepository,
)
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.ingesta.llm_provider import MockLlm
from classiflow.services.audit.service import AuditService
from classiflow.storage.document_storage import LocalDiskStorage

if TYPE_CHECKING:
    from classiflow.classification.domain.state import ClassificationState

_HIGH_CONFIDENCE_RESPONSE = '{"label": "ordenanzas", "confidence": 0.95, "reasoning": "..."}'
_LOW_CONFIDENCE_RESPONSE = '{"label": "ordenanzas", "confidence": 0.3, "reasoning": "..."}'
_JUDGE_ACCEPT_RESPONSE = '{"accept": true, "final_label": "ordenanzas", "reasoning": "confirmed"}'


class _NoSecondOpinionClassifier:
    def predict(self, _text: str) -> SecondOpinionResult:
        msg = "should not be called when second_opinion_enabled is False"
        raise AssertionError(msg)


def _build_graph(
    primary_response: str, tmp_path: Path, *, judge_response: str = _JUDGE_ACCEPT_RESPONSE
) -> tuple[object, InMemoryClassificationRecordRepository]:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    config = ClassificationConfig(second_opinion_enabled=False, foreign_municipality_enabled=True)
    repo = InMemoryClassificationRecordRepository()
    storage = LocalDiskStorage(root=str(tmp_path))

    primary = PrimaryClassifierNode(
        audit=audit,
        broadcaster=broadcaster,
        classification_chain=build_classification_chain(MockLlm(response=primary_response)),
        config=config,
    )
    second_opinion = SecondOpinionNode(
        audit=audit, broadcaster=broadcaster, classifier=_NoSecondOpinionClassifier(), config=config
    )
    foreign_municipality = ForeignMunicipalityNode(
        audit=audit, broadcaster=broadcaster, config=config
    )
    smells_risk = SmellsRiskNode(audit=audit, broadcaster=broadcaster, config=config)
    confidence_gate = ConfidenceGateNode(audit=audit, broadcaster=broadcaster, config=config)
    llm_judge = LlmJudgeNode(
        audit=audit,
        broadcaster=broadcaster,
        judge_chain=build_judge_chain(MockLlm(response=judge_response)),
    )
    routing = RoutingNode(
        audit=audit, broadcaster=broadcaster, storage=storage, classification_repo=repo
    )
    graph = build_classification_coordinator(
        primary,
        second_opinion,
        foreign_municipality,
        smells_risk,
        confidence_gate,
        llm_judge,
        routing,
    )
    return graph, repo


def _stage_file(tmp_path: Path, job_id: str, filename: str) -> None:
    # RoutingNode's move_to_final expects the source document to already be
    # staged (Task 2's ingestion flow does this in production) -- the graph
    # itself never writes bytes, so tests must seed it directly.
    staged_path = tmp_path / "staging" / f"{job_id}_{filename}"
    staged_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path.write_bytes(b"dummy content")


class TestClassificationCoordinatorAcceptPath:
    async def test_high_confidence_document_is_accepted_and_routed(self, tmp_path: Path) -> None:
        graph, repo = _build_graph(_HIGH_CONFIDENCE_RESPONSE, tmp_path)
        job_id = "coord-accept-001"
        filename = "ordenanza.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "Artículo 1º — texto de una ordenanza de Rosario.",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["review_route"] == "accept"
        # judged_by_llm is only ever set when the llm_judge branch actually ran
        # (ClassificationState is total=False) -- absent here means "never judged",
        # not "judged and rejected".
        assert result.get("judged_by_llm", False) is False
        assert Path("classified", "ordenanzas").as_posix() in Path(result["stored_path"]).as_posix()

        record = await repo.find_by_job_id("coord-accept-001")
        assert record is not None
        assert record.review_route == "accept"


class TestClassificationCoordinatorLlmJudgePath:
    async def test_low_confidence_routes_through_judge_to_accept(self, tmp_path: Path) -> None:
        graph, repo = _build_graph(_LOW_CONFIDENCE_RESPONSE, tmp_path)
        job_id = "coord-judge-001"
        filename = "ordenanza.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "Artículo 1º — texto de una ordenanza de Rosario.",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["review_route"] == "accept"
        assert result["judged_by_llm"] is True

        record = await repo.find_by_job_id("coord-judge-001")
        assert record is not None
        assert record.judged_by_llm is True


class TestClassificationCoordinatorHumanReviewPath:
    async def test_foreign_municipality_routes_to_human_review(self, tmp_path: Path) -> None:
        graph, repo = _build_graph(_HIGH_CONFIDENCE_RESPONSE, tmp_path)
        job_id = "coord-human-001"
        filename = "ordenanza.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "La Municipalidad de Cordoba informa...",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["review_route"] == "human_review"
        assert Path("review", "human_review").as_posix() in Path(result["stored_path"]).as_posix()

        record = await repo.find_by_job_id("coord-human-001")
        assert record is not None
        assert record.review_route == "human_review"
