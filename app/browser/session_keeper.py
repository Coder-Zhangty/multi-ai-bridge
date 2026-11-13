from __future__ import annotations

import asyncio
import logging

from app.core.config import AccountConfig, Settings

logger = logging.getLogger(__name__)


class SessionKeeper:
    """Periodically checks and maintains login sessions for all instances.

    For each instance, visits the platform homepage and checks whether the
    login indicator is still present. If a session has expired, attempts a
    one-time recovery by refreshing the page. If recovery fails, marks the
    instance as unhealthy.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._instances: list = []

    def register(self, instance) -> None:
        """Register a BrowserInstance for periodic health checks."""
        self._instances.append(instance)

    def unregister(self, instance) -> None:
        if instance in self._instances:
            self._instances.remove(instance)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.session_keepalive_interval)
            logger.info("Session keeper: checking %d instances", len(self._instances))
            for instance in self._instances:
                try:
                    healthy = await instance.check_health()
                    if not healthy:
                        logger.warning(
                            "Instance %s/%s is unhealthy — attempting recovery",
                            instance.platform,
                            instance.account.email,
                        )
                        try:
                            page = await instance.browser_manager.get_page(
                                instance.account, instance.platform,
                            )
                            await page.goto(
                                instance.adapter.base_url,
                                wait_until="domcontentloaded",
                                timeout=15_000,
                            )
                            if await instance.adapter.is_logged_in(page):
                                instance._page = page
                                instance._status = instance.status.__class__.IDLE
                                instance._last_error = None
                                logger.info(
                                    "Instance %s/%s recovered",
                                    instance.platform,
                                    instance.account.email,
                                )
                            else:
                                logger.warning(
                                    "Instance %s/%s still not logged in after recovery",
                                    instance.platform,
                                    instance.account.email,
                                )
                        except Exception as recovery_exc:
                            logger.error(
                                "Instance %s/%s recovery failed: %s",
                                instance.platform,
                                instance.account.email,
                                recovery_exc,
                            )
                except Exception as exc:
                    logger.error(
                        "Health check failed for %s/%s: %s",
                        instance.platform,
                        instance.account.email,
                        exc,
                    )

    async def run_once(self) -> None:
        """Run a single health check pass on all registered instances."""
        for instance in self._instances:
            try:
                healthy = await instance.check_health()
                status = "healthy" if healthy else "unhealthy"
                logger.info("Instance %s/%s: %s", instance.platform, instance.account.email, status)
            except Exception as exc:
                logger.error("Health check error %s/%s: %s", instance.platform, instance.account.email, exc)
