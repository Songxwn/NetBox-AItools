"""自然语言查询 Agent：LLM + NetBox MCP 工具循环。"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .config import AppConfig
from .llm import LLMClient
from .mcp_client import MCPClient

SYSTEM_PROMPT = """你是 NetBox 基础设施助手，通过 MCP 工具查询 NetBox 中的真实数据。

规则：
1. 优先使用可用 MCP 工具获取事实，不要编造设备、IP、站点等信息。
2. 查询时尽量加过滤条件，并在支持时使用 fields 只取必要字段，控制返回体积。
3. 可多轮调用工具；拿到足够信息后再用简洁中文回答用户。
4. 若工具返回为空或报错，说明原因并给出可尝试的下一步。
5. 回答聚焦用户问题，避免大段原始 JSON，必要时可做结构化摘要。
"""

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
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

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
        verbose = self.config.agent.verbose

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
                if verbose and self.console is not None:
                    self.console.print(Panel(Markdown(answer or "(空回复)"), title="回答"))
                return answer

            if verbose:
                self.console.print(
                    f"[dim]第 {round_idx} 轮工具调用：{len(tool_calls)} 个[/dim]"
                )

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
                    if verbose:
                        self.console.print(f"[red]✗ {name}[/red] {result_text}")
                else:
                    await self._emit(
                        on_event,
                        {
                            "type": "tool_call",
                            "name": name,
                            "arguments": arguments,
                        },
                    )
                    if verbose:
                        self.console.print(
                            f"[cyan]→ 调用[/cyan] {name} "
                            f"[dim]{json.dumps(arguments, ensure_ascii=False)}[/dim]"
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
                    if verbose:
                        self.console.print(f"[green]← 结果[/green]\n{preview[:800]}")

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
        if verbose:
            self.console.print(f"[yellow]{final}[/yellow]")
        return final


async def run_query(
    config: AppConfig,
    question: str,
    *,
    console: Console | None = None,
) -> str:
    console = console or Console()
    async with MCPClient(config.mcp) as mcp:
        if config.agent.verbose:
            names = ", ".join(t["name"] for t in mcp.tools) or "(无)"
            console.print(f"[dim]已连接 MCP: {config.mcp.url}[/dim]")
            console.print(f"[dim]可用工具: {names}[/dim]")
            console.print(f"[dim]AI: {config.ai.base_url} / {config.ai.model}[/dim]")
        agent = NetBoxAgent(config, mcp, LLMClient(config.ai), console=console)
        return await agent.ask(question)


async def run_repl(
    config: AppConfig,
    *,
    console: Console | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> None:
    console = console or Console()
    ask_input = input_fn or input

    async with MCPClient(config.mcp) as mcp:
        names = ", ".join(t["name"] for t in mcp.tools) or "(无)"
        console.print(
            Panel.fit(
                f"MCP: {config.mcp.url}\n"
                f"AI:  {config.ai.base_url}\n"
                f"模型: {config.ai.model}\n"
                f"工具: {names}\n\n"
                "输入自然语言问题查询 NetBox；输入 /exit 退出，/reset 清空对话。",
                title="NetBox AI 查询",
            )
        )
        agent = NetBoxAgent(config, mcp, LLMClient(config.ai), console=console)

        while True:
            try:
                question = ask_input("\n你> ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n再见。")
                break

            if not question:
                continue
            if question.lower() in {"/exit", "/quit", "exit", "quit"}:
                console.print("再见。")
                break
            if question.lower() in {"/reset", "reset"}:
                agent.reset()
                console.print("[dim]对话已重置。[/dim]")
                continue
            if question.lower() in {"/tools", "tools"}:
                await mcp.refresh_tools()
                for t in mcp.tools:
                    console.print(f"- [bold]{t['name']}[/bold]: {t['description']}")
                continue

            await agent.ask(question)
