from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from classiflow.database.base import Base


class AllowedUser(Base):
    __tablename__ = "allowed_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    node: Mapped[str] = mapped_column(String(100), nullable=False)
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)


class HashRecord(Base):
    __tablename__ = "hash_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    # onupdate fires only on ORM-level UPDATEs; Core session.execute(update(...))
    # bypasses it. Always include updated_at=func.now() in explicit .values() calls.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    failed_at_node: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_action_needed: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    steps: Mapped["list[DocumentStep]"] = relationship(
        "DocumentStep", back_populates="job", cascade="all, delete-orphan"
    )
    decisions: Mapped["list[HumanDecision]"] = relationship(
        "HumanDecision", back_populates="job", cascade="all, delete-orphan"
    )


class DocumentStep(Base):
    __tablename__ = "document_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    job: Mapped[Job] = relationship("Job", back_populates="steps")


class DocumentKb(Base):
    """Catalogue of documents indexed into the knowledge base.

    Also the source of truth for rebuilding the Chroma collection: everything needed
    to re-index (job, hash, chunk count and the document's own extracted metadata)
    lives here.
    """

    __tablename__ = "document_kb"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    year: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    # Nullable: rows created before this relationship existed cannot be backfilled
    # with a real match.
    enriched_record_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("enriched_records.id", ondelete="CASCADE"), nullable=True
    )


class HumanDecision(Base):
    __tablename__ = "human_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    decided_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    job: Mapped[Job] = relationship("Job", back_populates="decisions")


class EnrichedRecord(Base):
    __tablename__ = "enriched_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Stage 2's raw, pre-cleaning extraction output -- nullable because a migration
    # cannot backfill historical rows. Populated for every accepted job (unlike
    # Job.extracted_text, which only persists for non-accepted jobs) so it is
    # available for future embedding/analysis work.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Denormalized from the job, so this record is self-contained for indexing
    # (used by the KB indexing hook and the synchronize-kb backfill) without a join.
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entities: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    # Named metadata_ (not metadata) because `metadata` is reserved on every SQLAlchemy
    # Declarative class (Base.metadata is the schema's MetaData object) -- the DB column
    # itself is still named "metadata", only the Python attribute differs.
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ClassificationRecord(Base):
    __tablename__ = "classification_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    enriched_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("enriched_records.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    all_scores: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    second_opinion_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    second_opinion_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    classifier_disagreement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ood_metrics: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    svm_scores: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    svm_agrees_with_prediction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_route: Mapped[str] = mapped_column(String(20), nullable=False)
    smells: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    smell_review_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    foreign_municipality: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Whether the LLM Judge tier ran and produced the final review_route (spec Decision 6).
    judged_by_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Populated only when judged_by_llm=True (spec Decision 2's judge-as-advisory-opinion).
    judge_final_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    judge_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set by RoutingNode once the file has been moved to its final location (Decision 8).
    stored_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # review_route above is mutated to "accept" on review, which would erase whether the
    # safety net caught the miss. NULL means unknown, not "not escalated".
    machine_review_route: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Set by the human-decision endpoint (Decision 9).
    human_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The machine's prediction, preserved when a human overrides `label` -- that makes
    # each correction a labelled example.
    original_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Corpus ground truth (see classification/ground_truth.py). NULL means unknown, which
    # excludes the record from accuracy denominators.
    expected_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ConversationTurn(Base):
    """One question/answer pair in a user's chat history.

    Append-only: rows are never updated, and are only deleted by the explicit
    "clear conversation" action. The last RAW_WINDOW_SIZE rows for a user are sent
    verbatim in every chat prompt; older rows are folded into ConversationSummary
    instead but remain here as the source of truth.
    """

    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ConversationSummary(Base):
    """Running summary of a user's turns older than the raw prompting window.

    At most one row per user, overwritten in place each time a turn ages out of
    MemoryService.RAW_WINDOW_SIZE.
    """

    __tablename__ = "conversation_summaries"

    user_email: Mapped[str] = mapped_column(String(255), primary_key=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
