from __future__ import annotations

import json
from typing import Any

from flask import current_app, jsonify, request

from services.api_site import build_meta


WORKFLOW_SETTINGS = {
    "buying": "standalone_purchasing_enabled",
    "receiving": "standalone_receiving_enabled",
}


def workflow_enabled(root, workflow: str) -> bool:
    key = WORKFLOW_SETTINGS.get(workflow)
    if not key:
        return True
    value = (root.SystemSetting.get(key, "1") or "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def workflow_permissions(root, user) -> dict[str, bool]:
    can_write = bool(getattr(user, "can_edit_purchases", False))
    return {
        "can_create_opportunity": can_write and workflow_enabled(root, "buying"),
        "can_edit_preapproval_opportunity": can_write and workflow_enabled(root, "buying"),
        "can_record_delivery": can_write and workflow_enabled(root, "buying"),
        "can_receive_intake": can_write and workflow_enabled(root, "receiving"),
        "can_create_supplier": can_write and workflow_enabled(root, "buying"),
    }


def mobile_json(data: Any, *, status_code: int = 200, extra_meta: dict[str, object] | None = None):
    return jsonify({"meta": build_meta(extra=extra_meta), "data": data}), status_code


def mobile_json_error(message: str, *, status_code: int, code: str, extra_meta: dict[str, object] | None = None):
    return jsonify({
        "meta": build_meta(extra=extra_meta),
        "error": {"code": code, "message": message},
    }), status_code


def enforce_same_origin_for_write(root):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    if current_app.config.get("TESTING"):
        return None
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()
    host = (request.host_url or "").rstrip("/")
    if origin and origin.rstrip("/") != host:
        return mobile_json_error("Cross-site mobile writes are not allowed.", status_code=403, code="origin_forbidden")
    if referer and not referer.startswith(host):
        return mobile_json_error("Cross-site mobile writes are not allowed.", status_code=403, code="origin_forbidden")
    return None


def audit_mobile_action(root, *, action: str, entity_type: str, entity_id: str, workflow: str, details: dict[str, Any] | None = None, user_id: str | None = None):
    payload = {"source": "mobile_api", "workflow": workflow}
    if details:
        payload.update(details)
    root.log_audit(action, entity_type, entity_id, details=json.dumps(payload), user_id=user_id)


def mobile_capabilities(root, user) -> dict[str, Any]:
    perms = workflow_permissions(root, user)
    return {
        "auth_mode": "session_cookie",
        "write_workflows": {
            "buying": {
                "enabled": workflow_enabled(root, "buying"),
                "allowed": perms["can_create_opportunity"],
                "endpoints": [
                    "/api/mobile/v1/opportunities",
                    "/api/mobile/v1/opportunities/mine",
                    "/api/mobile/v1/opportunities/<id>",
                    "/api/mobile/v1/opportunities/<id>/delivery",
                    "/api/mobile/v1/opportunities/<id>/photos",
                    "/api/mobile/v1/suppliers",
                ],
            },
            "receiving": {
                "enabled": workflow_enabled(root, "receiving"),
                "allowed": perms["can_receive_intake"],
                "endpoints": [
                    "/api/mobile/v1/receiving/queue",
                    "/api/mobile/v1/receiving/queue/<id>",
                    "/api/mobile/v1/receiving/queue/<id>/receive",
                    "/api/mobile/v1/receiving/queue/<id>/photos",
                ],
            },
        },
        "upload_limits": {
            "max_files_per_request": int(current_app.config.get("MOBILE_UPLOAD_MAX_FILES_PER_REQUEST", 6)),
        },
    }
