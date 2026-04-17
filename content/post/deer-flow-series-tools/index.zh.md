---
title: "Deer-Flow Tools 工具集详解"
description: "深入剖析 Deer-Flow 的工具系统架构，包括工具分类、加载机制、内置工具实现和安全机制"
date: 2025-04-17
slug: "deer-flow-series-tools"
tags:
    - Deer-Flow
    - Agent
    - 工具系统
categories:
    - 技术笔记
---

## 背景

Tools 工具集是 Deer-Flow Agent 系统的核心组件之一，负责为 AI Agent 提供与外界交互的能力。通过工具，Agent 可以执行文件操作、调用外部服务、委派子任务等。本文将深入剖析工具系统的设计思路和实现细节。

## 目录结构

工具集的代码位于 `backend/packages/harness/deerflow/tools/` 目录下：

```
deerflow/tools/
├── tools.py                  # 工具加载入口，get_available_tools()
├── builtins/                 # 内置工具实现
│   ├── __init__.py           # 导出 present_file_tool, view_image_tool 等
│   ├── clarification_tool.py # ask_clarification_tool - 用户澄清
│   ├── present_file_tool.py  # present_files - 文件展示
│   ├── view_image_tool.py    # view_image - 图像查看
│   ├── task_tool.py          # task - 子代理任务委派
│   ├── tool_search.py        # tool_search - 延迟工具发现
│   ├── setup_agent_tool.py   # setup_agent - Agent 设置
│   └── invoke_acp_agent_tool.py  # invoke_acp_agent - ACP代理调用
├── skill_manage_tool.py      # skill_manage - 技能管理
└── (其他工具文件)
```

关键文件：
- `tools.py`：工具加载的入口函数 `get_available_tools()`，决定哪些工具可用
- `builtins/`：核心内置工具的实现，不依赖外部配置
- `tool_search.py`：延迟工具发现机制，用于处理大量 MCP 工具

## 工具分类

Deer-Flow 的工具系统将工具分为五大类：

| 分类 | 说明 | 来源 |
|------|------|------|
| **BUILTIN_TOOLS** | 基础工具，始终可用 | 代码内置 |
| **SUBAGENT_TOOLS** | 子代理工具，需显式启用 | 代码内置 |
| **MCP Tools** | MCP 服务器提供的工具 | 外部配置 |
| **ACP Tools** | ACP 代理提供的工具 | 外部配置 |
| **Config Tools** | 用户配置文件定义的工具 | config.yaml |

### BUILTIN_TOOLS

基础工具列表（定义在 `tools.py`）：

```python
BUILTIN_TOOLS = [
    present_file_tool,      # 文件展示给用户
    ask_clarification_tool, # 向用户请求澄清
]
```

这些工具始终加载，不依赖配置。

### SUBAGENT_TOOLS

子代理工具（用于任务委派）：

```python
SUBAGENT_TOOLS = [
    task_tool,  # 委派任务给子代理执行
]
```

默认不暴露给 LLM，需要通过 `subagent_enabled=True` 参数显式启用。这防止了子代理的递归嵌套。

### 条件性内置工具

除了上述固定列表，还有一些工具根据条件加载：

| 工具 | 启用条件 |
|------|----------|
| `skill_manage_tool` | `config.skill_evolution.enabled = True` |
| `view_image_tool` | 模型支持 vision (`model_config.supports_vision`) |
| `tool_search` | `config.tool_search.enabled = True` 且有 MCP 工具 |

## 核心机制

### get_available_tools() 函数

工具加载的核心入口是 `get_available_tools()` 函数，其工作流程如下：

```
┌─────────────────────────────────────────────────────────────┐
│                    get_available_tools()                     │
├─────────────────────────────────────────────────────────────┤
│  1. 加载 Config Tools (from config.yaml)                     │
│     - 按 groups 过滤                                         │
│     - 过滤 host_bash 工具（如果 LocalSandboxProvider）        │
│                                                              │
│  2. 组装 Builtin Tools                                       │
│     - 基础工具: present_file_tool, ask_clarification_tool    │
│     - 条件工具: skill_manage, view_image, tool_search        │
│     - 子代理工具: task_tool (if subagent_enabled)            │
│                                                              │
│  3. 加载 MCP Tools                                           │
│     - 从缓存获取已连接的 MCP 工具                             │
│     - 如果 tool_search 启用 → 注册到 DeferredRegistry        │
│                                                              │
│  4. 加载 ACP Tools                                           │
│     - 构建 invoke_acp_agent_tool                             │
│                                                              │
│  5. 合并返回: loaded + builtin + mcp + acp                   │
└─────────────────────────────────────────────────────────────┘
```

关键代码解析：

```python
def get_available_tools(
    groups: list[str] | None = None,      # 按组过滤工具
    include_mcp: bool = True,             # 是否包含 MCP 工具
    model_name: str | None = None,        # 用于判断 vision 支持
    subagent_enabled: bool = False,       # 是否启用子代理工具
) -> list[BaseTool]:
```

### 延迟工具发现机制

