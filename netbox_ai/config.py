"""配置加载：启动参数 > 环境变量 > config.yaml > 默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

DEFAULT_SYSTEM_PROMPT = """你是 NetBox 基础设施助手，通过 MCP 工具查询 NetBox 中的真实数据。

规则：
1. 优先使用可用 MCP 工具获取事实，不要编造设备、IP、站点等信息。
2. 查询时尽量加过滤条件，并在支持时使用 fields 只取必要字段，控制返回体积。
3. 可多轮调用工具；拿到足够信息后再用简洁中文回答用户。
4. 若工具返回为空或报错，说明原因并给出可尝试的下一步。
5. 回答聚焦用户问题，避免大段原始 JSON，必要时可做结构化摘要。
"""

DEFAULT_USER_TEMPLATE = "{message}"


@dataclass
class AIConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_tokens: int = 4096


@dataclass
class MCPConfig:
    url: str = "http://127.0.0.1:8000/mcp"
    token: str = ""
    timeout: float = 30.0
    sse_read_timeout: float = 300.0


@dataclass
class PromptConfig:
    """提示词配置：系统提示词 + 用户消息格式化模板。"""

    system: str = DEFAULT_SYSTEM_PROMPT
    # 必须包含 {message}，用于包装/格式化用户原始输入
    user_template: str = DEFAULT_USER_TEMPLATE

    def format_user_message(self, message: str) -> str:
        text = message.strip()
        template = self.user_template or DEFAULT_USER_TEMPLATE
        if "{message}" not in template:
            return f"{template.rstrip()}\n\n{text}"
        return template.replace("{message}", text)


@dataclass
class AgentConfig:
    max_tool_rounds: int = 8
    verbose: bool = True


@dataclass
class AppConfig:
    ai: AIConfig = field(default_factory=AIConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    prompts: PromptConfig = field(default_factory=PromptConfig)

    def validate(self) -> None:
        if not self.ai.api_key:
            raise ValueError("未配置 AI API Key，请在 .env / config.yaml 中设置 AI_API_KEY")
        if not self.ai.base_url:
            raise ValueError("未配置 AI 地址，请设置 AI_BASE_URL")
        if not self.mcp.url:
            raise ValueError("未配置 MCP 地址，请设置 MCP_URL")
        if not self.prompts.system.strip():
            raise ValueError("系统提示词不能为空，请检查 prompts.system")


def _deep_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _read_text_file(path: str | Path | None, base_dir: Path | None = None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    if not p.exists():
        raise FileNotFoundError(f"提示词文件不存在: {p}")
    return p.read_text(encoding="utf-8")


def load_config(
    config_path: str | Path | None = None,
    *,
    ai_base_url: str | None = None,
    ai_api_key: str | None = None,
    ai_model: str | None = None,
    mcp_url: str | None = None,
    mcp_token: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_tool_rounds: int | None = None,
    verbose: bool | None = None,
) -> AppConfig:
    """按优先级合并配置。"""
    load_dotenv()

    file_data: dict[str, Any] = {}
    path = Path(config_path) if config_path else _find_default_config()
    base_dir = path.parent if path else Path.cwd()
    if path and path.exists():
        with path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"配置文件格式错误: {path}")
            file_data = loaded

    system_from_file = _read_text_file(
        _first(
            os.getenv("SYSTEM_PROMPT_FILE"),
            _deep_get(file_data, "prompts", "system_file"),
        ),
        base_dir,
    )
    user_from_file = _read_text_file(
        _first(
            os.getenv("USER_PROMPT_TEMPLATE_FILE"),
            _deep_get(file_data, "prompts", "user_template_file"),
        ),
        base_dir,
    )

    cfg = AppConfig(
        ai=AIConfig(
            base_url=_first(
                ai_base_url,
                os.getenv("AI_BASE_URL"),
                _deep_get(file_data, "ai", "base_url"),
                "https://api.openai.com/v1",
            ),
            api_key=_first(
                ai_api_key,
                os.getenv("AI_API_KEY"),
                os.getenv("OPENAI_API_KEY"),
                _deep_get(file_data, "ai", "api_key"),
                "",
            ),
            model=_first(
                ai_model,
                os.getenv("AI_MODEL"),
                _deep_get(file_data, "ai", "model"),
                "gpt-4o-mini",
            ),
            temperature=float(
                _first(
                    temperature,
                    os.getenv("AI_TEMPERATURE"),
                    _deep_get(file_data, "ai", "temperature"),
                    0.2,
                )
            ),
            max_tokens=int(
                _first(
                    max_tokens,
                    os.getenv("AI_MAX_TOKENS"),
                    _deep_get(file_data, "ai", "max_tokens"),
                    4096,
                )
            ),
        ),
        mcp=MCPConfig(
            url=_first(
                mcp_url,
                os.getenv("MCP_URL"),
                _deep_get(file_data, "mcp", "url"),
                "http://127.0.0.1:8000/mcp",
            ),
            token=_first(
                mcp_token,
                os.getenv("MCP_TOKEN"),
                os.getenv("MCP_AUTH_TOKEN"),
                _deep_get(file_data, "mcp", "token"),
                "",
            ),
            timeout=float(
                _first(
                    os.getenv("MCP_TIMEOUT"),
                    _deep_get(file_data, "mcp", "timeout"),
                    30.0,
                )
            ),
            sse_read_timeout=float(
                _first(
                    os.getenv("MCP_SSE_READ_TIMEOUT"),
                    _deep_get(file_data, "mcp", "sse_read_timeout"),
                    300.0,
                )
            ),
        ),
        agent=AgentConfig(
            max_tool_rounds=int(
                _first(
                    max_tool_rounds,
                    os.getenv("MAX_TOOL_ROUNDS"),
                    _deep_get(file_data, "agent", "max_tool_rounds"),
                    8,
                )
            ),
            verbose=_as_bool(
                _first(
                    verbose,
                    os.getenv("AGENT_VERBOSE"),
                    _deep_get(file_data, "agent", "verbose"),
                    True,
                ),
                default=True,
            ),
        ),
        prompts=PromptConfig(
            system=str(
                _first(
                    system_from_file,
                    os.getenv("SYSTEM_PROMPT"),
                    _deep_get(file_data, "prompts", "system"),
                    DEFAULT_SYSTEM_PROMPT,
                )
            ).strip(),
            user_template=str(
                _first(
                    user_from_file,
                    os.getenv("USER_PROMPT_TEMPLATE"),
                    _deep_get(file_data, "prompts", "user_template"),
                    DEFAULT_USER_TEMPLATE,
                )
            ),
        ),
    )
    return cfg


def _find_default_config() -> Path | None:
    for name in ("config.yaml", "config.yml"):
        path = Path(name)
        if path.exists():
            return path
    return None


def _first(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return None
