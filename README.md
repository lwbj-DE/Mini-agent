# Mini Agent

一个从零实现的轻量级 AI Agent，支持多轮对话、工具调用、跨轮次状态持久化、MCP 协议。核心 ReAct 循环完全自研，不依赖 LangChain 等 Agent 框架。

# 演示视频
https://www.bilibili.com/video/BV18wEG6NEQN/?vd_source=dd37b3e7641dc1162a468d0427cc9a35（如果打不开请复制打开

## 特性

- **自研 ReAct 循环**：Think → Act → Observe，不依赖 LangChain / OpenHands 等框架
- **双 Agent 模式**：快速对话（ReAct）+ 规划执行（Plan → Execute → Replan）
- **流式输出**：推理过程和回答逐 token 实时推送，思考过程完成后自动折叠
- **6 个工具**：calculator / search / todo（本地）+ weather / get_current_time / echo（MCP 远程）
- **MCP 协议**：支持 stdio 和 streamable-http 两种传输，运行时动态发现远程工具
- **跨轮次持久化**：任务状态保存在会话中，关闭页面后回来继续推进
- **上下文自动压缩**：长对话超过 token 阈值自动摘要，防止超出模型限制
- **浅色 / 深色主题**：默认浅色，一键切换，偏好本地持久化
- **工具热重载**：修改 `tools.yaml` 后调用 API 即可重载，无需重启

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API
cp .env.example .env
# 编辑 .env，填入你的 LLM API key 和模型

# 3. 启动
python run.py --port 8000

# 4. 浏览器打开
# http://localhost:8000
```

## 配置

所有配置通过 `.env` 文件管理，支持任意 OpenAI 兼容的 LLM API。

```bash
# .env
api_key=sk-your-key-here           # API 密钥（必填）
base_url=https://api.example.com/v1 # API 地址
model=gpt-4o                       # 模型名称
temperature=0.7                     # 生成温度（0-1）
max_tokens=4096                     # 单次最大输出

# Agent 行为
max_steps=10                        # 最大工具调用步数

# 上下文压缩
compression_enabled=true            # 是否启用
compression_trigger_fraction=0.7    # 触发压缩的 token 占比
compression_keep_messages=20        # 压缩后保留的最近消息数
model_max_input_tokens=32768        # 模型上下文窗口大小
```

## 架构

```
frontend/                   后端 backend/
┌──────────────┐           ┌─────────────────────────┐
│  index.html  │  SSE/HTTP │  main.py (FastAPI)       │
│  js/         │◄────────►│  agent_runtime.py         │
│  ├─ app.js   │           │  agent_modes/            │
│  ├─ chat.js  │           │  ├─ react_mode.py        │
│  ├─ renderer │           │  └─ plan_execute.py      │
│  ├─ sessions │           │  llm_client.py            │
│  └─ theme.js │           │  tool_registry.py         │
│  css/        │           │  tool_loader.py           │
└──────────────┘           │  session_manager.py       │
                           │  mcp_client.py            │
 tools.yaml ── 工具配置 ──►│  mcp_tool.py              │
 mcp_servers/              │  tools/                   │
 └─ demo_server.py         │  ├─ calculator.py         │
                           │  ├─ search.py             │
 .env ────── 环境变量 ────►│  └─ todo.py               │
                           └─────────────────────────┘
```

### ReAct 循环（自研）

```
用户输入 → [Think: LLM 推理] → 需要工具？
                                  ├─ 是 → [Act: 执行工具] → [Observe: 读取结果] → 回到 Think
                                  └─ 否 → 输出最终回答
                                  最大步数限制：10 步（可配）
```

### Plan-Execute 模式

```
用户输入 → [Planner: 制定多步计划（含交付物和完成标准）]
               → [Executor: 每步内嵌 ReAct 子循环，最多 8 次工具调用]
                   → [Replanner: 感知步骤截断，决定 继续 / 重规划 / 结束]
                       最大总步数：15 步，截断步骤标记为 failed
```

**与 ReAct 模式的隔离**：子循环不恢复/不保存 session 的 tool_state，避免 todo 等有状态工具在 PlanExecute 内部与外层 session 之间互相污染。步骤完成后由外层统一保存 session。

## 工具系统

### 本地工具（3 个）

| 工具 | 功能 |
|------|------|
| `calculator` | AST 白名单安全计算器，支持三角函数、对数、阶乘、π 等 |
| `search` | 内置知识库搜索（30+ 条目，覆盖编程、AI、运维等领域） |
| `todo` | 任务管理器，支持创建/更新/查询，跨轮次状态持久化 |

### MCP 远程工具（3 个，来自 demo_server）

| 工具 | 来源 | 功能 |
|------|------|------|
| `weather` | mcp:demo | 查询城市天气（mock） |
| `get_current_time` | mcp:demo | 获取当前 UTC 时间 |
| `echo` | mcp:demo | 回显测试，验证连通性 |

### 添加 MCP 工具

在 `tools.yaml` 中配置：

```yaml
mcp_servers:
  - name: my-server
    transport: stdio              # stdio 或 streamable-http
    command: python
    args: [mcp_servers/my_tools.py]
    enabled: true
