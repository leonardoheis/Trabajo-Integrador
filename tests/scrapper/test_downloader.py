"""Tests for scrapper/downloader.py."""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from typing_extensions import Self

import scrapper.downloader as dl
from scrapper.downloader import (
    SKIP_PREFIX,
    _apply_migration,  # noqa: PLC2701
    _DownloadCtx,  # noqa: PLC2701
    _expand_boletines,  # noqa: PLC2701
    _filter_pending,  # noqa: PLC2701
    _is_pdf_url,  # noqa: PLC2701
    _log_progress,  # noqa: PLC2701
    _process_task,  # noqa: PLC2701
    build_normativa_pdf_url,
    build_task_list,
    download_file,
    expand_boletin_tasks,
    extract_pdf_url_from_html,
    html_to_pdf_file,
    is_pending,
    load_checkpoint,
    main,
    normalize_url,
    resolve_pdf_url,
    sanitize,
    save_checkpoint,
)

if TYPE_CHECKING:
    from pathlib import Path

# ─── HTTP fakes ───────────────────────────────────────────────────────────────


class _Resp:
    """Minimal fake aiohttp response, usable as an async context manager."""

    def __init__(
        self,
        *,
        status: int = 200,
        content_type: str = "text/html",
        text: str = "",
        body: bytes = b"",
        url: str = "http://example.com",
    ) -> None:
        self.status = status
        self.headers: dict[str, str] = {"Content-Type": content_type}
        self.url = url
        self._text = text
        self._body = body or text.encode()

    async def text(self, errors: str = "strict") -> str:  # noqa: ARG002
        return self._text

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass


class _ErrorResp:
    """Fake response whose __aenter__ raises aiohttp.ClientError."""

    async def __aenter__(self) -> Self:
        msg = "connection refused"
        raise aiohttp.ClientError(msg)

    async def __aexit__(self, *_: object) -> None:
        pass


class _Session:
    """Fake aiohttp.ClientSession returning responses from an ordered queue."""

    def __init__(self, *responses: _Resp | _ErrorResp) -> None:
        self._queue = list(responses)

    def get(self, url: str, **kwargs: object) -> _Resp | _ErrorResp:  # noqa: ARG002
        return self._queue.pop(0)


# ─── normalize_url ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("/www.foo.com/path", "http://www.foo.com/path"),
        ("/ssl.foo.com/path", "https://ssl.foo.com/path"),
        ("www.foo.com/path", "http://www.foo.com/path"),
        ("ssl.foo.com/path", "https://ssl.foo.com/path"),
        ("http://example.com/file.pdf", "http://example.com/file.pdf"),
        ("https://example.com/file.pdf", "https://example.com/file.pdf"),
        ("  https://example.com  ", "https://example.com"),
    ],
)
def test_normalize_url(raw: str, expected: str | None) -> None:
    assert normalize_url(raw) == expected


def test_normalize_url_path_only_returns_none() -> None:
    # "/path/only" → "http:///path/only" → netloc="" → None
    assert normalize_url("/path/only") is None


# ─── _is_pdf_url ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://rosario.gob.ar/normativa/verArchivo?id=1", True),
        ("https://rosario.gob.ar/getPdf?id=2", True),
        ("https://rosario.gob.ar/documento.do?id=3", True),
        ("https://example.com/file.pdf", True),
        ("https://example.com/FILE.PDF", True),
        ("https://example.com/page.html", False),
        ("", False),
    ],
)
def test_is_pdf_url(url: str, expected: bool) -> None:  # noqa: FBT001
    assert _is_pdf_url(url) is expected


# ─── build_normativa_pdf_url ──────────────────────────────────────────────────


def test_build_normativa_pdf_url_with_id() -> None:
    url = "https://www.rosario.gob.ar/normativa/visualExterna.do?idNormativa=123"
    result = build_normativa_pdf_url(url)
    assert (
        result == "https://www.rosario.gob.ar/normativa/verArchivo?tipo=pdf&id=123&modo=attachment"
    )


