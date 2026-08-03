"""Web 服务启动入口。"""

from __future__ import annotations

import sys

import click
from rich.console import Console

from . import __version__
from .config import load_config


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", "config_path", type=click.Path(exists=False, dir_okay=False), help="YAML 配置文件路径")
@click.option("--ai-base-url", help="AI 接口地址，如 https://api.openai.com/v1")
@click.option("--ai-api-key", help="AI API Key（建议写在 .env / config.yaml）")
@click.option("--ai-model", help="模型名，如 gpt-4o-mini / deepseek-chat")
@click.option("--mcp-url", help="NetBox MCP 地址，如 http://127.0.0.1:8000/mcp")
@click.option("--mcp-token", default=None, help="MCP Bearer Token（可选）")
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
    host: str,
    port: int,
) -> None:
    """启动 NetBox AI Web 界面。

    连接与提示词请在 .env / config.yaml / prompts/ 中配置。

    示例：

      python run.py

      python run.py --host 0.0.0.0 --port 8080
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
            verbose=False,
        )
    except Exception as exc:
        console.print(f"[red]配置错误:[/red] {exc}")
        sys.exit(2)

    from .web import run_web

    console.print(f"[green]NetBox AI Web[/green]  http://{host}:{port}")
    try:
        run_web(host=host, port=port, config=cfg)
    except KeyboardInterrupt:
        console.print("\n已停止。")
        sys.exit(130)


if __name__ == "__main__":
    main()
