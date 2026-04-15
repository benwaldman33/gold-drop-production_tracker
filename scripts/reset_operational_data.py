from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, UTC
from pathlib import Path

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app as app_module
from gold_drop.bootstrap_module import init_db
from models import (
    AuditLog,
    BiomassAvailability,
    FieldAccessToken,
    FieldPurchaseSubmission,
    LabTest,
    PhotoAsset,
    Purchase,
    PurchaseLot,
    Run,
    RunInput,
    SlackIngestedMessage,
    Supplier,
    SupplierAttachment,
    WeightCapture,
    db,
)


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


def _backup_sqlite_database() -> Path | None:
    db_path = _sqlite_database_path()
    if db_path is None or not db_path.exists():
        return None
    backup_dir = Path.cwd() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"golddrop_operational_reset_{stamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _delete_all(model) -> int:
    return db.session.query(model).delete(synchronize_session=False)


def reset_operational_data(*, backup: bool) -> tuple[Path | None, dict[str, int]]:
    backup_path = _backup_sqlite_database() if backup else None
    deleted: dict[str, int] = {}
    with app_module.app.app_context():
        if db.engine.url.get_backend_name() == "sqlite":
            db.session.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            deletion_order = [
                WeightCapture,
                RunInput,
                Run,
                PhotoAsset,
                SupplierAttachment,
                LabTest,
                FieldPurchaseSubmission,
                FieldAccessToken,
                SlackIngestedMessage,
                PurchaseLot,
                BiomassAvailability,
                Purchase,
                Supplier,
                AuditLog,
            ]
            for model in deletion_order:
                deleted[model.__tablename__] = _delete_all(model)
            db.session.commit()
        finally:
            if db.engine.url.get_backend_name() == "sqlite":
                db.session.execute(text("PRAGMA foreign_keys=ON"))
                db.session.commit()

        init_db(app_module)

    return backup_path, deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clear operational data while preserving users, passwords, system settings, KPI targets, "
            "Slack sync config, scale devices, and cost entries."
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
        print("No SQLite database file was backed up (path not found or non-SQLite database).")

    print("Operational reset complete. Deleted rows:")
    for table_name, count in deleted.items():
        print(f"  {table_name}: {count}")
    print("Retained rows: users, passwords, system settings, KPI targets, Slack sync config, scale devices, cost entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
