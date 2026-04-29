from __future__ import annotations

import argparse
import subprocess
import shutil
import sys
from datetime import datetime, UTC
from pathlib import Path

from sqlalchemy import func, select, text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app as app_module
from gold_drop.bootstrap_module import init_db
from models import RemoteSite, db


PRESERVED_TABLES = {
    "users",
    "system_settings",
    "kpi_targets",
    "slack_channel_sync_configs",
    "scale_devices",
    "cost_entries",
    "api_clients",
    "remote_sites",
}


def _sqlite_database_path() -> Path | None:
    with app_module.app.app_context():
        engine = db.engine
        if engine.url.get_backend_name() != "sqlite":
            return None
        raw = engine.url.database
        if not raw:
            return None
        path = Path(raw)
        if path.is_absolute():
            return path
        return (Path(app_module.app.instance_path) / path).resolve()


def _backup_dir() -> Path:
    backup_dir = Path.cwd() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _backup_sqlite_database() -> Path | None:
    db_path = _sqlite_database_path()
    if db_path is None or not db_path.exists():
        return None
    backup_dir = _backup_dir()
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"golddrop_operational_reset_{stamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _backup_postgres_database() -> Path:
    with app_module.app.app_context():
        db_url = db.engine.url.render_as_string(hide_password=False)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = _backup_dir() / f"golddrop_operational_reset_{stamp}.dump"
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(backup_path), db_url],
        check=True,
    )
    return backup_path


def _backup_database() -> Path | None:
    with app_module.app.app_context():
        backend = db.engine.url.get_backend_name()
    if backend == "sqlite":
        return _backup_sqlite_database()
    if backend == "postgresql":
        return _backup_postgres_database()
    return None


def _table_row_count(table) -> int:
    return int(db.session.execute(select(func.count()).select_from(table)).scalar_one() or 0)


def _clear_remote_site_cached_payloads() -> int:
    count = 0
    for site in RemoteSite.query.all():
        count += 1
        site.last_pull_started_at = None
        site.last_pull_finished_at = None
        site.last_pull_status = None
        site.last_pull_error = None
        site.last_site_payload_json = None
        site.last_manifest_payload_json = None
        site.last_dashboard_payload_json = None
        site.last_inventory_payload_json = None
        site.last_exceptions_payload_json = None
        site.last_slack_payload_json = None
        site.last_suppliers_payload_json = None
        site.last_strains_payload_json = None
    return count


def _tables_to_clear(backend: str):
    tables = [table for table in db.metadata.tables.values() if table.name not in PRESERVED_TABLES]
    if backend in {"postgresql", "sqlite"}:
        return sorted(tables, key=lambda table: table.name)
    return [table for table in reversed(db.metadata.sorted_tables) if table.name not in PRESERVED_TABLES]


def reset_operational_data(*, backup: bool) -> tuple[Path | None, dict[str, int]]:
    backup_path = _backup_database() if backup else None
    deleted: dict[str, int] = {}
    with app_module.app.app_context():
        backend = db.engine.url.get_backend_name()
        tables_to_clear = _tables_to_clear(backend)
        for table in tables_to_clear:
            deleted[table.name] = _table_row_count(table)

        if backend == "postgresql":
            quoted_names = ", ".join(table.name for table in tables_to_clear)
            if quoted_names:
                db.session.execute(text(f"TRUNCATE TABLE {quoted_names} RESTART IDENTITY CASCADE"))
            deleted["remote_sites.cached_payload_fields"] = _clear_remote_site_cached_payloads()
            db.session.commit()
        elif backend == "sqlite":
            db.session.execute(text("PRAGMA foreign_keys=OFF"))
            try:
                for table in tables_to_clear:
                    db.session.execute(table.delete())
                deleted["remote_sites.cached_payload_fields"] = _clear_remote_site_cached_payloads()
                db.session.commit()
            finally:
                db.session.execute(text("PRAGMA foreign_keys=ON"))
                db.session.commit()
        else:
            for table in tables_to_clear:
                db.session.execute(table.delete())
            deleted["remote_sites.cached_payload_fields"] = _clear_remote_site_cached_payloads()
            db.session.commit()

        init_db(app_module)

    return backup_path, deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clear operational data while preserving users, passwords, system settings, KPI targets, "
            "Slack sync config, scale devices, cost entries, API clients, and remote-site configuration."
        )
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the automatic SQLite backup before deleting data.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation flag to perform the reset.",
    )
    args = parser.parse_args()

    if not args.yes:
        parser.error("Pass --yes to confirm the operational reset.")

    backup_path, deleted = reset_operational_data(backup=not args.no_backup)

    if backup_path is not None:
        print(f"Backup created: {backup_path}")
    elif not args.no_backup:
        print("No database backup was created (path not found or unsupported database backend).")

    print("Operational reset complete. Deleted rows:")
    for table_name, count in deleted.items():
        print(f"  {table_name}: {count}")
    print(
        "Retained rows: users, passwords, system settings, KPI targets, Slack sync config, "
        "scale devices, cost entries, API clients, and remote-site configuration."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
