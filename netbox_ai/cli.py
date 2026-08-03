"""命令行入口。"""

from __future__ import annotations

import asyncio
import sys

import click
from rich.console import Console

from . import __version__
from .agent import run_query, run_repl
from .config import load_config


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", "config_path", type=click.Path(exists=False, dir_okay=False), help="YAML 配置文件路径")
@click.option("--ai-base-url", help="AI 接口地址，如 https://api.openai.com/v1 或 http://127.0.0.1:11434/v1")
@click.option("--ai-api-key", help="AI API Key")
@click.option("--ai-model", help="模型名，如 gpt-4o-mini / deepseek-chat / qwen-plus")
@click.option("--mcp-url", help="NetBox MCP 地址，如 http://127.0.0.1:8000/mcp")
@click.option("--mcp-token", default=None, help="MCP Bearer Token（可选）")
@click.option("--temperature", type=float, default=None, help="采样温度")
@click.option("--max-tokens", type=int, default=None, help="最大生成 token")
@click.option("--max-tool-rounds", type=int, default=None, help="最大工具调用轮次")
@click.option("--quiet", is_flag=True, help="安静模式，不打印工具调用过程")
@click.option("-q", "--query", "query", default=None, help="单次查询后退出；省略则进入交互模式")
@click.option("--web", is_flag=True, help="启动 Web 网页界面")
@click.option("--host", default="127.0.0.1", show_default=True, help="Web 监听地址")
@click.option("--port", default=8080, show_default=True, type=int, help="Web 监听端口")
@click.version_option(__version__, prog_name="netbox-ai")
def main(
    config_path: str | None,
    ai_base_url: str | None,
    ai_api_key: str | None,
    ai_model: str | None,
    mcp_url: str | None,
    mcp_token: str | None,
    temperature: float | None,
    max_tokens: int | None,
    max_tool_rounds: int | None,
    quiet: bool,
    query: str | None,
    web: bool,
    host: str,
    port: int,
) -> None:
    """连接 NetBox MCP，用自然语言查询基础设施信息。

    网页模式：

      netbox-ai --web

      netbox-ai --web --host 0.0.0.0 --port 8080

    命令行模式：

      netbox-ai -q "列出所有站点"
    """
    console = Console(stderr=True)
    try:
        cfg = load_config(
            config_path,
            ai_base_url=ai_base_url,
            ai_api_key=ai_api_key,
            ai_model=ai_model,
            mcp_url=mcp_url,
            mcp_token=mcp_token,
            temperature=temperature,
            max_tokens=max_tokens,
            max_tool_rounds=max_tool_rounds,
            verbose=False if quiet or web else None,
        )
        # Web 允许先启动再在页面里填 Key；CLI 模式仍强制校验
        if not web:
            cfg.validate()
    except Exception as exc:
        console.print(f"[red]配置错误:[/red] {exc}")
        sys.exit(2)

    if web:
        from .web import run_web

        console.print(f"[green]NetBox AI Web[/green]  http://{host}:{port}")
        try:
            run_web(host=host, port=port, config=cfg)
        except KeyboardInterrupt:
            console.print("\n已停止。")
            sys.exit(130)
        return

    out = Console()
    try:
        if query:
            answer = asyncio.run(run_query(cfg, query, console=out))
            if quiet:
                click.echo(answer)
        else:
            asyncio.run(run_repl(cfg, console=out))
    except KeyboardInterrupt:
        console.print("\n已中断。")
        sys.exit(130)
    except Exception as exc:
        console.print(f"[red]运行失败:[/red] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
