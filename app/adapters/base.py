from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from playwright.async_api import Page

from app.models.schemas import now_iso


class DomTarget:
    """Multi-level fallback selectors for a DOM element."""

    def __init__(
        self,
        description: str,
        css: str | None = None,
        xpath: str | None = None,
        text: str | None = None,
        placeholder: str | None = None,
    ):
        self.description = description
        self.css = css
        self.xpath = xpath
        self.text = text
        self.placeholder = placeholder

    def strategies(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if self.css:
            items.append(("css", self.css))
        if self.xpath:
            items.append(("xpath", self.xpath))
        if self.text:
            items.append(("text", self.text))
        if self.placeholder:
            items.append(("placeholder", self.placeholder))
        return items


class BaseAdapter(ABC):
    """Abstract adapter for a single AI chat platform.

    Subclasses define platform-specific DOM selectors and interaction
    logic. Instances receive an already-authenticated Playwright Page.
    """

    platform: str
    base_url: str

    # ----- subclasses must override -----

    @property
    @abstractmethod
    def input_box(self) -> DomTarget: ...

    @property
    @abstractmethod
    def send_button(self) -> DomTarget: ...

    @property
    @abstractmethod
    def response_area(self) -> DomTarget: ...

    @property
    @abstractmethod
    def new_chat_button(self) -> DomTarget: ...

    @property
    @abstractmethod
    def login_indicator(self) -> DomTarget: ...

    # ----- element helpers -----

    async def _locate(self, page: Page, target: DomTarget, timeout: float = 10_000):
        """Try each fallback strategy in order."""
        for strategy, value in target.strategies():
            try:
                if strategy == "css":
                    loc = page.locator(value)
                elif strategy == "xpath":
                    loc = page.locator(f"xpath={value}")
                elif strategy == "text":
                    loc = page.get_by_text(value, exact=False).first
                elif strategy == "placeholder":
                    loc = page.get_by_placeholder(value)
                else:
                    continue
                await loc.wait_for(state="visible", timeout=timeout)
                return loc
            except Exception:
                continue
        raise RuntimeError(
            f"Cannot locate '{target.description}' on {self.platform}. "
            f"Tried: {[s for s, _ in target.strategies()]}"
        )

    @staticmethod
    async def _human_delay(min_ms: int = 50, max_ms: int = 200) -> None:
        await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

    async def _type_like_human(self, loc, text: str, *, page: Page | None = None) -> None:
        await loc.click()
        await self._human_delay(100, 300)
        await loc.fill("")
        if page is not None:
            await page.keyboard.type(text, delay=random.randint(20, 120))
        else:
            await loc.fill(text)

    async def _move_mouse_naturally(self, page: Page, loc) -> None:
        box = await loc.bounding_box()
        if not box:
            return
        target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
        steps = random.randint(3, 8)
        current = await page.evaluate("() => ({x: window.innerWidth/2, y: window.innerHeight/2})")
        for i in range(steps):
            t = (i + 1) / steps
            mid_x = current["x"] + (target_x - current["x"]) * t + random.uniform(-20, 20)
            mid_y = current["y"] + (target_y - current["y"]) * t + random.uniform(-10, 10)
            await page.mouse.move(mid_x, mid_y)
            await asyncio.sleep(random.uniform(0.005, 0.03))
        await page.mouse.move(target_x, target_y)

    # ----- public interface -----

    async def is_logged_in(self, page: Page) -> bool:
        try:
            await self._locate(page, self.login_indicator, timeout=5_000)
            return True
        except Exception:
            return False

    @abstractmethod
    async def send_message(self, page: Page, text: str) -> None:
        """Locate input, type text, click send."""

    @abstractmethod
    async def wait_for_response(self, page: Page) -> AsyncGenerator[str, None]:
        """Stream response chunks from the DOM as they render."""

    async def create_new_chat(self, page: Page) -> str:
        await page.goto(self.base_url, wait_until="domcontentloaded")
        await self._human_delay(500, 1500)
        return now_iso().replace(":", "-")

    async def extract_reply(self, page: Page) -> str:
        """Non-streaming fallback: grab full reply from DOM."""
        loc = await self._locate(page, self.response_area, timeout=30_000)
        return (await loc.inner_text()).strip()
