from __future__ import annotations

import asyncio
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.browser.manager import BrowserManager
from app.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    settings.headless = False
    accounts = settings.get_platform_accounts("deepseek")
    if not accounts:
        raise RuntimeError(
            "No DeepSeek account is configured. Run scripts/migrate_accounts.py first."
        )

    manager = BrowserManager(settings)
    await manager.start()
    try:
        page = await manager.get_page(accounts[0], "deepseek")
        await page.goto("https://chat.deepseek.com", wait_until="domcontentloaded")
        print("Browser opened. Log in, then press Enter to save the session.")
        input()
    finally:
        await manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
