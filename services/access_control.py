from __future__ import annotations

import json


ROLE_TEMPLATE_SETTING_KEY = "access_control_role_templates"
USER_OVERRIDE_SETTING_KEY = "access_control_user_overrides"


PERMISSION_GROUPS = (
    ("purchasing", "Purchasing", ("purchasing.view", "purchasing.create", "purchasing.approve", "purchasing.import", "purchasing.export")),
    ("receiving", "Receiving", ("receiving.app", "receiving.confirm", "receiving.photos")),
    ("inventory", "Inventory", ("inventory.view", "inventory.edit", "inventory.import", "inventory.export")),
    ("extraction", "Extraction", ("extraction.app", "extraction.charge", "extraction.execute_sop", "runs.view", "runs.edit", "runs.import", "runs.export")),
    ("downstream", "Downstream", ("downstream.view", "downstream.route", "downstream.assign_owner")),
    ("alerts", "Alerts", ("alerts.view", "alerts.resolve", "alerts.supervisor_override")),
    ("journey", "Journey", ("journey.view", "journey.correct_genealogy", "journey.export")),
    ("finance", "Finance", ("finance.view", "finance.record_revenue", "finance.void_revenue", "finance.export")),
    ("standalone", "Standalone Apps", ("standalone.purchasing", "standalone.receiving", "standalone.extraction")),
    ("settings", "Settings", ("settings.operational", "settings.integrations", "settings.access_control", "settings.launch_readiness")),
    ("admin", "Administration", ("admin.users", "admin.audit")),
)

PERMISSION_LABELS = {
    permission: permission.replace(".", " - ").replace("_", " ").title()
    for _group_key, _group_label, permissions in PERMISSION_GROUPS
    for permission in permissions
}

ALL_PERMISSIONS = tuple(PERMISSION_LABELS.keys())
PERMISSION_INDEX = {permission: idx for idx, permission in enumerate(ALL_PERMISSIONS)}
PERMISSION_BY_INDEX = {str(idx): permission for permission, idx in PERMISSION_INDEX.items()}

DEFAULT_ROLE_TEMPLATES = {
    "viewer": [
        "inventory.view",
    ],
    "super_buyer": [
        "purchasing.view",
        "purchasing.create",
        "purchasing.approve",
        "purchasing.import",
        "purchasing.export",
        "receiving.app",
        "receiving.confirm",
        "receiving.photos",
        "inventory.view",
        "inventory.edit",
        "inventory.import",
        "inventory.export",
        "standalone.purchasing",
        "standalone.receiving",
    ],
    "user": [
        "purchasing.view",
        "purchasing.create",
        "purchasing.approve",
        "purchasing.import",
        "purchasing.export",
        "receiving.app",
        "receiving.confirm",
        "receiving.photos",
        "inventory.view",
        "inventory.edit",
        "inventory.import",
        "inventory.export",
        "extraction.app",
        "extraction.charge",
        "extraction.execute_sop",
        "runs.view",
        "runs.edit",
        "runs.import",
        "runs.export",
        "downstream.view",
        "downstream.route",
        "downstream.assign_owner",
        "alerts.view",
        "alerts.resolve",
        "alerts.supervisor_override",
        "journey.view",
        "journey.correct_genealogy",
        "journey.export",
        "finance.view",
        "finance.record_revenue",
        "finance.void_revenue",
        "finance.export",
        "standalone.purchasing",
        "standalone.receiving",
        "standalone.extraction",
    ],
    "super_admin": list(ALL_PERMISSIONS),
}


def _json_setting(root, key: str, default):
    raw = root.SystemSetting.get(key, "")
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _decode_permissions(values) -> list[str]:
    permissions = []
    for value in values or []:
        permission = value if isinstance(value, str) and value in ALL_PERMISSIONS else PERMISSION_BY_INDEX.get(str(value))
        if permission and permission not in permissions:
            permissions.append(permission)
    return permissions


def _encode_permissions(values) -> list[int]:
    return [
        PERMISSION_INDEX[permission]
        for permission in ALL_PERMISSIONS
        if permission in set(values or [])
    ]


def role_templates(root) -> dict[str, list[str]]:
    saved = _json_setting(root, ROLE_TEMPLATE_SETTING_KEY, {})
    merged = {role: list(perms) for role, perms in DEFAULT_ROLE_TEMPLATES.items()}
    for role, perms in saved.items():
        if isinstance(perms, list):
            merged[role] = _decode_permissions(perms)
    return merged


def user_overrides(root) -> dict[str, dict[str, list[str]]]:
    saved = _json_setting(root, USER_OVERRIDE_SETTING_KEY, {})
    cleaned = {}
    for user_id, values in saved.items():
        if not isinstance(values, dict):
            continue
        cleaned[user_id] = {
            "grant": _decode_permissions(values.get("grant", values.get("g", []))),
            "revoke": _decode_permissions(values.get("revoke", values.get("r", []))),
        }
    return cleaned


def effective_permissions(root, user) -> set[str]:
    if user is None:
        return set()
    role = getattr(user, "role", "viewer") or "viewer"
    permissions = set(role_templates(root).get(role, []))
    overrides = user_overrides(root).get(getattr(user, "id", ""), {})
    permissions.update(overrides.get("grant", []))
    permissions.difference_update(overrides.get("revoke", []))
    return permissions


def has_permission(root, user, permission: str) -> bool:
    if getattr(user, "is_super_admin", False):
        return True
    return permission in effective_permissions(root, user)


def save_access_control(root, templates: dict[str, list[str]], overrides: dict[str, dict[str, list[str]]]):
    compact_templates = {
        role: _encode_permissions(perms)
        for role, perms in templates.items()
        if list(perms or []) != list(DEFAULT_ROLE_TEMPLATES.get(role, []))
    }
    role_setting = root.db.session.get(root.SystemSetting, ROLE_TEMPLATE_SETTING_KEY)
    role_payload = json.dumps(compact_templates, separators=(",", ":"), sort_keys=True)
    if role_setting is None:
        root.db.session.add(root.SystemSetting(key=ROLE_TEMPLATE_SETTING_KEY, value=role_payload, description="Access-control role permission templates"))
    else:
        role_setting.value = role_payload
    compact_overrides = {}
    for user_id, values in overrides.items():
        grant = _encode_permissions(values.get("grant", []))
        revoke = _encode_permissions(values.get("revoke", []))
        if grant or revoke:
            compact_overrides[user_id] = {"g": grant, "r": revoke}
    override_setting = root.db.session.get(root.SystemSetting, USER_OVERRIDE_SETTING_KEY)
    override_payload = json.dumps(compact_overrides, separators=(",", ":"), sort_keys=True)
    if override_setting is None:
        root.db.session.add(root.SystemSetting(key=USER_OVERRIDE_SETTING_KEY, value=override_payload, description="Access-control per-user permission grants and revokes"))
    else:
        override_setting.value = override_payload
