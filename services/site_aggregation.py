from __future__ import annotations

import json
from urllib import error, request

from models import RemoteSite, RemoteSitePull, db, utc_now


AGGREGATION_DATASETS = (
    ("site_payload_json", "/api/v1/site"),
    ("manifest_payload_json", "/api/v1/sync/manifest"),
    ("dashboard_payload_json", "/api/v1/summary/dashboard"),
    ("inventory_payload_json", "/api/v1/summary/inventory"),
    ("exceptions_payload_json", "/api/v1/summary/exceptions"),
    ("slack_payload_json", "/api/v1/summary/slack-imports"),
)


def normalize_remote_base_url(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    return value.rstrip("/")


def fetch_remote_json(url: str, token: str | None = None, timeout_seconds: int = 10):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, headers=headers, method="GET")
    with request.urlopen(req, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload


def pull_remote_site(remote_site: RemoteSite, *, fetcher=None, timeout_seconds: int = 10) -> RemoteSitePull:
    fetcher = fetcher or fetch_remote_json
    remote_site.base_url = normalize_remote_base_url(remote_site.base_url)

    pull = RemoteSitePull(remote_site=remote_site, started_at=utc_now(), status="started")
    db.session.add(pull)
    remote_site.last_pull_started_at = pull.started_at
    remote_site.last_pull_status = "started"
    remote_site.last_pull_error = None
    db.session.flush()

    try:
        for attr_name, path in AGGREGATION_DATASETS:
            payload = fetcher(f"{remote_site.base_url}{path}", remote_site.api_token, timeout_seconds)
            if isinstance(payload, dict) and "data" in payload:
                data_value = payload["data"]
            else:
                data_value = payload
            pull.set_payload(attr_name, data_value)
            if attr_name == "site_payload_json":
                remote_site.site_code = (data_value or {}).get("site_code") or remote_site.site_code
                remote_site.site_name = (data_value or {}).get("site_name") or remote_site.site_name
                remote_site.site_region = (data_value or {}).get("site_region") or remote_site.site_region
                remote_site.site_environment = (data_value or {}).get("site_environment") or remote_site.site_environment
            remote_site.set_payload(f"last_{attr_name}", data_value)

        pull.status = "success"
        remote_site.last_pull_status = "success"
        remote_site.last_pull_error = None
    except (ValueError, error.URLError, error.HTTPError, OSError) as exc:
        pull.status = "failed"
        pull.error_message = str(exc)
        remote_site.last_pull_status = "failed"
        remote_site.last_pull_error = str(exc)
    finally:
        finished_at = utc_now()
        pull.finished_at = finished_at
        remote_site.last_pull_finished_at = finished_at
        db.session.commit()

    return pull
