"""Upgrade behaviour for revision 0015 (machine_review_route + accuracy backfill).

Runs against a throwaway SQLite file, never `data/classiflow.db`: the checked-in
development database already has the columns, so it cannot prove a fresh upgrade works.
"""

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from classiflow.settings import Settings

_PROJECT_ROOT = Path(__file__).parents[1]

_EXPECTED_BACKFILLED_ROWS = 5


def _alembic_config() -> Config:
    config = Config(str(_PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    return config


def _seed_0013_shaped_rows(database_path: Path) -> None:
    """Insert jobs and classification records as revision 0014 leaves them."""
    connection = sqlite3.connect(database_path)
    cases = [
        # job_id, filename, label, review_route, human_overridden, expected_label
        ("recognized", "ordenanza_9964_2019.pdf", "ordenanzas", "accept", 0, None),
        ("longest-prefix", "decreto_cm_68770_2025.pdf", "decretos", "accept", 0, None),
        ("explicit-otro", "A0470.pdf", "otro", "human_review", 0, None),
        ("unknown-name", "test.txt", "decretos", "accept", 0, None),
        ("overridden", "convenio_394_2023.pdf", "convenios", "accept", 1, None),
        ("preexisting", "boletin_980_2019.pdf", "boletines", "accept", 0, "boletines"),
    ]
    for job_id, filename, label, route, overridden, expected in cases:
        connection.execute(
            "INSERT INTO jobs (job_id, filename, status) VALUES (?, ?, 'classified')",
            (job_id, filename),
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
                expected_label)
               VALUES (?, ?, ?, 0.9, '{}', 0.0, 0, '{}', 1, ?, '[]', 0, 0, 0, ?, ?)""",
            (job_id, enriched_id, label, route, overridden, expected),
        )
    connection.commit()
    connection.close()


@pytest.fixture
def upgraded_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database_path = tmp_path / "migration_test.db"
    # alembic/env.py reads Settings.DATABASE_URL, not the ini option.
    monkeypatch.setattr(Settings, "DATABASE_URL", f"sqlite+aiosqlite:///{database_path.as_posix()}")
    config = _alembic_config()
    command.upgrade(config, "0014")
    _seed_0013_shaped_rows(database_path)
    command.upgrade(config, "0015")
    return database_path


def _fetch(database_path: Path, job_id: str) -> sqlite3.Row:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM classification_records WHERE job_id = ?", (job_id,)
    ).fetchone()
    connection.close()
    return row


class TestExpectedLabelBackfill:
    def test_recognized_prefix_is_labelled(self, upgraded_database: Path) -> None:
        assert _fetch(upgraded_database, "recognized")["expected_label"] == "ordenanzas"

    def test_longest_prefix_wins(self, upgraded_database: Path) -> None:
        row = _fetch(upgraded_database, "longest-prefix")
        assert row["expected_label"] == "decretos_concejo_municipal"

    def test_explicit_otro_is_labelled(self, upgraded_database: Path) -> None:
        assert _fetch(upgraded_database, "explicit-otro")["expected_label"] == "otro"

    def test_unknown_filename_stays_null(self, upgraded_database: Path) -> None:
        assert _fetch(upgraded_database, "unknown-name")["expected_label"] is None

    def test_preexisting_value_is_preserved(self, upgraded_database: Path) -> None:
        assert _fetch(upgraded_database, "preexisting")["expected_label"] == "boletines"


class TestMachineReviewRouteBackfill:
    def test_overridden_record_is_reconstructed_as_escalated(self, upgraded_database: Path) -> None:
        # Its current route reads accept, but the decision endpoint only accepts records
        # in human_review, so it must have been escalated.
        row = _fetch(upgraded_database, "overridden")
        assert row["review_route"] == "accept"
        assert row["machine_review_route"] == "human_review"

    def test_untouched_record_copies_its_current_route(self, upgraded_database: Path) -> None:
        assert _fetch(upgraded_database, "explicit-otro")["machine_review_route"] == "human_review"
        assert _fetch(upgraded_database, "recognized")["machine_review_route"] == "accept"

    def test_every_row_gets_a_route(self, upgraded_database: Path) -> None:
        connection = sqlite3.connect(upgraded_database)
        missing = connection.execute(
            "SELECT COUNT(*) FROM classification_records WHERE machine_review_route IS NULL"
        ).fetchone()[0]
        connection.close()
        assert missing == 0


class TestDowngrade:
    def test_drops_the_column_and_keeps_backfilled_labels(self, upgraded_database: Path) -> None:
        command.downgrade(_alembic_config(), "0014")

        connection = sqlite3.connect(upgraded_database)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(classification_records)")
        }
        labelled = connection.execute(
            "SELECT COUNT(*) FROM classification_records WHERE expected_label IS NOT NULL"
        ).fetchone()[0]
        connection.close()

        assert "machine_review_route" not in columns
        # Backfilled labels are deliberately not reversed -- see the migration's downgrade.
        assert labelled == _EXPECTED_BACKFILLED_ROWS
