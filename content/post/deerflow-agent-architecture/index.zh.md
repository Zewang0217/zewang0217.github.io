---
title: "DeerFlow Agent 架构详解：从 Lead Agent 到完整执行链"
description: "深入剖析 DeerFlow 的 Lead Agent 架构设计，包括 ThreadState 状态管理、14 个 Middleware 执行链、动态 Prompt 组装机制等核心组件"
date: 2026-04-14
slug: "deerflow-agent-architecture"
tags:
    - AI
    - Agent
    - LangGraph
    - DeerFlow
    - 架构设计
categories:
    - 技术笔记
---

## 背景

DeerFlow 的 Agent 不是简单的 LLM 调用封装，而是一个精心设计的执行引擎。本文将深入剖析 Lead Agent 的架构，帮助你理解：

- Agent 如何组装（Model + Tools + Prompt + Middleware）
- 状态如何流转（ThreadState 的设计）
- 请求如何被处理（Middleware Chain 的执行顺序）
- Prompt 如何动态生成（Skills、Memory、Subagent 的注入）

核心文件位于：`backend/packages/harness/deerflow/agents/lead_agent/`

---

## Agent 组成结构

### 三大核心组件

`make_lead_agent()` 函数负责组装 Agent：

```python
def make_lead_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    *,
    agent_name: str | None = None,
    available_skills: set[str] | None = None,
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
) -> CompiledStateGraph:
```

Agent 由三部分组成：

```
┌─────────────────────────────────────┐
│           Lead Agent                 │
│  ┌─────────────┬─────────────┬─────┐│
│  │   Model     │   Tools     │Prompt││
│  │ (LLM实例)   │(工具集合)   │(动态) ││
│  └─────────────┴─────────────┴─────┘│
│                                     │
│  + Middleware Chain (14个中间件)    │
└─────────────────────────────────────┘
```

**Model**: LangChain 的 `BaseChatModel` 实例（如 ChatOpenAI）

**Tools**: 工具集合，包括：
- Built-in tools（present_files, ask_clarification）
- Sandbox tools（bash, read_file, write_file）
- Config tools（web_search）
- MCP tools（从 extensions_config.json 加载）

**Prompt**: 动态生成的 system prompt，包含 Skills、Memory、Subagent 指引

### CompiledStateGraph：为什么是单节点图？

Agent 本质是 LangGraph 的 `CompiledStateGraph`：

```python
# create_agent 来自 langchain.agents
from langchain.agents import create_agent

return create_agent(
    model=model,
    tools=tools,
    middleware=middlewares,
    system_prompt=prompt,
    state_schema=ThreadState,
)
```

**你可能疑惑：为什么只有一个节点？**

LangGraph 理论上支持复杂的多节点图（planning → execution → reflection），但 DeerFlow 只用了一个 "agent" 节点。原因如下：

#### 1. ReAct 循环由 LangGraph 内部处理

`create_agent` 是 LangChain 提供的 ReAct agent 构建函数。它内部已经实现了：

```
思考 → 工具调用 → 观察 → 再思考（自动循环）
```

你不需要手动构建这种循环图。LangGraph 会自动：
- 调用 Model 获取 response
- 如果有 tool_calls，执行工具
- 将工具结果追加到 messages
- 再次调用 Model
- 直到 response 没有 tool_calls

所以"单节点"不意味着简单，复杂逻辑在内部循环中。

#### 2. Middleware 模式比多节点图更灵活

| 方案 | 优点 | 缺点 |
|------|------|------|
| 多节点图 | 流程可视化 | 每次修改要改图结构，状态分散，调试困难 |
| Middleware Chain | 动态组合、职责单一、易扩展 | 需要 Middleware 框架支持 |

DeerFlow 选择 Middleware Chain：
- 14 个 Middleware 按需启用/禁用（通过 features 配置）
- 职责单一：每个 Middleware 只做一件事
- 新增功能只需添加新 Middleware，不改图结构
- 执行顺序清晰：注册顺序即执行顺序

#### 3. 状态管理简化

单节点 + ThreadState：
- 只有一个状态容器（`ThreadState`）
- 所有 Middleware 读写同一个状态
- 进出一趟，状态清晰

多节点图意味着：
- 状态在节点间流转
- 需要中间状态字段（如 `planning_result`、`reflection_notes`）
- 调试时很难追踪状态变化

#### 4. Checkpointer 开箱即用

LangGraph 的 checkpointer 提供状态持久化：
- 单节点图也能享受这个功能
- ThreadState 在每次执行前后自动保存
- 支持恢复、回滚、时间旅行调试

