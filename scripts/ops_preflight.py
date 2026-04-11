"""Operational preflight checks for local/runtime sanity."""

from __future__ import annotations

import json
import os
from typing import Any


def run_preflight(flask_app) -> dict[str, Any]:
    """Run lightweight runtime checks against probe/diagnostics endpoints."""
    checks: dict[str, Any] = {"ok": True, "checks": []}

    with flask_app.test_client() as client:
        probe_specs = [
            ("/livez", 200, {"status"}),
            ("/readyz", 200, {"status", "db", "app_env"}),
            ("/healthz", 200, {"status", "db", "app_env"}),
            ("/version", 200, {"version", "app_env"}),
        ]

        for path, expected_status, required_keys in probe_specs:
            res = client.get(path)
            payload = res.get_json(silent=True) or {}
            status_ok = res.status_code == expected_status
            keys_ok = required_keys.issubset(set(payload.keys()))
            passed = status_ok and keys_ok
            checks["checks"].append(
                {
                    "path": path,
                    "status_code": res.status_code,
                    "expected_status": expected_status,
                    "required_keys": sorted(required_keys),
                    "payload_keys": sorted(payload.keys()),
                    "ok": passed,
                }
            )
            if not passed:
                checks["ok"] = False

    app_env = (os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or "development").strip().lower()
    production_like_envs = {"prod", "production", "staging"}
    env_requirements = []
    if app_env in production_like_envs:
        env_requirements = ["SECRET_KEY", "APP_VERSION"]

    for key in env_requirements:
        present = bool((os.environ.get(key) or "").strip())
        checks["checks"].append(
            {
                "path": f"env:{key}",
                "status_code": 200 if present else 500,
                "expected_status": 200,
                "required_keys": [],
                "payload_keys": [],
                "ok": present,
            }
        )
        if not present:
            checks["ok"] = False

    return checks


def main() -> int:
    import app as app_module

    result = run_preflight(app_module.app)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
