# NetBox AI Tools

基于 **NetBox MCP** 的自然语言查询 Web 工具。AI / MCP / 提示词均在**服务器后台**配置，网页仅用于对话查询。

## 功能

- Web 聊天查询 NetBox
- 后台配置 AI、MCP 地址与密钥
- 可配置系统提示词、用户消息格式化模板
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

若出现 `No matching distribution found for mcp`：

```bash
pip install -r requirements.txt -i https://pypi.org/simple
```

## 后台配置

复制并编辑配置文件（任选其一或组合使用）：

```bash
# Windows
copy .env.example .env
copy config.example.yaml config.yaml

# Linux / macOS
# cp .env.example .env
# cp config.example.yaml config.yaml
```

### 连接配置

| 配置项 | 环境变量 / YAML | 说明 |
|--------|-----------------|------|
| AI 地址 | `AI_BASE_URL` / `ai.base_url` | 如 `https://api.openai.com/v1` |
| AI Key | `AI_API_KEY` / `ai.api_key` | API Key |
| 模型 | `AI_MODEL` / `ai.model` | 如 `gpt-4o-mini` |
| MCP 地址 | `MCP_URL` / `mcp.url` | 如 `http://127.0.0.1:8000/mcp` |
| MCP Token | `MCP_TOKEN` / `mcp.token` | 可选 |

### 提示词配置

用于约束模型行为，并**格式化用户发送的内容**：

| 配置项 | 说明 |
|--------|------|
| `prompts.system` | 系统提示词 |
| `prompts.user_template` | 用户消息模板，必须包含 `{message}` |
| `prompts.system_file` | 从文件加载系统提示词 |
| `prompts.user_template_file` | 从文件加载用户模板 |

示例（`config.yaml`）：

```yaml
prompts:
  system_file: prompts/system.txt
  user_template_file: prompts/user_template.txt
```

用户输入 `列出所有站点` 时，实际送给模型的内容会按模板展开，例如：

```text
请根据以下用户需求查询 NetBox...
【用户需求】
列出所有站点
```

优先级：**启动参数 > 环境变量 > config.yaml > 默认值**

## 运行

```bash
python run.py
```

浏览器打开：http://127.0.0.1:8080

局域网访问：

```bash
python run.py --host 0.0.0.0 --port 8080
```

修改 `.env` / `config.yaml` / `prompts/` 后需**重启服务**生效。

## 项目结构

```text
run.py                 # 启动：python run.py
config.example.yaml    # 后台配置示例（含提示词）
prompts/               # 提示词文件示例
netbox_ai/
  config.py            # 配置与提示词加载
  agent.py             # 工具调用循环
  web/                 # Web 界面与 API
```

## 常见问题

**提示未配置 AI**  
在服务器 `.env` 或 `config.yaml` 中填写 `AI_API_KEY` 等，然后重启 `python run.py`。

**连不上 MCP**  
确认 MCP 以 `TRANSPORT=http` 运行，`MCP_URL` 指向 `/mcp`。

**用户模板不生效**  
确认模板包含 `{message}`，修改后重启服务。
