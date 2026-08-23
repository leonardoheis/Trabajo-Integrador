from classiflow.classification.config_classification import ClassificationConfig
from classiflow.classification.nodes.foreign_municipality import ForeignMunicipalityNode
from classiflow.database.repositories.audit import InMemoryAuditRepository
from classiflow.events.broadcaster import EventBroadcaster
from classiflow.pipeline.context import JobContext
from classiflow.services.audit.service import AuditService

_JOB_ID = "test-job-foreign-municipality-001"


def _node(config: ClassificationConfig) -> ForeignMunicipalityNode:
    return ForeignMunicipalityNode(
        audit=AuditService(InMemoryAuditRepository()), broadcaster=EventBroadcaster(), config=config
    )


class TestForeignMunicipalityDetect:
    def test_returns_none_for_trained_municipality(self) -> None:
        node = _node(
            ClassificationConfig(
                foreign_municipality_enabled=True, ood_trained_municipality="rosario"
            )
        )
        assert node.detect("La Municipalidad de Rosario informa...") is None

    def test_returns_name_for_a_different_municipality(self) -> None:
        node = _node(
            ClassificationConfig(
                foreign_municipality_enabled=True, ood_trained_municipality="rosario"
            )
        )
        assert node.detect("La Municipalidad de Cordoba informa...") == "Cordoba"

    def test_returns_none_when_disabled(self) -> None:
        node = _node(ClassificationConfig(foreign_municipality_enabled=False))
        assert node.detect("La Municipalidad de Cordoba informa...") is None


class TestForeignMunicipalityRun:
    async def test_run_emits_started_then_passed(self) -> None:
        broadcaster = EventBroadcaster()
        audit_repo = InMemoryAuditRepository()
        node = ForeignMunicipalityNode(
            audit=AuditService(audit_repo),
            broadcaster=broadcaster,
            config=ClassificationConfig(foreign_municipality_enabled=True),
        )
        ctx = JobContext(job_id=_JOB_ID, filename="doc.pdf")
        result = await node.run(ctx, "La Municipalidad de Cordoba informa...")
        assert result == "Cordoba"
        records = await audit_repo.list_for_job(_JOB_ID)
        assert records[0].event == "passed"
