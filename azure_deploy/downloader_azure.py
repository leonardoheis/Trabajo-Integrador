"""
Variante del descargador para Azure Container Instances.
En lugar de guardar en disco, sube cada PDF directamente a Azure Blob Storage.

Variables de entorno requeridas:
    AZURE_STORAGE_CONNECTION_STRING  - connection string de la Storage Account
    AZURE_CONTAINER_NAME             - nombre del contenedor blob (default: rosario-docs)
    SCRAPPER_DIR                     - ruta local con los CSVs (se copian al montar el share)
    CONCURRENCY                      - simultaneous downloads (default: 8)
    DELAY                            - delay entre requests (default: 0.3)
"""

import asyncio
import csv
import json
import logging
import os
import re
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import aiohttp
from bs4 import BeautifulSoup
from azure.storage.blob.aio import BlobServiceClient
from tqdm.asyncio import tqdm

# ──────────────────────────────────────────────────────────────
# Config desde entorno
# ──────────────────────────────────────────────────────────────

CONN_STR        = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
CONTAINER_NAME  = os.environ.get("AZURE_CONTAINER_NAME", "rosario-docs")
SCRAPPER_DIR    = Path(os.environ.get("SCRAPPER_DIR", "./Scrapper"))
CONCURRENCY     = int(os.environ.get("CONCURRENCY", "8"))
DELAY           = float(os.environ.get("DELAY", "0.3"))
BASE_URL        = "https://www.rosario.gob.ar"
CHECKPOINT_BLOB = "checkpoint.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# (misma CSV_CONFIG que downloader.py — omitida por brevedad, importar desde allí)
from downloader import CSV_CONFIG, HEADERS, normativa_id_from_url, build_pdf_url, sanitize


# ──────────────────────────────────────────────────────────────
# Checkpoint en Blob Storage
# ──────────────────────────────────────────────────────────────

async def load_checkpoint(container) -> set:
    try:
        blob = container.get_blob_client(CHECKPOINT_BLOB)
        data = await blob.download_blob()
        content = await data.readall()
        return set(json.loads(content))
    except Exception:
        return set()


async def save_checkpoint(container, done: set):
    blob = container.get_blob_client(CHECKPOINT_BLOB)
    await blob.upload_blob(json.dumps(list(done)), overwrite=True)


# ──────────────────────────────────────────────────────────────
# Descarga y upload a Blob Storage
# ──────────────────────────────────────────────────────────────

async def download_and_upload(
    session: aiohttp.ClientSession,
    container,
    pdf_url: str,
    blob_path: str,
    delay: float,
    retries: int = 3,
) -> bool:
    await asyncio.sleep(delay)
    for attempt in range(1, retries + 1):
        try:
            async with session.get(
                pdf_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 404:
                    log.warning("404: %s", pdf_url)
                    return False
                if resp.status != 200:
                    await asyncio.sleep(2 ** attempt)
                    continue

                data = await resp.read()
                if b"%PDF" not in data[:10]:
                    return False

                blob = container.get_blob_client(blob_path)
                await blob.upload_blob(BytesIO(data), overwrite=False)
                return True

        except Exception as exc:
            log.warning("Intento %d/%d fallido (%s): %s", attempt, retries, pdf_url, exc)
            await asyncio.sleep(2 ** attempt)

    return False


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

async def run():
    async with BlobServiceClient.from_connection_string(CONN_STR) as blob_service:
        container = blob_service.get_container_client(CONTAINER_NAME)
        try:
            await container.create_container()
        except Exception:
            pass  # ya existe

        done = await load_checkpoint(container)
        tasks = build_task_list()
        pending = [t for t in tasks if t["key"] not in done]

        log.info("Pendientes: %d / %d", len(pending), len(tasks))
        semaphore = asyncio.Semaphore(CONCURRENCY)
        stats = {"ok": 0, "fail": 0}

        connector = aiohttp.TCPConnector(limit=CONCURRENCY, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:

            async def process(task):
                async with semaphore:
                    # Resolver URL del PDF
                    page_url = task["page_url"]
                    link_type = task["link_type"]

                    if link_type == "direct_pdf":
                        pdf_url = page_url
                    elif link_type == "normativa":
                        nid = normativa_id_from_url(page_url)
                        pdf_url = build_pdf_url(nid) if nid else None
                    else:
                        pdf_url = None  # scrape_page: simplificado aquí

                    if not pdf_url:
                        stats["fail"] += 1
                        return

                    blob_path = task["blob_path"]
                    ok = await download_and_upload(session, container, pdf_url, blob_path, DELAY)
                    if ok:
                        stats["ok"] += 1
                        done.add(task["key"])
                        if stats["ok"] % 100 == 0:
                            await save_checkpoint(container, done)
                    else:
                        stats["fail"] += 1

            await tqdm.gather(*[process(t) for t in pending], total=len(pending))

        await save_checkpoint(container, done)
        log.info("Fin. OK: %d | Fail: %d", stats["ok"], stats["fail"])


def build_task_list():
    tasks = []
    for csv_file, cfg in CSV_CONFIG.items():
        csv_path = SCRAPPER_DIR / csv_file
        if not csv_path.exists():
            continue
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                link = row.get(cfg["link_col"], "").strip().strip('"')
                if not link:
                    continue
                name_parts = {k: sanitize(row.get(k, "").strip()) for k in cfg["name_cols"]}
                filename = cfg["name_fmt"].format(**name_parts)
                blob_path = f"{cfg['folder']}/{filename}"
                tasks.append({
                    "key": blob_path,
                    "page_url": link,
                    "link_type": cfg["link_type"],
                    "blob_path": blob_path,
                })
    return tasks


if __name__ == "__main__":
    asyncio.run(run())