当 MCP 服务器提供大量工具时（可能数十甚至上百个），直接将所有工具 schema 注入 context 会造成：
- Token 消耗过大
- LLM 决策困难（工具太多难以选择）

Deer-Flow 采用 **延迟工具发现** 策略解决这个问题：

**核心设计**：
1. Agent 启动时，MCP 工具只以 **名称列表** 形式出现在 `<available-deferred-tools>` 提示中
2. Agent 只能看到工具名，无法直接调用（缺少参数 schema）
3. Agent 需要通过 `tool_search` 工具搜索并获取完整定义
4. 获取后，工具被 "promote" 为可调用状态

**DeferredToolRegistry 实现**：

```python
class DeferredToolRegistry:
    """延迟工具注册表，支持按正则表达式搜索"""
    
    def search(self, query: str) -> list[BaseTool]:
        """三种搜索模式：
        - "select:Read,Edit" → 精确名称匹配
        - "+slack send" → 名称必须含 slack，按剩余词排序
        - "file read" → 正则匹配 name + description
        """
```

**ContextVar 隔离**：

每个请求有独立的 registry，防止并发请求互相干扰：

```python
_registry_var: contextvars.ContextVar[DeferredToolRegistry | None] = contextvars.ContextVar(
    "deferred_tool_registry", default=None
)

## 内置工具详解

### ask_clarification_tool

用于向用户请求澄清，避免 Agent 在不确定的情况下盲目执行。

```python
@tool("ask_clarification", parse_docstring=True, return_direct=True)
def ask_clarification_tool(
    question: str,
    clarification_type: Literal[
        "missing_info",          # 缺少必要信息
        "ambiguous_requirement", # 需求模糊
        "approach_choice",       # 多种方案可选
        "risk_confirmation",     # 危险操作确认
        "suggestion",            # 建议征求同意
    ],
    context: str | None = None,   # 补充背景
    options: list[str] | None = None,  # 可选项列表
) -> str:
```

**设计亮点**：
- `return_direct=True`：调用后直接返回给用户，中断 Agent 执行
- 实际逻辑由 `ClarificationMiddleware` 处理，工具本身只是触发器

**使用场景**：
| clarification_type | 使用时机 |
|--------------------|----------|
| `missing_info` | 缺少文件路径、URL、参数等 |
| `ambiguous_requirement` | 需求有多种解读方式 |
| `approach_choice` | 有多种实现方案，需用户选择 |
| `risk_confirmation` | 删除文件、修改生产环境等危险操作 |
| `suggestion` | Agent 有建议，需用户确认 |

### task_tool

用于委派任务给子代理执行，实现任务隔离和并行处理。

```python
@tool("task", parse_docstring=True)
async def task_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,      # 简短描述（3-5词）
    prompt: str,           # 详细任务说明
    subagent_type: str,    # 子代理类型
    max_turns: int | None = None,  # 最大轮次
) -> str:
```

**子代理类型**：
- `general-purpose`：通用代理，处理复杂多步骤任务
- `bash`：命令执行专员，仅在 host bash 允许时可用

**防嵌套设计**：

子代理加载工具时会显式禁用子代理工具：

```python
# Subagents should not have subagent tools enabled (prevent recursive nesting)
tools = get_available_tools(model_name=parent_model, subagent_enabled=False)
```

**后台执行机制**：

任务在后台异步执行，主线程轮询状态：

```python
# 启动后台执行
task_id = executor.execute_async(prompt, task_id=tool_call_id)

# 后端轮询（LLM 无需主动轮询）
while True:
    result = get_background_task_result(task_id)
    # 处理状态更新...
```

**流式消息**：

通过 `get_stream_writer()` 发送进度通知：

```python
writer({"type": "task_started", "task_id": task_id, "description": description})
writer({"type": "task_progress", "task_id": task_id, "status": status})
writer({"type": "task_completed", "task_id": task_id, "result": result})
```

### present_file_tool

将文件内容展示给用户，支持分页和格式化。

### view_image_tool

图像查看工具，仅在模型支持 vision 时启用。

### skill_manage_tool

技能管理工具，用于创建、修改、删除自定义技能。启用条件：

```yaml
skill_evolution:
  enabled: true
```

## 安全机制

### Host Bash 执行控制

Deer-Flow 对宿主机 bash 执行有严格的安全控制，防止在不受信任的环境中执行危险操作。

**核心逻辑**：

```python
def is_host_bash_allowed(config=None) -> bool:
    """判断是否允许执行宿主机 bash 命令"""
    # 非 LocalSandboxProvider → 允许（已有隔离）
    if not uses_local_sandbox_provider(config):
        return True
    # LocalSandboxProvider → 需显式配置 allow_host_bash
    return bool(getattr(sandbox_cfg, "allow_host_bash", False))
