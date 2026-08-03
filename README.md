# NetBox AI Tools

用自然语言查询 NetBox 数据的 Python 工具：连接 **NetBox MCP**，并通过可自定义的 **OpenAI 兼容 AI 接口** 完成工具编排与回答。支持 **Web 网页** 与命令行两种使用方式。

## 功能

- Web 聊天界面，页面内可配置 AI / MCP 地址
- 自定义 AI 地址 / Key / 模型（OpenAI、DeepSeek、通义、Ollama 等）
- 自定义 NetBox MCP HTTP 地址与可选 Bearer Token
- 流式展示工具调用过程与最终回答
- 命令行单次查询 / 交互对话

## 前置条件

1. 已有可访问的 NetBox 实例与只读 API Token  
2. 已启动 [NetBox MCP Server](https://github.com/netboxlabs/netbox-mcp-server)（HTTP 模式）  
3. Python 3.10+

启动 MCP 示例：

```bash
NETBOX_URL=https://netbox.example.com/ \
NETBOX_TOKEN=<token> \
TRANSPORT=http \
HOST=127.0.0.1 \
PORT=8000 \
uv run netbox-mcp-server
```

MCP 默认地址：`http://127.0.0.1:8000/mcp`

## 安装

```bash
cd NetBox-AItools
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
# source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

## 配置

复制模板：

```bash
copy .env.example .env
copy config.example.yaml config.yaml
```

优先级：**CLI 参数 > 环境变量 > config.yaml > 默认值**（Web 页面保存的设置仅作用于当前进程内存）

| 配置项 | 环境变量 | 说明 |
|--------|----------|------|
| AI 地址 | `AI_BASE_URL` | 如 `https://api.openai.com/v1`、`http://127.0.0.1:11434/v1` |
| AI Key | `AI_API_KEY` | API Key |
| 模型 | `AI_MODEL` | 如 `gpt-4o-mini`、`deepseek-chat` |
| MCP 地址 | `MCP_URL` | 如 `http://127.0.0.1:8000/mcp` |
| MCP Token | `MCP_TOKEN` | 对应服务端 `MCP_AUTH_TOKEN`（可选） |

## Web 使用（推荐）

```bash
netbox-ai --web
# 浏览器打开 http://127.0.0.1:8080

# 局域网访问
netbox-ai --web --host 0.0.0.0 --port 8080
```

打开页面后：

1. 点「连接设置」填写 AI Base URL / API Key / 模型 / MCP URL  
2. 保存并连接  
3. 直接用自然语言提问，例如「列出所有站点」

## 命令行使用

```bash
netbox-ai -q "列出所有站点"
netbox-ai -q "Equinix DC14 站点有哪些设备？"
netbox-ai
```

自定义 AI 与 MCP：

```bash
netbox-ai --web ^
  --ai-base-url http://127.0.0.1:11434/v1 ^
  --ai-api-key ollama ^
  --ai-model qwen2.5 ^
  --mcp-url http://127.0.0.1:8000/mcp
```

## 项目结构

```text
netbox_ai/
  cli.py           # 命令行 / Web 启动入口
  config.py        # 配置合并
  mcp_client.py    # MCP Streamable HTTP 客户端
  llm.py           # OpenAI 兼容客户端
  agent.py         # 自然语言 → 工具调用 → 回答
  web/
    app.py         # FastAPI 服务
    templates/     # 网页模板
    static/        # 样式与前端脚本
```

## 常见问题

**连不上 MCP**  
确认服务已用 `TRANSPORT=http` 启动，URL 带协议且路径为 `/mcp`（必要时试 `/mcp/`）。可在网页「连接设置」里点「仅重连 MCP」。

**AI 返回不了 tool_calls**  
请使用支持 function calling 的模型；部分本地小模型可能不支持，可换更大模型。

**MCP 需要鉴权**  
服务端设置 `MCP_AUTH_TOKEN` 后，在网页设置或 `--mcp-token` / `MCP_TOKEN` 中传入。
