from __future__ import annotations

import asyncio
import json
import logging
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.models.schemas import ChatRequest, HealthResponse
from app.pool.dispatcher import Dispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("multi-ai-bridge")

settings = get_settings()
dispatcher = Dispatcher(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Multi-AI Bridge...")
    await dispatcher.start()
    logger.info("Ready. Listening on %s:%d", settings.host, settings.port)
    yield
    logger.info("Shutting down...")
    await dispatcher.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


def _check_api_key(request: Request) -> None:
    if not settings.api_key:
        return
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {settings.api_key}"
    if auth != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


@app.post("/v1/chat")
async def chat(request: ChatRequest, req: Request):
    _check_api_key(req)

    available = dispatcher.platforms
    if request.platform not in available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform '{request.platform}'. Available: {available}",
        )

    async def event_stream():
        try:
            async for chunk in dispatcher.chat_stream(
                platform=request.platform,
                message=request.message,
                conversation_id=request.conversation_id,
                timeout=request.timeout,
            ):
                yield f"event: {chunk['event']}\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("Chat stream error")
            yield f"event: error\ndata: {json.dumps({'event': 'error', 'message': str(exc), 'platform': request.platform}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/v1/health")
async def health(req: Request):
    _check_api_key(req)
    return HealthResponse(status="ok", platforms=dispatcher.health())


@app.get("/api/health")
async def simple_health():
    return {"status": "ok", "platforms": dispatcher.platforms}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
