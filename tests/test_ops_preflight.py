"""Tests for ops preflight probe checks."""

from __future__ import annotations

import app as app_module
from scripts.ops_preflight import run_preflight


def test_run_preflight_reports_all_probe_checks_ok(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    result = run_preflight(app_module.app)
    assert result["ok"] is True
    paths = [c["path"] for c in result["checks"]]
    assert paths == ["/livez", "/readyz", "/healthz", "/version"]
    assert all(c["ok"] for c in result["checks"])


def test_run_preflight_checks_required_env_vars_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)

    result = run_preflight(app_module.app)
    assert result["ok"] is False
    env_checks = [c for c in result["checks"] if c["path"].startswith("env:")]
    assert {c["path"] for c in env_checks} == {"env:SECRET_KEY", "env:APP_VERSION"}
    assert all(c["ok"] is False for c in env_checks)
