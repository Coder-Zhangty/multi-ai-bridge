from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

from app.browser.stealth import inject_stealth
from app.core.config import AccountConfig, Settings


logger = logging.getLogger(__name__)


class BrowserManager:
    """Manage Playwright contexts whose state lives outside the source tree."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._playwright = None
        self._contexts: dict[str, BrowserContext] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._playwright:
            return
        self.settings.profile_root.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        logger.info("Playwright started (headless=%s)", self.settings.headless)

    def _resolve_profile_dir(self, configured_path: str) -> Path:
        profile_dir = Path(configured_path).expanduser()
        if not profile_dir.is_absolute():
            profile_dir = self.settings.profile_root / profile_dir
        return profile_dir.resolve()

    async def get_or_create_context(
        self,
        account: AccountConfig,
        platform: str,
    ) -> BrowserContext:
        profile_dir = self._resolve_profile_dir(account.profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        context_key = f"{platform}:{account.email}"

        async with self._lock:
            if context_key in self._contexts:
                context = self._contexts[context_key]
                try:
                    if context.pages:
                        return context
                except Exception:
                    del self._contexts[context_key]

            if self._playwright is None:
                await self.start()

            context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=self.settings.headless,
                slow_mo=self.settings.browser_slow_mo,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                ],
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                timezone_id="America/New_York",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )

            if self.settings.stealth_enabled:
                await inject_stealth(context)

            self._contexts[context_key] = context
            logger.info("Created persistent context for %s (%s)", account.email, platform)
            return context

    async def get_page(self, account: AccountConfig, platform: str) -> Page:
        context = await self.get_or_create_context(account, platform)
        return context.pages[0] if context.pages else await context.new_page()

    async def close_context(self, platform: str, email: str) -> None:
        context_key = f"{platform}:{email}"
        async with self._lock:
            context = self._contexts.pop(context_key, None)
        if context:
            try:
                await context.close()
            except Exception:
                pass

    async def shutdown(self) -> None:
        for context in list(self._contexts.values()):
            try:
                await context.close()
            except Exception:
                pass
        self._contexts.clear()

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("Browser shutdown complete")
