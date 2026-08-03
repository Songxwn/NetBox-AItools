"""FastAPI Web 服务：浏览器里用自然语言查询 NetBox。"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .. import __version__
from ..agent import SYSTEM_PROMPT, NetBoxAgent
from ..config import AIConfig, AgentConfig, AppConfig, MCPConfig, load_config
from ..llm import LLMClient
from ..mcp_client import MCPClient

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))


class SettingsUpdate(BaseModel):
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=256, le=128000)
    mcp_url: str | None = None
    mcp_token: str | None = None
    max_tool_rounds: int | None = Field(default=None, ge=1, le=30)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class ResetRequest(BaseModel):
    session_id: str | None = None


class RuntimeState:
    """进程内运行时配置、MCP 连接与会话历史。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.mcp: MCPClient | None = None
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._chat_lock = asyncio.Lock()

    def public_settings(self) -> dict[str, Any]:
        key = self.config.ai.api_key
        masked = ""
        if key:
            masked = key[:4] + "…" + key[-4:] if len(key) > 8 else "****"
        return {
            "ai_base_url": self.config.ai.base_url,
            "ai_api_key_masked": masked,
            "ai_api_key_set": bool(key),
            "ai_model": self.config.ai.model,
            "temperature": self.config.ai.temperature,
            "max_tokens": self.config.ai.max_tokens,
            "mcp_url": self.config.mcp.url,
            "mcp_token_set": bool(self.config.mcp.token),
            "max_tool_rounds": self.config.agent.max_tool_rounds,
            "tools": [t["name"] for t in (self.mcp.tools if self.mcp else [])],
            "mcp_connected": self.mcp is not None,
            "version": __version__,
        }

    async def apply_settings(self, update: SettingsUpdate) -> None:
        async with self._lock:
            cfg = self.config
            reconnect = False

            if update.ai_base_url is not None and update.ai_base_url.strip():
                cfg.ai.base_url = update.ai_base_url.strip().rstrip("/")
            if update.ai_api_key is not None and update.ai_api_key.strip():
                cfg.ai.api_key = update.ai_api_key.strip()
            if update.ai_model is not None and update.ai_model.strip():
                cfg.ai.model = update.ai_model.strip()
            if update.temperature is not None:
                cfg.ai.temperature = update.temperature
            if update.max_tokens is not None:
                cfg.ai.max_tokens = update.max_tokens
            if update.max_tool_rounds is not None:
                cfg.agent.max_tool_rounds = update.max_tool_rounds

            if update.mcp_url is not None and update.mcp_url.strip():
                new_url = update.mcp_url.strip()
                if new_url != cfg.mcp.url:
                    cfg.mcp.url = new_url
                    reconnect = True
            if update.mcp_token is not None:
                # 允许传空字符串清空 token
                new_token = update.mcp_token.strip()
                if new_token != cfg.mcp.token:
                    cfg.mcp.token = new_token
                    reconnect = True

            cfg.validate()
            if reconnect or self.mcp is None:
                await self._reconnect_unlocked()

    async def reconnect(self) -> None:
        async with self._lock:
            await self._reconnect_unlocked()

    async def ensure_mcp(self) -> MCPClient:
        async with self._lock:
            if self.mcp is None:
                await self._reconnect_unlocked()
            assert self.mcp is not None
            return self.mcp

    async def _reconnect_unlocked(self) -> None:
        if self.mcp is not None:
            await self.mcp.close()
            self.mcp = None
        client = MCPClient(self.config.mcp)
        await client.connect()
        self.mcp = client

    def get_or_create_session(self, session_id: str | None) -> tuple[str, list[dict[str, Any]]]:
        sid = session_id or uuid.uuid4().hex
        if sid not in self.sessions:
            self.sessions[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
        return sid, self.sessions[sid]

    def reset_session(self, session_id: str | None) -> str:
        sid = session_id or uuid.uuid4().hex
        self.sessions[sid] = [{"role": "system", "content": SYSTEM_PROMPT}]
        return sid

    async def close(self) -> None:
        async with self._lock:
            if self.mcp is not None:
                await self.mcp.close()
                self.mcp = None


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    # Web 默认不向终端刷 verbose
    cfg.agent.verbose = False
    state = RuntimeState(cfg)

    app = FastAPI(title="NetBox AI", version=__version__)
    app.state.runtime = state
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.on_event("startup")
    async def _startup() -> None:
        try:
            await state.ensure_mcp()
        except Exception:
            pass

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await state.close()

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"version": __version__},
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "mcp_connected": state.mcp is not None,
        }

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        return state.public_settings()

    @app.put("/api/settings")
    async def put_settings(body: SettingsUpdate) -> dict[str, Any]:
        try:
            await state.apply_settings(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"连接 MCP 失败: {exc}") from exc
        return state.public_settings()

    @app.post("/api/mcp/reconnect")
    async def reconnect_mcp() -> dict[str, Any]:
        try:
            await state.reconnect()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"连接 MCP 失败: {exc}") from exc
        return state.public_settings()

    @app.post("/api/reset")
    async def reset_chat(body: ResetRequest) -> dict[str, str]:
        sid = state.reset_session(body.session_id)
        return {"session_id": sid}

    @app.post("/api/chat")
    async def chat(body: ChatRequest) -> StreamingResponse:
        message = body.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="消息不能为空")

        try:
            state.config.validate()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        sid, history = state.get_or_create_session(body.session_id)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def on_event(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def runner() -> None:
            try:
                async with state._chat_lock:
                    mcp = await state.ensure_mcp()
                    agent = NetBoxAgent(
                        state.config,
                        mcp,
                        LLMClient(state.config.ai),
                        messages=history,
                    )
                    await queue.put({"type": "session", "session_id": sid})
                    answer = await agent.ask(message, on_event=on_event)
                    await queue.put({"type": "done", "content": answer, "session_id": sid})
            except Exception as exc:
                await queue.put({"type": "error", "message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(runner())

        async def event_stream():
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def run_web(
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    config: AppConfig | None = None,
) -> None:
    import uvicorn

    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level="info")
