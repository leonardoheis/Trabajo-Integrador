"""
Bulk document downloader — Municipalidad de Rosario
Downloads PDFs from open-data CSVs and organizes them by category.

Usage:
    pip install aiohttp aiofiles tqdm beautifulsoup4 lxml weasyprint
    python downloader.py [--output ./downloads] [--concurrency 5] [--delay 0.5]

Environment variables:
    SCRAPPER_DIR  — path to the folder containing CSVs (default: ./Scrapper)

Supported link types:
    direct_pdf   — URL already points to the PDF (newer boletines)
    boletin_html — HTML page with an index of internal PDFs (boletines IDs 2-218)
    normativa    — visualExterna.do?idNormativa=X → direct verArchivo URL
    html_to_pdf  — Plone /mr/normativa/ page → converted with weasyprint
    scrape_page  — generic scraping (compendios)
"""

import asyncio
import csv
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse, parse_qs, urljoin

import aiofiles
import aiohttp
from bs4 import BeautifulSoup
from tqdm.asyncio import tqdm

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

BASE_URL = "https://www.rosario.gob.ar"

# Can be overridden via environment variable (useful in Colab/Azure)
SCRAPPER_DIR = Path(os.environ.get("SCRAPPER_DIR", str(Path(__file__).parent / "Scrapper")))
CHECKPOINT_FILE = Path(__file__).parent / "checkpoint.json"

