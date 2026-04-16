from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app as app_module
from models import ApiClient, db
from services.api_auth import generate_api_token, hash_api_token


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a read-only internal API client token.")
    parser.add_argument("--name", required=True, help="Display name for the API client.")
    parser.add_argument(
        "--scopes",
        required=True,
        help="Comma-separated scopes, e.g. read:site,read:lots,read:inventory",
    )
    parser.add_argument("--notes", default="", help="Optional notes stored with the API client.")
    args = parser.parse_args()

    scopes = sorted({part.strip() for part in (args.scopes or "").split(",") if part.strip()})
    if not scopes:
        parser.error("At least one scope is required.")

    raw_token = generate_api_token()
    with app_module.app.app_context():
        client = ApiClient(
            name=args.name.strip(),
            token_hash=hash_api_token(raw_token),
            notes=(args.notes or "").strip() or None,
        )
        client.set_scopes(scopes)
        db.session.add(client)
        db.session.commit()

        print("API client created.")
        print(f"id: {client.id}")
        print(f"name: {client.name}")
        print(f"scopes: {','.join(client.scopes)}")
        print(f"token: {raw_token}")
        print("Store this token now. It is not saved in plain text and will not be shown again.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
