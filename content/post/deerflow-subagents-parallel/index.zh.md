---
title: "DeerFlow Subagents 并行执行：任务委派、线程池与取消机制"
description: "深入剖析 DeerFlow 的 Subagents 系统，包括 SubagentConfig 配置定义、SubagentExecutor 执行引擎、task_tool 委派入口、三层线程池架构、超时控制与协作式取消机制"
date: 2026-04-21
slug: "deerflow-subagents-parallel"
tags:
    - AI
    - Agent
    - Subagent
    - DeerFlow
    - 并发编程
categories:
    - 技术笔记
---

## 背景

在前几篇笔记中，我们分析了 Agent 架构、Sandbox 系统、Skills 机制、Tools 工具集和 LangGraph 运行时。这些组件定义了单个 Agent 的能力边界和执行方式。

但真实场景中，复杂任务往往需要**拆解并行执行**。比如：
- 同时调研三个不同主题，最后合并结论
- 一个 Agent 负责探索代码结构，另一个负责编写实现
- 执行冗长的构建命令，同时保持主对话不被阻塞

DeerFlow 的答案是 **Subagents 系统**——一个完整的任务委派框架：

```
┌──────────────────────────────────────────────────┐
│              Lead Agent (主代理)                  │
│                                                  │
│   task_tool → "帮我调研 X、Y、Z 三个方向"         │
│       ↓                                          │
└──────────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────────┐
│          Subagent Executor (执行引擎)            │
│                                                  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
│  │ Agent X │  │ Agent Y │  │ Agent Z │          │
│  │(独立线程)│  │(独立线程)│  │(独立线程)│          │
│  └─────────┘  └─────────┘  └─────────┘          │
│                                                  │
│  ThreadPoolExecutor (max 3 并发)                 │
└──────────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────────┐
│          Background Tasks Store                  │
│                                                  │
│  task_id → SubagentResult (状态、结果、消息)     │
└──────────────────────────────────────────────────┘
```

核心文件位于：`backend/packages/harness/deerflow/subagents/`

> [!NOTE]
> 本篇是 DeerFlow 学习系列的第 6 篇。建议先阅读：
> - [DeerFlow 导学路线](../deerflow-learning-guide)
> - [DeerFlow Agent 架构](../deerflow-agent-architecture)
> - [DeerFlow Tools 工具集](../deer-flow-series-tools)

---

## 架构总览

### 目录结构

```
deerflow/subagents/
├── __init__.py              # 公共 API 导出
├── config.py                # SubagentConfig 定义
├── registry.py              # 内置 Subagent 注册表
├── executor.py              # SubagentExecutor 执行引擎（核心）
└── builtins/
    ├── __init__.py          # BUILTIN_SUBAGENTS 注册表
    ├── general_purpose.py   # general-purpose Subagent
    └── bash_agent.py        # bash Subagent
```

### 核心概念关系

```
┌─────────────────────────────────────────────────────┐
│                 SubagentConfig                       │
│  (配置：名称、描述、工具过滤、超时、max_turns)        │
└─────────────────────────────────────────────────────┘
                        ↓ 注册
┌─────────────────────────────────────────────────────┐
│                 Registry                              │
│  BUILTIN_SUBAGENTS = {"general-purpose", "bash"}     │
│  + config.yaml 覆盖（timeout、max_turns）            │
└─────────────────────────────────────────────────────┘
                        ↓ 获取
┌─────────────────────────────────────────────────────┐
│                 task_tool                             │
│  @tool("task")                                        │
│  参数：description, prompt, subagent_type            │
└─────────────────────────────────────────────────────┘
                        ↓ 创建
┌─────────────────────────────────────────────────────┐
│                 SubagentExecutor                      │
│  创建独立 Agent、过滤工具、执行任务                   │
│  ThreadPoolExecutor 后台运行 + 超时控制              │
└─────────────────────────────────────────────────────┘
                        ↓ 存储
┌─────────────────────────────────────────────────────┐
│                 _background_tasks                     │
│  Dict[task_id, SubagentResult]                       │
│  状态：PENDING → RUNNING → COMPLETED/FAILED/TIMED_OUT │
└─────────────────────────────────────────────────────┘
```