CSV_CONFIG = {
    "boletines.csv": {
        "folder": "boletines",
        "link_col": "LINK",
        "link_type": "direct_pdf",   # URL already points directly to the PDF
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
        "link_type": "normativa",    # visualExterna.do → scraping for real PDF
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
        logging.FileHandler("downloader.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# URL utilities
# ──────────────────────────────────────────────────────────────

def normalize_url(url: str) -> Optional[str]:
    """
    Normalizes malformed URLs found in some CSVs:
    - 'www.foo.com/path'   → 'http://www.foo.com/path'
    - '/www.foo.com/path'  → 'http://www.foo.com/path'
    - 'ssl.foo.com/path'   → 'https://ssl.foo.com/path'
    Returns None if the URL is empty or invalid.
    """
    url = url.strip()
    if not url:
        return None

    # Strip erroneous leading slash before the domain
    if url.startswith("/www.") or url.startswith("/ssl."):
        url = url[1:]

    # Add scheme if missing
    if not url.startswith("http"):
        scheme = "https" if url.startswith("ssl.") else "http"
        url = f"{scheme}://{url}"

    parsed = urlparse(url)
    if not parsed.netloc:
        return None

    return url


def extract_pdf_url_from_html(html: str, page_url: str) -> Optional[str]:
    """
    Searches for the PDF URL in the HTML of a Rosario portal page.
    Known patterns:
      1. /normativa/verArchivo?tipo=pdf&id=XXX  (new portal — most common)
      2. getPdf in href/src/embed/object
      3. href/src ending in .pdf
    """
    soup = BeautifulSoup(html, "lxml")

    def is_pdf_url(u: str) -> bool:
        return bool(u and (
            "verArchivo" in u
            or "getPdf" in u
            or "documento.do" in u
            or u.lower().endswith(".pdf")
        ))

    def resolve(href: str) -> str:
        if href.startswith("http"):
            return href
        return urljoin(page_url, href)

    for tag, attr in [
        ("a", "href"),
        ("iframe", "src"),
        ("embed", "src"),
        ("object", "data"),
        ("frame", "src"),
    ]:
        for el in soup.find_all(tag):
            val = el.get(attr, "")
            if is_pdf_url(val):
                return resolve(val)

    for el in soup.find_all(True):
        for attr, val in el.attrs.items():
            if isinstance(val, str) and is_pdf_url(val):
                return resolve(val)

    # Search in raw HTML (scripts, data-attributes, onclick, etc.)
    for pattern in [r'["\']([^"\']*verArchivo[^"\']*)["\']',
                    r'["\']([^"\']*getPdf[^"\']*)["\']']:
        matches = re.findall(pattern, html)
        if matches:
            return resolve(matches[0])

    return None


# ──────────────────────────────────────────────────────────────
# Checkpoint
# ──────────────────────────────────────────────────────────────
# The set stores two entry types:
#   "path/to/file.pdf"      → successfully downloaded
#   "SKIP:path/to/file.pdf" → permanent failure, do not retry

SKIP_PREFIX = "SKIP:"


def load_checkpoint() -> set:
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_checkpoint(done: set):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(list(done), f)


def is_pending(key: str, done: set) -> bool:
    """True if the item still needs to be processed (neither OK nor permanent failure)."""
    return key not in done and (SKIP_PREFIX + key) not in done


# ──────────────────────────────────────────────────────────────
# PDF URL resolution
# ──────────────────────────────────────────────────────────────

def build_normativa_pdf_url(page_url: str) -> Optional[str]:
    """
    For URLs of the form visualExterna.do?idNormativa=X, builds the download
    URL directly: /normativa/verArchivo?tipo=pdf&id=X&modo=attachment
    Avoids an extra HTTP request for ~95% of documents.
    """
    qs = parse_qs(urlparse(page_url).query)
    nid = qs.get("idNormativa", [None])[0]
    if nid:
        return f"{BASE_URL}/normativa/verArchivo?tipo=pdf&id={nid}&modo=attachment"
    return None


async def resolve_pdf_url(
    session: aiohttp.ClientSession,
    page_url: str,
    link_type: str,
    delay: float,
) -> Optional[str]:
    """
    Returns the downloadable PDF URL.

    - direct_pdf : already is the PDF (boletines).
    - normativa  : if it has idNormativa → builds direct URL without HTTP.
                   Otherwise (old /mr/normativa/ URLs) → scrapes the page.
    - scrape_page: scraping (compendios).
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
        # URL without idNormativa not detected as html_to_pdf → fallback to scraping

    # Page scraping (compendios and edge cases)
    await asyncio.sleep(delay)
    try:
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=30),
            allow_redirects=True,
        ) as resp:
            if resp.status == 404:
                log.info("Page not found (404): %s", url)
                return "PERMANENT"
            if resp.status != 200:
                log.warning("HTTP %d while resolving: %s", resp.status, url)
                return None  # transient

            # Server already returns PDF directly (e.g. compendios)
            ct = resp.headers.get("Content-Type", "")
            if "pdf" in ct.lower():
                return str(resp.url)

            html = await resp.text(errors="replace")
            final_url = str(resp.url)
            # Re-check after redirect: if it ended up at visualExterna.do
            direct = build_normativa_pdf_url(final_url)
            if direct:
                return direct
    except Exception as exc:
        log.warning("Error accessing %s: %s", url, exc)
        return None  # transient

    pdf_url = extract_pdf_url_from_html(html, final_url)
    if pdf_url:
        return normalize_url(pdf_url)

    log.info("No PDF found on page (will be skipped on future runs): %s", url)
    return "PERMANENT"


# ──────────────────────────────────────────────────────────────
# Individual download
# ──────────────────────────────────────────────────────────────

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
            async with session.get(
                pdf_url,
                headers={**HEADERS, "Accept": "application/pdf,*/*"},
                timeout=aiohttp.ClientTimeout(total=90),
                allow_redirects=True,
            ) as resp:
                if resp.status == 404:
                    log.warning("404 (document not available): %s", pdf_url)
                    return False
                if resp.status != 200:
                    log.warning("HTTP %d on attempt %d/%d: %s", resp.status, attempt, retries, pdf_url)
                    await asyncio.sleep(2 ** attempt)
                    continue

                data = await resp.read()

                # Verify it is actually a PDF
                if not data or b"%PDF" not in data[:10]:
                    ct = resp.headers.get("Content-Type", "")
                    log.warning(
                        "No valid PDF (Content-Type: %s, bytes: %d) — will be skipped: %s",
                        ct, len(data), pdf_url,
                    )
                    # Permanent failure: server responded 200 but content is not a PDF
                    return "PERMANENT"

                dest_path.parent.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(dest_path, "wb") as f:
                    await f.write(data)
                return True

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Error on attempt %d/%d (%s): %s", attempt, retries, pdf_url, exc)
            await asyncio.sleep(2 ** attempt)

    log.error("Permanent network failure (will retry next run): %s", pdf_url)
    return False  # transient: do not add to checkpoint


# ──────────────────────────────────────────────────────────────
# CSV reading
# ──────────────────────────────────────────────────────────────

def sanitize(text: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", text).strip()


def build_task_list(output_dir: Path) -> List[dict]:
    tasks = []
    for csv_file, cfg in CSV_CONFIG.items():
        csv_path = SCRAPPER_DIR / csv_file
        if not csv_path.exists():
            log.warning("CSV not found: %s", csv_path)
            continue

        folder = output_dir / cfg["folder"]
        with open(csv_path, newline="", encoding="utf-8") as f:
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
                if "boletin.do?accion=ver2" in link or "boletin.do" in link and "ver2" in link:
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
    boletin_tasks: List[dict],
    delay: float,
) -> List[dict]:
    """
    For each HTML boletin (boletin.do?accion=ver2), scrapes the page,
    extracts the internal PDF IDs via ver(id) in the JS, and returns
    one individual task per PDF found.
    """
    expanded = []
    for task in boletin_tasks:
        url = normalize_url(task["page_url"])
        if not url:
            continue
        await asyncio.sleep(delay)
        try:
            async with session.get(
                url, headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    log.warning("HTTP %d expanding boletin: %s", resp.status, url)
                    continue
                html = await resp.text(errors="replace")
        except Exception as exc:
            log.warning("Error expanding boletin %s: %s", url, exc)
            continue

        pdf_ids = re.findall(r'\bver\((\d+)\)', html)
        if not pdf_ids:
            log.info("Boletin with no internal PDFs: %s", url)
            continue

        log.info("Boletin %s → %d internal PDFs", task["page_url"], len(pdf_ids))
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

    return expanded


# ──────────────────────────────────────────────────────────────
# Type 2: HTML → PDF conversion with weasyprint (Plone pages)
# ──────────────────────────────────────────────────────────────

async def html_to_pdf_file(
    session: aiohttp.ClientSession,
    page_url: str,
    dest_path: Path,
    delay: float,
) -> str:
    """
    Downloads the HTML of a Plone page and converts it to PDF with weasyprint.
    Returns True, "PERMANENT", or False (same contract as download_file).
    """
    try:
        import weasyprint
    except ImportError:
        log.error("weasyprint not installed. Run: pip install weasyprint")
        return False

    url = normalize_url(page_url)
    if not url:
        return "PERMANENT"

    await asyncio.sleep(delay)
    try:
        async with session.get(
            url, headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=30),
            allow_redirects=True,
        ) as resp:
            if resp.status == 404:
                return "PERMANENT"
            if resp.status != 200:
                return False
            html = await resp.text(errors="replace")
            final_url = str(resp.url)
    except Exception as exc:
        log.warning("Error fetching HTML from %s: %s", url, exc)
        return False

    # Run in an executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    try:
        def _convert():
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            weasyprint.HTML(string=html, base_url=final_url).write_pdf(str(dest_path))

        await loop.run_in_executor(None, _convert)
        return True
    except Exception as exc:
        log.warning("weasyprint failed for %s: %s", url, exc)
        return "PERMANENT"


# ──────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────

async def run(output_dir: Path, concurrency: int, delay: float):
    tasks = build_task_list(output_dir)
    done = load_checkpoint()

    # Migration: unblock tasks previously marked SKIP that now have a specific
    # handler (boletin_html, html_to_pdf). Happens on first run with updated code.
    newly_supported = {"boletin_html", "html_to_pdf"}
    keys_to_unblock = {
        SKIP_PREFIX + t["key"]
        for t in tasks if t["link_type"] in newly_supported
    }
    removed = len(done & keys_to_unblock)
    if removed:
        done -= keys_to_unblock
        save_checkpoint(done)
        log.info("Migration: %d SKIP entries unblocked for reprocessing", removed)

    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
    stats = {"ok": 0, "permanent": 0, "transient": 0}

    async with aiohttp.ClientSession(connector=connector) as session:

        # ── Phase 1: expand HTML boletines into individual tasks ──
        boletin_html_tasks = [
            t for t in tasks
            if t["link_type"] == "boletin_html" and is_pending(t["key"], done)
        ]
        if boletin_html_tasks:
            log.info("Expanding %d HTML boletines...", len(boletin_html_tasks))
            expanded = await expand_boletin_tasks(session, boletin_html_tasks, delay)
            log.info("→ %d internal PDFs found in boletines", len(expanded))
            # Mark container boletines as processed (they are not files themselves)
            for t in boletin_html_tasks:
                done.add(SKIP_PREFIX + t["key"])
            # Add expanded tasks to the full set
            tasks = [t for t in tasks if t["link_type"] != "boletin_html"] + expanded
            save_checkpoint(done)

        # ── Phase 2: filter pending tasks ──
        pending = [
            t for t in tasks
            if is_pending(t["key"], done) and not Path(t["key"]).exists()
        ]

        skipped = sum(1 for t in tasks if (SKIP_PREFIX + t["key"]) in done)
        ok_prev  = sum(1 for t in tasks if t["key"] in done)
        log.info(
            "Total: %d | Previously OK: %d | Skipped: %d | Pending: %d",
            len(tasks), ok_prev, skipped, len(pending),
        )

        # ── Phase 3: download / convert ──
        semaphore = asyncio.Semaphore(concurrency)

        async def process(task: dict):
            async with semaphore:
                outcome = None

                if task["link_type"] == "html_to_pdf":
                    outcome = await html_to_pdf_file(
                        session, task["page_url"], task["dest"], delay
                    )
                else:
                    result = await resolve_pdf_url(
                        session, task["page_url"], task["link_type"], delay
                    )
                    if result == "PERMANENT":
                        outcome = "PERMANENT"
                    elif result is None:
                        outcome = None  # transient
                    else:
                        outcome = await download_file(
                            session, result, task["dest"], delay
                        )

                if outcome is True:
                    stats["ok"] += 1
                    done.add(task["key"])
                    if stats["ok"] % 50 == 0:
                        save_checkpoint(done)
                        log.info("Checkpoint: %d OK so far", stats["ok"])
                elif outcome == "PERMANENT":
                    stats["permanent"] += 1
                    done.add(SKIP_PREFIX + task["key"])
                else:
                    stats["transient"] += 1

        await tqdm.gather(
            *[process(t) for t in pending],
            desc="Downloading",
            total=len(pending),
        )

    save_checkpoint(done)
    log.info(
        "Done. OK: %d | No PDF/permanent: %d | Network error (retryable): %d",
        stats["ok"], stats["permanent"], stats["transient"],
    )


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bulk downloader — Municipalidad de Rosario")
    parser.add_argument("--output", default="./downloads")
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Parallel downloads (default: 5 — keep low to avoid being blocked)")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="Seconds to wait between requests (default: 0.5)")
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("SCRAPPER_DIR: %s", SCRAPPER_DIR)
    log.info("Output: %s | Concurrency: %d | Delay: %.1fs",
             output_dir, args.concurrency, args.delay)

    asyncio.run(run(output_dir, args.concurrency, args.delay))


if __name__ == "__main__":
    main()