def test_build_normativa_pdf_url_without_id_returns_none() -> None:
    assert build_normativa_pdf_url("https://www.rosario.gob.ar/normativa/ver.do?tipo=pdf") is None


def test_build_normativa_pdf_url_with_multiple_params() -> None:
    url = "https://www.rosario.gob.ar/normativa/visualExterna.do?tipo=pdf&idNormativa=456&foo=bar"
    result = build_normativa_pdf_url(url)
    assert (
        result == "https://www.rosario.gob.ar/normativa/verArchivo?tipo=pdf&id=456&modo=attachment"
    )


# ─── sanitize ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('decreto: "especial" <2024>', "decreto_ _especial_ _2024_"),
        ("normal text", "normal text"),
        ("  spaces  ", "spaces"),
        (r'a\b*c?d:"<>|', "a_b_c_d_____"),
    ],
)
def test_sanitize(raw: str, expected: str) -> None:
    assert sanitize(raw) == expected


# ─── is_pending ───────────────────────────────────────────────────────────────


def test_is_pending_new_key() -> None:
    assert is_pending("path/file.pdf", set()) is True


def test_is_pending_already_done() -> None:
    assert is_pending("path/file.pdf", {"path/file.pdf"}) is False


def test_is_pending_in_skip() -> None:
    assert is_pending("path/file.pdf", {SKIP_PREFIX + "path/file.pdf"}) is False


# ─── extract_pdf_url_from_html ────────────────────────────────────────────────


def test_extract_pdf_url_from_html_anchor_tag() -> None:
    html = '<html><a href="https://rosario.gob.ar/normativa/verArchivo?id=1">link</a></html>'
    result = extract_pdf_url_from_html(html, "https://rosario.gob.ar/page")
    assert result == "https://rosario.gob.ar/normativa/verArchivo?id=1"


def test_extract_pdf_url_from_html_iframe() -> None:
    html = '<html><iframe src="https://rosario.gob.ar/getPdf?id=2"></iframe></html>'
    result = extract_pdf_url_from_html(html, "https://rosario.gob.ar/page")
    assert result == "https://rosario.gob.ar/getPdf?id=2"


def test_extract_pdf_url_from_html_relative_url_resolved() -> None:
    html = '<html><a href="/normativa/verArchivo?id=3">PDF</a></html>'
    result = extract_pdf_url_from_html(html, "https://rosario.gob.ar/page")
    assert result == "https://rosario.gob.ar/normativa/verArchivo?id=3"


def test_extract_pdf_url_from_html_regex_fallback() -> None:
    html = "<script>var url = '/normativa/verArchivo?tipo=pdf&id=4&modo=attachment';</script>"
    result = extract_pdf_url_from_html(html, "https://rosario.gob.ar/page")
    assert result == "https://rosario.gob.ar/normativa/verArchivo?tipo=pdf&id=4&modo=attachment"


def test_extract_pdf_url_from_html_no_pdf_returns_none() -> None:
    result = extract_pdf_url_from_html("<html><p>No PDF here</p></html>", "https://example.com")
    assert result is None


# ─── Checkpoint ───────────────────────────────────────────────────────────────


def test_checkpoint_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    done = {"path/to/file.pdf", SKIP_PREFIX + "path/to/other.pdf"}
    save_checkpoint(done)
    assert load_checkpoint() == done


def test_load_checkpoint_returns_empty_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "nonexistent.json")
    assert load_checkpoint() == set()


def test_save_checkpoint_persists_all_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cp = tmp_path / "checkpoint.json"
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", cp)
    save_checkpoint({"a", "b", "c"})
    data = json.loads(cp.read_text())
    assert set(data) == {"a", "b", "c"}


# ─── build_task_list ──────────────────────────────────────────────────────────


