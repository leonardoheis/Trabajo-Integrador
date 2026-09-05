"""Render the accuracy charts for the presentation from the live database.

Standalone on purpose: matplotlib is not a project dependency, so run this with
`uv run --with matplotlib python scripts/plot_accuracy.py`.
"""

import collections
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

_PROJECT_ROOT = Path(__file__).parents[1]
_DATABASE = _PROJECT_ROOT / "data" / "classiflow.db"
_OUTPUT = _PROJECT_ROOT / "docs" / "accuracy-charts.png"

_HUMAN_REVIEW = "human_review"
_SHORT_NAMES = {
    "decretos_concejo_municipal": "decretos_cm",
    "resoluciones_concejo_municipal": "resoluciones_cm",
    "declaraciones_concejo_municipal": "declaraciones_cm",
}


def _scored_pairs(connection: sqlite3.Connection) -> list[tuple[str, str, bool]]:
    """Truth, prediction and whether the safety net caught it, per scoreable record."""
    rows = connection.execute("""
        SELECT label, original_label, expected_label, machine_review_route, human_overridden
        FROM classification_records
    """).fetchall()
    pairs = []
    for label, original, expected, machine_route, overridden in rows:
        if overridden:
            if original is None or label is None:
                continue
            truth, prediction = label, original
        elif expected is not None and label is not None:
            truth, prediction = expected, label
        else:
            continue
        pairs.append((truth, prediction, machine_route == _HUMAN_REVIEW))
    return pairs


def _per_category(pairs: list[tuple[str, str, bool]]) -> list[tuple[str, int, float, float]]:
    hits: collections.Counter[str] = collections.Counter()
    predicted: collections.Counter[str] = collections.Counter()
    support: collections.Counter[str] = collections.Counter()
    for truth, prediction, _ in pairs:
        support[truth] += 1
        predicted[prediction] += 1
        if truth == prediction:
            hits[truth] += 1

    categories = sorted(set(support) | set(predicted), key=lambda c: -support[c])
    return [
        (
            _SHORT_NAMES.get(category, category),
            support[category],
            hits[category] / support[category] if support[category] else 0.0,
            hits[category] / predicted[category] if predicted[category] else 0.0,
        )
        for category in categories
    ]


def main() -> None:
    connection = sqlite3.connect(_DATABASE)
    try:
        pairs = _scored_pairs(connection)
    finally:
        connection.close()

    total = len(pairs)
    correct = sum(1 for truth, prediction, _ in pairs if truth == prediction)
    safeguarded = sum(1 for truth, prediction, caught in pairs if truth == prediction or caught)
    rows = _per_category(pairs)

    figure, (left, right) = plt.subplots(1, 2, figsize=(16, 6), width_ratios=[2.4, 1])

    positions = range(len(rows))
    width = 0.4
    left.bar(
        [p - width / 2 for p in positions],
        [recall for _, _, recall, _ in rows],
        width,
        label="Recall",
        color="#e07b39",
    )
    left.bar(
        [p + width / 2 for p in positions],
        [precision for _, _, _, precision in rows],
        width,
        label="Precision",
        color="#3b6ea5",
    )
    left.axhline(1.0, color="#94a3b8", linestyle=":", linewidth=1)
    left.set_xticks(list(positions))
    left.set_xticklabels([name for name, _, _, _ in rows], rotation=45, ha="right")
    left.set_ylim(0, 1.15)
    left.set_title(f"Classiflow — Recall/Precision por categoría (pipeline completo, n={total})")
    left.legend(loc="lower left")
    for position, (_, support, _, _) in zip(positions, rows, strict=True):
        left.text(position, 1.08, f"n={support}", ha="center", fontsize=9, color="#64748b")

    strict_pct = correct / total * 100
    safeguarded_pct = safeguarded / total * 100
    bars = right.bar(
        [f"Estricta\n({strict_pct:.1f} %)", f"Con red de\nseguridad ({safeguarded_pct:.1f} %)"],
        [strict_pct, safeguarded_pct],
        color=["#3b6ea5", "#4ca66b"],
    )
    for bar, value in zip(bars, (strict_pct, safeguarded_pct), strict=True):
        right.text(
            bar.get_x() + bar.get_width() / 2,
            value + 2,
            f"{value:.1f} %",
            ha="center",
            fontweight="bold",
        )
    right.set_ylim(0, 112)
    right.set_ylabel("%")
    right.set_title(f"Accuracy del pipeline\n({total} documentos clasificados)")

    figure.tight_layout()
    figure.savefig(_OUTPUT, dpi=150)
    print(f"strict {correct}/{total} = {strict_pct:.1f}%")
    print(f"safeguarded {safeguarded}/{total} = {safeguarded_pct:.1f}%")
    print(f"written to {_OUTPUT}")


if __name__ == "__main__":
    main()
