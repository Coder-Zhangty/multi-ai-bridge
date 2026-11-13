from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from playwright.async_api import Page

from app.adapters.base import BaseAdapter, DomTarget
from app.models.schemas import now_iso


class DoubaoAdapter(BaseAdapter):
    platform = "doubao"
    base_url = "https://www.doubao.com/chat"

    @property
    def input_box(self) -> DomTarget:
        return DomTarget(
            description="豆包 input box",
            css='textarea',
            xpath='//textarea[@placeholder]',
            placeholder="请输入你的问题",
        )

    @property
    def send_button(self) -> DomTarget:
        return DomTarget(
            description="豆包 send button",
            css='button[type="submit"]',
            xpath='//button[contains(@class, "send")]',
        )

    @property
    def response_area(self) -> DomTarget:
        return DomTarget(
            description="豆包 latest response",
            css='.bot-message:last-of-type',
            xpath='(//div[contains(@class, "bot-message")])[last()]',
        )

    @property
    def new_chat_button(self) -> DomTarget:
        return DomTarget(
            description="豆包 new chat",
            css='button:has-text("新对话")',
            xpath='//button[contains(., "新对话")]',
            text="新对话",
        )

    @property
    def login_indicator(self) -> DomTarget:
        return DomTarget(
            description="豆包 user avatar",
            css='img[alt*="avatar"]',
            xpath='//div[contains(@class, "user-info")]',
        )

    @property
    def _stop_button(self) -> DomTarget:
        return DomTarget(
            description="豆包 stop generating",
            css='button:has-text("停止")',
            xpath='//button[contains(., "停止")]',
        )

    async def send_message(self, page: Page, text: str) -> None:
        await self._human_delay(200, 500)

        if "/chat" not in page.url:
            await page.goto(f"{self.base_url}/", wait_until="domcontentloaded")
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
        await page.goto(f"{self.base_url}/", wait_until="domcontentloaded")
        await self._human_delay(800, 1500)
        try:
            btn = await self._locate(page, self.new_chat_button, timeout=5_000)
            await self._move_mouse_naturally(page, btn)
            await btn.click()
            await self._human_delay(500, 1000)
        except Exception:
            pass
        return now_iso().replace(":", "-")