#### 5. 为扩展留空间

单节点不排斥未来扩展：
- 可以随时添加 planning、reflection 节点
- Subagent 其实就是一种"多 agent"的变体
- DeerFlow 用 Middleware 模式，比硬编码节点更灵活

**总结**：DeerFlow 选择"单节点 + Middleware Chain"而非"多节点图"，是因为：
1. ReAct 循环已内置，无需手动构建
2. Middleware 比节点更灵活、更易扩展
3. 单一状态容器简化状态管理
4. Checkpointer 自动工作

---

## ThreadState：状态容器

`ThreadState`（`thread_state.py`）是 Agent 的状态容器，继承 `BaseMessageThreadState`：

```python
class ThreadState(BaseMessageThreadState):
    # === Sandbox 执行环境 ===
    sandbox: SandboxInfo | None = None
    sandbox_tools: list[Tool] = field(default_factory=list)
    
    # === 文件系统 ===
    uploaded_files: list[UploadedFileInfo] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)  # 输出文件列表
    
    # === 任务管理（Plan Mode）===
    todos: list[TodoItem] = field(default_factory=list)
    
    # === Subagent 控制 ===
    subagent_limit: SubagentLimitInfo | None = None
    active_subagent_count: int = 0
    
    # === Memory 系统 ===
    memory_save_request: MemorySaveRequest | None = None
    
    # === 其他 ===
    is_streaming: bool = False
    ...
```

### 关键字段说明

| 字段 | 用途 |
|------|------|
| `messages` | 对话历史（继承自 BaseMessageThreadState） |
| `sandbox` | 当前 sandbox 的信息（路径、类型等） |
| `uploaded_files` | 用户上传的文件列表 |
| `artifacts` | Agent 生成的输出文件（用于 present_files） |
| `todos` | 任务清单（Plan Mode 使用） |
| `subagent_limit` | Subagent 并发限制信息 |
| `memory_save_request` | Memory 系统的保存请求 |

### 状态流转

每次请求时，ThreadState 从 LangGraph checkpointer 加载，执行过程中被中间件修改，最后保存回 checkpointer。

---

## Middleware Chain：执行链

DeerFlow 的核心魔力在于 **Middleware Chain**。14 个中间件按顺序执行，每个负责特定功能。

### 注册顺序 vs 执行顺序

注册顺序（`middlewares.py`）：

```python
def get_middlewares() -> list[Middleware]:
    return [
        SandboxMiddleware(),           # 0
        UploadedFilesMiddleware(),     # 1
        SandboxToolsMiddleware(),      # 2
        DanglingToolCallMiddleware(),  # 3
        GuardrailMiddleware(),         # 4
        ToolErrorHandlingMiddleware(), # 5
        SummarizationMiddleware(),     # 6
        TodoMiddleware(),              # 7
        TitleMiddleware(),             # 8
        MemoryMiddleware(),            # 9
        ViewImageMiddleware(),         # 10
        SubagentLimitMiddleware(),     # 11
        LoopDetectionMiddleware(),     # 12
        ClarificationMiddleware(),     # 13 (最后)
    ]
```

### 钩子方法

每个 Middleware 有 6 个钩子：

```python
class Middleware:
    async def before_agent(self, state: ThreadState, agent: CompiledStateGraph) -> ThreadState:
        """Agent 执行前"""
        return state
    
    async def after_agent(self, state: ThreadState, agent: CompiledStateGraph, result: AgentResult) -> tuple[ThreadState, AgentResult]:
        """Agent 执行后"""
        return state, result
    
    async def before_model(self, state: ThreadState, agent: CompiledStateGraph) -> ThreadState:
        """Model 调用前"""
        return state
    
    async def after_model(self, state: ThreadState, agent: CompiledStateGraph, response: BaseModel) -> tuple[ThreadState, BaseModel]:
        """Model 调用后"""
        return state, response
    
    async def wrap_model_call(self, state: ThreadState, agent: CompiledStateGraph, call_next: Callable) -> BaseModel:
        """包装 Model 调用"""
        return await call_next(state)
    
    async def wrap_tool_call(self, state: ThreadState, agent: CompiledStateGraph, tool: Tool, args: dict, call_next: Callable) -> Any:
        """包装 Tool 调用"""
        return await call_next(state, tool, args)
```

### 执行流程

