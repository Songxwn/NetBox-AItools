"""FastAPI Web 服务：浏览器里用自然语言查询 NetBox。"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .. import __version__
from ..agent import NetBoxAgent
from ..config import AppConfig, load_config
from ..llm import LLMClient
from ..mcp_client import MCPClient

logger = logging.getLogger("netbox_ai")

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))
MCP_CONNECT_TIMEOUT = 20.0


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

    def public_status(self) -> dict[str, Any]:
        """只读状态，不暴露密钥与可写配置入口。"""
        return {
            "ai_model": self.config.ai.model,
            "ai_base_url": self.config.ai.base_url,
            "mcp_url": self.config.mcp.url,
            "tools": [t["name"] for t in (self.mcp.tools if self.mcp else [])],
            "mcp_connected": self.mcp is not None,
            "ai_configured": bool(self.config.ai.api_key),
            "version": __version__,
        }

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
            try:
                await self.mcp.close()
            except Exception:
                logger.exception("关闭旧 MCP 连接失败")
            self.mcp = None

        logger.info("正在连接 MCP: %s", self.config.mcp.url)
        client = MCPClient(self.config.mcp)
        try:
            await asyncio.wait_for(client.connect(), timeout=MCP_CONNECT_TIMEOUT)
        except asyncio.TimeoutError as exc:
            try:
                await client.close()
            except Exception:
                pass
            raise TimeoutError(
                f"连接 MCP 超时（{MCP_CONNECT_TIMEOUT:.0f}s）：{self.config.mcp.url}"
            ) from exc
        except Exception:
            try:
                await client.close()
            except Exception:
                pass
            raise

        self.mcp = client
        logger.info(
            "MCP 已连接，工具: %s",
            ", ".join(t["name"] for t in client.tools) or "(无)",
        )

    def _new_history(self) -> list[dict[str, Any]]:
        return [{"role": "system", "content": self.config.prompts.system}]

    def get_or_create_session(self, session_id: str | None) -> tuple[str, list[dict[str, Any]]]:
        sid = session_id or uuid.uuid4().hex
        if sid not in self.sessions:
            self.sessions[sid] = self._new_history()
        return sid, self.sessions[sid]

    def reset_session(self, session_id: str | None) -> str:
        sid = session_id or uuid.uuid4().hex
        self.sessions[sid] = self._new_history()
        return sid

    async def close(self) -> None:
        async with self._lock:
            if self.mcp is not None:
                await self.mcp.close()
                self.mcp = None


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    cfg.agent.verbose = False
    state = RuntimeState(cfg)

    app = FastAPI(title="NetBox AI", version=__version__)
    app.state.runtime = state
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

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
            "ai_configured": bool(state.config.ai.api_key),
        }

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return state.public_status()

    @app.post("/api/reset")
    async def reset_chat(body: ResetRequest) -> dict[str, str]:
        sid = state.reset_session(body.session_id)
        logger.info("重置会话: %s", sid)
        return {"session_id": sid}

    @app.post("/api/chat")
    async def chat(body: ChatRequest) -> StreamingResponse:
        raw_message = body.message.strip()
        if not raw_message:
            raise HTTPException(status_code=400, detail="消息不能为空")

        try:
            state.config.validate()
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"{exc}（请在服务器后台 .env / config.yaml 中配置）",
            ) from exc

        formatted = state.config.prompts.format_user_message(raw_message)
        sid, history = state.get_or_create_session(body.session_id)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        logger.info("收到提问 session=%s: %s", sid, raw_message[:200])

        async def on_event(event: dict[str, Any]) -> None:
            etype = event.get("type")
            if etype == "status":
                logger.info("状态: %s", event.get("message"))
            elif etype == "tool_call":
                logger.info("调用工具: %s args=%s", event.get("name"), event.get("arguments"))
            elif etype == "tool_result":
                preview = str(event.get("preview") or "")
                logger.info("工具结果: %s (%d chars)", event.get("name"), len(preview))
            elif etype == "tool_error":
                logger.warning("工具错误: %s %s", event.get("name"), event.get("error"))
            elif etype == "answer":
                logger.info("生成回答 (%d chars)", len(str(event.get("content") or "")))
            await queue.put(event)

        async def runner() -> None:
            try:
                await queue.put({"type": "session", "session_id": sid})
                await queue.put({"type": "status", "message": "正在连接 MCP…"})

                async with state._chat_lock:
                    try:
                        mcp = await state.ensure_mcp()
                    except Exception as exc:
                        logger.exception("MCP 连接失败")
                        # 失败后清掉坏连接，便于下次重试
                        async with state._lock:
                            state.mcp = None
                        raise RuntimeError(f"连接 MCP 失败: {exc}") from exc

                    await queue.put(
                        {
                            "type": "status",
                            "message": f"MCP 已连接（{len(mcp.tools)} 个工具），正在调用 AI…",
                        }
                    )
                    agent = NetBoxAgent(
                        state.config,
                        mcp,
                        LLMClient(state.config.ai),
                        messages=history,
                    )
                    answer = await agent.ask(formatted, on_event=on_event)
                    await queue.put({"type": "done", "content": answer, "session_id": sid})
                    logger.info("问答完成 session=%s", sid)
            except Exception as exc:
                logger.exception("问答失败 session=%s", sid)
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
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
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

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    # 降低第三方库噪音，保留业务日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.INFO)

    cfg = config or load_config()
    logger.info("启动 NetBox AI Web  http://%s:%s", host, port)
    logger.info("AI: %s / %s", cfg.ai.base_url, cfg.ai.model)
    logger.info("MCP: %s", cfg.mcp.url)
    logger.info("AI Key: %s", "已配置" if cfg.ai.api_key else "未配置")

    app = create_app(cfg)
    uvicorn.run(app, host=host, port=port, log_level="info")