---

## SubagentConfig：配置定义

**文件**：`config.py`

```python
@dataclass
class SubagentConfig:
    """Subagent 的配置定义"""
    
    name: str                          # 唯一标识符
    description: str                   # 委派时机描述（LLM 决策依据）
    system_prompt: str                 # 系统提示词
    
    tools: list[str] | None = None     # 允许的工具列表（None=继承全部）
    disallowed_tools: list[str] = ["task"]  # 禁止的工具（防止递归）
    
    model: str = "inherit"             # 模型选择（"inherit"=继承父 Agent）
    max_turns: int = 50                # 最大轮次限制
    timeout_seconds: int = 900         # 超时时间（默认 15 分钟）
```

### 关键字段解析

| 字段 | 用途 | 设计考量 |
|------|------|----------|
| `name` | 标识符，task_tool 参数 | 简短、语义明确 |
| `description` | 告诉 LLM何时委派 | 嵌入在 task_tool docstring |
| `system_prompt` | 子 Agent 行为指导 | 包含工作目录、输出格式要求 |
| `tools` | 工具白名单 | bash Agent 只保留沙箱工具 |
| `disallowed_tools` | 工具黑名单 | **必须禁止 task，防止无限递归** |
| `model` | 模型选择 | "inherit" 避免配置复杂性 |
| `max_turns` | Agent 循环限制 | 防止无限循环消耗资源 |
| `timeout_seconds` | 执行超时 | 15 分钟上限，防止任务卡死 |

---

## 内置 Subagents

DeerFlow 提供两个内置 Subagent：

### general-purpose（通用型）

**文件**：`builtins/general_purpose.py`

```python
GENERAL_PURPOSE_CONFIG = SubagentConfig(
    name="general-purpose",
    description="""A capable agent for complex, multi-step tasks...
    
Use when:
- Task requires both exploration and modification
- Complex reasoning needed
- Multiple dependent steps
""",
    system_prompt="""You are a general-purpose subagent...

<guidelines>
- Focus on completing delegated task efficiently
- Think step by step but act decisively
- Do NOT ask for clarification - work with provided information
</guidelines>

<output_format>
1. Brief summary of accomplishments
2. Key findings or results
3. Relevant file paths, data, artifacts
4. Issues encountered
5. Citations: [citation:Title](URL)
</output_format>

<working_directory>
- User uploads: /mnt/user-data/uploads
- User workspace: /mnt/user-data/workspace
- Output files: /mnt/user-data/outputs
</working_directory>
""",
    tools=None,  # 继承父 Agent 所有工具
    disallowed_tools=["task", "ask_clarification", "present_files"],
    max_turns=100,  # 允许更多轮次处理复杂任务
)
```

**特点**：
- 继承全部工具（除了 task、clarification、present_files）
- 100 轮次上限，适合复杂推理
- 输出格式标准化（摘要、结果、引用）

### bash（命令专家）

**文件**：`builtins/bash_agent.py`

```python
BASH_AGENT_CONFIG = SubagentConfig(
    name="bash",
    description="""Command execution specialist...

Use when:
- Running series of related bash commands
- Terminal operations: git, npm, docker
- Command output is verbose (isolate from main context)
""",
    system_prompt="""You are a bash command specialist...

<guidelines>
- Execute commands one at a time when dependent
- Use parallel execution when independent
- Report both stdout and stderr
- Be cautious with destructive operations
</guidelines>
""",
    tools=["bash", "ls", "read_file", "write_file", "str_replace"],
    disallowed_tools=["task", "ask_clarification", "present_files"],
    max_turns=60,
)
```