def _write_csv(path: Path, header: list[str], *rows: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(row)


def test_build_task_list_single_normativa_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_dir = tmp_path / "csvs"
    csv_dir.mkdir()
    _write_csv(
        csv_dir / "ordenanzas.csv",
        ["TEXTO_VIGENTE_NORMA", "NUMERO", "ANIO"],
        ["https://www.rosario.gob.ar/normativa/visualExterna.do?idNormativa=1", "42", "2024"],
    )
    monkeypatch.setattr(dl, "SCRAPPER_DIR", csv_dir)

    tasks = build_task_list(tmp_path / "downloads")

    assert len(tasks) == 1
    t = tasks[0]
    assert t["link_type"] == "normativa"
    assert t["page_url"] == "https://www.rosario.gob.ar/normativa/visualExterna.do?idNormativa=1"
    assert t["dest"] == tmp_path / "downloads" / "ordenanzas" / "ordenanza_42_2024.pdf"


def test_build_task_list_skips_empty_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_dir = tmp_path / "csvs"
    csv_dir.mkdir()
    _write_csv(
        csv_dir / "ordenanzas.csv",
        ["TEXTO_VIGENTE_NORMA", "NUMERO", "ANIO"],
        ["", "42", "2024"],
    )
    monkeypatch.setattr(dl, "SCRAPPER_DIR", csv_dir)
    assert build_task_list(tmp_path / "downloads") == []


def test_build_task_list_boletin_html_link_type_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_dir = tmp_path / "csvs"
    csv_dir.mkdir()
    _write_csv(
        csv_dir / "boletines.csv",
        ["LINK", "NUMERO", "ANIO"],
        ["https://rosario.gob.ar/mr/boletines/boletin.do?accion=ver2&id=50", "50", "2020"],
    )
    monkeypatch.setattr(dl, "SCRAPPER_DIR", csv_dir)

    tasks = build_task_list(tmp_path / "downloads")

    assert len(tasks) == 1
    assert tasks[0]["link_type"] == "boletin_html"


def test_build_task_list_html_to_pdf_link_type_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_dir = tmp_path / "csvs"
    csv_dir.mkdir()
    _write_csv(
        csv_dir / "ordenanzas.csv",
        ["TEXTO_VIGENTE_NORMA", "NUMERO", "ANIO"],
        ["https://rosario.gob.ar/mr/normativa/ver?id=10", "10", "2023"],
    )
    monkeypatch.setattr(dl, "SCRAPPER_DIR", csv_dir)

    tasks = build_task_list(tmp_path / "downloads")

    assert len(tasks) == 1
    assert tasks[0]["link_type"] == "html_to_pdf"


def test_build_task_list_missing_csv_produces_no_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dl, "SCRAPPER_DIR", tmp_path / "nonexistent")
    assert build_task_list(tmp_path / "downloads") == []


# ─── _filter_pending ──────────────────────────────────────────────────────────


def test_filter_pending_includes_new_task() -> None:
    tasks = [{"key": "/nonexistent/path.pdf"}]
    assert _filter_pending(tasks, set()) == tasks


def test_filter_pending_excludes_completed_on_disk(tmp_path: Path) -> None:
    f = tmp_path / "file.pdf"
    f.write_bytes(b"%PDF")
    assert _filter_pending([{"key": str(f)}], set()) == []


def test_filter_pending_excludes_key_in_done() -> None:
    tasks = [{"key": "/some/path.pdf"}]
    assert _filter_pending(tasks, {"/some/path.pdf"}) == []


def test_filter_pending_excludes_skip_in_done() -> None:
    tasks = [{"key": "/some/path.pdf"}]
    assert _filter_pending(tasks, {SKIP_PREFIX + "/some/path.pdf"}) == []


# ─── _apply_migration ─────────────────────────────────────────────────────────


def test_apply_migration_unblocks_html_to_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "cp.json")
    tasks = [{"key": "doc.pdf", "link_type": "html_to_pdf"}]
    done: set[str] = {SKIP_PREFIX + "doc.pdf"}
    _apply_migration(tasks, done)
    assert SKIP_PREFIX + "doc.pdf" not in done


