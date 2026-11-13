from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from playwright.async_api import Page

from app.adapters.base import BaseAdapter, DomTarget


class ChatGPTAdapter(BaseAdapter):
    platform = "chatgpt"
    base_url = "https://chat.openai.com"

    # ----- DOM selectors (multi-level fallback) -----

    @property
    def input_box(self) -> DomTarget:
        return DomTarget(
            description="ChatGPT input box",
            css='div[contenteditable="true"]',
            xpath='//*[@id="prompt-textarea"]',
            placeholder="Message ChatGPT",
        )

    @property
    def send_button(self) -> DomTarget:
        return DomTarget(
            description="ChatGPT send button",
            css='button[data-testid="send-button"]',
            xpath='//button[@aria-label="Send prompt"]',
            text="Send",
        )

    @property
    def response_area(self) -> DomTarget:
        return DomTarget(
            description="ChatGPT assistant response",
            css='div[data-message-author-role="assistant"]:last-of-type',
            xpath='(//div[@data-message-author-role="assistant"])[last()]',
        )

    @property
    def new_chat_button(self) -> DomTarget:
        return DomTarget(
            description="ChatGPT new chat button",
            text="New chat",
            css='button[aria-label="New chat"]',
            xpath='//nav//button[contains(., "New chat")]',
        )

    @property
    def login_indicator(self) -> DomTarget:
        return DomTarget(
            description="ChatGPT user menu",
            css='button[data-testid="profile-button"]',
            xpath='//button[contains(@aria-label, "User")]',
        )

    @property
    def _stop_button(self) -> DomTarget:
        return DomTarget(
            description="ChatGPT stop generating button",
            css='button[data-testid="stop-button"]',
            xpath='//button[@aria-label="Stop streaming"]',
        )

    async def send_message(self, page: Page, text: str) -> None:
        await self._human_delay(200, 500)

        # Ensure we are on the chat page
        if "/chat" not in page.url and "/c/" not in page.url:
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
        """Poll the last assistant message for new text until generation stops."""
        seen = 0
        stable_count = 0
        max_stable = 6

        while True:
            try:
                # Check if the stop button is still visible (means still generating)
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
            # Already on a fresh chat page
            pass
        conv_id = page.url.rstrip("/").split("/")[-1]
        return conv_id if conv_id else super().create_new_chat(page)
