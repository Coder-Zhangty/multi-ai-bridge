from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from app.adapters.api_adapter import ApiAdapter, _API_INCOMPATIBLE_PLATFORMS
from app.adapters.base import BaseAdapter
from app.adapters.chatgpt import ChatGPTAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.deepseek import DeepSeekAdapter
from app.adapters.doubao import DoubaoAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.kimi import KimiAdapter
from app.adapters.perplexity import PerplexityAdapter
from app.adapters.tongyi import TongyiAdapter
from app.browser.manager import BrowserManager
from app.browser.session_keeper import SessionKeeper
from app.core.config import Settings
from app.models.schemas import InstanceStatus, PlatformHealth
from app.pool.instance_pool import InstancePool

logger = logging.getLogger(__name__)

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "chatgpt": ChatGPTAdapter,
    "claude": ClaudeAdapter,
    "gemini": GeminiAdapter,
    "perplexity": PerplexityAdapter,
    "kimi": KimiAdapter,
    "tongyi": TongyiAdapter,
    "deepseek": DeepSeekAdapter,
    "doubao": DoubaoAdapter,
}


class Dispatcher:
    """Top-level orchestrator: browser pools + API adapters, browser-first with API fallback."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.browser_manager = BrowserManager(settings)
        self.session_keeper = SessionKeeper(settings)
        self._pools: dict[str, InstancePool] = {}
        self._api_adapters: dict[str, ApiAdapter] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.browser_manager.start()

        for platform in self.settings.supported_platforms:
            mode = self.settings.get_platform_mode(platform)

            # Init browser pool if mode requires it
            if mode in ("browser_first", "browser_only"):
                adapter_cls = ADAPTER_REGISTRY.get(platform)
                if adapter_cls is None:
                    logger.warning("No browser adapter for '%s' — skipping browser pool", platform)
                else:
                    accounts = self.settings.get_platform_accounts(platform)
                    if accounts:
                        adapter = adapter_cls()
                        pool = InstancePool(platform, adapter, accounts, self.browser_manager, self.settings)
                        self._pools[platform] = pool
                    else:
                        logger.warning("No browser accounts for '%s', mode=%s — skipping browser pool", platform, mode)

            # Init API adapter if mode requires it
            if mode in ("browser_first", "api_first", "api_only"):
                if platform in _API_INCOMPATIBLE_PLATFORMS:
                    logger.warning("'%s' API is not OpenAI-compatible — skipping ApiAdapter", platform)
                else:
                    api_cfg = self.settings.get_platform_api(platform)
                    if api_cfg and api_cfg.api_key:
                        self._api_adapters[platform] = ApiAdapter(
                            platform=platform,
                            api_key=api_cfg.api_key,
                            api_base=api_cfg.api_base,
                            model=api_cfg.model,
                        )
                        logger.info("API adapter ready for '%s' (mode=%s)", platform, mode)

        if not self._pools and not self._api_adapters:
            raise RuntimeError("No platforms configured. Check accounts.json and API key env vars.")

        # Start all browser pools in parallel
        for pool in self._pools.values():
            await pool.start_all()

        # Register instances for session keepalive
        for pool in self._pools.values():
            for instance in pool.instances:
                self.session_keeper.register(instance)

        await self.session_keeper.start()
        self._started = True
        logger.info(
            "Dispatcher started — browser: %s, api: %s",
            list(self._pools.keys()),
            list(self._api_adapters.keys()),
        )

    async def shutdown(self) -> None:
        await self.session_keeper.stop()
        for pool in self._pools.values():
            await pool.stop_all()
        for api_adapter in self._api_adapters.values():
            await api_adapter.close()
        await self.browser_manager.shutdown()
        self._started = False

    def _get_platform_names(self) -> list[str]:
        return sorted(set(self._pools.keys()) | set(self._api_adapters.keys()))

    async def chat(
        self,
        platform: str,
        message: str,
        conversation_id: str | None = None,
        timeout: float = 180.0,
    ) -> dict:
        """Route a chat request. Browser-first, API fallback."""
        platform = platform.lower()
        mode = self.settings.get_platform_mode(platform)
        pool = self._pools.get(platform)
        api_adapter = self._api_adapters.get(platform)

        if not pool and not api_adapter:
            available = self._get_platform_names()
            raise ValueError(f"Unsupported platform '{platform}'. Available: {available}")

        # Browser-first: try browser, fallback to API
        if mode in ("browser_first", "browser_only"):
            if pool is not None:
                try:
                    return await pool.dispatch(message, conversation_id, timeout)
                except Exception as exc:
                    if mode == "browser_first" and api_adapter:
                        logger.warning(
                            "Browser call failed for '%s', falling back to API: %s", platform, exc
                        )
                        return await api_adapter.chat(message, conversation_id)
                    raise
            # No browser pool — fall through to API if available
            if mode == "browser_first" and api_adapter:
                logger.info("No browser pool for '%s', using API directly", platform)
                return await api_adapter.chat(message, conversation_id)
            raise RuntimeError(f"No browser pool for '{platform}'. Add accounts in accounts.json.")

        # API-first: try API, fallback to browser
        if mode == "api_first":
            if api_adapter:
                try:
                    return await api_adapter.chat(message, conversation_id)
                except Exception as exc:
                    if pool is not None:
                        logger.warning(
                            "API call failed for '%s', falling back to browser: %s", platform, exc
                        )
                        return await pool.dispatch(message, conversation_id, timeout)
                    raise
            # No API adapter — fall through to browser if available
            if pool is not None:
                logger.info("No API adapter for '%s', using browser directly", platform)
                return await pool.dispatch(message, conversation_id, timeout)
            raise RuntimeError(f"No API key for '{platform}'. Set {platform.upper()}_API_KEY env var.")

        # API-only
        if api_adapter:
            return await api_adapter.chat(message, conversation_id)

        raise RuntimeError(f"No API key for '{platform}'. Set {platform.upper()}_API_KEY env var.")

    async def chat_stream(
        self,
        platform: str,
        message: str,
        conversation_id: str | None = None,
        timeout: float = 180.0,
    ) -> AsyncGenerator[dict, None]:
        """Streaming chat. Browser-first with API fallback."""
        platform = platform.lower()
        mode = self.settings.get_platform_mode(platform)
        pool = self._pools.get(platform)
        api_adapter = self._api_adapters.get(platform)

        if not pool and not api_adapter:
            available = self._get_platform_names()
            raise ValueError(f"Unsupported platform '{platform}'. Available: {available}")

        # Helper: yield from browser result as SSE chunks
        async def _stream_browser_result(result: dict):
            reply = result["reply"]
            chunk_size = 10
            for i in range(0, len(reply), chunk_size):
                yield {
                    "event": "chunk",
                    "delta": reply[i : i + chunk_size],
                    "conversation_id": result["conversation_id"],
                    "platform": platform,
                }
            yield {
                "event": "done",
                "conversation_id": result["conversation_id"],
                "platform": platform,
                "model": "",
            }

        # Browser-first
        if mode in ("browser_first", "browser_only"):
            if pool is not None:
                try:
                    result = await pool.dispatch(message, conversation_id, timeout)
                    async for chunk in _stream_browser_result(result):
                        yield chunk
                    return
                except Exception as exc:
                    if mode == "browser_first" and api_adapter:
                        logger.warning(
                            "Browser stream failed for '%s', falling back to API: %s", platform, exc
                        )
                        async for chunk in api_adapter.chat_stream(message, conversation_id):
                            yield chunk
                        return
                    raise
            if mode == "browser_first" and api_adapter:
                logger.info("No browser pool for '%s', using API directly", platform)
                async for chunk in api_adapter.chat_stream(message, conversation_id):
                    yield chunk
                return
            raise RuntimeError(f"No browser pool for '{platform}'. Add accounts in accounts.json.")

        # API-first: try API, fallback to browser
        if mode == "api_first":
            if api_adapter:
                try:
                    async for chunk in api_adapter.chat_stream(message, conversation_id):
                        yield chunk
                    return
                except Exception as exc:
                    if pool is not None:
                        logger.warning(
                            "API stream failed for '%s', falling back to browser: %s", platform, exc
                        )
                        result = await pool.dispatch(message, conversation_id, timeout)
                        async for chunk in _stream_browser_result(result):
                            yield chunk
                        return
                    raise
            # No API adapter — fall through to browser if available
            if pool is not None:
                logger.info("No API adapter for '%s', using browser directly", platform)
                result = await pool.dispatch(message, conversation_id, timeout)
                async for chunk in _stream_browser_result(result):
                    yield chunk
                return
            raise RuntimeError(f"No API key for '{platform}'. Set {platform.upper()}_API_KEY env var.")

        # API-only
        if api_adapter:
            async for chunk in api_adapter.chat_stream(message, conversation_id):
                yield chunk
            return

        raise RuntimeError(f"No API key for '{platform}'. Set {platform.upper()}_API_KEY env var.")

    def health(self) -> list[PlatformHealth]:
        result = []
        for platform, pool in self._pools.items():
            result.append(
                PlatformHealth(
                    platform=platform,
                    total_instances=len(pool.instances),
                    healthy_instances=pool.healthy_count,
                    idle_instances=pool.idle_count,
                    busy_instances=pool.busy_count,
                    instances=pool.snapshot(),
                )
            )
        # Also report API-only platforms
        for platform, api_adapter in self._api_adapters.items():
            if platform not in self._pools:
                result.append(
                    PlatformHealth(
                        platform=platform,
                        total_instances=1,
                        healthy_instances=1,
                        idle_instances=1,
                        busy_instances=0,
                        instances=[],
                    )
                )
        return result

    @property
    def platforms(self) -> list[str]:
        return self._get_platform_names()