def test_apply_migration_does_not_unblock_boletin_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "cp.json")
    tasks = [{"key": "boletin.pdf", "link_type": "boletin_html"}]
    done: set[str] = {SKIP_PREFIX + "boletin.pdf"}
    _apply_migration(tasks, done)
    # boletin_html is intentionally excluded from migration after the re-scrape loop fix
    assert SKIP_PREFIX + "boletin.pdf" in done


def test_apply_migration_no_op_when_nothing_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "cp.json")
    tasks = [{"key": "doc.pdf", "link_type": "normativa"}]
    done: set[str] = {"other/key.pdf"}
    _apply_migration(tasks, done)
    assert done == {"other/key.pdf"}


# ─── resolve_pdf_url (async) ──────────────────────────────────────────────────


def test_resolve_pdf_url_invalid_url_returns_none() -> None:
    result = asyncio.run(resolve_pdf_url(_Session(), "", "direct_pdf", delay=0))
    assert result is None


def test_resolve_pdf_url_direct_pdf_returns_normalized_url() -> None:
    result = asyncio.run(
        resolve_pdf_url(_Session(), "http://example.com/file.pdf", "direct_pdf", delay=0)
    )
    assert result == "http://example.com/file.pdf"


def test_resolve_pdf_url_normativa_with_id_builds_url_without_http() -> None:
    url = "https://www.rosario.gob.ar/normativa/visualExterna.do?idNormativa=789"
    result = asyncio.run(resolve_pdf_url(_Session(), url, "normativa", delay=0))
    assert (
        result == "https://www.rosario.gob.ar/normativa/verArchivo?tipo=pdf&id=789&modo=attachment"
    )


def test_resolve_pdf_url_scrape_finds_pdf_link() -> None:
    html = '<a href="/normativa/verArchivo?id=42">PDF</a>'
    resp = _Resp(status=200, text=html, url="https://rosario.gob.ar/page")
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            resolve_pdf_url(_Session(resp), "https://rosario.gob.ar/page", "scrape_page", delay=0)
        )
    assert result == "https://rosario.gob.ar/normativa/verArchivo?id=42"


def test_resolve_pdf_url_scrape_404_returns_permanent() -> None:
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            resolve_pdf_url(
                _Session(_Resp(status=404)),
                "https://rosario.gob.ar/page",
                "scrape_page",
                delay=0,
            )
        )
    assert result == "PERMANENT"


def test_resolve_pdf_url_scrape_no_pdf_returns_permanent() -> None:
    resp = _Resp(status=200, text="<html><p>no pdf</p></html>", url="https://rosario.gob.ar/page")
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            resolve_pdf_url(_Session(resp), "https://rosario.gob.ar/page", "scrape_page", delay=0)
        )
    assert result == "PERMANENT"


# ─── expand_boletin_tasks (async) ────────────────────────────────────────────


def _boletin_task(folder: Path) -> dict:
    return {
        "page_url": "https://rosario.gob.ar/boletin.do?accion=ver2&id=50",
        "key": str(folder / "boletin_50_2020.pdf"),
        "folder": folder,
        "name_base": "boletin_50_2020",
    }


def test_expand_boletin_tasks_extracts_pdf_ids(tmp_path: Path) -> None:
    html = "<script>function ver(id){} ver(101); ver(202);</script>"
    resp = _Resp(status=200, text=html, url="https://rosario.gob.ar/boletin")
    task = _boletin_task(tmp_path)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        expanded, expanded_keys = asyncio.run(expand_boletin_tasks(_Session(resp), [task], delay=0))

    expected_pdf_count = 2
    assert len(expanded) == expected_pdf_count
    assert task["key"] in expanded_keys
    urls = {t["page_url"] for t in expanded}
    assert any("101" in u for u in urls)
    assert any("202" in u for u in urls)
    assert all(t["link_type"] == "direct_pdf" for t in expanded)