```

然后调用 `POST /api/tools/reload` 热重载。

### 添加本地工具

1. 在 `backend/tools/` 下创建类，继承 `BaseTool`
2. 在 `tools.yaml` 中注册：

```yaml
tools:
  - name: my_tool
    enabled: true
    module: backend.tools.my_tool
    class: MyTool
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 + 工具列表 |
| `GET` | `/api/tools` | 所有工具及 JSON Schema |
| `POST` | `/api/tools/reload` | 热重载工具配置 |
| `POST` | `/api/sessions` | 创建新会话 |
| `GET` | `/api/sessions` | 列出所有会话 |
| `GET` | `/api/sessions/{id}` | 获取会话详情（含消息和 tool_state） |
| `DELETE` | `/api/sessions/{id}` | 删除会话 |
| `PATCH` | `/api/sessions/{id}/rename` | 重命名会话 |
| `POST` | `/api/sessions/{id}/chat` | 发送消息（SSE 流式响应） |

### Chat 请求格式

```json
{
  "message": "帮我制定学习 Rust 的计划",
  "mode": "plan_execute"
}
```

`mode` 可选值：`react`（默认，快速对话）/ `plan_execute`（规划执行）

### SSE 事件类型

| 事件 | 说明 |
|------|------|
| `step_start` | 循环迭代开始 |
| `reasoning` | LLM 推理 token（流式） |
| `message` | 回答文本 token（流式，`final=true` 时结束） |
| `tool_call` | 工具调用请求 |
| `tool_result` | 工具执行结果 |
| `plan_created` | 计划制定完成（Plan-Execute 模式） |
| `plan_step_update` | 计划步骤状态变更 |
| `error` | 错误信息 |
| `done` | 对话完成 |

## Memory 的召回时机与放置方式

### 放置时机

1. **ReAct 模式每轮结束时**：`session.tool_state = tools.get_state()` 将工具状态（todo 任务列表）写入 session JSON 文件
2. **PlanExecute 模式整体结束后**：外层统一调用 `tools.get_state()` 保存，子循环不单独保存（避免中途写入不完整状态）
3. **消息历史实时追加**：每轮对话的 user/assistant/tool 消息直接 append 到 `session.messages`，session 结束时统一 save

### 召回时机

1. **进入已有 session 时**：`tools.set_state(session.tool_state)` 将之前保存的 todo 任务列表恢复到内存，Agent 可感知已有任务的进度
2. **上下文压缩触发时**（估算 tokens 超过 `compression_trigger_fraction × model_max_input_tokens`）：早期消息被 LLM 摘要为一段系统消息，保留最近 N 条消息（`compression_keep_messages`）
3. **侧栏会话列表**：读取每个 session 文件提取 `summary`（含 `task_total` / `task_done`），显示进度徽标

### 隔离策略

PlanExecute 子循环使用 `isolate_state=True`，不恢复也不保存 tool_state，确保规划模式内的 todo 操作不影响外层 session 的持久化状态。

## 跨轮次继续执行

1. **第一轮**：发送"帮我制定学习 Rust 的 3 步计划"，Agent 用 `todo` 创建任务
2. **第二轮**：点击同一会话继续，说"完成了第一步"，Agent 基于已有状态更新进度
3. 侧栏会话列表显示任务进度徽标（`📋 1/3`）
4. 进入旧会话时顶部显示任务进度条

## 项目结构

```
mini-agent/
├── run.py                      # 启动入口
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
├── tools.yaml                  # 工具配置（本地 + MCP）
│
├── backend/
│   ├── agent_runtime.py        # 模式调度器
│   ├── agent_modes/
│   │   ├── react_mode.py       # ReAct 模式（含上下文压缩）
│   │   └── plan_execute.py     # Plan-Execute 模式
│   ├── config.py               # pydantic-settings 配置
│   ├── events.py               # SSE 事件类型定义
│   ├── llm_client.py           # LLM API 封装（流式/非流式）
│   ├── main.py                 # FastAPI 应用
│   ├── mcp_client.py           # MCP JSON-RPC 客户端
│   ├── mcp_tool.py             # MCP 工具代理（包装为 BaseTool）
│   ├── session_manager.py      # 会话 JSON 持久化
│   ├── tool_loader.py          # 工具 YAML 加载 + 热重载
│   ├── tool_registry.py        # 工具注册中心
│   └── tools/
│       ├── base.py             # 工具基类
│       ├── calculator.py       # 安全计算器
│       ├── search.py           # 知识库搜索
│       └── todo.py             # 任务管理器
│
├── frontend/
│   ├── index.html              # SPA 入口
│   ├── css/style.css           # 样式（浅色/深色双主题）
│   └── js/
│       ├── app.js              # 应用入口 + 事件绑定
│       ├── chat.js             # SSE 流式对话引擎
│       ├── renderer.js         # DOM 渲染层（marked + highlight.js）
│       ├── sessions.js         # 会话管理
│       └── theme.js            # 主题切换
│
├── mcp_servers/
│   └── demo_server.py          # 示例 MCP 服务器
│
└── data/
    ├── sessions/               # 会话 JSON 文件
    └── logs/                   # 日志文件（按日切割）
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + uvicorn |
| LLM SDK | openai（兼容任意 OpenAI 格式 API） |
| 配置 | pydantic-settings + .env |
| 日志 | Loguru（彩色控制台 + 按日切割 + zip 压缩） |
| 工具配置 | PyYAML + 动态 import |
| MCP | 自研 JSON-RPC 2.0 客户端（stdio + streamable-http） |
| 前端 | 原生 HTML/CSS/JS，marked.js + highlight.js |

## 许可证

MIT
