"""Version endpoint tests."""

from __future__ import annotations

import app as app_module


def test_version_endpoint_returns_metadata(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "test-sha-123")
    monkeypatch.setenv("APP_ENV", "production")
    app = app_module.app
    with app.test_client() as client:
        res = client.get("/version")
        assert res.status_code == 200
        payload = res.get_json()
        assert payload["version"] == "test-sha-123"
        assert payload["app_env"] == "production"
