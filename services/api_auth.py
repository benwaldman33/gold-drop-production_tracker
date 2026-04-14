from __future__ import annotations

import hashlib
import secrets
from functools import wraps

from flask import g, jsonify, request

from models import ApiClient, ApiClientRequestLog, db, gen_uuid, utc_now
from services.api_site import build_meta


def generate_api_token() -> str:
    return secrets.token_urlsafe(32)


def hash_api_token(raw_token: str) -> str:
    return hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()


def get_bearer_token(req) -> str | None:
    auth_header = (req.headers.get("Authorization") or "").strip()
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def lookup_api_client(raw_token: str) -> ApiClient | None:
    if not raw_token:
        return None
    token_hash = hash_api_token(raw_token)
    return ApiClient.query.filter_by(token_hash=token_hash).first()


def json_api_error(message: str, *, status_code: int, code: str):
    return jsonify({"meta": build_meta(), "error": {"code": code, "message": message}}), status_code


def require_api_scope(scope: str):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            raw_token = get_bearer_token(request)
            if not raw_token:
                return json_api_error("Missing bearer token", status_code=401, code="unauthorized")

            client = lookup_api_client(raw_token)
            if client is None:
                return json_api_error("Invalid API token", status_code=401, code="unauthorized")
            if not client.is_active:
                return json_api_error("API client is inactive", status_code=403, code="forbidden")
            if scope not in set(client.scopes):
                return json_api_error(f"Missing scope {scope}", status_code=403, code="forbidden")

            g.api_client = client
            response = fn(*args, **kwargs)
            flask_response = response if hasattr(response, "status_code") else None
            status_code = getattr(flask_response, "status_code", None)

            try:
                client.last_used_at = utc_now()
                client.last_used_scope = scope
                client.last_used_endpoint = request.path
                db.session.add(
                    ApiClientRequestLog(
                        id=gen_uuid(),
                        api_client_id=client.id,
                        request_path=request.path,
                        request_method=request.method,
                        scope_used=scope,
                        status_code=status_code,
                    )
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
            return response

        return wrapped

    return decorator
