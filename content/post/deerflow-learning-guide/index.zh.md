---
title: "DeerFlow 学习指南：从入门到精通"
description: "系统性的 DeerFlow 项目学习路线，帮助你从零开始掌握这个 super agent harness 的核心概念与架构设计"
date: 2026-04-14
slug: "deerflow-learning-guide"
tags:
    - AI
    - Agent
    - DeerFlow
    - 开源项目
categories:
    - 技术笔记
---

## 项目简介

DeerFlow（Deep Exploration and Efficient Research Flow）是字节跳动开源的 **super agent harness**。它不是简单的聊天机器人框架，而是真正让 AI Agent "能把事情做完" 的运行时基础设施。

核心特点：
- **Sub-Agents**：复杂任务自动拆解，多路并行执行
- **Sandbox**：隔离的 Docker 执行环境，Agent 有自己的"电脑"
- **Skills**：可扩展的能力模块，用 Markdown 定义工作流
- **Memory**：跨会话持久记忆，越用越懂你
- **MCP**：支持 Model Context Protocol，扩展工具生态

技术栈：Python 3.12+ (Backend) + Node.js 22+ (Frontend) + LangGraph + LangChain

GitHub: https://github.com/bytedance/deer-flow

---

## 学习路线总览

```
阶段一：入门使用 (1-2天)
    ├── 理解项目定位
    ├── 本地环境搭建
    └── 基础功能体验

阶段二：核心概念 (3-5天)
    ├── Agent 架构
    ├── Sandbox 系统
    ├── Skills 机制
    └── Tools 工具集

阶段三：架构深入 (5-7天)
    ├── LangGraph Server
    ├── Gateway API
    ├── Frontend 实现
    └── 配置系统

阶段四：高级特性 (7-10天)
    ├── Subagents 委派
    ├── Memory 系统
    ├── MCP 集成
    └ IM Channels

阶段五：实战扩展 (持续)
    ├── 自定义 Skills
    ├── 扩展 Tools
    ├── 生产部署
    └── 性能调优
```

---

## 阶段一：入门使用

### 1.1 理解项目定位

**关键问题**：DeerFlow 和普通的 Agent 框架有什么不同？

答案是：**Harness vs Framework**

传统框架（如 LangChain）是拼装积木，你需要自己搭建一切。DeerFlow 是 harness —— 开箱即用的运行时，自带：
- 文件系统（sandbox）
- 记忆系统（memory）
- 能力模块（skills）
- 子代理（subagents）

你可以直接用，也可以拆开重组。

**推荐阅读**：
- README.md（官方介绍）
- README_zh.md（中文版）
- ARCHITECTURE.md（架构概览）

### 1.2 环境搭建

**前置要求**：
- Docker（推荐）或 本地开发环境
- 4 vCPU + 8GB 内存（最低）
- 模型 API Key（OpenAI、DeepSeek、Kimi 等）

**Docker 方式（推荐）**：

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow

# 生成配置文件
make config

# 编辑 config.yaml，配置模型
# 编辑 .env，填写 API Key

