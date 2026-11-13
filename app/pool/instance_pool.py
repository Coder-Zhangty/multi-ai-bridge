from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections.abc import AsyncGenerator

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.adapters.base import BaseAdapter
from app.browser.manager import BrowserManager
from app.core.config import AccountConfig, Settings
from app.models.schemas import ChatChunk, ChatDone, ChatError, InstanceInfo, InstanceStatus, now_iso

logger = logging.getLogger(__name__)


class BrowserInstance:
    """A single browser instance bound to one platform account.

    Holds a persistent page and a serial request queue.  Only one chat
    request is processed at a time per instance (the queue is FIFO).
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        account: AccountConfig,
        browser_manager: BrowserManager,
        settings: Settings,
    ):
        self.instance_id = uuid.uuid4().hex[:12]
        self.platform = adapter.platform
        self.adapter = adapter
        self.account = account
        self.browser_manager = browser_manager
        self.settings = settings

        self._page: Page | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._status: InstanceStatus = InstanceStatus.STARTING
        self._last_used_at: str | None = None
        self._last_error: str | None = None

    @property
    def status(self) -> InstanceStatus:
        return self._status

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        """Initialize the page and verify login, then start the worker."""
        try:
            self._page = await self.browser_manager.get_page(self.account, self.platform)
            await self._page.goto(self.adapter.base_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)  # Let the page fully render
            if not await self.adapter.is_logged_in(self._page):
                logger.warning(
                    "%s/%s: not logged in. Navigate to %s and log in manually.",
                    self.platform,
                    self.account.email,
                    self.adapter.base_url,
                )
                self._status = InstanceStatus.UNHEALTHY
            else:
                self._status = InstanceStatus.IDLE
                logger.info("%s/%s: ready", self.platform, self.account.email)
        except Exception as exc:
            logger.error("Failed to start instance %s/%s: %s", self.platform, self.account.email, exc)
            self._status = InstanceStatus.UNHEALTHY
            self._last_error = str(exc)

        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            self._worker_task = None
        await self.browser_manager.close_context(self.platform, self.account.email)

    async def check_health(self) -> bool:
        """Verify the session is still valid."""
        if self._page is None:
            self._status = InstanceStatus.UNHEALTHY
            return False
        try:
            if await self.adapter.is_logged_in(self._page):
                if self._status != InstanceStatus.BUSY:
                    self._status = InstanceStatus.IDLE
                return True
            else:
                self._status = InstanceStatus.UNHEALTHY
                self._last_error = "Session expired — login indicator not found"
                return False
        except Exception as exc:
            self._status = InstanceStatus.UNHEALTHY
            self._last_error = str(exc)
            return False

    async def enqueue(self, message: str, conversation_id: str | None, timeout: float) -> dict:
        """Push a request onto the serial queue and await its completion (non-streaming)."""
        future: asyncio.Future = asyncio.Future()
        await self._queue.put((message, conversation_id, timeout, future, False))
        return await future

    async def enqueue_stream(self, message: str, conversation_id: str | None, timeout: float):
        """Push a request and get an async generator that yields chunks in real time."""
        queue: asyncio.Queue = asyncio.Queue()
        await self._queue.put((message, conversation_id, timeout, queue, True))
        while True:
            item = await queue.get()
            if item is None:  # sentinel: stream done
                break
            yield item

    async def _worker_loop(self) -> None:
        """Serial worker that processes one chat request at a time."""
        while True:
            try:
                message, conversation_id, timeout, sink, is_stream = await self._queue.get()
                self._status = InstanceStatus.BUSY
                self._last_used_at = now_iso()
                self._last_error = None

                try:
                    result = await asyncio.wait_for(
                        self._process_chat(message, conversation_id, sink if is_stream else None),
                        timeout=timeout,
                    )
                    if is_stream:
                        sink.put_nowait(None)  # sentinel
                    else:
                        try:
                            sink.set_result(result)
                        except asyncio.InvalidStateError:
                            pass
                except asyncio.TimeoutError:
                    if is_stream:
                        sink.put_nowait(None)
                    else:
                        try:
                            sink.set_exception(TimeoutError(f"Chat request timed out after {timeout}s"))
                        except asyncio.InvalidStateError:
                            pass
                    self._last_error = "timeout"
                except Exception as exc:
                    if is_stream:
                        sink.put_nowait(None)
                    else:
                        try:
                            sink.set_exception(exc)
                        except asyncio.InvalidStateError:
                            pass
                    self._last_error = str(exc)
                    logger.error("%s/%s chat error: %s\n%s", self.platform, self.account.email, exc, traceback.format_exc())

                self._status = InstanceStatus.IDLE
                self._queue.task_done()

            except asyncio.CancelledError:
                break

    async def _process_chat(self, message: str, conversation_id: str | None, stream_queue=None):
        """Execute a single chat interaction end-to-end."""
        if self._page is None:
            raise RuntimeError("Browser page is not initialized")

        page = self._page

        if conversation_id is None:
            conversation_id = await self.adapter.create_new_chat(page)

        await self.adapter.send_message(page, message)

        chunks: list[str] = []
        async for chunk in self.adapter.wait_for_response(page):
            if stream_queue is not None:
                stream_queue.put_nowait({"event": "chunk", "delta": chunk, "conversation_id": conversation_id, "platform": self.platform})
            chunks.append(chunk)

        result = {
            "conversation_id": conversation_id,
            "reply": "".join(chunks),
        }
        if stream_queue is not None:
            stream_queue.put_nowait({"event": "done", "conversation_id": conversation_id, "platform": self.platform, "model": ""})
        return result

    def snapshot(self) -> InstanceInfo:
        return InstanceInfo(
            instance_id=self.instance_id,
            platform=self.platform,
            status=self._status,
            account_email=self.account.email,
            queue_size=self._queue.qsize(),
            last_used_at=self._last_used_at,
            last_error=self._last_error,
        )


class InstancePool:
    """Manages browser instances for one platform."""

    def __init__(
        self,
        platform: str,
        adapter: BaseAdapter,
        accounts: list[AccountConfig],
        browser_manager: BrowserManager,
        settings: Settings,
    ):
        self.platform = platform
        self.adapter = adapter
        self.browser_manager = browser_manager
        self.settings = settings
        self.instances: list[BrowserInstance] = []
        self._next_index = 0
        self._lock = asyncio.Lock()

        # Create one instance per account, capped
        max_n = min(len(accounts), settings.max_instances_per_platform)
        for account in accounts[:max_n]:
            instance = BrowserInstance(adapter, account, browser_manager, settings)
            self.instances.append(instance)

    async def start_all(self) -> None:
        await asyncio.gather(*(instance.start() for instance in self.instances))

    async def stop_all(self) -> None:
        await asyncio.gather(*(instance.stop() for instance in self.instances))

    async def dispatch(self, message: str, conversation_id: str | None, timeout: float) -> dict:
        """Pick an idle instance (round-robin) and enqueue the request.

        If all instances are busy, waits for the next available one.
        """
        deadline = asyncio.get_running_loop().time() + timeout

        while True:
            healthy = [i for i in self.instances if i.status != InstanceStatus.UNHEALTHY]
            if not healthy:
                raise RuntimeError(f"No healthy instances available for platform '{self.platform}'")

            # Pick least-busy instance
            instance = min(healthy, key=lambda i: (0 if i.status == InstanceStatus.IDLE else 1, i.queue_size))

            if instance.status == InstanceStatus.IDLE:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f"No instance became available within {timeout}s for platform '{self.platform}'")
                return await instance.enqueue(message, conversation_id, remaining)

            # All busy — wait a short time and retry
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"No instance became available within {timeout}s for platform '{self.platform}'")
            await asyncio.sleep(min(1.0, remaining))

    def snapshot(self) -> list[InstanceInfo]:
        return [i.snapshot() for i in self.instances]

    @property
    def healthy_count(self) -> int:
        return sum(1 for i in self.instances if i.status != InstanceStatus.UNHEALTHY)

    @property
    def idle_count(self) -> int:
        return sum(1 for i in self.instances if i.status == InstanceStatus.IDLE)

    @property
    def busy_count(self) -> int:
        return sum(1 for i in self.instances if i.status == InstanceStatus.BUSY)
