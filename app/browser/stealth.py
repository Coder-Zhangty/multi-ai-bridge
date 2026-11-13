from __future__ import annotations

import asyncio
import random

from playwright.async_api import BrowserContext, Page


STEALTH_JS = r"""
// ------- navigator.webdriver removal -------
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// ------- chrome.runtime spoof -------
window.chrome = {
  runtime: {},
  loadTimes: function() {},
  csi: function() {},
  app: {}
};

// ------- permissions spoof -------
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
  parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);

// ------- plugin spoof -------
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5]
});

// ------- language spoof -------
Object.defineProperty(navigator, 'languages', {
  get: () => ['en-US', 'en']
});

// ------- hardware concurrency -------
Object.defineProperty(navigator, 'hardwareConcurrency', {
  get: () => 8
});

// ------- device memory -------
Object.defineProperty(navigator, 'deviceMemory', {
  get: () => 8
});
"""


async def inject_stealth(context: BrowserContext) -> None:
    """Inject anti-detection scripts into every new page in the context."""

    async def _on_page(page: Page):
        await page.add_init_script(STEALTH_JS)

    context.on("page", _on_page)

    # Also add to any existing pages
    for page in context.pages:
        await page.add_init_script(STEALTH_JS)


# ----- human-like behavior helpers -----

async def random_scroll(page: Page) -> None:
    """Simulate a small random scroll to appear human."""
    scroll_y = random.randint(50, 300)
    await page.evaluate(f"window.scrollBy(0, {scroll_y})")
    await asyncio.sleep(random.uniform(0.1, 0.4))


async def random_mouse_movement(page: Page) -> None:
    """Move mouse randomly on the page."""
    width = await page.evaluate("window.innerWidth")
    height = await page.evaluate("window.innerHeight")
    x = random.uniform(width * 0.1, width * 0.9)
    y = random.uniform(height * 0.1, height * 0.9)
    await page.mouse.move(x, y)
    await asyncio.sleep(random.uniform(0.05, 0.2))