**特点**：
- 只保留沙箱工具，精简能力
- 60 轮次上限
- **安全限制**：仅在 `is_host_bash_allowed()` 时可用

> [!WARNING]
> bash Subagent 在本地模式（无 Docker 沙箱）默认禁用，防止宿主机命令执行风险。

### Registry 与配置覆盖

**文件**：`registry.py`

```python
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
}

def get_subagent_config(name: str) -> SubagentConfig | None:
    """获取配置，应用 config.yaml 覆盖"""
    config = BUILTIN_SUBAGENTS.get(name)
    if config is None:
        return None
    
    # 应用 config.yaml 的超时和 max_turns 覆盖
    app_config = get_subagents_app_config()
    effective_timeout = app_config.get_timeout_for(name)
    effective_max_turns = app_config.get_max_turns_for(name, config.max_turns)
    
    if effective_timeout != config.timeout_seconds:
        overrides["timeout_seconds"] = effective_timeout
    if effective_max_turns != config.max_turns:
        overrides["max_turns"] = effective_max_turns
    
    return replace(config, **overrides)
```

**设计亮点**：
- 默认值在代码中定义（清晰可读）
- 运行时可通过 config.yaml 调整（灵活部署）
- 使用 `dataclasses.replace()` 避免修改原对象

---

## task_tool：委派入口

**文件**：`tools/builtins/task_tool.py`

task_tool 是 Lead Agent 调用 Subagent 的入口：

```python
@tool("task", parse_docstring=True)
async def task_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,      # 3-5 词简短描述
    prompt: str,           # 详细任务描述
    subagent_type: str,    # "general-purpose" 或 "bash"
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_turns: int | None = None,  # 可选覆盖
) -> str:
    """Delegate a task to a specialized subagent...
    
    Args:
        description: Short (3-5 word) description. ALWAYS FIRST.
        prompt: Task description for subagent. ALWAYS SECOND.
        subagent_type: Type of subagent. ALWAYS THIRD.
    """
```

### 执行流程

```
task_tool 被调用
    ↓
① 获取 SubagentConfig（应用 config.yaml 覆盖）
    ↓
② 注入 Skills prompt（如启用）
    ↓
③ 创建 SubagentExecutor（工具过滤、父 Agent 状态传递）
    ↓
④ execute_async() 启动后台任务
    ↓
⑤ 轮询 _background_tasks 获取状态
    ↓
⑥ 发送 SSE 事件（task_started → task_running → task_completed）
    ↓
⑦ 返回结果，清理 task_id
```

### 关键代码片段

```python
# 1. 获取配置
config = get_subagent_config(subagent_type)
if config is None:
    return f"Error: Unknown subagent type '{subagent_type}'"

# 2. 注入 Skills
skills_section = get_skills_prompt_section()
if skills_section:
    config = replace(config, system_prompt=config.system_prompt + "\n\n" + skills_section)

# 3. 创建 Executor
tools = get_available_tools(subagent_enabled=False)  # 禁止递归
executor = SubagentExecutor(
    config=config,
    tools=tools,
    sandbox_state=runtime.state.get("sandbox"),
    thread_data=runtime.state.get("thread_data"),
    thread_id=runtime.context.get("thread_id"),
    trace_id=metadata.get("trace_id"),
)

# 4. 启动后台执行
task_id = executor.execute_async(prompt, task_id=tool_call_id)

# 5. 轮询状态
while True:
    result = get_background_task_result(task_id)
    
    if result.status == SubagentStatus.COMPLETED:
        cleanup_background_task(task_id)
        return f"Task Succeeded. Result: {result.result}"
    
    await asyncio.sleep(5)  # 每 5 秒轮询
```

---

## SubagentExecutor：执行引擎

**文件**：`executor.py`（核心，约 600 行）

### 三层线程池架构

```python
# 全局线程池定义
_scheduler_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-scheduler-")
_execution_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-exec-")
_isolated_loop_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-isolated-")
```

