# NetBox AI Tools

基于 **NetBox MCP** 的自然语言查询 Web 工具：在网页中连接可自定义的 **OpenAI 兼容 AI 接口**，查询 NetBox 基础设施数据。

## 功能

- Web 聊天界面，页面内可配置 AI / MCP 地址
- 支持 OpenAI、DeepSeek、通义、Ollama 等兼容接口
- 自定义 NetBox MCP HTTP 地址与可选 Bearer Token
- 流式展示工具调用过程与最终回答

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
```

若出现 `No matching distribution found for mcp`，多半是镜像未同步。可改用官方源：

```bash
pip install -r requirements.txt -i https://pypi.org/simple
```

或确认 Python ≥ 3.10：`python --version`

## 配置（可选）

可预先写入环境变量，也可启动后在网页「连接设置」中填写：

```bash
# Windows
copy .env.example .env

# Linux / macOS
# cp .env.example .env
```

| 配置项 | 环境变量 | 说明 |
|--------|----------|------|
| AI 地址 | `AI_BASE_URL` | 如 `https://api.openai.com/v1`、`http://127.0.0.1:11434/v1` |
| AI Key | `AI_API_KEY` | API Key |
| 模型 | `AI_MODEL` | 如 `gpt-4o-mini`、`deepseek-chat` |
| MCP 地址 | `MCP_URL` | 如 `http://127.0.0.1:8000/mcp` |
| MCP Token | `MCP_TOKEN` | 对应服务端 `MCP_AUTH_TOKEN`（可选） |

优先级：**启动参数 > 环境变量 > config.yaml > 默认值**（网页保存的设置仅作用于当前进程）

## 运行

在项目根目录执行：

```bash
python run.py
```

浏览器打开：http://127.0.0.1:8080

局域网访问：

```bash
python run.py --host 0.0.0.0 --port 8080
```

带初始连接参数启动：

```bash
python run.py --ai-base-url http://127.0.0.1:11434/v1 --ai-api-key ollama --ai-model qwen2.5 --mcp-url http://127.0.0.1:8000/mcp
```

打开页面后：

1. 点「连接设置」填写 AI Base URL / API Key / 模型 / MCP URL（若启动时未传）  
2. 保存并连接  
3. 用自然语言提问，例如「列出所有站点」

## 项目结构

```text
run.py                 # 启动脚本：python run.py
netbox_ai/
  cli.py               # 启动参数入口
  config.py            # 配置合并
  mcp_client.py        # MCP 客户端
  llm.py               # OpenAI 兼容客户端
  agent.py             # 自然语言 → 工具调用 → 回答
  web/
    app.py             # FastAPI Web 服务
    templates/         # 网页模板
    static/            # 样式与前端脚本
```

## 常见问题

**连不上 MCP / 安装报 mcp 找不到**  
确认 Python ≥ 3.10。若镜像没有包：`pip install -r requirements.txt -i https://pypi.org/simple`。MCP 需用 `TRANSPORT=http`，URL 带 `/mcp`。

**AI 返回不了 tool_calls**  
请使用支持 function calling 的模型。

**MCP 需要鉴权**  
服务端设置 `MCP_AUTH_TOKEN` 后，在网页设置或 `--mcp-token` / `MCP_TOKEN` 中传入。