def test_expand_boletin_tasks_empty_page_not_in_expanded_keys(tmp_path: Path) -> None:
    resp = _Resp(status=200, text="<html>no pdf ids</html>", url="https://rosario.gob.ar/boletin")
    task = _boletin_task(tmp_path)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        expanded, expanded_keys = asyncio.run(expand_boletin_tasks(_Session(resp), [task], delay=0))

    assert expanded == []
    assert task["key"] not in expanded_keys


def test_expand_boletin_tasks_http_error_not_in_expanded_keys(tmp_path: Path) -> None:
    task = _boletin_task(tmp_path)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        expanded, expanded_keys = asyncio.run(
            expand_boletin_tasks(_Session(_ErrorResp()), [task], delay=0)
        )

    assert expanded == []
    assert task["key"] not in expanded_keys


def test_expand_boletin_tasks_http_error_does_not_raise(tmp_path: Path) -> None:
    task = _boletin_task(tmp_path)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        # Should complete without propagating the ClientError
        result = asyncio.run(expand_boletin_tasks(_Session(_ErrorResp()), [task], delay=0))
    assert result == ([], set())


# ─── download_file (async) ───────────────────────────────────────────────────


_PDF = b"%PDF-1.4 fake content for tests"


def test_download_file_success_writes_file(tmp_path: Path) -> None:
    resp = _Resp(status=200, content_type="application/pdf", body=_PDF)
    dest = tmp_path / "sub" / "file.pdf"
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            download_file(_Session(resp), "http://example.com/file.pdf", dest, delay=0)
        )
    assert result is True
    assert dest.read_bytes() == _PDF


def test_download_file_creates_parent_directories(tmp_path: Path) -> None:
    resp = _Resp(status=200, content_type="application/pdf", body=_PDF)
    dest = tmp_path / "a" / "b" / "c" / "file.pdf"
    with patch("asyncio.sleep", new_callable=AsyncMock):
        asyncio.run(download_file(_Session(resp), "http://example.com/file.pdf", dest, delay=0))
    assert dest.exists()


def test_download_file_404_returns_permanent(tmp_path: Path) -> None:
    resp = _Resp(status=404)
    dest = tmp_path / "file.pdf"
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            download_file(_Session(resp), "http://example.com/file.pdf", dest, delay=0)
        )
    assert result == "PERMANENT"
    assert not dest.exists()


def test_download_file_non_pdf_content_returns_permanent(tmp_path: Path) -> None:
    resp = _Resp(status=200, content_type="text/html", body=b"<html>not a pdf</html>")
    dest = tmp_path / "file.pdf"
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            download_file(_Session(resp), "http://example.com/file.pdf", dest, delay=0)
        )
    assert result == "PERMANENT"
    assert not dest.exists()


def test_download_file_retry_on_503_then_success(tmp_path: Path) -> None:
    retry_resp = _Resp(status=503)
    ok_resp = _Resp(status=200, content_type="application/pdf", body=_PDF)
    dest = tmp_path / "file.pdf"
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            download_file(
                _Session(retry_resp, ok_resp), "http://example.com/file.pdf", dest, delay=0
            )
        )
    assert result is True
    assert dest.read_bytes() == _PDF


def test_download_file_all_retries_exhausted_returns_false(tmp_path: Path) -> None:
    dest = tmp_path / "file.pdf"
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            download_file(
                _Session(_Resp(status=503), _Resp(status=503), _Resp(status=503)),
                "http://example.com/file.pdf",
                dest,
                delay=0,
                retries=3,
            )
        )
    assert result is False
    assert not dest.exists()


# ─── extract_pdf_url_from_html: generic attrs sweep ──────────────────────────


def test_extract_pdf_url_from_html_data_attr_sweep() -> None:
    # PDF URL in a non-standard attribute — exercises _search_all_attrs
    html = '<div data-file="https://rosario.gob.ar/normativa/verArchivo?id=5"></div>'
    result = extract_pdf_url_from_html(html, "https://rosario.gob.ar/page")
    assert result == "https://rosario.gob.ar/normativa/verArchivo?id=5"


# ─── _scrape_pdf_url alternate paths (via resolve_pdf_url) ───────────────────