# 启动服务
make docker-init    # 拉取 sandbox 镜像
make docker-start   # 启动全部服务
```

访问 http://localhost:2026 即可使用。

**本地开发方式**：

```bash
make check      # 检查依赖（Node 22+、pnpm、uv）
make install    # 安装依赖
make dev        # 启动服务
```

Windows 用户请用 Git Bash，不支持原生 cmd/PowerShell。

### 1.3 基础功能体验

启动后，尝试以下任务：

1. **简单对话**：测试 Agent 基础能力
2. **文件上传**：上传 PDF/图片，让 Agent 分析
3. **网页搜索**：让 Agent 搜索并总结信息
4. **代码执行**：让 Agent 写代码并在 sandbox 里运行
5. **报告生成**：让 Agent 生成一份研究报告

> [!TIP]
> 观察右上角的"思考"过程，理解 Agent 的工作流程

---

## 阶段二：核心概念

### 2.1 Agent 架构

**核心文件**：`backend/packages/harness/deerflow/agents/lead_agent/agent.py`

Agent 由三部分组成：

```
┌─────────────────────────────────────┐
│           Lead Agent                 │
│  ┌─────────────┬─────────────┬─────┐│
│  │   Model     │   Tools     │Prompt││
│  │ (LLM实例)   │(工具集合)   │(含Skills)││
│  └─────────────┴─────────────┴─────┘│
│                                     │
│  + Middleware Chain (10个中间件)    │
└─────────────────────────────────────┘
```

**ThreadState**（`thread_state.py`）是 Agent 的状态容器：
- `messages`：对话历史
- `sandbox`：执行环境信息
- `artifacts`：生成的文件列表
- `todos`：任务清单（plan mode）

**学习重点**：
- 理解 `make_lead_agent()` 如何组装 Agent
- 跟踪一次请求的完整生命周期
- 观察 middleware 的执行顺序

### 2.2 Sandbox 系统

**核心文件**：`backend/packages/harness/deerflow/sandbox/`

Sandbox 是 DeerFlow 的"执行引擎"，让 Agent 能真正做事。

**虚拟路径映射**：

| Agent 看到的路径 | 实际物理路径 |
|-----------------|-------------|
| `/mnt/user-data/workspace` | `.deer-flow/threads/{id}/user-data/workspace` |
| `/mnt/user-data/uploads` | `.deer-flow/threads/{id}/user-data/uploads` |
| `/mnt/user-data/outputs` | `.deer-flow/threads/{id}/user-data/outputs` |
| `/mnt/skills` | `deer-flow/skills/` |

**三种 Sandbox 模式**：
1. **Local**：直接在宿主机执行（开发用）
2. **Docker**：隔离容器执行（推荐）
3. **Kubernetes**：通过 provisioner 在 Pod 中执行

**学习重点**：
- 理解 SandboxProvider 的 acquire/get/release 生命周期
- 查看 `sandbox/tools.py` 里的工具实现（bash、read_file、write_file）
- 尝试切换不同 sandbox 模式

### 2.3 Skills 机制

**目录**：`deer-flow/skills/`

Skill 是 DeerFlow 的"能力模块"，用 Markdown 定义工作流。

**结构**：

```
skills/
├── public/          # 内置 Skills（已提交）
│   ├── research/SKILL.md
│   ├── report-generation/SKILL.md
│   └── slide-creation/SKILL.md
└── custom/          # 自定义 Skills（本地）
    └── my-skill/SKILL.md
```

**SKILL.md 格式**：

```yaml
---
name: 报告生成
description: 生成结构化的研究报告
license: MIT
allowed-tools:
    - web_search
    - read_file
    - write_file
---

