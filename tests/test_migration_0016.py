"""Upgrade behaviour for revision 0016 (original_label recovered from the audit log).

Runs against a throwaway SQLite file, never `data/classiflow.db`.
"""

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from classiflow.settings import Settings

_PROJECT_ROOT = Path(__file__).parents[1]

_EXPECTED_RECOVERED_ROWS = 3


def _alembic_config() -> Config:
    config = Config(str(_PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    return config


def _seed_0015_shaped_rows(database_path: Path) -> None:
    """Insert records and their audit trail as revision 0015 leaves them."""
    connection = sqlite3.connect(database_path)
    cases = [
        # job_id, label, human_overridden, original_label, audit predictions
        ("corrected", "convenios", 1, None, ["otro"]),
        ("confirmed", "boletines", 1, None, ["boletines"]),
        ("mislabelled", "convenios", 1, "ordenanzas", ["convenios"]),
        ("untouched", "decretos", 0, None, ["ordenanzas"]),
        ("no-audit", "ordenanzas", 1, None, []),
    ]
    for job_id, label, overridden, original, predictions in cases:
        connection.execute(
            "INSERT INTO jobs (job_id, filename, status) VALUES (?, ?, 'classified')",
            (job_id, f"{job_id}.pdf"),
        )
        connection.execute(
            """INSERT INTO enriched_records (job_id, cleaned_text, entities, metadata)
               VALUES (?, 'texto', '{}', '{}')""",
            (job_id,),
        )
        enriched_id = connection.execute(
            "SELECT id FROM enriched_records WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO classification_records
               (job_id, enriched_id, label, confidence, all_scores, second_opinion_confidence,
                classifier_disagreement, svm_scores, svm_agrees_with_prediction, review_route,
                smells, risk_score, smell_review_suggested, judged_by_llm, human_overridden,
                original_label)
               VALUES (?, ?, ?, 0.9, '{}', 0.0, 0, '{}', 1, 'accept', '[]', 0, 0, 0, ?, ?)""",
            (job_id, enriched_id, label, overridden, original),
        )
        for index, prediction in enumerate(predictions):
            connection.execute(
                """INSERT INTO audit_records (job_id, node, event, timestamp, detail)
                   VALUES (?, 'classification_primary_classifier', 'passed', ?, ?)""",
                (job_id, f"2026-08-24 15:0{index}:00", f'{{"label": "{prediction}"}}'),
            )
    connection.commit()
    connection.close()


@pytest.fixture
def upgraded_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database_path = tmp_path / "migration_test.db"
    # alembic/env.py reads Settings.DATABASE_URL, not the ini option.
    monkeypatch.setattr(Settings, "DATABASE_URL", f"sqlite+aiosqlite:///{database_path.as_posix()}")
    config = _alembic_config()
    command.upgrade(config, "0015")
    _seed_0015_shaped_rows(database_path)
    command.upgrade(config, "0016")
    return database_path


def _original_label(database_path: Path, job_id: str) -> str | None:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT original_label FROM classification_records WHERE job_id = ?", (job_id,)
        ).fetchone()
        return None if row is None else row[0]
    finally:
        connection.close()


class TestOriginalLabelRecovery:
    def test_recovers_the_prediction_for_a_corrected_record(self, upgraded_database: Path) -> None:
        assert _original_label(upgraded_database, "corrected") == "otro"

    def test_recovers_the_prediction_when_the_machine_was_right(
        self, upgraded_database: Path
    ) -> None:
        assert _original_label(upgraded_database, "confirmed") == "boletines"

    def test_replaces_a_reviewers_answer_stored_as_the_prediction(
        self, upgraded_database: Path
    ) -> None:
        assert _original_label(upgraded_database, "mislabelled") == "convenios"

    def test_leaves_records_no_human_touched(self, upgraded_database: Path) -> None:
        assert _original_label(upgraded_database, "untouched") is None

    def test_leaves_records_without_an_audit_trail(self, upgraded_database: Path) -> None:
        assert _original_label(upgraded_database, "no-audit") is None

    def test_recovers_only_the_overridden_records(self, upgraded_database: Path) -> None:
        connection = sqlite3.connect(upgraded_database)
        try:
            recovered = connection.execute(
                "SELECT COUNT(*) FROM classification_records WHERE original_label IS NOT NULL"
            ).fetchone()[0]
        finally:
            connection.close()
        assert recovered == _EXPECTED_RECOVERED_ROWS
