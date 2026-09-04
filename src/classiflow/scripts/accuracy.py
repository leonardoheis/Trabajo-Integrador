"""Print classification accuracy from the live database, and write a markdown report.

    uv run poe accuracy

All figures come from MetricsService -- this module only formats them, so the CLI and the
`GET /classification/metrics` endpoint can never disagree about what a number means.
"""

import asyncio
import contextlib
from datetime import datetime, timezone
from pathlib import Path

from classiflow.database.base import get_session
from classiflow.database.repositories.classification_record import (
    SqlClassificationRecordRepository,
)
from classiflow.database.repositories.job import SqlJobRepository
from classiflow.services.metrics.domain import AccuracyReport
from classiflow.services.metrics.service import MetricsService

_REPORTS_DIR = Path("storage") / "reports"


async def _build_report() -> AccuracyReport:
    # get_session() is an async generator (it commits on teardown), so it's driven with
    # contextlib rather than `async for` -- which would otherwise need an unreachable
    # raise after the loop to satisfy the return type.
    async with contextlib.aclosing(get_session()) as sessions:
        session = await anext(sessions)
        service = MetricsService(
            SqlClassificationRecordRepository(session), SqlJobRepository(session)
        )
        return await service.accuracy_report()


def _status_breakdown(report: AccuracyReport) -> str:
    """`  (rejected 8, failed 1)`, or empty when everything reached the classifier.

    Returns:
        A parenthesised status breakdown, or "" when there is nothing to explain.
    """
    if not report.never_classified_by_status:
        return ""
    parts = ", ".join(
        f"{status} {count}" for status, count in sorted(report.never_classified_by_status.items())
    )
    return f"  ({parts})"


def _format_terminal(report: AccuracyReport) -> str:
    lines = [
        "",
        "Classification accuracy",
        "=" * 60,
        f"  ingested              {report.total_jobs}",
        f"  never classified      {report.never_classified}{_status_breakdown(report)}",
        f"  classified            {report.total_classified}",
        f"  with ground truth     {report.labelled}",
        "",
        (
            f"  strict accuracy       {report.correct}/{report.labelled} "
            f"= {report.strict_accuracy:.1%}"
        ),
        (
            f"  safeguarded accuracy  {report.safeguarded_accuracy:.1%}  "
            "(correct, or escalated to review)"
        ),
        "",
        f"  wrong, escalated      {report.wrong_caught}",
        f"  wrong, filed anyway   {report.wrong_uncaught}",
        "",
        "Per category",
        "-" * 60,
        f"  {'category':34}{'n':>4}{'recall':>9}{'prec':>8}{'f1':>7}",
    ]
    lines.extend(
        f"  {metric.category:34}{metric.support:>4}"
        f"{metric.recall:>9.2f}{metric.precision:>8.2f}{metric.f1:>7.2f}"
        for metric in report.per_category
    )

    if report.unevaluated_categories:
        lines += [
            "",
            "  unevaluated (no labelled examples):",
            *(f"    {category}" for category in report.unevaluated_categories),
        ]

    if report.unknown_labels:
        lines += [
            "",
            "  labels outside the taxonomy (stale or corrupt data):",
            *(f"    {label}" for label in report.unknown_labels),
        ]

    uncaught = [miss for miss in report.misses if not miss.caught_by_safety_net]
    if uncaught:
        lines += ["", "Wrong labels filed without review", "-" * 60]
        lines += [
            f"  {miss.filename}\n    expected {miss.expected}, got {miss.predicted}"
            for miss in uncaught
        ]

    return "\n".join([*lines, ""])


def _format_markdown(report: AccuracyReport) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Classification accuracy",
        "",
        f"Measured {stamp} over {report.labelled} labelled documents.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Documents ingested | {report.total_jobs} |",
        f"| Never reached the classifier | {report.never_classified}{_status_breakdown(report)} |",
        f"| Documents classified | {report.total_classified} |",
        f"| With ground truth | {report.labelled} |",
        (
            f"| Strict accuracy | **{report.correct}/{report.labelled} "
            f"= {report.strict_accuracy:.1%}** |"
        ),
        f"| Safeguarded accuracy | **{report.safeguarded_accuracy:.1%}** |",
        f"| Wrong, escalated to review | {report.wrong_caught} |",
        f"| Wrong, filed without review | {report.wrong_uncaught} |",
        "",
        "## Per category",
        "",
        "| Category | Support | Recall | Precision | F1 |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| `{m.category}` | {m.support} | {m.recall:.2f} | {m.precision:.2f} | {m.f1:.2f} |"
        for m in report.per_category
    ]
    lines += [f"| `{category}` | 0 | — | — | — |" for category in report.unevaluated_categories]

    if report.misses:
        lines += [
            "",
            "## Misses",
            "",
            "| Document | Expected | Predicted | Caught by safety net |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| `{m.filename}` | {m.expected} | {m.predicted} | "
            f"{'yes' if m.caught_by_safety_net else '**no**'} |"
            for m in report.misses
        ]

    return "\n".join([*lines, ""])


def main() -> None:
    report = asyncio.run(_build_report())
    print(_format_terminal(report))

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _REPORTS_DIR / f"accuracy_{stamp}.md"
    path.write_text(_format_markdown(report), encoding="utf-8")
    print(f"report written to {path}")


if __name__ == "__main__":
    main()
