from pathlib import Path
from typing import TYPE_CHECKING

from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.coordinator import build_classification_coordinator
from classiflow.classification.domain.results import JudgeOutput, SecondOpinionResult
from classiflow.classification.nodes import (
    ConfidenceGateNode,
    ForeignMunicipalityNode,
    LlmJudgeNode,
    PrimaryClassifierNode,
    RoutingNode,
    SecondOpinionNode,
    SmellsRiskNode,
)
from classiflow.classification.prompts.llm_judge import JudgeInput, build_judge_chain
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
_DISAGREEING_SECOND_OPINION_CONFIDENCE = 0.996


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
        # Even though the judge accepts (judge_response defaults to accept), a
        # foreign_municipality flag forces HUMAN_REVIEW as the final outcome -- the
        # judge still runs (its verdict/reasoning is persisted as advisory signal),
        # per confidence_gate.forces_human_review's non-negotiable list.
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
        assert result["judged_by_llm"] is True
        assert Path("review", "human_review").as_posix() in Path(result["stored_path"]).as_posix()

        record = await repo.find_by_job_id("coord-human-001")
        assert record is not None
        assert record.review_route == "human_review"


_OTRO_HIGH_CONFIDENCE_RESPONSE = (
    '{"label": "otro", "confidence": 0.9, "reasoning": "not a municipal document"}'
)


class TestClassificationCoordinatorOtroPath:
    async def test_primary_otro_routes_to_human_review_via_judge(self, tmp_path: Path) -> None:
        # "otro" also forces HUMAN_REVIEW as the final outcome regardless of the
        # judge's verdict (judge_response defaults to accept), but per
        # confidence_gate.forces_human_review the judge still runs and its
        # verdict/reasoning is persisted as advisory signal.
        graph, repo = _build_graph(_OTRO_HIGH_CONFIDENCE_RESPONSE, tmp_path)
        job_id = "coord-otro-001"
        filename = "banco_central_circular.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "Banco Central de la República Argentina, Comunicación A 470.",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["review_route"] == "human_review"
        assert result["judged_by_llm"] is True
        assert Path("review", "human_review").as_posix() in Path(result["stored_path"]).as_posix()

        record = await repo.find_by_job_id(job_id)
        assert record is not None
        assert record.review_route == "human_review"
        assert record.label == "otro"
        assert record.judged_by_llm is True


class _DisagreeingClassifier:
    def predict(self, _text: str) -> SecondOpinionResult:
        return SecondOpinionResult(
            label="resolucion_concejo_municipal",
            confidence=_DISAGREEING_SECOND_OPINION_CONFIDENCE,
            svm_agrees_with_prediction=False,
        )


def _build_graph_with_disagreement(
    tmp_path: Path, *, judge_response: str
) -> tuple[object, InMemoryClassificationRecordRepository]:
    audit = AuditService(InMemoryAuditRepository())
    broadcaster = EventBroadcaster()
    config = ClassificationConfig(second_opinion_enabled=True, foreign_municipality_enabled=True)
    repo = InMemoryClassificationRecordRepository()
    storage = LocalDiskStorage(root=str(tmp_path))

    primary = PrimaryClassifierNode(
        audit=audit,
        broadcaster=broadcaster,
        classification_chain=build_classification_chain(
            MockLlm(response=_HIGH_CONFIDENCE_RESPONSE)
        ),
        config=config,
    )
    second_opinion = SecondOpinionNode(
        audit=audit, broadcaster=broadcaster, classifier=_DisagreeingClassifier(), config=config
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


class TestClassificationCoordinatorDisagreementPath:
    async def test_disagreement_reaches_judge_and_stays_human_review_even_when_judge_accepts(
        self, tmp_path: Path
    ) -> None:
        # Critical invariant: JudgeOutput.accept=True must NOT flip a disagreement
        # case to ACCEPT -- disagreement always stays HUMAN_REVIEW regardless of the
        # judge's verdict, per the spec's non-negotiable constraint.
        judge_accepts_response = (
            '{"accept": true, "final_label": "resoluciones_concejo_municipal", '
            '"reasoning": "second opinion is correct"}'
        )
        graph, repo = _build_graph_with_disagreement(
            tmp_path, judge_response=judge_accepts_response
        )
        job_id = "coord-disagreement-001"
        filename = "resolucion_cm.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "Artículo 1º — texto de una resolución del Concejo Municipal.",
            "enriched_id": 1,
        }
        result = await graph.ainvoke(initial)

        assert result["classifier_disagreement"] is True
        assert result["judged_by_llm"] is True
        assert result["review_route"] == "human_review"

        record = await repo.find_by_job_id(job_id)
        assert record is not None
        assert record.review_route == "human_review"
        assert record.classifier_disagreement is True

    async def test_judge_input_receives_ood_and_svm_signals(self, tmp_path: Path) -> None:
        captured: dict[str, JudgeInput] = {}

        class _CapturingJudgeChain:
            def invoke(self, inp: JudgeInput, **_kwargs: object) -> JudgeOutput:
                captured["input"] = inp
                return JudgeOutput(accept=False, final_label=inp.primary_label, reasoning="test")

        audit = AuditService(InMemoryAuditRepository())
        broadcaster = EventBroadcaster()
        config = ClassificationConfig(
            second_opinion_enabled=True, foreign_municipality_enabled=True
        )
        repo = InMemoryClassificationRecordRepository()
        storage = LocalDiskStorage(root=str(tmp_path))
        graph = build_classification_coordinator(
            PrimaryClassifierNode(
                audit=audit,
                broadcaster=broadcaster,
                classification_chain=build_classification_chain(
                    MockLlm(response=_HIGH_CONFIDENCE_RESPONSE)
                ),
                config=config,
            ),
            SecondOpinionNode(
                audit=audit,
                broadcaster=broadcaster,
                classifier=_DisagreeingClassifier(),
                config=config,
            ),
            ForeignMunicipalityNode(audit=audit, broadcaster=broadcaster, config=config),
            SmellsRiskNode(audit=audit, broadcaster=broadcaster, config=config),
            ConfidenceGateNode(audit=audit, broadcaster=broadcaster, config=config),
            LlmJudgeNode(audit=audit, broadcaster=broadcaster, judge_chain=_CapturingJudgeChain()),
            RoutingNode(
                audit=audit, broadcaster=broadcaster, storage=storage, classification_repo=repo
            ),
        )
        job_id = "coord-disagreement-002"
        filename = "resolucion_cm.pdf"
        _stage_file(tmp_path, job_id, filename)
        initial: ClassificationState = {
            "job_id": job_id,
            "filename": filename,
            "cleaned_text": "Artículo 1º — texto de una resolución del Concejo Municipal.",
            "enriched_id": 1,
        }
        await graph.ainvoke(initial)

        judge_input = captured["input"]
        assert judge_input.second_opinion_confidence == _DISAGREEING_SECOND_OPINION_CONFIDENCE
        assert judge_input.svm_agrees_with_prediction is False
