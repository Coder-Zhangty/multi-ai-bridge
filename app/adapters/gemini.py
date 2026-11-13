from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from playwright.async_api import Page

from app.adapters.base import BaseAdapter, DomTarget
from app.models.schemas import now_iso


class GeminiAdapter(BaseAdapter):
    platform = "gemini"
    base_url = "https://gemini.google.com/app"

    @property
    def input_box(self) -> DomTarget:
        return DomTarget(
            description="Gemini input box",
            css='div[contenteditable="true"]',
            xpath='//div[@contenteditable="true" and contains(@class, "ql-editor")]',
            placeholder="Enter a prompt here",
        )

    @property
    def send_button(self) -> DomTarget:
        return DomTarget(
            description="Gemini send button",
            css='button[aria-label="Send message"]',
            xpath='//button[@aria-label="Send message"]',
        )

    @property
    def response_area(self) -> DomTarget:
        return DomTarget(
            description="Gemini latest response",
            css='.model-response-content:last-of-type',
            xpath='(//div[contains(@class, "model-response")])[last()]//message-content',
        )

    @property
    def new_chat_button(self) -> DomTarget:
        return DomTarget(
            description="Gemini new chat button",
            css='a[aria-label="New chat"]',
            xpath='//a[contains(@aria-label, "New chat")]',
            text="New chat",
        )

    @property
    def login_indicator(self) -> DomTarget:
        return DomTarget(
            description="Gemini user menu",
            css='button[aria-label*="Account"]',
            xpath='//button[contains(@aria-label, "Google Account")]',
        )

    @property
    def _stop_button(self) -> DomTarget:
        return DomTarget(
            description="Gemini stop generating",
            css='button[aria-label="Stop"]',
            xpath='//button[contains(@aria-label, "Stop")]',
        )

    async def send_message(self, page: Page, text: str) -> None:
        await self._human_delay(200, 500)

        if "/app" not in page.url:
            await page.goto(self.base_url, wait_until="domcontentloaded")
            await self._human_delay(1000, 2000)

        input_loc = await self._locate(page, self.input_box)
        await self._move_mouse_naturally(page, input_loc)
        await self._type_like_human(input_loc, text, page=page)

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
        await page.goto(self.base_url, wait_until="domcontentloaded")
        await self._human_delay(800, 1500)
        try:
            btn = await self._locate(page, self.new_chat_button, timeout=5_000)
            await self._move_mouse_naturally(page, btn)
            await btn.click()
            await self._human_delay(500, 1000)
        except Exception:
            pass
        return now_iso().replace(":", "-")