| 线程池 | 用途 | max_workers |
|--------|------|-------------|
| `_scheduler_pool` | 任务调度、超时控制 | 3 |
| `_execution_pool` | Agent 实际执行 | 3 |
| `_isolated_loop_pool` | 独立事件循环执行 | 3 |

**为什么需要三层？**

```
主 Agent 在 async 上下文（LangGraph Server）
    ↓
调用 task_tool（async）
    ↓
不能直接 asyncio.run()——会冲突
    ↓
方案：在独立线程池创建独立事件循环
    ↓
_isolated_loop_pool → asyncio.new_event_loop() → run_until_complete()
```

### SubagentExecutor 类

```python
class SubagentExecutor:
    """Subagent 执行引擎"""
    
    def __init__(self, config, tools, parent_model, sandbox_state, thread_data, thread_id, trace_id):
        # 工具过滤
        self.tools = _filter_tools(tools, config.tools, config.disallowed_tools)
        self.trace_id = trace_id or str(uuid.uuid4())[:8]
    
    def _create_agent(self):
        """创建独立 Agent"""
        model = create_chat_model(name=self.parent_model, thinking_enabled=False)
        middlewares = build_subagent_runtime_middlewares(lazy_init=True)
        
        return create_agent(
            model=model,
            tools=self.tools,
            middleware=middlewares,
            system_prompt=self.config.system_prompt,
            state_schema=ThreadState,
        )
    
    def _build_initial_state(self, task: str) -> dict:
        """构建初始状态"""
        state = {"messages": [HumanMessage(content=task)]}
        if self.sandbox_state:
            state["sandbox"] = self.sandbox_state  # 继承沙箱状态
        if self.thread_data:
            state["thread_data"] = self.thread_data
        return state
```

### execute_async：后台执行

```python
def execute_async(self, task: str, task_id: str | None = None) -> str:
    """启动后台任务"""
    
    task_id = task_id or str(uuid.uuid4())[:8]
    result = SubagentResult(
        task_id=task_id,
        trace_id=self.trace_id,
        status=SubagentStatus.PENDING,
    )
    
    _background_tasks[task_id] = result
    
    def run_task():
        # 更新状态为 RUNNING
        _background_tasks[task_id].status = SubagentStatus.RUNNING
        
        # 提交到执行池，带超时
        execution_future = _execution_pool.submit(self.execute, task, result_holder)
        
        try:
            exec_result = execution_future.result(timeout=self.config.timeout_seconds)
            # 更新结果
            _background_tasks[task_id].status = exec_result.status
            _background_tasks[task_id].result = exec_result.result
        except FuturesTimeoutError:
            # 超时处理
            _background_tasks[task_id].status = SubagentStatus.TIMED_OUT
            result_holder.cancel_event.set()
    
    _scheduler_pool.submit(run_task)
    return task_id
```

### _aexecute：异步核心

```python
async def _aexecute(self, task: str, result_holder: SubagentResult) -> SubagentResult:
    """核心异步执行"""
    
    agent = self._create_agent()
    state = self._build_initial_state(task)
    run_config = {"recursion_limit": self.config.max_turns}
    
    # 流式执行，收集 AI 消息
    async for chunk in agent.astream(state, config=run_config, stream_mode="values"):
        # 协作式取消检查
        if result_holder.cancel_event.is_set():
            result_holder.status = SubagentStatus.CANCELLED
            return result_holder
        
        # 提取 AI 消息
        messages = chunk.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage):
            result_holder.ai_messages.append(messages[-1].model_dump())
    
    # 提取最终结果
    last_ai_message = find_last_ai_message(final_state)
    result_holder.result = extract_text_content(last_ai_message)
    result_holder.status = SubagentStatus.COMPLETED
    
    return result_holder
```

---

## SubagentResult：状态容器

