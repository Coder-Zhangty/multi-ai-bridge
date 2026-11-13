from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from playwright.async_api import Page

from app.adapters.base import BaseAdapter, DomTarget
from app.models.schemas import now_iso


class DeepSeekAdapter(BaseAdapter):
    platform = "deepseek"
    base_url = "https://chat.deepseek.com"

    @property
    def input_box(self) -> DomTarget:
        return DomTarget(
            description="DeepSeek input box",
            css='textarea, [contenteditable="true"], [role="textbox"]',
            xpath='//textarea | //div[@contenteditable="true"] | //div[@role="textbox"]',
            placeholder="给 DeepSeek 发送消息",
        )

    @property
    def send_button(self) -> DomTarget:
        return DomTarget(
            description="DeepSeek send button",
            css='textarea ~ button, [class*="send"] button, button[class*="send"]',
            xpath='//button[descendant::*[local-name()="svg"]] | //button[contains(@class, "send") or contains(@class, "submit")] | //*[@role="button"][contains(@class, "send")]',
            text="发送",
        )

    @property
    def response_area(self) -> DomTarget:
        return DomTarget(
            description="DeepSeek latest response",
            css='.ds-markdown:last-of-type',
            xpath='(//div[contains(@class, "ds-markdown")])[last()]',
        )

    @property
    def new_chat_button(self) -> DomTarget:
        return DomTarget(
            description="DeepSeek new chat",
            css='button:has-text("新建对话")',
            xpath='//button[contains(., "新建对话")]',
            text="新建对话",
        )

    @property
    def login_indicator(self) -> DomTarget:
        return DomTarget(
            description="DeepSeek chat input",
            css='textarea[id="chat-input"]',
            xpath='//textarea',
            placeholder="给 DeepSeek 发送消息",
        )

    @property
    def _stop_button(self) -> DomTarget:
        return DomTarget(
            description="DeepSeek stop generating",
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
