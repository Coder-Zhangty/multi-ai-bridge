from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Platform(StrEnum):
    CHATGPT = "chatgpt"
    CLAUDE = "claude"
    GEMINI = "gemini"
    PERPLEXITY = "perplexity"
    KIMI = "kimi"
    TONGYI = "tongyi"
    DEEPSEEK = "deepseek"
    DOUBAO = "doubao"


class InstanceStatus(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"


class ChatRequest(BaseModel):
    platform: str = Field(description="Target platform: chatgpt / claude")
    message: str = Field(min_length=1, max_length=100000)
    conversation_id: str | None = Field(default=None)
    timeout: float = Field(default=180.0, ge=10, le=600)


class ChatChunk(BaseModel):
    event: str = "chunk"
    delta: str = ""
    conversation_id: str | None = None
    platform: str = ""


class ChatDone(BaseModel):
    event: str = "done"
    conversation_id: str
    platform: str
    model: str = ""


class ChatError(BaseModel):
    event: str = "error"
    message: str
    platform: str
    conversation_id: str | None = None


class InstanceInfo(BaseModel):
    instance_id: str
    platform: str
    status: InstanceStatus
    account_email: str
    queue_size: int
    last_used_at: str | None = None
    last_error: str | None = None


class PlatformHealth(BaseModel):
    platform: str
    total_instances: int
    healthy_instances: int
    idle_instances: int
    busy_instances: int
    instances: list[InstanceInfo]


class HealthResponse(BaseModel):
    status: str
    platforms: list[PlatformHealth]
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
