from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from classiflow.classification.bert.label_mapping import classifier_disagreement
from classiflow.classification.bert.ood_scorer import OodMetrics
from classiflow.classification.domain.results import RoutingInput
from classiflow.classification.domain.review_route import ReviewRoute
from classiflow.classification.domain.state import ClassificationState, ClassificationUpdate
from classiflow.classification.ground_truth import expected_label
from classiflow.classification.nodes.confidence_gate import ConfidenceGateNode
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.classification.nodes.llm_judge import LlmJudgeNode
from classiflow.classification.nodes.primary_classifier import PrimaryClassifierNode
from classiflow.classification.nodes.routing import RoutingNode
from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.classification.nodes.smells_risk import SmellsRiskNode
from classiflow.classification.prompts.llm_judge import JudgeInput
from classiflow.pipeline.context import JobContext

ClassificationUpdateValue = str | float | int | bool | dict[str, float] | OodMetrics | list[str]

# LangGraph node identifiers (add_node/add_conditional_edges targets) -- distinct
# concept from ReviewRoute despite the "llm_judge" name collision; these two graph
# node names never change and stay bare strings.
_LLM_JUDGE_NODE = "llm_judge"
_ROUTING_NODE = "routing"


def _dump(update: ClassificationUpdate) -> dict[str, ClassificationUpdateValue]:
    return {k: v for k, v in update if v is not None}


def _judge_review_route(*, judge_accepted: bool, forced_human_review: bool) -> ReviewRoute:
    # A forced-human-review reason (disagreement, foreign municipality, "otro") is
    # judged strictly higher-risk than low-confidence-alone: the judge's verdict is
    # still captured as advisory data (final_label/reasoning), but these cases NEVER
    # auto-accept no matter what the judge concludes. Only the low-confidence-alone
    # path still derives the route from JudgeOutput.accept.
    if forced_human_review:
        return ReviewRoute.HUMAN_REVIEW
    return ReviewRoute.ACCEPT if judge_accepted else ReviewRoute.HUMAN_REVIEW