def test_resolve_pdf_url_scrape_network_error_returns_none() -> None:
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            resolve_pdf_url(
                _Session(_ErrorResp()),
                "https://rosario.gob.ar/page",
                "scrape_page",
                delay=0,
            )
        )
    assert result is None


def test_resolve_pdf_url_scrape_non_200_returns_none() -> None:
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            resolve_pdf_url(
                _Session(_Resp(status=503)),
                "https://rosario.gob.ar/page",
                "scrape_page",
                delay=0,
            )
        )
    assert result is None


def test_resolve_pdf_url_scrape_pdf_content_type_returns_final_url() -> None:
    resp = _Resp(status=200, content_type="application/pdf", url="https://rosario.gob.ar/file.pdf")
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            resolve_pdf_url(_Session(resp), "https://rosario.gob.ar/page", "scrape_page", delay=0)
        )
    assert result == "https://rosario.gob.ar/file.pdf"


def test_resolve_pdf_url_scrape_normativa_redirect_builds_direct_url() -> None:
    # After a redirect the final URL is a normativa page → build_normativa_pdf_url succeeds
    normativa = "https://www.rosario.gob.ar/normativa/visualExterna.do?idNormativa=789"
    resp = _Resp(status=200, content_type="text/html", text="<html></html>", url=normativa)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            resolve_pdf_url(_Session(resp), "https://rosario.gob.ar/page", "scrape_page", delay=0)
        )
    assert (
        result == "https://www.rosario.gob.ar/normativa/verArchivo?tipo=pdf&id=789&modo=attachment"
    )


# ─── download_file: network error with retry ─────────────────────────────────


def test_download_file_network_error_then_success(tmp_path: Path) -> None:
    ok_resp = _Resp(status=200, content_type="application/pdf", body=_PDF)
    dest = tmp_path / "file.pdf"
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            download_file(
                _Session(_ErrorResp(), ok_resp),
                "http://example.com/file.pdf",
                dest,
                delay=0,
            )
        )
    assert result is True
    assert dest.read_bytes() == _PDF


# ─── expand_boletin_tasks: additional edge cases ─────────────────────────────


def test_expand_boletin_tasks_invalid_url_skips_task() -> None:
    # normalize_url("") → None → task is skipped
    task: dict = {"page_url": "", "key": "boletin.pdf", "folder": "unused", "name_base": "b"}
    with patch("asyncio.sleep", new_callable=AsyncMock):
        expanded, expanded_keys = asyncio.run(expand_boletin_tasks(_Session(), [task], delay=0))
    assert expanded == []
    assert "boletin.pdf" not in expanded_keys


def test_expand_boletin_tasks_non_200_response_skips(tmp_path: Path) -> None:
    task = _boletin_task(tmp_path)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        expanded, expanded_keys = asyncio.run(
            expand_boletin_tasks(_Session(_Resp(status=404)), [task], delay=0)
        )
    assert expanded == []
    assert task["key"] not in expanded_keys


# ─── html_to_pdf_file ────────────────────────────────────────────────────────


def test_html_to_pdf_invalid_url_returns_permanent(tmp_path: Path) -> None:
    result = asyncio.run(html_to_pdf_file(_Session(), "", tmp_path / "out.pdf", delay=0))
    assert result == "PERMANENT"


def test_html_to_pdf_404_returns_permanent(tmp_path: Path) -> None:
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            html_to_pdf_file(
                _Session(_Resp(status=404)),
                "https://example.com/page",
                tmp_path / "out.pdf",
                delay=0,
            )
        )
    assert result == "PERMANENT"


def test_html_to_pdf_non_200_returns_false(tmp_path: Path) -> None:
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            html_to_pdf_file(
                _Session(_Resp(status=503)),
                "https://example.com/page",
                tmp_path / "out.pdf",
                delay=0,
            )
        )
    assert result is False