# Skill 指导
具体的工作流程说明...
```

**学习重点**：
- 阅读 3-5 个内置 Skill，理解格式和结构
- 尝试创建一个简单的自定义 Skill
- 观察 Skill 如何被注入到 system prompt

### 2.4 Tools 工具集

> [!NOTE]
> 详细笔记已发布：[Deer-Flow Tools 工具集详解](/post/deer-flow-series-tools/)

**核心文件**：`backend/packages/harness/deerflow/tools/`

工具分为五类：

|| 类型 | 来源 | 加载条件 | 示例 |
||-----|------|----------|------|
|| Built-in | `tools/builtins/` | 无 | present_files, ask_clarification |
|| Subagent | `tools/builtins/task_tool.py` | `subagent_enabled=True` | task |
|| Config | `config.yaml` | 按 groups 过滤 | web_search, web_fetch |
|| MCP | `extensions_config.json` | `include_mcp=True` | github, filesystem |
|| ACP | ACP 配置 | 有 ACP 代理 | invoke_acp_agent |

**核心设计亮点**：
1. **分层加载**：Config → Builtin → MCP → ACP
2. **延迟发现**：大量 MCP 工具时，按需获取 schema
3. **子代理隔离**：`subagent_enabled=False` 防止递归嵌套
4. **安全沙箱**：`is_host_bash_allowed()` 控制 host bash

**学习重点**：
- 理解 `get_available_tools()` 如何组装工具集
- 掌握延迟工具发现机制 (`tool_search`)
- 查看 `builtins/` 目录的内置工具实现
- 尝试通过 MCP Server 添加新工具

---

## 阶段三：架构深入

### 3.1 LangGraph Server

**端口**：2024

LangGraph Server 是 Agent 的运行时引擎，负责：
- Agent 创建与配置
- Thread 状态管理
- SSE 流式响应
- Checkpointing（状态持久化）

**配置**：`backend/langgraph.json`

```json
{
  "agent": {
    "type": "agent",
    "path": "deerflow.agents:make_lead_agent"
  }
}
```

**学习重点**：
- 理解 LangGraph 的 graph/node/edge 抽象
- 跟踪 `/api/langgraph/threads/{id}/runs` 的请求流程
- 观察 SSE 事件流（messages-tuple、values、end）

### 3.2 Gateway API

**端口**：8001

Gateway 是 FastAPI 应用，提供 REST API：

| Router | 路径 | 功能 |
|--------|------|------|
| Models | `/api/models` | 模型列表与详情 |
| MCP | `/api/mcp` | MCP Server 配置 |
| Skills | `/api/skills` | Skills 管理 |
| Uploads | `/api/threads/{id}/uploads` | 文件上传 |
| Artifacts | `/api/threads/{id}/artifacts` | 输出文件访问 |
| Memory | `/api/memory` | 记忆系统 |

**核心文件**：`backend/app/gateway/app.py`

**学习重点**：
- 理解 Gateway 与 LangGraph 的分工
- 查看 `routers/` 下的各个路由实现
- 尝试通过 API 调用而非 Web UI 操作

### 3.3 Frontend 实现

**端口**：3000

基于 Next.js 16 + React 19 的 Web 界面。

**目录结构**：

```
frontend/src/
├── app/            # 页面路由
├── components/     # UI 组件
├── core/           # 核心逻辑
├── hooks/          # React Hooks
└── lib/            # 工具函数
```

**关键依赖**：
- `@langchain/langgraph-sdk`：与 LangGraph Server 通信
- `@tanstack/react-query`：数据请求
- `@radix-ui`：UI 组件库
- `codemirror`：代码编辑器

**学习重点**：
- 理解前端如何通过 SDK 与后端交互
- 查看 SSE 流式响应的处理逻辑
- 观察状态管理（threads、messages、artifacts）

### 3.4 配置系统

**两个核心配置文件**：

**config.yaml**（主配置）：

```yaml
models:           # 模型定义
  - name: gpt-4
    use: langchain_openai:ChatOpenAI
    model: gpt-4
    api_key: $OPENAI_API_KEY

tools:            # 工具配置
  - name: web_search
    use: deerflow.community.tavily:tavily_search

sandbox:          # Sandbox 模式
  use: deerflow.community.aio_sandbox:AioSandboxProvider

memory:           # 记忆配置
  enabled: true
  debounce_seconds: 30

subagents:        # 子代理
  enabled: true
```

**extensions_config.json**（扩展配置）：

```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  },
  "skills": {
    "research": { "enabled": true },
    "report-generation": { "enabled": true }
  }
}
```

**学习重点**：
- 理解 `$VAR` 环境变量解析机制
- 查看 `config/` 目录的配置加载逻辑
- 尝试动态修改配置并观察效果

---

## 阶段四：高级特性

### 4.1 Subagents 委派

**核心文件**：`backend/packages/harness/deerflow/subagents/`

复杂任务自动拆解，并行执行。

**内置 Agent**：
- `general-purpose`：全能型，所有工具
- `bash`：命令专家

**并发控制**：
- 最大 3 个并发 subagent
- 15 分钟超时

**学习重点**：
- 理解 `task()` 工具的调用机制
- 查看 `executor.py` 的后台执行引擎
- 尝试一个需要拆解的复杂任务

### 4.2 Memory 系统

**核心文件**：`backend/packages/harness/deerflow/agents/memory/`

跨会话持久记忆，存储在 `memory.json`。

**数据结构**：

```json
{
  "workContext": "...",
  "personalContext": "...",
  "facts": [
    {
      "id": "fact-001",
      "content": "用户偏好使用 Python",
      "category": "preference",
      "confidence": 0.85
    }
  ]
}
```

**工作流**：
1. `MemoryMiddleware` 过滤对话
2. 异步队列（30秒 debounce）
3. LLM 提取 facts
4. 去重后写入 memory.json
5. 下次对话注入到 prompt

**学习重点**：
- 理解 fact 提取的 prompt 设计
- 查看 memory 更新的去重逻辑
- 尝试多轮对话观察 memory 的积累

### 4.3 MCP 集成

**核心文件**：`backend/packages/harness/deerflow/mcp/`

支持 Model Context Protocol，扩展工具生态。

**传输类型**：
- `stdio`：通过命令启动本地进程
- `SSE`：Server-Sent Events
- `HTTP`：标准 HTTP API

**OAuth 支持**：HTTP/SSE server 支持 `client_credentials` 和 `refresh_token` 流程。

**学习重点**：
- 配置一个 MCP Server（如 github）
- 理解 lazy initialization + mtime cache invalidation
- 查看 MCP tools 如何被合并到工具集

### 4.4 IM Channels

**核心文件**：`backend/app/channels/`

支持即时通讯平台接入：
- Telegram（Bot API long-polling）
- Slack（Socket Mode）
- 飞书/Lark（WebSocket）
- 企业微信智能机器人（WebSocket）

**特点**：无需公网 IP，WebSocket/long-polling 直连。

**命令**：
- `/new`：新对话
- `/status`：查看状态
- `/models`：可用模型
- `/memory`：查看记忆

**学习重点**：
- 理解 `MessageBus` 的 pub/sub 机制
- 查看 `manager.py` 的 thread 管理
- 尝试接入 Telegram 或飞书

---

## 阶段五：实战扩展

### 5.1 自定义 Skills

创建目录：`skills/custom/my-skill/SKILL.md`

```yaml
---
name: 数据分析
description: 使用 Python 进行数据分析
allowed-tools:
    - bash
    - read_file
    - write_file
