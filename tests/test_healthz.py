"""Health endpoint tests."""

from __future__ import annotations

import app as app_module


def test_healthz_returns_ok_payload():
    app = app_module.app
    with app.test_client() as client:
        res = client.get("/healthz")
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["status"] == "ok"
        assert payload["db"] == "ok"
        assert "app_env" in payload


def test_livez_returns_ok():
    app = app_module.app
    with app.test_client() as client:
        res = client.get("/livez")
        assert res.status_code == 200
        assert res.get_json() == {"status": "ok"}


def test_readyz_returns_ok_payload():
    app = app_module.app
    with app.test_client() as client:
        res = client.get("/readyz")
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["status"] == "ok"
        assert payload["db"] == "ok"
