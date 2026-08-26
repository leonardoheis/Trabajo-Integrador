from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from classiflow.api import app as app_module
from classiflow.api.app import create_app


class TestCreateAppFrontendMount:
    def test_root_returns_404_when_frontend_dist_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(app_module, "_FRONTEND_DIST", tmp_path / "does-not-exist")

        client = TestClient(create_app())
        response = client.get("/")

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_root_serves_index_html_when_frontend_dist_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html><body>Classiflow</body></html>")
        monkeypatch.setattr(app_module, "_FRONTEND_DIST", dist)

        client = TestClient(create_app())
        response = client.get("/")

        assert response.status_code == HTTPStatus.OK
        assert "Classiflow" in response.text