```python
@dataclass
class SubagentResult:
    """Subagent 执行结果"""
    
    task_id: str                           # 任务 ID
    trace_id: str                          # 分布式追踪 ID
    status: SubagentStatus                 # 当前状态
    
    result: str | None = None              # 最终结果文本
    error: str | None = None               # 错误信息
    ai_messages: list[dict] | None = None  # AI 消息记录（用于 SSE 推送）
    
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    cancel_event: threading.Event = field(default_factory=threading.Event)
```

### SubagentStatus 状态流转

```python
class SubagentStatus(Enum):
    PENDING = "pending"      # 已创建，等待执行
    RUNNING = "running"      # 正在执行
    COMPLETED = "completed"  # 成功完成
    FAILED = "failed"        # 执行失败
    CANCELLED = "cancelled"  # 用户取消
    TIMED_OUT = "timed_out"  # 超时终止
```

状态流转图：

```
PENDING → RUNNING → COMPLETED（正常）
                ↘ FAILED（异常）
                ↘ TIMED_OUT（超时）
                ↘ CANCELLED（取消）
```

---

## 超时控制

### 双重超时机制

```python
# 1. ThreadPoolExecutor 超时
execution_future.result(timeout=self.config.timeout_seconds)

# 2. task_tool 轮询超时（兜底）
max_poll_count = (config.timeout_seconds + 60) // 5
if poll_count > max_poll_count:
    return "Task polling timed out..."
```

**为什么需要双重？**

- ThreadPoolExecutor 超时依赖线程可被中断
- 但 Python 线程无法强制终止（只能协作式）
- 轮询超时作为安全网，防止任务卡死无响应

### 超时后的清理

```python
except FuturesTimeoutError:
    # 设置取消标志（协作式）
    result_holder.cancel_event.set()
    # 取消 Future（可能无效）
    execution_future.cancel()
    # 更新状态
    _background_tasks[task_id].status = SubagentStatus.TIMED_OUT
```

---

## 取消机制

### 协作式取消（Cooperative Cancellation）

Python 线程无法被外部强制终止，DeerFlow 采用协作式取消：

```python
# 设置取消标志
def request_cancel_background_task(task_id: str):
    result = _background_tasks.get(task_id)
    if result:
        result.cancel_event.set()

# Subagent 检查标志
async for chunk in agent.astream(...):
    if result_holder.cancel_event.is_set():
        result_holder.status = SubagentStatus.CANCELLED
        return result_holder
```

**取消时机**：
- 每次 `astream()` 迭代边界检查
- 长时间工具调用无法中断（需等待下一轮）

### CancelledError 处理

```python
# task_tool 捕获取消
except asyncio.CancelledError:
    request_cancel_background_task(task_id)
    
    # 安排延迟清理
    async def cleanup_when_done():
        while result.status not in TERMINAL_STATES:
            await asyncio.sleep(5)
        cleanup_background_task(task_id)
    
    asyncio.create_task(cleanup_when_done())
    raise  # 传播取消信号
```

---

## SSE 事件推送

task_tool 通过 `get_stream_writer()` 推送实时状态：

```python
writer = get_stream_writer()

# 任务启动
writer({"type": "task_started", "task_id": task_id, "description": description})

# 实时消息
for message in result.ai_messages[last_count:]:
    writer({
        "type": "task_running",
        "task_id": task_id,
        "message": message,
        "message_index": i + 1,
    })

# 任务完成
writer({"type": "task_completed", "task_id": task_id, "result": result.result})
```

前端收到 SSE 事件后，可实时展示 Subagent 的思考过程。

---

## 并发限制

```python
MAX_CONCURRENT_SUBAGENTS = 3  # 全局最大并发数
```

**限制来源**：
- `_scheduler_pool` max_workers=3
- `_execution_pool` max_workers=3

超过 3 个并发任务时，新任务排队等待。

---

## 工具过滤机制

