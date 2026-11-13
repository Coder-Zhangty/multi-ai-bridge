from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncGenerator

from playwright.async_api import Page

from app.adapters.base import BaseAdapter, DomTarget
from app.models.schemas import now_iso


class ClaudeAdapter(BaseAdapter):
    platform = "claude"
    base_url = "https://claude.ai"

    # ----- DOM selectors (multi-level fallback) -----

    @property
    def input_box(self) -> DomTarget:
        return DomTarget(
            description="Claude input box",
            css='div[contenteditable="true"].ProseMirror',
            xpath='//div[@contenteditable="true" and contains(@class, "ProseMirror")]',
            placeholder="Ask anything",
        )

    @property
    def send_button(self) -> DomTarget:
        return DomTarget(
            description="Claude send button",
            css='button[aria-label="Send Message"]',
            xpath='//button[@aria-label="Send Message"]',
        )

    @property
    def response_area(self) -> DomTarget:
        return DomTarget(
            description="Claude assistant response",
            css='div.assistant-message:last-of-type div[class*="content"]',
            xpath='(//div[contains(@class, "assistant")])[last()]//div[contains(@class, "content")]',
        )

    @property
    def new_chat_button(self) -> DomTarget:
        return DomTarget(
            description="Claude new chat button",
            css='button[aria-label="New chat"]',
            xpath='//button[contains(@aria-label, "New chat")]',
            text="New chat",
        )

    @property
    def login_indicator(self) -> DomTarget:
        return DomTarget(
            description="Claude user avatar",
            css='button[data-testid="user-menu"]',
            xpath='//button[contains(@aria-label, "Account")]',
        )

    @property
    def _stop_button(self) -> DomTarget:
        return DomTarget(
            description="Claude stop button",
            css='button[aria-label="Stop Response"]',
            xpath='//button[contains(@aria-label, "Stop")]',
        )

    async def send_message(self, page: Page, text: str) -> None:
        await self._human_delay(200, 500)

        # Navigate to chat if on a different page
        if "/chat" not in page.url:
            await page.goto(f"{self.base_url}/new", wait_until="domcontentloaded")
            await self._human_delay(1000, 2000)

        # Claude's input area: click to focus the contenteditable div
        input_loc = await self._locate(page, self.input_box)
        await self._move_mouse_naturally(page, input_loc)
        await input_loc.click()
        await self._human_delay(100, 300)

        # Type into the focused element
        for char in text:
            await page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.02, 0.10))

        await self._human_delay(100, 300)
        send = await self._locate(page, self.send_button)
        await self._move_mouse_naturally(page, send)
        await send.click()

    async def wait_for_response(self, page: Page) -> AsyncGenerator[str, None]:
        seen = 0
        stable_count = 0
        max_stable = 6

        while True:
            try:
                try:
                    await self._locate(page, self._stop_button, timeout=2_000)
                    still_streaming = True
                except Exception:
                    still_streaming = False

                loc = await self._locate(page, self.response_area, timeout=5_000)
                full_text = (await loc.inner_text()).strip()

                if len(full_text) > seen:
                    new_chunk = full_text[seen:]
                    seen = len(full_text)
                    stable_count = 0
                    yield new_chunk
                else:
                    if not still_streaming:
                        stable_count += 1
                        if stable_count >= max_stable:
                            break
                    await asyncio.sleep(0.4)
                    continue

                await asyncio.sleep(0.3)

            except Exception:
                stable_count += 1
                if stable_count >= max_stable:
                    break
                await asyncio.sleep(0.5)

    async def create_new_chat(self, page: Page) -> str:
        await page.goto(f"{self.base_url}/new", wait_until="domcontentloaded")
        await self._human_delay(800, 1500)
        try:
            btn = await self._locate(page, self.new_chat_button, timeout=5_000)
            await self._move_mouse_naturally(page, btn)
            await btn.click()
            await self._human_delay(500, 1000)
        except Exception:
            pass
        conv_id = page.url.rstrip("/").split("/")[-1]
        return conv_id if conv_id else now_iso()
