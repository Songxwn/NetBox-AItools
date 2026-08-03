"""自然语言查询 Agent：LLM + NetBox MCP 工具循环。"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

from rich.console import Console

from .config import AppConfig
from .llm import LLMClient
from .mcp_client import MCPClient

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class NetBoxAgent:
    def __init__(
        self,
        config: AppConfig,
        mcp: MCPClient,
        llm: LLMClient,
        console: Console | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self.mcp = mcp
        self.llm = llm
        self.console = console or Console(quiet=True)
        self.messages: list[dict[str, Any]] = messages or [
            {"role": "system", "content": config.prompts.system},
        ]

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": self.config.prompts.system}]

    async def _emit(self, on_event: EventCallback | None, event: dict[str, Any]) -> None:
        if on_event is None:
            return
        result = on_event(event)
        if inspect.isawaitable(result):
            await result

    async def ask(
        self,
        question: str,
        *,
        on_event: EventCallback | None = None,
    ) -> str:
        self.messages.append({"role": "user", "content": question})
        tools = self.mcp.openai_tools()

        for round_idx in range(1, self.config.agent.max_tool_rounds + 1):
            await self._emit(
                on_event,
                {"type": "status", "message": f"思考中（第 {round_idx} 轮）…"},
            )
            response = await asyncio.to_thread(self.llm.chat, self.messages, tools or None)
            message = response.choices[0].message
            tool_calls = message.tool_calls or []

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
            }
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ]
            self.messages.append(assistant_msg)

            if not tool_calls:
                answer = (message.content or "").strip()
                await self._emit(on_event, {"type": "answer", "content": answer})
                return answer

            await self._emit(
                on_event,
                {
                    "type": "tool_round",
                    "round": round_idx,
                    "count": len(tool_calls),
                },
            )

            for tc in tool_calls:
                name = tc.function.name
                raw_args = tc.function.arguments or "{}"
                try:
                    arguments = json.loads(raw_args) if raw_args.strip() else {}
                    if not isinstance(arguments, dict):
                        raise ValueError("工具参数必须是 JSON 对象")
                except Exception as exc:
                    result_text = f"参数解析失败: {exc}; raw={raw_args!r}"
                    await self._emit(
                        on_event,
                        {
                            "type": "tool_error",
                            "name": name,
                            "error": result_text,
                        },
                    )
                else:
                    await self._emit(
                        on_event,
                        {
                            "type": "tool_call",
                            "name": name,
                            "arguments": arguments,
                        },
                    )
                    try:
                        result_text = await self.mcp.call_tool(name, arguments)
                    except Exception as exc:
                        result_text = f"工具调用异常: {exc}"
                    preview = (
                        result_text if len(result_text) <= 1200 else result_text[:1200] + "…"
                    )
                    await self._emit(
                        on_event,
                        {
                            "type": "tool_result",
                            "name": name,
                            "preview": preview,
                        },
                    )

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    }
                )

        final = (
            "已达到最大工具调用轮次仍未得到最终答案。"
            "请缩小问题范围，或提高 agent.max_tool_rounds。"
        )
        await self._emit(on_event, {"type": "answer", "content": final})
        return final