```

**LocalSandboxProvider 的安全考量**：

`LocalSandboxProvider` 直接在宿主机执行命令，没有隔离边界。因此：

| 场景 | `is_host_bash_allowed()` | 说明 |
|------|--------------------------|------|
| AioSandboxProvider | `True` | 容器隔离，安全 |
| LocalSandboxProvider + 默认配置 | `False` | 禁止，不安全 |
| LocalSandboxProvider + `allow_host_bash: true` | `True` | 显式允许，用户自负责任 |

**影响范围**：

`is_host_bash_allowed()` 控制以下功能：

```python
# 1. 工具加载时过滤
if not is_host_bash_allowed(config):
    tool_configs = [t for t in tool_configs if not _is_host_bash_tool(t)]

# 2. bash 子代理注册
if subagent_type == "bash" and not is_host_bash_allowed():
    return f"Error: {LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE}"
```

### 工具过滤机制

在 `get_available_tools()` 中，工具会经过多层过滤：

```
┌─────────────────────────────────────────────────────────────┐
│                    工具过滤流水线                            │
├─────────────────────────────────────────────────────────────┤
│  1. Group 过滤                                              │
│     - 按配置的 groups 字段筛选                               │
│                                                              │
│  2. 安全过滤                                                 │
│     - LocalSandboxProvider 下过滤 host_bash 工具            │
│                                                              │
│  3. 条件加载                                                 │
│     - skill_manage: skill_evolution.enabled                 │
│     - view_image: model_config.supports_vision              │
│     - tool_search: tool_search.enabled + MCP tools          │
│     - task_tool: subagent_enabled 参数                      │
│                                                              │
│  4. 子代理隔离                                               │
│     - 子代理加载时 subagent_enabled=False                   │
└─────────────────────────────────────────────────────────────┘
```

**_is_host_bash_tool() 判断**：

```python
def _is_host_bash_tool(tool: object) -> bool:
    """识别配置中代表 host-bash 的工具"""
    group = getattr(tool, "group", None)
    use = getattr(tool, "use", None)
    if group == "bash":
        return True
    if use == "deerflow.sandbox.tools:bash_tool":
        return True
    return False
```

### 错误信息

当用户尝试在不允许的场景执行 host bash 时，会收到明确的错误提示：

```python
LOCAL_HOST_BASH_DISABLED_MESSAGE = (
    "Host bash execution is disabled for LocalSandboxProvider because it is not a secure "
    "sandbox boundary. Switch to AioSandboxProvider for isolated bash access, or set "
    "sandbox.allow_host_bash: true only in a fully trusted local environment."
)
```

## 总结

### 核心设计亮点

Deer-Flow 的工具系统设计有以下几个亮点：

**1. 分层加载策略**

```
Config Tools → Builtin Tools → MCP Tools → ACP Tools
```

每一层独立管理，支持按需启用。内置工具始终可用，外部工具依赖配置。

**2. 延迟工具发现**

当 MCP 工具数量庞大时，采用延迟发现机制：
- 启动时只注入工具名称列表
- Agent 通过 `tool_search` 按需获取完整 schema
- 有效控制 token 消耗，避免决策困难

**3. 子代理隔离**

`task_tool` 支持任务委派，但通过 `subagent_enabled=False` 防止递归嵌套：

```python
# 父代理 → 可用 task_tool
tools = get_available_tools(subagent_enabled=True)

# 子代理 → 禁用 task_tool
tools = get_available_tools(subagent_enabled=False)
```

**4. 安全沙箱控制**

`is_host_bash_allowed()` 实现细粒度的安全控制：
- 默认禁止 LocalSandboxProvider 的 host bash
- 需显式配置 `allow_host_bash: true` 才能启用
- 隔离环境 (AioSandboxProvider) 自动允许

### 工具类型速查表

| 类型 | 来源 | 条件加载 | 用途 |
|------|------|----------|------|
| `present_file_tool` | 内置 | 无 | 文件展示 |
| `ask_clarification_tool` | 内置 | 无 | 用户澄清 |
| `task_tool` | 内置 | `subagent_enabled=True` | 任务委派 |
| `view_image_tool` | 内置 | `supports_vision=True` | 图像查看 |
| `skill_manage_tool` | 内置 | `skill_evolution.enabled` | 技能管理 |
| `tool_search` | 内置 | `tool_search.enabled` + MCP | 延迟工具发现 |
| MCP Tools | 外部 | `include_mcp=True` | 外部服务集成 |
| ACP Tools | 外部 | 有 ACP 配置 | ACP 代理调用 |
| Config Tools | 配置 | `groups` 过滤 | 用户自定义 |

### 关键文件索引

| 文件 | 职责 |
|------|------|
| `tools/tools.py` | 工具加载入口 `get_available_tools()` |
| `tools/builtins/` | 内置工具实现 |
| `tools/builtins/tool_search.py` | 延迟工具发现机制 |
| `sandbox/security.py` | 安全控制 `is_host_bash_allowed()` |
| `config/extensions_config.py` | MCP 服务器配置 |

### 下一步学习

Tools 工具集是 Agent 执行能力的基础。接下来建议学习：

1. **Sandbox 沙箱系统**：了解命令执行如何被隔离
2. **MCP 集成**：如何连接外部 MCP 服务器获取更多工具
3. **Subagent 子代理**：深入了解任务委派机制