```
用户请求 → LangGraph Server
    │
    ├─► before_agent (所有中间件，顺序 0→13)
    │
    ├─► wrap_model_call (嵌套执行)
    │   │
    │   ├─► before_model (顺序)
    │   │
    │   ├─► LLM 调用
    │   │
    │   ├─► after_model (逆序)
    │   │
    │   └─► Tool 调用（如有）
    │       │
    │       ├─► wrap_tool_call (嵌套)
    │       │   ├─► before_tool_call (不存在，直接 wrap)
    │       │   ├─► Tool 执行
    │       │   ├─► after_tool_call (不存在)
    │       │
    │       └─► 循环直到无 Tool 调用
    │
    ├─► after_agent (所有中间件，逆序 13→0)
    │
    └─► 返回响应
```

### 关键中间件详解

#### SandboxMiddleware (0)

职责：为 Thread 分配 sandbox

```python
async def before_agent(self, state, agent):
    if state.sandbox is None:
        sandbox = await sandbox_provider.acquire(thread_id)
        state.sandbox = SandboxInfo(
            sandbox_id=sandbox.sandbox_id,
            root_path=sandbox.root_path,
            ...
        )
    return state
```

#### ToolErrorHandlingMiddleware (5)

职责：捕获 Tool 执行异常，生成友好错误消息

```python
async def wrap_tool_call(self, state, agent, tool, args, call_next):
    try:
        return await call_next(state, tool, args)
    except Exception as e:
        return f"Tool execution failed: {str(e)}. Please try a different approach."
```

#### MemoryMiddleware (9)

职责：异步保存对话到 Memory 系统

```python
async def after_agent(self, state, agent, result):
    if should_save_memory(state):
        state.memory_save_request = MemorySaveRequest(
            messages=state.messages,
            debounce_seconds=30
        )
    return state, result
```

#### ClarificationMiddleware (13)

职责：处理 `ask_clarification` 工具调用

```python
async def wrap_tool_call(self, state, agent, tool, args, call_next):
    if tool.name == "ask_clarification":
        # 不执行工具，直接抛出 ClarificationRequested 异常
        raise ClarificationRequested(question=args["question"])
    return await call_next(state, tool, args)
```

这个中间件放在最后，确保 clarification 请求能中断执行流程。

---

## Prompt 组装机制

`prompt.py` 的 `apply_prompt_template()` 生成最终 system prompt。

### 模板结构

```python
SYSTEM_PROMPT_TEMPLATE = """
<role>
You are {agent_name}, an open-source super agent.
</role>

{soul}
{memory_context}

<thinking_style>
- Think concisely and strategically...
{subagent_thinking}
</thinking_style>

<clarification_system>
5 种 clarification types + workflow
</clarification_system>

{skills_section}
{deferred_tools_section}
{subagent_section}

<working_directory>
路径映射规则
</working_directory>

<response_style>
回复风格指引
</response_style>

<citations>
引用规范
</citations>

<critical_reminders>
关键提醒
</critical_reminders>
"""
```

### 动态注入组件

#### SOUL.md

Agent 的"个性"定义：

```python
def get_agent_soul(agent_name: str | None) -> str:
    soul = load_agent_soul(agent_name)  # 从 agents_config.yaml 加载
    if soul:
        return f"<soul>\n{soul}\n</soul>\n"
    return ""
```

#### Memory Context

跨会话记忆注入：

```python
def _get_memory_context(agent_name: str | None) -> str:
    memory_data = get_memory_data(agent_name)
    memory_content = format_memory_for_injection(memory_data)
    return f"<memory>\n{memory_content}\n</memory>\n"
```

#### Skills Section

Skills 动态加载 + 缓存：

```python
def get_skills_prompt_section(available_skills: set[str] | None) -> str:
    skills = _get_enabled_skills()  # 从 extensions_config.json 读取
    # 使用 lru_cache 缓存
    return _get_cached_skills_prompt_section(skill_signature, ...)
```

**Skills 缓存机制**：

```python
# 线程异步加载
_enabled_skills_cache: list[Skill] | None = None
_enabled_skills_lock = threading.Lock()

def _refresh_enabled_skills_cache_worker():
    while True:
        skills = _load_enabled_skills_sync()
        with _enabled_skills_lock:
            _enabled_skills_cache = skills

# LRU 缓存 prompt 片段
@lru_cache(maxsize=32)
def _get_cached_skills_prompt_section(...):
    ...
```

#### Subagent Section

动态生成 subagent 指引，包含并发限制：

```python
def _build_subagent_section(max_concurrent: int) -> str:
    n = max_concurrent
    return f"""
**HARD CONCURRENCY LIMIT: MAXIMUM {n} `task` CALLS PER RESPONSE**
- If count ≤ {n}: Launch all in this response
- If count > {n}: Pick the {n} most important sub-tasks
"""
```

### Clarification Types