---

## 工作流程

1. 确认数据文件格式
2. 使用 pandas 加载数据
3. 执行分析任务
4. 输出结果到 /mnt/user-data/outputs/

## 注意事项

- 大文件先用 head 查看结构
- 结果用 markdown 格式输出
```

### 5.2 扩展 Tools

在 `backend/packages/harness/deerflow/community/` 创建新工具：

```python
# my_tool.py
from langchain_core.tools import tool

@tool
def my_custom_tool(query: str) -> str:
    """自定义工具说明"""
    # 实现逻辑
    return result
```

在 `config.yaml` 注册：

```yaml
tools:
  - name: my_custom_tool
    use: deerflow.community.my_tool:my_custom_tool
    group: custom
```

### 5.3 生产部署

**Docker Compose**：

```bash
make up     # 构建并启动生产服务
make down   # 停止并清理
```

**资源规划**：
- 本地体验：4 vCPU + 8 GB
- Docker 开发：4 vCPU + 8 GB + 25 GB SSD
- 生产服务：8 vCPU + 16 GB + 40 GB SSD

**监控**：
- LangSmith 集成（链路追踪）
- Gateway `/health`（健康检查）

---

## 学习资源

**官方文档**：
- README.md / README_zh.md
- ARCHITECTURE.md
- CLAUDE.md（给 Claude Code 的开发指南）
- CONTRIBUTING.md

**代码目录**：
- `backend/docs/`：详细文档
- `backend/packages/harness/deerflow/`：核心框架
- `backend/app/`：应用层
- `skills/public/`：内置 Skills

**推荐顺序**：

1. 先跑起来，体验功能
2. 读 ARCHITECTURE.md，建立全局认知
3. 读 CLAUDE.md，理解开发约定
4. 跟踪一次请求，理解数据流
5. 阅读核心模块代码
6. 尝试扩展（Skills / Tools）

---

## 后续笔记计划

本导学笔记是系列的第一篇，后续将逐一深入各模块：

| 序号 | 主题 | 重点 |
|-----|------|------|
| 02 | Agent 架构详解 | middleware chain、thread state、prompt 组装 |
| 03 | Sandbox 系统深入 | provider pattern、路径映射、隔离机制 |
| 04 | Skills 设计与实践 | 格式规范、加载机制、自定义开发 |
| 05 | LangGraph 运行时 | graph 抽象、SSE 流式、checkpointing |
|| 06 | Subagents 并行执行 | 任务拆解、线程池、结果合并 | ✅ 已完成 |
| 07 | Memory 系统原理 | fact 提取、去重策略、注入机制 |
| 08 | MCP 工具集成 | server 配置、lazy init、OAuth 流程 |
| 09 | IM Channels 实现 | message bus、thread 映射、平台适配 |
| 10 | 生产部署与调优 | Docker Compose、资源规划、监控告警 |

> [!NOTE]
> 本系列笔记将边学边写，预计 2-3 周完成全部内容。