```python
def _filter_tools(all_tools, allowed, disallowed):
    """过滤工具"""
    
    filtered = all_tools
    
    # 白名单
    if allowed is not None:
        filtered = [t for t in filtered if t.name in set(allowed)]
    
    # 黑名单
    if disallowed is not None:
        filtered = [t for t in filtered if t.name not in set(disallowed)]
    
    return filtered
```

**bash Agent 工具限制**：

```python
tools=["bash", "ls", "read_file", "write_file", "str_replace"]
```

只保留沙箱操作工具，无 MCP、无 web_search。

---

## 递归嵌套防护

**防止 Subagent 创建 Subagent**：

```python
# 1. disallowed_tools 默认包含 "task"
disallowed_tools: list[str] = field(default_factory=lambda: ["task"])

# 2. 创建工具集时显式禁用
tools = get_available_tools(subagent_enabled=False)

# 3. task_tool 检查
available_subagent_names = get_available_subagent_names()
if subagent_type not in available_subagent_names:
    return f"Error: Unknown subagent type..."
```

三层防护确保不会出现无限递归。

---

## 资源清理

```python
def cleanup_background_task(task_id: str):
    """清理已完成的任务"""
    
    result = _background_tasks.get(task_id)
    if result is None:
        return
    
    # 只清理终态任务（避免竞态）
    is_terminal = result.status in {
        SubagentStatus.COMPLETED,
        SubagentStatus.FAILED,
        SubagentStatus.CANCELLED,
        SubagentStatus.TIMED_OUT,
    }
    
    if is_terminal or result.completed_at is not None:
        del _background_tasks[task_id]
```

**何时清理**：
- task_tool 返回前调用
- 延迟清理任务（CancelledError 处理）

---

## 分布式追踪

每个 Subagent 执行携带 `trace_id`：

```python
trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]
```

日志格式：

```
[trace=abc123] Subagent general-purpose starting async execution
[trace=abc123] Task task_id status: running
[trace=abc123] Task task_id completed after 12 polls
```

便于跨线程、跨进程关联日志。

---

## 总结

### 核心设计亮点

| 亮点 | 实现 | 价值 |
|------|------|------|
| 三层线程池 | scheduler/exec/isolated | 解决 async 上下文冲突 |
| 协作式取消 | cancel_event + 迭代检查 | 无法强制终止 Python 线程 |
| 双重超时 | ThreadPoolExecutor + 轮询兜底 | 防止任务卡死 |
| 递归防护 | disallowed_tools + subagent_enabled=False | 防止无限嵌套 |
| 工具过滤 | 白名单/黑名单 | 精简 Agent 能力边界 |
| SSE 推送 | task_running 事件 | 前端实时展示思考过程 |
| 分布式追踪 | trace_id | 跨线程日志关联 |

### 并发模型

```
Lead Agent (async)
    ↓ task_tool
Scheduler Pool (3 threads)
    ↓ submit
Execution Pool (3 threads)
    ↓ 每个线程创建独立事件循环
_isolated_loop_pool → asyncio.new_event_loop()
    ↓
Agent.astream() 流式执行
    ↓
_background_tasks 状态存储
    ↓
task_tool 轮询 → SSE 推送
```

### 与其他组件的关系

```
Subagents
    ├── 依赖 Tools（工具过滤）
    ├── 依赖 Sandbox（状态继承）
    ├── 依赖 LangGraph（Agent 构建）
    ├── 依赖 Memory（不继承，隔离）
    └── 被 task_tool 调用（委派入口）
```

---

## 后续笔记

下一篇将分析 **Memory 系统**——跨会话持久记忆的实现原理。

| 序号 | 主题 | 重点 |
|-----|------|------|
| 07 | Memory 系统原理 | fact 提取、去重策略、注入机制 |

---

## 参考资料

**源码目录**：
- `backend/packages/harness/deerflow/subagents/` — Subagents 核心
- `backend/packages/harness/deerflow/tools/builtins/task_tool.py` — 委派入口

**相关文档**：
- ARCHITECTURE.md
- CLAUDE.md