5 种 clarification 类型：

| 类型 | 用途 | 示例 |
|------|------|------|
| `missing_info` | 缺失关键信息 | "Deploy the app" → 缺少环境信息 |
| `ambiguous_requirement` | 多种理解方式 | "Optimize the code" → 性能 vs 可读性 |
| `approach_choice` | 多种方案可选 | "Add auth" → JWT vs OAuth |
| `risk_confirmation` | 危险操作确认 | 删除文件、修改生产配置 |
| `suggestion` | 建议征询 | "I recommend refactoring..." |

---

## 完整请求生命周期

用一个例子说明完整流程：

**用户请求**："分析这个 PDF 并生成报告"

```
1. LangGraph Server 收到请求
   └─► 从 checkpointer 加载 ThreadState
   
2. before_agent (所有中间件)
   ├─► SandboxMiddleware: 分配 sandbox
   ├─► UploadedFilesMiddleware: 解析上传的 PDF
   ├─► SandboxToolsMiddleware: 注册 sandbox 工具
   └─► ... 其他 before_agent
   
3. wrap_model_call 嵌套执行
   ├─► before_model (顺序)
   │   └─► SummarizationMiddleware: 检查是否需要压缩历史
   │
   ├─► Model 调用 (LLM)
   │   └─► System Prompt 包含: Skills、Memory、uploaded_files
   │   └─► LLM 返回: tool_calls = [read_file("xxx.pdf")]
   │
   ├─► after_model (逆序)
   │   └─► DanglingToolCallMiddleware: 检查 dangling calls
   │
   └─► Tool 执行循环
       ├─► wrap_tool_call
       │   ├─► ToolErrorHandlingMiddleware: 捕获异常
       │   ├─► read_file 执行
       │   └─► 返回 PDF 内容
       │
       ├─► 再次 Model 调用
       │   └─► LLM 返回: write_file("report.md", "...")
       │
       ├─► wrap_tool_call
       │   └─► write_file 执行
       │   └─► state.artifacts.append("report.md")
       │
       ├─► 再次 Model 调用
       │   └─► LLM 返回: present_files(["report.md"])
       │
       ├─► wrap_tool_call
       │   └─► present_files 执行
       │   └─► 返回文件列表给前端
       │
       └─► 无更多 tool_calls，结束循环
   
4. after_agent (所有中间件，逆序)
   ├─► ClarificationMiddleware: 检查是否有 clarification 请求
   ├─► MemoryMiddleware: 请求保存记忆
   ├─► TitleMiddleware: 生成对话标题
   ├─► TodoMiddleware: 更新任务状态
   └─► SandboxMiddleware: 清理 sandbox（如需要）
   
5. 返回响应
   ├─► SSE 流式返回给前端
   └─► ThreadState 保存到 checkpointer
```

---

## 关键设计洞察

### 1. Middleware Chain 的灵活性

中间件模式让功能模块化，易于扩展。新增功能只需添加新中间件，无需修改核心代码。

### 2. 状态驱动的执行

ThreadState 作为单一状态容器，所有中间件读写同一个状态，避免状态分散。

### 3. 动态 Prompt 组装

Prompt 不是静态字符串，而是根据配置动态生成：
- Skills 从 `extensions_config.json` 加载
- Memory 从 `memory.json` 加载
- Subagent section 根据并发限制动态生成

### 4. Skills 缓存优化

Skills 加载使用线程异步 + LRU 缓存：
- 避免每次请求都读取文件
- `mtime` 检测文件变更自动刷新缓存

### 5. Clarification 中断机制

`ClarificationMiddleware` 通过抛出异常中断执行，确保 clarification 请求能立即停止 Agent，等待用户输入。

---

## 扩展建议

如果你想深入理解 Agent 架构，建议：

1. **跟踪一次完整请求**：在 `agent.py` 的 `agent_node()` 加日志，观察每一步
2. **修改中间件顺序**：尝试调整 middleware 注册顺序，观察行为变化
3. **自定义中间件**：创建一个简单的中间件，理解钩子机制
4. **动态 Prompt 实验**：修改 `prompt.py` 的模板，观察 Agent 行为变化

---

## 总结

DeerFlow 的 Lead Agent 是一个精心设计的执行引擎：

- **组装**：Model + Tools + Prompt + Middleware
- **状态**：ThreadState 作为单一状态容器
- **执行**：Middleware Chain 按 hooks 钩子执行
- **Prompt**：动态组装，注入 Skills、Memory、Subagent 指引

理解这个架构，是深入学习 DeerFlow 其他模块（Sandbox、Memory、MCP）的基础。