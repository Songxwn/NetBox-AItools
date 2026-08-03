"""NetBox MCP 客户端（Streamable HTTP，兼容 mcp SDK 1.x / 2.x）。"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

from .config import MCPConfig


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    text = getattr(content, "text", None)
    if text is not None:
        return str(text)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False, indent=2)
    return str(content)


def tool_result_to_text(result: Any) -> str:
    """把 MCP CallToolResult 转成可读文本。"""
    parts: list[str] = []
    contents = getattr(result, "content", None) or []
    for item in contents:
        parts.append(_content_to_text(item))

    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False, indent=2))

    text = "\n".join(p for p in parts if p).strip()
    is_error = bool(getattr(result, "is_error", False) or getattr(result, "isError", False))
    if is_error:
        return f"[工具执行错误]\n{text or 'unknown error'}"
    return text or "(空结果)"


def _detect_sdk() -> str:
    """返回 'v1' 或 'v2'。"""
    try:
        from mcp.client.streamable_http import streamablehttp_client  # noqa: F401

        return "v1"
    except ImportError:
        pass
    try:
        from mcp.client.streamable_http import streamable_http_client  # noqa: F401

        return "v2"
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "未找到可用的 mcp SDK。请安装: pip install 'mcp>=1.9.0,<2'"
        ) from exc


class MCPClient:
    """连接 NetBox MCP 并提供 tools/list、tools/call。"""

    def __init__(self, config: MCPConfig) -> None:
        self.config = config
        self._stack: AsyncExitStack | None = None
        self._sdk = _detect_sdk()
        # v1: ClientSession；v2: Client
        self._session: Any = None
        self._tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._session is not None:
            return

        headers: dict[str, str] = {}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            if self._sdk == "v1":
                from mcp import ClientSession
                from mcp.client.streamable_http import streamablehttp_client

                transport = await stack.enter_async_context(
                    streamablehttp_client(
                        self.config.url,
                        headers=headers or None,
                        timeout=self.config.timeout,
                        sse_read_timeout=self.config.sse_read_timeout,
                    )
                )
                read, write = transport[0], transport[1]
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self._session = session
            else:
                import httpx2
                from mcp import Client
                from mcp.client.streamable_http import (
                    create_mcp_http_client,
                    streamable_http_client,
                )

                http_client = create_mcp_http_client(
                    headers=headers or None,
                    timeout=httpx2.Timeout(self.config.timeout, read=self.config.sse_read_timeout),
                )
                await stack.enter_async_context(http_client)
                transport = streamable_http_client(self.config.url, http_client=http_client)
                client = Client(transport, read_timeout_seconds=self.config.sse_read_timeout)
                self._session = await stack.enter_async_context(client)

            self._stack = stack
            await self.refresh_tools()
        except Exception:
            await stack.aclose()
            self._session = None
            self._stack = None
            raise

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None
        self._tools = []

    async def refresh_tools(self) -> list[dict[str, Any]]:
        session = self._require_session()
        result = await session.list_tools()
        tools: list[dict[str, Any]] = []
        for tool in result.tools:
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": schema,
                }
            )
        self._tools = tools
        return tools

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self._tools

    def openai_tools(self) -> list[dict[str, Any]]:
        """转换为 OpenAI function calling 工具定义。"""
        converted: list[dict[str, Any]] = []
        for tool in self._tools:
            parameters = tool["input_schema"] or {
                "type": "object",
                "properties": {},
            }
            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"] or tool["name"],
                        "parameters": parameters,
                    },
                }
            )
        return converted

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        session = self._require_session()
        result = await session.call_tool(name, arguments or {})
        return tool_result_to_text(result)

    def _require_session(self) -> Any:
        if self._session is None:
            raise RuntimeError("MCP 尚未连接，请先调用 connect()")
        return self._session
