from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app as app_module
from gold_drop.bootstrap_module import init_db


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed the historical/demo dataset explicitly. Normal startup no longer does this automatically."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation flag to seed demo/historical records.",
    )
    args = parser.parse_args()

    if not args.yes:
        parser.error("Pass --yes to confirm demo-data seeding.")

    with app_module.app.app_context():
        init_db(app_module)
        app_module._seed_historical_data()

    print("Demo/historical data seeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
