from __future__ import annotations

from flask import Flask, request

import app as app_module
from models import ApiClient, SystemSetting, db
from services.api_auth import generate_api_token, get_bearer_token, hash_api_token


def test_init_db_seeds_site_identity_defaults():
    app = app_module.app
    with app.app_context():
        assert db.session.get(SystemSetting, "site_code") is not None
        assert db.session.get(SystemSetting, "site_name") is not None
        assert db.session.get(SystemSetting, "site_timezone") is not None


def test_api_client_scopes_round_trip():
    client = ApiClient(name="internal-test", token_hash="hash")
    client.set_scopes(["read:lots", "read:site", "read:lots"])
    assert client.scopes == ["read:lots", "read:site"]


def test_api_auth_helpers_extract_and_hash_tokens():
    token = generate_api_token()
    assert token
    assert hash_api_token(token) == hash_api_token(token)

    app = Flask(__name__)
    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        assert get_bearer_token(request) == token
