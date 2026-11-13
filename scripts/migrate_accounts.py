from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.account_store import AccountStore
from app.core.config import ACCOUNTS_DB_PATH, CREDENTIAL_KEY_PATH, STATE_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import legacy accounts.json into encrypted SQLite storage."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT / "accounts.json",
    )
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Account file not found: {source}")

    imported = AccountStore(
        database_path=ACCOUNTS_DB_PATH,
        key_path=CREDENTIAL_KEY_PATH,
    ).import_json(
        source,
        source_project_root=PROJECT_ROOT,
        state_root=STATE_ROOT,
    )
    print(f"Imported {imported} account(s) into {ACCOUNTS_DB_PATH}")
    print("Verify the database before removing the legacy JSON file.")


if __name__ == "__main__":
    main()
