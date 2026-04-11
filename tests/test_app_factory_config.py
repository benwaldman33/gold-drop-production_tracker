"""App factory configuration safety tests."""

from __future__ import annotations

import pytest

import app as app_module


def test_create_app_allows_default_secret_in_development(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    app = app_module.create_app()
    assert app.config["SECRET_KEY"] == "gold-drop-dev-key-change-in-prod"


def test_create_app_requires_secret_in_production_like_env(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        app_module.create_app()


def test_create_app_accepts_secret_in_production_like_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "unit-test-secret")

    app = app_module.create_app()
    assert app.config["SECRET_KEY"] == "unit-test-secret"


def test_should_seed_demo_data_defaults_on_in_development(monkeypatch):
    monkeypatch.delenv("SEED_DEMO_DATA", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    assert app_module._should_seed_demo_data_from_env() is True


def test_should_seed_demo_data_defaults_off_in_production_like_env(monkeypatch):
    monkeypatch.delenv("SEED_DEMO_DATA", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert app_module._should_seed_demo_data_from_env() is False


def test_should_seed_demo_data_explicit_env_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SEED_DEMO_DATA", "1")
    assert app_module._should_seed_demo_data_from_env() is True
