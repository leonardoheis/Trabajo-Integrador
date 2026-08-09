"""
Bulk document downloader — Municipalidad de Rosario
Downloads PDFs from open-data CSVs and organizes them by category.

Usage:
    uv sync --dev
    uv run python scrapper/downloader.py [--output ./downloads] [--concurrency 5] [--delay 0.5]

Environment variables:
    SCRAPPER_DIR  — path to the folder containing CSVs (default: directory of this file)

Supported link types:
    direct_pdf   — URL already points to the PDF (newer boletines)
    boletin_html — HTML page with an index of internal PDFs (boletines IDs 2-218)
    normativa    — visualExterna.do?idNormativa=X → direct verArchivo URL
    html_to_pdf  — Plone /mr/normativa/ page → converted with weasyprint
    scrape_page  — generic scraping (compendios)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlparse

if TYPE_CHECKING:
    from collections.abc import Callable

import aiofiles
import aiohttp
import weasyprint
from bs4 import BeautifulSoup
from tqdm.asyncio import tqdm

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

BASE_URL = "https://www.rosario.gob.ar"

HTTP_OK = 200
HTTP_NOT_FOUND = 404

# Can be overridden via environment variable (useful in Colab/Azure)
SCRAPPER_DIR = Path(os.environ.get("SCRAPPER_DIR", str(Path(__file__).parent)))
CHECKPOINT_FILE = Path(__file__).parent / "checkpoint.json"

CSV_CONFIG = {
    "boletines.csv": {
        "folder": "boletines",
        "link_col": "LINK",
        "link_type": "direct_pdf",  # URL already points directly to the PDF
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "boletin_{NUMERO}_{ANIO}.pdf",
    },
    "compendios_de_boletines.csv": {
        "folder": "compendios_de_boletines",
        "link_col": "LINK",
        "link_type": "scrape_page",  # page with iframe/embed of the PDF
        "name_cols": ["COMPENDIO", "PERIODO"],
        "name_fmt": "{COMPENDIO}_{PERIODO}.pdf",
    },
    "convenios.csv": {
        "folder": "convenios",
        "link_col": "TEXTO_VIGENTE_NORMA",
        "link_type": "normativa",  # visualExterna.do → scraping for real PDF
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "convenio_{NUMERO}_{ANIO}.pdf",
    },
    "declaraciones_concejo_municipal.csv": {
        "folder": "declaraciones_concejo_municipal",
        "link_col": "TEXTO_VIGENTE_NORMA",
        "link_type": "normativa",
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "declaracion_{NUMERO}_{ANIO}.pdf",
    },
    "decreto_ordenanzas.csv": {
        "folder": "decreto_ordenanzas",
        "link_col": "TEXTO_VIGENTE_NORMA",
        "link_type": "normativa",
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "decreto_ordenanza_{NUMERO}_{ANIO}.pdf",
    },
    "decretos.csv": {
        "folder": "decretos",
        "link_col": "TEXTO_VIGENTE_NORMA",
        "link_type": "normativa",
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "decreto_{NUMERO}_{ANIO}.pdf",
    },
    "decretos_concejo_municipal.csv": {
        "folder": "decretos_concejo_municipal",
        "link_col": "TEXTO_VIGENTE_NORMA",
        "link_type": "normativa",
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "decreto_cm_{NUMERO}_{ANIO}.pdf",
    },
    "ordenanzas.csv": {
        "folder": "ordenanzas",
        "link_col": "TEXTO_VIGENTE_NORMA",
        "link_type": "normativa",
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "ordenanza_{NUMERO}_{ANIO}.pdf",
    },
    "resoluciones.csv": {
        "folder": "resoluciones",
        "link_col": "TEXTO_VIGENTE_NORMA",
        "link_type": "normativa",
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "resolucion_{NUMERO}_{ANIO}.pdf",
    },
    "resoluciones_concejo_municipal.csv": {
        "folder": "resoluciones_concejo_municipal",
        "link_col": "TEXTO_VIGENTE_NORMA",
        "link_type": "normativa",
        "name_cols": ["NUMERO", "ANIO"],
        "name_fmt": "resolucion_cm_{NUMERO}_{ANIO}.pdf",
    },
}

# Real browser User-Agent to avoid being blocked
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scrapper/downloader.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# URL utilities
# ──────────────────────────────────────────────────────────────


def normalize_url(url: str) -> str | None:
    """
    Normalizes malformed URLs found in some CSVs:
    - 'www.foo.com/path'   → 'http://www.foo.com/path'
    - '/www.foo.com/path'  → 'http://www.foo.com/path'
    - 'ssl.foo.com/path'   → 'https://ssl.foo.com/path'

    Returns:
        The normalized URL string, or None if the URL is empty or has no valid netloc.
    """
    url = url.strip()
    if not url:
        return None

    # Strip erroneous leading slash before the domain
    if url.startswith(("/www.", "/ssl.")):
        url = url[1:]

    # Add scheme if missing
    if not url.startswith("http"):
        scheme = "https" if url.startswith("ssl.") else "http"
        url = f"{scheme}://{url}"

    parsed = urlparse(url)
    if not parsed.netloc:
        return None

    return url


_PDF_URL_PATTERNS = (
    r'["\']([^"\']*verArchivo[^"\']*)["\']',
    r'["\']([^"\']*getPdf[^"\']*)["\']',
)

_TAG_ATTRS = [
    ("a", "href"),
    ("iframe", "src"),
    ("embed", "src"),
    ("object", "data"),
    ("frame", "src"),
]


def _is_pdf_url(u: str) -> bool:
    """Return True if *u* looks like a Rosario portal PDF URL.

    Returns:
        True when the URL contains a known PDF-serving path or ends in .pdf.
    """
    return bool(
        u
        and (
            "verArchivo" in u or "getPdf" in u or "documento.do" in u or u.lower().endswith(".pdf")
        )
    )


def _search_tagged_elements(
    soup: BeautifulSoup,
    resolve: Callable[[str], str],
) -> str | None:
    """Check known tag/attribute pairs (a, iframe, embed, object, frame).

    Returns:
        First matching PDF URL found, or None.
    """
    for tag, attr in _TAG_ATTRS:
        for el in soup.find_all(tag):
            val = el.get(attr, "")
            if _is_pdf_url(val):
                return resolve(val)
    return None


def _search_all_attrs(
    soup: BeautifulSoup,
    resolve: Callable[[str], str],
) -> str | None:
    """Sweep every element and every attribute looking for a PDF URL.

    Returns:
        First matching PDF URL found, or None.
    """
    for el in soup.find_all(name=True):
        for val in el.attrs.values():
            if isinstance(val, str) and _is_pdf_url(val):
                return resolve(val)
    return None


def _search_raw_html(
    html: str,
    resolve: Callable[[str], str],
) -> str | None:
    """Regex fallback: search raw HTML for PDF URLs in scripts or data-attributes.

    Returns:
        First matching PDF URL found, or None.
    """
    for pattern in _PDF_URL_PATTERNS:
        matches = re.findall(pattern, html)
        if matches:
            return resolve(matches[0])
    return None


def extract_pdf_url_from_html(html: str, page_url: str) -> str | None:
    """Search for the PDF URL in the HTML of a Rosario portal page.

    Tries three strategies in order: known tag/attr pairs, generic attribute
    sweep, then raw HTML regex.

    Returns:
        The absolute PDF URL if found, or None if no PDF link is detected.
    """
    soup = BeautifulSoup(html, "lxml")

    def resolve(href: str) -> str:
        return href if href.startswith("http") else urljoin(page_url, href)

    return (
        _search_tagged_elements(soup, resolve)
        or _search_all_attrs(soup, resolve)
        or _search_raw_html(html, resolve)
    )


# ──────────────────────────────────────────────────────────────
# Checkpoint
# ──────────────────────────────────────────────────────────────
# The set stores two entry types:
#   "path/to/file.pdf"      → successfully downloaded
#   "SKIP:path/to/file.pdf" → permanent failure, do not retry

SKIP_PREFIX = "SKIP:"


def load_checkpoint() -> set:
    """Load the set of checkpoint keys from disk.

    Returns:
        Set of string keys for completed and permanently-skipped items.
    """
    if CHECKPOINT_FILE.exists():
        with Path(CHECKPOINT_FILE).open(encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_checkpoint(done: set) -> None:
    with Path(CHECKPOINT_FILE).open("w", encoding="utf-8") as f:
        json.dump(list(done), f)


def is_pending(key: str, done: set) -> bool:
    """Check whether an item still needs to be processed.

    Returns:
        True if the key is absent from the checkpoint (neither completed nor permanently skipped).
    """
    return key not in done and (SKIP_PREFIX + key) not in done


# ──────────────────────────────────────────────────────────────
# PDF URL resolution
# ──────────────────────────────────────────────────────────────


def build_normativa_pdf_url(page_url: str) -> str | None:
    """
    For URLs of the form visualExterna.do?idNormativa=X, builds the download
    URL directly: /normativa/verArchivo?tipo=pdf&id=X&modo=attachment
    Avoids an extra HTTP request for ~95% of documents.

    Returns:
        The direct PDF download URL, or None if idNormativa is not present in the query string.
    """
    qs = parse_qs(urlparse(page_url).query)
    nid = qs.get("idNormativa", [None])[0]
    if nid:
        return f"{BASE_URL}/normativa/verArchivo?tipo=pdf&id={nid}&modo=attachment"
    return None


async def _fetch_page_data(
    session: aiohttp.ClientSession,
    url: str,
) -> tuple[int, str, str, str]:
    """Open *url* and return (status, content_type, html, final_url).

    Returns:
        4-tuple with HTTP status, Content-Type header, response body (empty when
        status != 200), and the final URL after redirects.
    """
    async with session.get(
        url,
        headers=HEADERS,
        timeout=aiohttp.ClientTimeout(total=30),
        allow_redirects=True,
    ) as resp:
        content_type = resp.headers.get("Content-Type", "")
        final_url = str(resp.url)
        html = await resp.text(errors="replace") if resp.status == HTTP_OK else ""
        return resp.status, content_type, html, final_url


async def _scrape_pdf_url(
    session: aiohttp.ClientSession,
    url: str,
    delay: float,
) -> str | None:
    """Fetch *url* and extract the PDF URL by scraping the response.

    Returns:
        The PDF URL, "PERMANENT" for definitive failures, or None for transient errors.
    """
    await asyncio.sleep(delay)
    try:
        status, content_type, html, final_url = await _fetch_page_data(session, url)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        log.warning("Error accessing %s: %s", url, exc)
        return None

    if status == HTTP_NOT_FOUND:
        log.info("Page not found (404): %s", url)
        return "PERMANENT"
    if status != HTTP_OK:
        log.warning("HTTP %d while resolving: %s", status, url)
        return None
    if "pdf" in content_type.lower():
        return final_url
    direct = build_normativa_pdf_url(final_url)
    if direct:
        return direct
    pdf_url = extract_pdf_url_from_html(html, final_url)
    if not pdf_url:
        log.info("No PDF found on page (will be skipped on future runs): %s", url)
    return normalize_url(pdf_url) if pdf_url else "PERMANENT"


async def resolve_pdf_url(
    session: aiohttp.ClientSession,
    page_url: str,
    link_type: str,
    delay: float,
) -> str | None:
    """Dispatch to the correct PDF resolution strategy for *link_type*.

    Returns:
        The resolved PDF URL string, "PERMANENT" if the resource is definitively absent,
        or None for transient failures that should be retried.
    """
    url = normalize_url(page_url)
    if not url:
        log.warning("Invalid URL, skipping: %r", page_url)
        return None
    if link_type == "direct_pdf":
        return url
    if link_type == "normativa":
        direct = build_normativa_pdf_url(url)
        if direct:
            return direct
    return await _scrape_pdf_url(session, url, delay)


# ──────────────────────────────────────────────────────────────
# Individual download
# ──────────────────────────────────────────────────────────────


async def _fetch_download_data(
    session: aiohttp.ClientSession,
    pdf_url: str,
    attempt: int,
    retries: int,
) -> tuple[bool | str, bytes | None]:
    """Perform a single HTTP GET and validate the PDF response.

    Returns:
        (True, data) on success with valid PDF bytes,
        (False, None) on 404,
        ("PERMANENT", None) when server returns non-PDF content,
        ("RETRY", None) on a retryable HTTP error.
    """
    async with session.get(
        pdf_url,
        headers={**HEADERS, "Accept": "application/pdf,*/*"},
        timeout=aiohttp.ClientTimeout(total=90),
        allow_redirects=True,
    ) as resp:
        if resp.status == HTTP_NOT_FOUND:
            log.warning("404 (document not available): %s", pdf_url)
            return "PERMANENT", None
        if resp.status != HTTP_OK:
            log.warning("HTTP %d on attempt %d/%d: %s", resp.status, attempt, retries, pdf_url)
            return "RETRY", None

        data = await resp.read()

        if not data or b"%PDF" not in data[:10]:
            ct = resp.headers.get("Content-Type", "")
            log.warning(
                "No valid PDF (Content-Type: %s, bytes: %d) — will be skipped: %s",
                ct,
                len(data),
                pdf_url,
            )
            return "PERMANENT", None

        return True, data


async def download_file(
    session: aiohttp.ClientSession,
    pdf_url: str,
    dest_path: Path,
    delay: float,
    retries: int = 3,
) -> bool:
    await asyncio.sleep(delay)
    for attempt in range(1, retries + 1):
        try:
            result, data = await _fetch_download_data(session, pdf_url, attempt, retries)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Error on attempt %d/%d (%s): %s", attempt, retries, pdf_url, exc)
            await asyncio.sleep(2**attempt)
            continue

        if result == "RETRY":
            await asyncio.sleep(2**attempt)
            continue
        if result is not True:
            return result  # type: ignore[return-value]  # False or "PERMANENT"

        assert data is not None
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(dest_path, "wb") as f:
            await f.write(data)
        return True

    log.error("Permanent network failure (will retry next run): %s", pdf_url)
    return False  # transient: do not add to checkpoint


# ──────────────────────────────────────────────────────────────
# CSV reading
# ──────────────────────────────────────────────────────────────


def sanitize(text: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", text).strip()


def build_task_list(output_dir: Path) -> list[dict]:
    tasks = []
    for csv_file, cfg in CSV_CONFIG.items():
        csv_path = SCRAPPER_DIR / csv_file
        if not csv_path.exists():
            log.warning("CSV not found: %s", csv_path)
            continue

        folder = output_dir / cfg["folder"]
        with Path(csv_path).open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                link = row.get(cfg["link_col"], "").strip().strip('"')
                if not link:
                    continue

                name_parts = {k: sanitize(row.get(k, "").strip()) for k in cfg["name_cols"]}
                filename = cfg["name_fmt"].format(**name_parts)
                dest = folder / filename

                # Detect special link types from the URL content
                link_type = cfg["link_type"]
                if "boletin.do?accion=ver2" in link or ("boletin.do" in link and "ver2" in link):
                    link_type = "boletin_html"
                elif "/mr/normativa/" in link:
                    link_type = "html_to_pdf"

                tasks.append({
                    "key": str(dest),
                    "page_url": link,
                    "link_type": link_type,
                    "dest": dest,
                    # extra data for naming sub-files in boletin_html
                    "folder": folder,
                    "name_base": filename.replace(".pdf", ""),
                })

    return tasks


# ──────────────────────────────────────────────────────────────
# Type 1: expand HTML boletines into individual tasks
# ──────────────────────────────────────────────────────────────


async def expand_boletin_tasks(
    session: aiohttp.ClientSession,
    boletin_tasks: list[dict],
    delay: float,
) -> tuple[list[dict], set[str]]:
    """
    For each HTML boletin (boletin.do?accion=ver2), scrapes the page,
    extracts the internal PDF IDs via ver(id) in the JS, and returns
    one individual task per PDF found.

    Returns:
        2-tuple of (expanded sub-tasks, set of parent task keys that produced at least one
        sub-task). Keys absent from the set had a transient failure or empty page and should
        not be permanently skipped — they will be retried on the next run.
    """
    expanded: list[dict] = []
    expanded_keys: set[str] = set()
    for task in boletin_tasks:
        url = normalize_url(task["page_url"])
        if not url:
            continue
        await asyncio.sleep(delay)
        try:
            async with session.get(
                url,
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as resp:
                if resp.status != HTTP_OK:
                    log.warning("HTTP %d expanding boletin: %s", resp.status, url)
                    continue
                html = await resp.text(errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Error expanding boletin %s: %s", url, exc)
            continue

        pdf_ids = re.findall(r"\bver\((\d+)\)", html)
        if not pdf_ids:
            log.info("Boletin with no internal PDFs: %s", url)
            continue

        log.info("Boletin %s → %d internal PDFs", task["page_url"], len(pdf_ids))
        expanded_keys.add(task["key"])
        for pdf_id in pdf_ids:
            pdf_url = f"{BASE_URL}/normativa/verArchivo?tipo=pdf&id={pdf_id}&modo=attachment"
            dest = task["folder"] / f"{task['name_base']}_doc_{pdf_id}.pdf"
            expanded.append({
                "key": str(dest),
                "page_url": pdf_url,
                "link_type": "direct_pdf",
                "dest": dest,
                "folder": task["folder"],
                "name_base": task["name_base"],
            })

    return expanded, expanded_keys


# ──────────────────────────────────────────────────────────────
# Type 2: HTML → PDF conversion with weasyprint (Plone pages)
# ──────────────────────────────────────────────────────────────


async def html_to_pdf_file(
    session: aiohttp.ClientSession,
    page_url: str,
    dest_path: Path,
    delay: float,
) -> bool | str:
    """
    Downloads the HTML of a Plone page and converts it to PDF with weasyprint.

    Returns:
        True on success, "PERMANENT" if the page is definitively unavailable or
        conversion fails irrecoverably, False for transient network errors.
    """
    url = normalize_url(page_url)
    if not url:
        return "PERMANENT"

    await asyncio.sleep(delay)
    try:
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=30),
            allow_redirects=True,
        ) as resp:
            if resp.status == HTTP_NOT_FOUND:
                return "PERMANENT"
            if resp.status != HTTP_OK:
                return False
            html = await resp.text(errors="replace")
            final_url = str(resp.url)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        log.warning("Error fetching HTML from %s: %s", url, exc)
        return False

    # Run in an executor to avoid blocking the event loop
    loop = asyncio.get_running_loop()
    try:

        def _convert() -> None:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            weasyprint.HTML(string=html, base_url=final_url).write_pdf(str(dest_path))

        await loop.run_in_executor(None, _convert)
    except (OSError, ValueError) as exc:
        log.warning("weasyprint failed for %s: %s", url, exc)
        return "PERMANENT"
    else:
        return True


# ──────────────────────────────────────────────────────────────
# Orchestrator helpers
# ──────────────────────────────────────────────────────────────


def _apply_migration(tasks: list[dict], done: set) -> None:
    """Unblock tasks previously marked SKIP that now have a dedicated handler.

    Mutates *done* in place and persists the checkpoint when entries are removed.
    """
    newly_supported = {"html_to_pdf"}
    keys_to_unblock = {SKIP_PREFIX + t["key"] for t in tasks if t["link_type"] in newly_supported}
    removed = len(done & keys_to_unblock)
    if removed:
        done -= keys_to_unblock
        save_checkpoint(done)
        log.info("Migration: %d SKIP entries unblocked for reprocessing", removed)


async def _expand_boletines(
    session: aiohttp.ClientSession,
    tasks: list[dict],
    done: set,
    delay: float,
) -> list[dict]:
    """Phase 1: replace boletin_html container tasks with their individual PDF tasks.

    Returns:
        Updated task list with boletin_html entries replaced by expanded PDF tasks.
    """
    boletin_html_tasks = [
        t for t in tasks if t["link_type"] == "boletin_html" and is_pending(t["key"], done)
    ]
    if not boletin_html_tasks:
        return tasks
    log.info("Expanding %d HTML boletines...", len(boletin_html_tasks))
    expanded, expanded_keys = await expand_boletin_tasks(session, boletin_html_tasks, delay)
    log.info("→ %d internal PDFs found in boletines", len(expanded))
    done.update(SKIP_PREFIX + t["key"] for t in boletin_html_tasks if t["key"] in expanded_keys)
    save_checkpoint(done)
    return [t for t in tasks if t["link_type"] != "boletin_html"] + expanded


def _filter_pending(tasks: list[dict], done: set) -> list[dict]:
    """Phase 2: return tasks that are pending and not already present on disk.

    Returns:
        Subset of *tasks* that still need to be downloaded or converted.
    """
    return [t for t in tasks if is_pending(t["key"], done) and not Path(t["key"]).exists()]


def _log_progress(tasks: list[dict], pending: list[dict], done: set) -> None:
    """Log a summary of task counts before starting downloads."""
    skipped = sum(1 for t in tasks if (SKIP_PREFIX + t["key"]) in done)
    ok_prev = sum(1 for t in tasks if t["key"] in done)
    log.info(
        "Total: %d | Previously OK: %d | Skipped: %d | Pending: %d",
        len(tasks),
        ok_prev,
        skipped,
        len(pending),
    )


@dataclass
class _DownloadCtx:
    session: aiohttp.ClientSession
    semaphore: asyncio.Semaphore
    delay: float


async def _process_task(
    ctx: _DownloadCtx,
    task: dict,
    done: set,
    stats: dict[str, int],
) -> None:
    """Download or convert a single task, updating *done* and *stats* in place."""
    async with ctx.semaphore:
        outcome: bool | str | None = None

        if task["link_type"] == "html_to_pdf":
            outcome = await html_to_pdf_file(ctx.session, task["page_url"], task["dest"], ctx.delay)
        else:
            result = await resolve_pdf_url(
                ctx.session, task["page_url"], task["link_type"], ctx.delay
            )
            if result == "PERMANENT":
                outcome = "PERMANENT"
            elif result is not None:
                outcome = await download_file(ctx.session, result, task["dest"], ctx.delay)

        if outcome is True:
            stats["ok"] += 1
            done.add(task["key"])
            if stats["ok"] % 50 == 0:
                save_checkpoint(done)
                log.info("Checkpoint: %d OK so far", stats["ok"])
        elif outcome == "PERMANENT":
            stats["permanent"] += 1
            done.add(SKIP_PREFIX + task["key"])
            if stats["permanent"] % 50 == 0:
                save_checkpoint(done)
        else:
            stats["transient"] += 1


# ──────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────


async def run(output_dir: Path, concurrency: int, delay: float) -> None:
    tasks = build_task_list(output_dir)
    done = load_checkpoint()
    _apply_migration(tasks, done)

    connector = aiohttp.TCPConnector(limit=concurrency)
    stats: dict[str, int] = {"ok": 0, "permanent": 0, "transient": 0}

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = await _expand_boletines(session, tasks, done, delay)
        pending = _filter_pending(tasks, done)
        _log_progress(tasks, pending, done)

        ctx = _DownloadCtx(session=session, semaphore=asyncio.Semaphore(concurrency), delay=delay)
        await tqdm.gather(
            *[_process_task(ctx, t, done, stats) for t in pending],
            desc="Downloading",
            total=len(pending),
        )

    save_checkpoint(done)
    log.info(
        "Done. OK: %d | No PDF/permanent: %d | Network error (retryable): %d",
        stats["ok"],
        stats["permanent"],
        stats["transient"],
    )


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────


def main() -> None:

    parser = argparse.ArgumentParser(description="Bulk downloader — Municipalidad de Rosario")
    parser.add_argument("--output", default="./downloads")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Parallel downloads (default: 5 — keep low to avoid being blocked)",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5, help="Seconds to wait between requests (default: 0.5)"
    )
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("SCRAPPER_DIR: %s", SCRAPPER_DIR)
    log.info(
        "Output: %s | Concurrency: %d | Delay: %.1fs", output_dir, args.concurrency, args.delay
    )

    asyncio.run(run(output_dir, args.concurrency, args.delay))


if __name__ == "__main__":
    main()
