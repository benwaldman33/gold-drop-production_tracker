from __future__ import annotations

from datetime import UTC, datetime

from models import SystemSetting


def get_site_identity() -> dict[str, str]:
    return {
        "site_code": SystemSetting.get("site_code", "DEFAULT"),
        "site_name": SystemSetting.get("site_name", "Gold Drop"),
        "site_timezone": SystemSetting.get("site_timezone", "America/Los_Angeles"),
    }


def build_meta(*, count: int | None = None, limit: int | None = None, offset: int | None = None) -> dict[str, object]:
    site = get_site_identity()
    meta: dict[str, object] = {
        "api_version": "v1",
        "site_code": site["site_code"],
        "site_name": site["site_name"],
        "site_timezone": site["site_timezone"],
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if count is not None:
        meta["count"] = count
    if limit is not None:
        meta["limit"] = limit
    if offset is not None:
        meta["offset"] = offset
    return meta
