from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app as app_module
from services.site_aggregation import pull_all_remote_sites


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull cached manifest and summary data from registered remote sites.")
    parser.add_argument("--all", action="store_true", help="Include inactive remote sites.")
    parser.add_argument("--timeout", type=int, default=10, help="Per-request timeout in seconds.")
    args = parser.parse_args()

    with app_module.app.app_context():
        pulls = pull_all_remote_sites(timeout_seconds=max(1, args.timeout), active_only=not args.all)
        if not pulls:
            print("No remote sites matched the pull criteria.")
            return 0
        success_count = sum(1 for pull in pulls if pull.status == "success")
        failure_count = len(pulls) - success_count
        print(f"Pulled {len(pulls)} remote site(s). Success: {success_count}. Failed: {failure_count}.")
        for pull in pulls:
            print(f"{pull.remote_site.name}: {pull.status}{f' - {pull.error_message}' if pull.error_message else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
