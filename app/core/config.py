from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from app.core.account_store import AccountStore, resolve_state_root


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_ROOT = resolve_state_root(PROJECT_ROOT)
PROFILE_ROOT = STATE_ROOT / "profiles"
ACCOUNTS_DB_PATH = Path(
    os.getenv("ACCOUNTS_DB_PATH", "").strip() or STATE_ROOT / "bridge.db"
).expanduser()
CREDENTIAL_KEY_PATH = Path(
    os.getenv("CREDENTIAL_KEY_PATH", "").strip() or STATE_ROOT / "credential.key"
).expanduser()


def _load_accounts() -> dict[str, list[dict[str, str]]]:
    return AccountStore(
        database_path=ACCOUNTS_DB_PATH,
        key_path=CREDENTIAL_KEY_PATH,
    ).load_accounts()


class AccountConfig(BaseModel):
    email: str
    password: str = Field(default="", repr=False)
    profile_dir: str = ""


class PlatformApiKey(BaseModel):
    api_key: str = Field(default="", repr=False)
    api_base: str = ""
    model: str = ""


class Settings(BaseModel):
    app_name: str = "Multi-AI Bridge"
    host: str = "127.0.0.1"
    port: int = 8100
    headless: bool = True
    browser_slow_mo: int = 0
    request_timeout: float = 180.0
    session_keepalive_interval: int = 600
    max_instances_per_platform: int = 3
    stealth_enabled: bool = True
    api_key: str = Field(default="", repr=False)
    state_root: Path = STATE_ROOT
    profile_root: Path = PROFILE_ROOT
    accounts_db_path: Path = ACCOUNTS_DB_PATH
    accounts: dict[str, list[AccountConfig]] = Field(default_factory=dict, repr=False)
    platform_api_keys: dict[str, PlatformApiKey] = Field(default_factory=dict, repr=False)
    platform_mode: dict[str, str] = Field(default_factory=dict)

    def get_platform_accounts(self, platform: str) -> list[AccountConfig]:
        return self.accounts.get(platform, [])

    def get_platform_api(self, platform: str) -> PlatformApiKey | None:
        return self.platform_api_keys.get(platform)

    def get_platform_mode(self, platform: str) -> str:
        if platform in self.platform_mode:
            return self.platform_mode[platform]
        has_browser = platform in self.accounts
        has_api = (
            platform in self.platform_api_keys
            and bool(self.platform_api_keys[platform].api_key)
        )
        if has_browser:
            return "browser_first" if has_api else "browser_only"
        if has_api:
            return "api_only"
        return "browser_only"

    @property
    def supported_platforms(self) -> list[str]:
        platforms = set(self.accounts) | set(self.platform_api_keys)
        return sorted(platforms)


_API_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {"api_base": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "tongyi": {
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
    },
    "kimi": {"api_base": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "doubao": {"api_base": "https://ark.cn-beijing.volces.com/api/v3", "model": ""},
    "chatgpt": {"api_base": "https://api.openai.com/v1", "model": "gpt-4o"},
    "claude": {
        "api_base": "https://api.anthropic.com/v1",
        "model": "claude-3-5-sonnet-20241022",
    },
    "gemini": {
        "api_base": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-1.5-pro",
    },
    "perplexity": {
        "api_base": "https://api.perplexity.com",
        "model": "llama-3.1-sonar-large-128k-online",
    },
}


def _load_platform_api_keys() -> dict[str, PlatformApiKey]:
    result: dict[str, PlatformApiKey] = {}
    for platform, defaults in _API_DEFAULTS.items():
        key = os.getenv(f"{platform.upper()}_API_KEY", "")
        if not key:
            continue
        result[platform] = PlatformApiKey(
            api_key=key,
            api_base=os.getenv(f"{platform.upper()}_API_BASE", defaults["api_base"]),
            model=os.getenv(f"{platform.upper()}_MODEL", defaults["model"]),
        )
    return result


def _load_platform_modes() -> dict[str, str]:
    valid_modes = {"api_first", "browser_first", "api_only", "browser_only"}
    result: dict[str, str] = {}
    for item in os.getenv("PLATFORM_MODES", "").split(","):
        if ":" not in item:
            continue
        platform, mode = (part.strip() for part in item.split(":", 1))
        if platform and mode in valid_modes:
            result[platform] = mode
    return result


def get_settings() -> Settings:
    parsed: dict[str, list[AccountConfig]] = {}
    for platform, entries in _load_accounts().items():
        parsed[platform] = [AccountConfig(**entry) for entry in entries]

    return Settings(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8100")),
        headless=os.getenv("HEADLESS", "true").lower() == "true",
        browser_slow_mo=int(os.getenv("BROWSER_SLOW_MO", "0")),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "180")),
        session_keepalive_interval=int(os.getenv("SESSION_KEEPALIVE_INTERVAL", "600")),
        max_instances_per_platform=int(os.getenv("MAX_INSTANCES_PER_PLATFORM", "3")),
        stealth_enabled=os.getenv("STEALTH_ENABLED", "true").lower() == "true",
        api_key=os.getenv("API_KEY", ""),
        state_root=STATE_ROOT,
        profile_root=PROFILE_ROOT,
        accounts_db_path=ACCOUNTS_DB_PATH,
        accounts=parsed,
        platform_api_keys=_load_platform_api_keys(),
        platform_mode=_load_platform_modes(),
    )
