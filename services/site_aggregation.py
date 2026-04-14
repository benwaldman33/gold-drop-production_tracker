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


def serialize_remote_site_cache(remote_site: RemoteSite) -> dict:
    return {
        "id": remote_site.id,
        "name": remote_site.name,
        "base_url": remote_site.base_url,
        "site_code": remote_site.site_code,
        "site_name": remote_site.site_name,
        "site_region": remote_site.site_region,
        "site_environment": remote_site.site_environment,
        "is_active": bool(remote_site.is_active),
        "notes": remote_site.notes,
        "last_pull_status": remote_site.last_pull_status,
        "last_pull_error": remote_site.last_pull_error,
        "last_pull_started_at": _iso(remote_site.last_pull_started_at),
        "last_pull_finished_at": _iso(remote_site.last_pull_finished_at),
        "cached_payloads": {
            "site": remote_site.payload("last_site_payload_json"),
            "manifest": remote_site.payload("last_manifest_payload_json"),
            "dashboard": remote_site.payload("last_dashboard_payload_json"),
            "inventory": remote_site.payload("last_inventory_payload_json"),
            "exceptions": remote_site.payload("last_exceptions_payload_json"),
            "slack_imports": remote_site.payload("last_slack_payload_json"),
        },
    }


def build_aggregation_summary(local_site: dict, *, local_dashboard: dict, local_inventory: dict, local_exceptions: dict, local_slack: dict) -> dict:
    remote_sites = RemoteSite.query.order_by(RemoteSite.name.asc()).all()
    active_sites = [site for site in remote_sites if site.is_active]

    total_sites = 1 + len(active_sites)
    successful_remote_pulls = sum(1 for site in active_sites if site.last_pull_status == "success")

    total_runs = int((local_dashboard.get("totals") or {}).get("total_runs") or 0)
    total_lbs = float((local_dashboard.get("totals") or {}).get("total_lbs") or 0)
    total_output = float((local_dashboard.get("totals") or {}).get("total_dry_output_g") or 0)
    total_on_hand = float(local_inventory.get("total_on_hand_lbs") or 0)
    total_exceptions = int(local_exceptions.get("total_exceptions") or 0)
    total_slack = int(local_slack.get("total_messages") or 0)

    site_summaries = [{
        "site_code": local_site.get("site_code"),
        "site_name": local_site.get("site_name"),
        "site_region": local_site.get("site_region"),
        "site_environment": local_site.get("site_environment"),
        "source": "local",
        "status": "local",
        "totals": local_dashboard.get("totals") or {},
        "inventory": local_inventory,
        "exceptions": local_exceptions,
        "slack_imports": local_slack,
    }]

    for site in active_sites:
        dashboard = site.payload("last_dashboard_payload_json") or {}
        inventory = site.payload("last_inventory_payload_json") or {}
        exceptions = site.payload("last_exceptions_payload_json") or {}
        slack_imports = site.payload("last_slack_payload_json") or {}
        total_runs += int((dashboard.get("totals") or {}).get("total_runs") or 0)
        total_lbs += float((dashboard.get("totals") or {}).get("total_lbs") or 0)
        total_output += float((dashboard.get("totals") or {}).get("total_dry_output_g") or 0)
        total_on_hand += float(inventory.get("total_on_hand_lbs") or 0)
        total_exceptions += int(exceptions.get("total_exceptions") or 0)
        total_slack += int(slack_imports.get("total_messages") or 0)
        site_summaries.append({
            "site_code": site.site_code,
            "site_name": site.site_name or site.name,
            "site_region": site.site_region,
            "site_environment": site.site_environment,
            "source": "remote_cache",
            "status": site.last_pull_status or "never_pulled",
            "last_pull_finished_at": _iso(site.last_pull_finished_at),
            "totals": dashboard.get("totals") or {},
            "inventory": inventory,
            "exceptions": exceptions,
            "slack_imports": slack_imports,
        })

    return {
        "sites_total": total_sites,
        "remote_sites_active": len(active_sites),
        "remote_sites_successful": successful_remote_pulls,
        "totals": {
            "total_runs": total_runs,
            "total_lbs": float(total_lbs),
            "total_dry_output_g": float(total_output),
            "total_on_hand_lbs": float(total_on_hand),
            "total_exceptions": total_exceptions,
            "total_slack_messages": total_slack,
        },
        "sites": site_summaries,
    }


def _iso(value):
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z") if hasattr(value, "isoformat") else value