def build_classification_coordinator(
    primary_classifier: PrimaryClassifierNode,
    second_opinion: SecondOpinionNode,
    foreign_municipality: ForeignMunicipalityNode,
    smells_risk: SmellsRiskNode,
    confidence_gate: ConfidenceGateNode,
    llm_judge: LlmJudgeNode,
    routing: RoutingNode,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    async def _primary_classifier(
        state: ClassificationState,
    ) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await primary_classifier.run(ctx, state["cleaned_text"])
        return _dump(
            ClassificationUpdate(
                label=result.label, confidence=result.confidence, all_scores=result.all_scores
            )
        )

    async def _second_opinion(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await second_opinion.run(ctx, state["cleaned_text"])
        if result is None:
            return {}
        return _dump(
            ClassificationUpdate(
                second_opinion_label=result.label,
                second_opinion_confidence=result.confidence,
                classifier_disagreement=classifier_disagreement(state["label"], result.label),
                ood_metrics=result.ood_metrics,
                svm_scores=result.svm_scores,
                svm_agrees_with_prediction=result.svm_agrees_with_prediction,
            )
        )

    async def _foreign_municipality(
        state: ClassificationState,
    ) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await foreign_municipality.run(ctx, state["cleaned_text"])
        return _dump(ClassificationUpdate(foreign_municipality=result))

    async def _smells_risk(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await smells_risk.run(
            ctx,
            cleaned_text=state["cleaned_text"],
            confidence=state["confidence"],
            classifier_disagreement=state.get("classifier_disagreement", False),
            foreign_municipality=state.get("foreign_municipality"),
            svm_agrees_with_prediction=state.get("svm_agrees_with_prediction", True),
        )
        return _dump(
            ClassificationUpdate(
                smells=result.smells,
                risk_score=result.risk_score,
                smell_review_suggested=result.smell_review_suggested,
            )
        )

    async def _confidence_gate(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        route = await confidence_gate.run(
            ctx,
            primary_label=state["label"],
            confidence=state["confidence"],
            foreign_municipality=state.get("foreign_municipality"),
            classifier_disagreement=state.get("classifier_disagreement", False),
            risk_score=state.get("risk_score", 0),
        )
        return _dump(ClassificationUpdate(review_route=route))

    async def _llm_judge(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        judge_input = JudgeInput(
            cleaned_text=state["cleaned_text"],
            primary_label=state["label"],
            primary_confidence=state["confidence"],
            second_opinion_label=state.get("second_opinion_label"),
            second_opinion_confidence=state.get("second_opinion_confidence"),
            ood_metrics=state.get("ood_metrics"),
            svm_agrees_with_prediction=state.get("svm_agrees_with_prediction", True),
            smells=state.get("smells", []),
            risk_score=state.get("risk_score", 0),
            foreign_municipality=state.get("foreign_municipality"),
        )
        result = await llm_judge.run(ctx, judge_input)
        forced_human_review = confidence_gate.forces_human_review(
            primary_label=state["label"],
            foreign_municipality=state.get("foreign_municipality"),
            classifier_disagreement=state.get("classifier_disagreement", False),
            risk_score=state.get("risk_score", 0),
        )
        review_route = _judge_review_route(
            judge_accepted=result.accept, forced_human_review=forced_human_review
        )
        return _dump(
            ClassificationUpdate(
                review_route=review_route,
                judged_by_llm=True,
                judge_final_label=result.final_label,
                judge_reasoning=result.reasoning,
            )
        )

    async def _routing(state: ClassificationState) -> dict[str, ClassificationUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        routing_input = RoutingInput(
            job_id=state["job_id"],
            filename=state["filename"],
            enriched_id=state["enriched_id"],
            label=state["label"],
            confidence=state["confidence"],
            all_scores=state.get("all_scores", {}),
            second_opinion_label=state.get("second_opinion_label"),
            second_opinion_confidence=state.get("second_opinion_confidence", 0.0),
            classifier_disagreement=state.get("classifier_disagreement", False),
            ood_metrics=state.get("ood_metrics"),
            svm_scores=state.get("svm_scores", {}),
            svm_agrees_with_prediction=state.get("svm_agrees_with_prediction", True),
            review_route=state["review_route"],
            smells=state.get("smells", []),
            risk_score=state.get("risk_score", 0),
            smell_review_suggested=state.get("smell_review_suggested", False),
            foreign_municipality=state.get("foreign_municipality"),
            judged_by_llm=state.get("judged_by_llm", False),
            judge_final_label=state.get("judge_final_label"),
            judge_reasoning=state.get("judge_reasoning"),
            # Weak label from the corpus filing convention, recorded alongside the
            # prediction so accuracy can be measured later without a manual pass.
            # None for anything the convention doesn't cover -- see ground_truth.py.
            expected_label=expected_label(state["filename"]),
        )
        result = await routing.run(ctx, routing_input)
        return _dump(ClassificationUpdate(stored_path=result.stored_path))

    def _route_after_gate(state: ClassificationState) -> str:
        return (
            _LLM_JUDGE_NODE if state.get("review_route") == ReviewRoute.LLM_JUDGE else _ROUTING_NODE
        )

    graph: StateGraph = StateGraph(ClassificationState)  # type: ignore[type-arg]
    graph.add_node("primary_classifier", _primary_classifier)
    graph.add_node("second_opinion", _second_opinion)
    graph.add_node("foreign_municipality", _foreign_municipality)
    graph.add_node("smells_risk", _smells_risk)
    graph.add_node("confidence_gate", _confidence_gate)
    graph.add_node("llm_judge", _llm_judge)
    graph.add_node("routing", _routing)

    graph.set_entry_point("primary_classifier")
    graph.add_edge("primary_classifier", "second_opinion")
    graph.add_edge("second_opinion", "foreign_municipality")
    graph.add_edge("foreign_municipality", "smells_risk")
    graph.add_edge("smells_risk", "confidence_gate")
    graph.add_conditional_edges(
        "confidence_gate",
        _route_after_gate,
        {_LLM_JUDGE_NODE: _LLM_JUDGE_NODE, _ROUTING_NODE: _ROUTING_NODE},
    )
    graph.add_edge("llm_judge", "routing")
    graph.add_edge("routing", END)

    return graph.compile()
