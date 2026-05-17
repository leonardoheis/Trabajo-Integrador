"""Tests — main.py (app wiring + lifespan)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
class TestLifespan:
    def test_startup_creates_output_directories(self, tmp_output_dir) -> None:
        from main import app
        with TestClient(app) as client:
            response = client.get("/")
        assert response.status_code == 200
        for folder in ("invoices", "contracts", "tax_returns", "reports", "review"):
            assert (tmp_output_dir / folder).is_dir()

    def test_health_during_lifespan(self, tmp_output_dir) -> None:
        from main import app
        with TestClient(app) as client:
            response = client.get("/")
            assert response.json()["status"] == "ok"