def test_html_to_pdf_network_error_returns_false(tmp_path: Path) -> None:
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            html_to_pdf_file(
                _Session(_ErrorResp()),
                "https://example.com/page",
                tmp_path / "out.pdf",
                delay=0,
            )
        )
    assert result is False


def test_html_to_pdf_weasyprint_success(tmp_path: Path) -> None:
    html = "<html><body>Content</body></html>"
    resp = _Resp(status=200, content_type="text/html", text=html, url="https://example.com/page")
    mock_wp = MagicMock()
    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.dict(sys.modules, {"weasyprint": mock_wp}),
    ):
        result = asyncio.run(
            html_to_pdf_file(
                _Session(resp), "https://example.com/page", tmp_path / "out.pdf", delay=0
            )
        )
    assert result is True
    mock_wp.HTML.assert_called_once()


def test_html_to_pdf_weasyprint_oserror_returns_permanent(tmp_path: Path) -> None:
    html = "<html><body>Content</body></html>"
    resp = _Resp(status=200, content_type="text/html", text=html, url="https://example.com/page")
    mock_wp = MagicMock()
    mock_wp.HTML.side_effect = OSError("cannot load library")
    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.dict(sys.modules, {"weasyprint": mock_wp}),
    ):
        result = asyncio.run(
            html_to_pdf_file(
                _Session(resp), "https://example.com/page", tmp_path / "out.pdf", delay=0
            )
        )
    assert result == "PERMANENT"


# ─── _expand_boletines ────────────────────────────────────────────────────────


def test_expand_boletines_no_boletin_tasks_returns_unchanged() -> None:
    tasks: list[dict] = [{"link_type": "direct_pdf", "key": "file.pdf"}]
    done: set[str] = set()
    result = asyncio.run(_expand_boletines(_Session(), tasks, done, delay=0))
    assert result == tasks


def test_expand_boletines_expands_and_marks_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "cp.json")
    task = {
        "link_type": "boletin_html",
        "key": str(tmp_path / "boletin.pdf"),
        "page_url": "https://rosario.gob.ar/boletin.do?accion=ver2&id=50",
        "folder": tmp_path,
        "name_base": "boletin_50_2020",
    }
    resp = _Resp(
        status=200, text="<script>ver(101);</script>", url="https://rosario.gob.ar/boletin"
    )
    done: set[str] = set()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(_expand_boletines(_Session(resp), [task], done, delay=0))
    assert all(t["link_type"] != "boletin_html" for t in result)
    assert SKIP_PREFIX + task["key"] in done


# ─── _log_progress ────────────────────────────────────────────────────────────


def test_log_progress_does_not_raise() -> None:
    tasks: list[dict] = [{"key": "ok.pdf"}, {"key": "skip.pdf"}, {"key": "pending.pdf"}]
    done: set[str] = {"ok.pdf", SKIP_PREFIX + "skip.pdf"}
    pending: list[dict] = [{"key": "pending.pdf"}]
    _log_progress(tasks, pending, done)  # verifies no exception


# ─── _process_task ────────────────────────────────────────────────────────────


def test_process_task_html_to_pdf_success(tmp_path: Path) -> None:
    task = {
        "link_type": "html_to_pdf",
        "page_url": "https://example.com/page",
        "dest": tmp_path / "out.pdf",
        "key": str(tmp_path / "out.pdf"),
    }
    done: set[str] = set()
    stats: dict[str, int] = {"ok": 0, "permanent": 0, "transient": 0}
    ctx = _DownloadCtx(session=_Session(), semaphore=asyncio.Semaphore(1), delay=0)
    with patch("scrapper.downloader.html_to_pdf_file", new_callable=AsyncMock, return_value=True):
        asyncio.run(_process_task(ctx, task, done, stats))
    assert task["key"] in done
    assert stats["ok"] == 1


