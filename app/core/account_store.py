from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from cryptography.fernet import Fernet, InvalidToken


def resolve_state_root(project_root: Path) -> Path:
    configured = os.getenv("AURORA_BRIDGE_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "AuroraBridge"
    xdg_data_home = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "aurora-bridge"
    return Path.home() / ".local" / "share" / "aurora-bridge"


class AccountStore:
    def __init__(self, *, database_path: Path, key_path: Path):
        self.database_path = database_path
        self.key_path = key_path

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bridge_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password_encrypted TEXT,
                    profile_dir TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(platform, email)
                )
                """
            )

    def _fernet(self) -> Fernet:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
            try:
                self.key_path.chmod(0o600)
            except OSError:
                pass
        return Fernet(self.key_path.read_bytes().strip())

    def _encrypt(self, value: str) -> str | None:
        if not value:
            return None
        return self._fernet().encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            return self._fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Bridge account credentials could not be decrypted.") from exc

    def load_accounts(self) -> dict[str, list[dict[str, str]]]:
        self.initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT platform, email, password_encrypted, profile_dir
                FROM bridge_accounts
                WHERE enabled = 1
                ORDER BY platform, id
                """
            ).fetchall()
        accounts: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            accounts.setdefault(row["platform"], []).append(
                {
                    "email": row["email"],
                    "password": self._decrypt(row["password_encrypted"]),
                    "profile_dir": row["profile_dir"],
                }
            )
        return accounts

    def import_json(
        self,
        source_path: Path,
        *,
        source_project_root: Path,
        state_root: Path,
    ) -> int:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Account JSON must contain an object keyed by platform.")
        self.initialize()
        imported = 0
        now = self._now()
        with sqlite3.connect(self.database_path) as connection:
            for platform, entries in payload.items():
                if not isinstance(platform, str) or not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    email = str(entry.get("email") or "").strip()
                    if not email:
                        continue
                    raw_profile = str(
                        entry.get("profile_dir")
                        or f"profiles/{platform}_{email.replace('@', '_at_')}"
                    )
                    profile_path = Path(raw_profile).expanduser()
                    if not profile_path.is_absolute():
                        old_profile_path = (source_project_root / profile_path).resolve()
                        try:
                            relative_profile = old_profile_path.relative_to(
                                source_project_root.resolve()
                            )
                        except ValueError:
                            relative_profile = Path("profiles") / profile_path.name
                        profile_path = (state_root / relative_profile).resolve()
                    password = str(entry.get("password") or "")
                    connection.execute(
                        """
                        INSERT INTO bridge_accounts (
                            platform, email, password_encrypted, profile_dir,
                            enabled, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 1, ?, ?)
                        ON CONFLICT(platform, email) DO UPDATE SET
                            password_encrypted = excluded.password_encrypted,
                            profile_dir = excluded.profile_dir,
                            enabled = 1,
                            updated_at = excluded.updated_at
                        """,
                        (
                            platform.strip().lower(),
                            email,
                            self._encrypt(password),
                            str(profile_path),
                            now,
                            now,
                        ),
                    )
                    imported += 1
        return imported
