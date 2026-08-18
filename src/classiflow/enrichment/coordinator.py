from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from classiflow.enrichment.domain.results import (
    EntityExtractionResult,
    MetadataEnrichmentResult,
    TextCleaningResult,
)
from classiflow.enrichment.domain.state import EnrichmentState, EnrichmentUpdate
from classiflow.enrichment.nodes import EntityExtractorNode, MetadataEnricherNode, TextCleanerNode
from classiflow.pipeline.context import JobContext

EnrichmentUpdateValue = str | TextCleaningResult | EntityExtractionResult | MetadataEnrichmentResult


def _dump(update: EnrichmentUpdate) -> dict[str, EnrichmentUpdateValue]:
    return {k: v for k, v in update if v is not None}


def build_enrichment_coordinator(
    text_cleaner: TextCleanerNode,
    entity_extractor: EntityExtractorNode,
    metadata_enricher: MetadataEnricherNode,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    async def _clean(state: EnrichmentState) -> dict[str, EnrichmentUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await text_cleaner.run(ctx, state["text"])
        return _dump(EnrichmentUpdate(cleaning=result, cleaned_text=result.cleaned_text))

    async def _extract(state: EnrichmentState) -> dict[str, EnrichmentUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await entity_extractor.run(ctx, state["cleaned_text"])
        return _dump(EnrichmentUpdate(entities=result))

    async def _enrich(state: EnrichmentState) -> dict[str, EnrichmentUpdateValue]:
        ctx = JobContext(job_id=state["job_id"], filename=state["filename"])
        result = await metadata_enricher.run(
            ctx,
            filename=state["filename"],
            language=state["language"],
            sha256=state["sha256"],
            stage2_extractor_used=state["stage2_extractor_used"],
        )
        return _dump(EnrichmentUpdate(metadata=result))

    graph: StateGraph = StateGraph(EnrichmentState)  # type: ignore[type-arg]
    graph.add_node("clean", _clean)
    graph.add_node("extract", _extract)
    graph.add_node("enrich", _enrich)
    graph.set_entry_point("clean")
    graph.add_edge("clean", "extract")
    graph.add_edge("extract", "enrich")
    graph.add_edge("enrich", END)

    return graph.compile()