def test_process_task_html_to_pdf_permanent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "cp.json")
    task = {
        "link_type": "html_to_pdf",
        "page_url": "https://example.com/page",
        "dest": tmp_path / "out.pdf",
        "key": str(tmp_path / "out.pdf"),
    }
    done: set[str] = set()
    stats: dict[str, int] = {"ok": 0, "permanent": 0, "transient": 0}
    ctx = _DownloadCtx(session=_Session(), semaphore=asyncio.Semaphore(1), delay=0)
    with patch(
        "scrapper.downloader.html_to_pdf_file", new_callable=AsyncMock, return_value="PERMANENT"
    ):
        asyncio.run(_process_task(ctx, task, done, stats))
    assert SKIP_PREFIX + task["key"] in done
    assert stats["permanent"] == 1


def test_process_task_html_to_pdf_transient(tmp_path: Path) -> None:
    task = {
        "link_type": "html_to_pdf",
        "page_url": "https://example.com/page",
        "dest": tmp_path / "out.pdf",
        "key": str(tmp_path / "out.pdf"),
    }
    done: set[str] = set()
    stats: dict[str, int] = {"ok": 0, "permanent": 0, "transient": 0}
    ctx = _DownloadCtx(session=_Session(), semaphore=asyncio.Semaphore(1), delay=0)
    with patch("scrapper.downloader.html_to_pdf_file", new_callable=AsyncMock, return_value=False):
        asyncio.run(_process_task(ctx, task, done, stats))
    assert done == set()
    assert stats["transient"] == 1


def test_process_task_resolve_and_download_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "cp.json")
    task = {
        "link_type": "scrape_page",
        "page_url": "https://example.com/page",
        "dest": tmp_path / "out.pdf",
        "key": str(tmp_path / "out.pdf"),
    }
    done: set[str] = set()
    stats: dict[str, int] = {"ok": 0, "permanent": 0, "transient": 0}
    ctx = _DownloadCtx(session=_Session(), semaphore=asyncio.Semaphore(1), delay=0)
    with (
        patch(
            "scrapper.downloader.resolve_pdf_url",
            new_callable=AsyncMock,
            return_value="https://example.com/file.pdf",
        ),
        patch("scrapper.downloader.download_file", new_callable=AsyncMock, return_value=True),
    ):
        asyncio.run(_process_task(ctx, task, done, stats))
    assert task["key"] in done
    assert stats["ok"] == 1


def test_process_task_resolve_permanent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dl, "CHECKPOINT_FILE", tmp_path / "cp.json")
    task = {
        "link_type": "scrape_page",
        "page_url": "https://example.com/page",
        "dest": tmp_path / "out.pdf",
        "key": str(tmp_path / "out.pdf"),
    }
    done: set[str] = set()
    stats: dict[str, int] = {"ok": 0, "permanent": 0, "transient": 0}
    ctx = _DownloadCtx(session=_Session(), semaphore=asyncio.Semaphore(1), delay=0)
    with patch(
        "scrapper.downloader.resolve_pdf_url",
        new_callable=AsyncMock,
        return_value="PERMANENT",
    ):
        asyncio.run(_process_task(ctx, task, done, stats))
    assert SKIP_PREFIX + task["key"] in done
    assert stats["permanent"] == 1


def test_process_task_resolve_none_is_transient(tmp_path: Path) -> None:
    task = {
        "link_type": "scrape_page",
        "page_url": "https://example.com/page",
        "dest": tmp_path / "out.pdf",
        "key": str(tmp_path / "out.pdf"),
    }
    done: set[str] = set()
    stats: dict[str, int] = {"ok": 0, "permanent": 0, "transient": 0}
    ctx = _DownloadCtx(session=_Session(), semaphore=asyncio.Semaphore(1), delay=0)
    with patch("scrapper.downloader.resolve_pdf_url", new_callable=AsyncMock, return_value=None):
        asyncio.run(_process_task(ctx, task, done, stats))
    assert done == set()
    assert stats["transient"] == 1


# ─── main ─────────────────────────────────────────────────────────────────────


def test_main_parses_args_and_calls_asyncio_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["downloader.py", "--output", str(tmp_path)])
    with patch("asyncio.run") as mock_run:
        main()
    mock_run.assert_called_once()
