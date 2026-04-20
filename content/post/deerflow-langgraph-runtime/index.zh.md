---
title: "DeerFlow LangGraph 运行时详解：Run Manager、Worker 与 SSE 流式"
description: "深入剖析 DeerFlow 的 LangGraph 运行时架构，包括 RunManager 状态管理、run_agent 执行引擎、StreamBridge SSE 流式响应、多任务策略与取消机制"
date: 2026-04-21
slug: "deerflow-langgraph-runtime"
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

在前几篇笔记中，我们分析了 Agent 架构、Sandbox 系统、Skills 机制和 Tools 工具集。这些是 DeerFlow 的"静态"组件——定义了 Agent **能做什么**。

本文聚焦"动态"部分：**Agent 如何运行**。核心问题是：

1. 一个对话请求如何变成后台任务？
2. 多个请求同时到达，如何处理冲突？
3. 如何实现 SSE 流式响应，让前端实时看到 Agent 的思考过程？
4. 用户中途断开，任务该继续还是取消？
5. 如何安全地中断正在执行的任务？

DeerFlow 的答案是一个精心设计的 **Runtime 模块**，采用三层架构：

```
┌─────────────────────────────────────────────┐
│            Gateway API (REST)               │
│  POST /threads/{id}/runs  → 创建 Run        │
│  GET  /threads/{id}/runs/stream → SSE      │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│            Run Manager                      │
│  RunRecord 状态管理、多任务策略、取消控制   │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│            Worker + StreamBridge            │
│  run_agent() 执行 + SSE 事件推送           │
└─────────────────────────────────────────────┘
```

核心文件位于：`backend/packages/harness/deerflow/runtime/`

> [!NOTE]
> 本篇是 DeerFlow 学习系列的第 5 篇。建议先阅读：
> - [DeerFlow 导学路线](../deerflow-learning-guide)
> - [DeerFlow Agent 架构](../deerflow-agent-architecture)

---

## 架构总览

### 目录结构

```
deerflow/runtime/
├── __init__.py              # 公共 API 导出
├── runs/
│   ├── manager.py           # RunManager + RunRecord
│   ├── worker.py            # run_agent() 执行引擎
│   └── schemas.py           # RunStatus, DisconnectMode
├── stream_bridge/
│   ├── base.py              # StreamBridge 抽象基类
│   └── memory.py            # MemoryStreamBridge 实现
├── serialization.py         # LangChain 对象序列化
└── store.py                 # LangGraph Store 配置
```

### 三层职责

| 层级 | 模块 | 职责 |
|------|------|------|
| **管理层** | RunManager | RunRecord 创建、状态流转、并发控制、取消机制 |
| **执行层** | worker.run_agent() | Agent 构建与执行、LangGraph 流式、异常处理 |
| **传输层** | StreamBridge | SSE 事件队列、心跳保活、断线重连 |

### 核心数据流

```
用户请求 → Gateway
    ↓
RunManager.create_or_reject()  // 检查冲突、创建 RunRecord
    ↓
asyncio.create_task(run_agent())  // 后台执行
    ↓
run_agent() 构建 Agent → agent.astream() 流式执行
    ↓
每产生一个 chunk → StreamBridge.publish() 入队
    ↓
前端 SSE 连接 → StreamBridge.subscribe() 消费
    ↓
任务完成 → publish_end() → cleanup()
```

---

## Run Manager：状态管理中枢

RunManager 是 Runtime 的"大脑"，负责管理所有 Run 的生命周期。

### RunRecord：单次运行的数据容器

```python
@dataclass
class RunRecord:
    """Mutable record for a single run."""
    
    run_id: str                    # UUID，唯一标识
    thread_id: str                 # 所属对话线程
    assistant_id: str | None       # 关联的 Assistant（可选）
    status: RunStatus              # 当前状态
    on_disconnect: DisconnectMode  # 断开时的行为
    multitask_strategy: str        # 多任务策略：reject/interrupt/rollback
    metadata: dict                 # 用户自定义元数据
    kwargs: dict                   # 传递给 Agent 的参数
    created_at: str                # ISO 时间戳
    updated_at: str                # 最后更新时间
    
    # 内部状态（不可序列化）
    task: asyncio.Task | None      # 后台执行任务
    abort_event: asyncio.Event     # 取消信号
    abort_action: str              # 取消动作：interrupt/rollback
    error: str | None              # 错误信息
```

**设计要点**：

1. `run_id` 用 UUID 确保唯一性
2. `task` 和 `abort_event` 是 **不可序列化** 的运行时状态，用 `repr=False` 排除
3. `metadata` 和 `kwargs` 支持用户传递自定义配置

### RunStatus：状态枚举

```python
class RunStatus(StrEnum):
    pending = "pending"      # 已创建，等待执行
    running = "running"      # 正在执行
    success = "success"      # 成功完成
    error = "error"          # 执行失败
    timeout = "timeout"      # 超时（预留）
    interrupted = "interrupted"  # 用户中断
```

状态流转图：

```
pending → running → success/error/interrupted
         ↑
         └── cancel() 可从 pending/running 转到 interrupted
```

### DisconnectMode：断开行为

```python
class DisconnectMode(StrEnum):
    cancel = "cancel"        # 用户断开 → 立即取消任务
    continue_ = "continue"  # 用户断开 → 后台继续执行
```

默认是 `cancel`，符合大多数场景预期。`continue_` 用于异步任务（如生成报告后发送邮件）。

### RunManager 核心方法

#### 1. create()：创建 Run

```python
async def create(
    self,
    thread_id: str,
    assistant_id: str | None = None,
    *,
    on_disconnect: DisconnectMode = DisconnectMode.cancel,
    metadata: dict | None = None,
    kwargs: dict | None = None,
    multitask_strategy: str = "reject",
) -> RunRecord:
    """Create a new pending run and register it."""
    run_id = str(uuid.uuid4())
    now = _now_iso()
    record = RunRecord(...)
    
    async with self._lock:
        self._runs[run_id] = record
    return record
```

**注意**：所有状态修改都在 `async with self._lock` 下进行，确保并发安全。

#### 2. create_or_reject()：原子性检查与创建

这是最关键的方法，解决 **TOCTOU（Time-of-check to time-of-use）竞态**：

```python
async def create_or_reject(
    self,
    thread_id: str,
    ...,
    multitask_strategy: str = "reject",
) -> RunRecord:
    """Atomically check for inflight runs and create a new one."""
    
    async with self._lock:  # 整个检查+创建在锁内完成
        # 1. 检查是否有正在执行的 Run
        inflight = [r for r in self._runs.values() 
                    if r.thread_id == thread_id 
                    and r.status in (RunStatus.pending, RunStatus.running)]
        
        # 2. 根据策略处理
        if multitask_strategy == "reject" and inflight:
            raise ConflictError(f"Thread {thread_id} already has an active run")
        
        if multitask_strategy in ("interrupt", "rollback") and inflight:
            for r in inflight:
                r.abort_action = multitask_strategy
                r.abort_event.set()
                if r.task and not r.task.done():
                    r.task.cancel()
                r.status = RunStatus.interrupted
        
        # 3. 创建新 Run
        record = RunRecord(...)
        self._runs[run_id] = record
    
    return record
```

**三种 multitask_strategy**：

| 策略 | 行为 | 适用场景 |
|------|------|----------|
| `reject` | 有冲突 → 抛异常 | 默认，防止用户误操作 |
| `interrupt` | 中断旧任务，保留 checkpoint | 用户想重新提问 |
| `rollback` | 中断旧任务，回滚到 pre-run 状态 | 取消整个任务 |

#### 3. cancel()：主动取消

```python
async def cancel(self, run_id: str, *, action: str = "interrupt") -> bool:
    """Request cancellation of a run."""
    async with self._lock:
        record = self._runs.get(run_id)
        if not record or record.status not in (RunStatus.pending, RunStatus.running):
            return False
        
        record.abort_action = action
        record.abort_event.set()        # 触发信号
        if record.task and not record.task.done():
            record.task.cancel()        # 取消 asyncio.Task
        record.status = RunStatus.interrupted
    return True
```

`abort_event` 是关键：Worker 在每次 `astream()` 循环中检查 `abort_event.is_set()`，实现 **优雅中断**。

#### 4. cleanup()：延迟清理

```python
async def cleanup(self, run_id: str, *, delay: float = 300) -> None:
    """Remove a run record after an optional delay."""
    if delay > 0:
        await asyncio.sleep(delay)
    async with self._lock:
        self._runs.pop(run_id, None)
```

默认延迟 300 秒，给迟到的客户端留出重连时间。

---

## Worker：执行引擎

`run_agent()` 是 Agent 执行的核心函数，在后台 `asyncio.Task` 中运行。

### 执行流程概览

```python
async def run_agent(
    bridge: StreamBridge,
    run_manager: RunManager,
    record: RunRecord,
    *,
    checkpointer: Any,
    store: Any | None = None,
    agent_factory: Any,
    graph_input: dict,
    config: dict,
    stream_modes: list[str] | None = None,
    stream_subgraphs: bool = False,
    interrupt_before: list[str] | Literal["*"] | None = None,
    interrupt_after: list[str] | Literal["*"] | None = None,
) -> None:
```

完整流程：

```
1. set_status(running)
2. 记录 pre_run_checkpoint_id（用于 rollback）
3. publish("metadata", {run_id, thread_id})
4. 构建 Agent（注入 Runtime、Checkpointer、Store）
5. 配置 interrupt_before/after
6. 处理 stream_modes → 转为 LangGraph 内部模式
7. agent.astream() 循环 → publish 每个 chunk
8. 处理中断/异常 → set_status 最终状态
9. publish_end() → cleanup()
```

### 关键步骤详解

#### 步骤 1：标记运行状态

```python
await run_manager.set_status(run_id, RunStatus.running)
```

#### 步骤 2：记录 pre-run checkpoint

```python
pre_run_checkpoint_id = None
try:
    config_for_check = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    ckpt_tuple = await checkpointer.aget_tuple(config_for_check)
    if ckpt_tuple is not None:
        pre_run_checkpoint_id = getattr(ckpt_tuple, "config", {}).get("configurable", {}).get("checkpoint_id")
except Exception:
    logger.debug("Could not get pre-run checkpoint_id")
```

这是为 `rollback` 策略预留：中断时可以回滚到 Run 开始前的状态。

#### 步骤 3：构建 Agent

```python
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

# 注入 Runtime context（让 middleware 能访问 thread_id）
runtime = Runtime(context={"thread_id": thread_id}, store=store)
config.setdefault("configurable", {})["__pregel_runtime"] = runtime

runnable_config = RunnableConfig(**config)
agent = agent_factory(config=runnable_config)

# 挂载 checkpointer 和 store
if checkpointer:
    agent.checkpointer = checkpointer
if store:
    agent.store = store
```

**Runtime 注入**：LangGraph 的 Middleware 需要访问 `thread_id`，这里手动注入（langgraph-cli 会自动做，但 Gateway 需要自己处理）。

#### 步骤 4：处理 stream_modes

LangGraph 的 `astream()` 支持多种模式，但 Gateway 需要适配：

```python
_VALID_LG_MODES = {"values", "updates", "checkpoints", "tasks", "debug", "messages", "custom"}

lg_modes: list[str] = []
for m in requested_modes:
    if m == "messages-tuple":
        lg_modes.append("messages")     # 用户请求 "messages-tuple" → 内部用 "messages"
    elif m == "events":
        continue                        # "events" 模式不支持（需要 astream_events）
    elif m in _VALID_LG_MODES:
        lg_modes.append(m)

if not lg_modes:
    lg_modes = ["values"]               # 默认模式
```

**关于 "events" 模式**：

```python
if "events" in requested_modes:
    logger.info("'events' stream_mode not supported in gateway (requires astream_events + checkpoint callbacks). Skipping.")
```

`events` 模式需要 `graph.astream_events()`，它不能同时产生 `values` 快照。LangGraph JS 版通过内部 checkpoint callbacks 实现，但 Python 公共 API 没暴露。

#### 步骤 5：流式循环

```python
if len(lg_modes) == 1 and not stream_subgraphs:
    # 单模式，无 subgraphs：astream 直接 yield chunk
    single_mode = lg_modes[0]
    async for chunk in agent.astream(graph_input, config=runnable_config, stream_mode=single_mode):
        if record.abort_event.is_set():  # 检查中断信号
            logger.info("Run %s abort requested — stopping", run_id)
            break
        sse_event = _lg_mode_to_sse_event(single_mode)
        await bridge.publish(run_id, sse_event, serialize(chunk, mode=single_mode))
else:
    # 多模式或 subgraphs：astream yield tuple
    async for item in agent.astream(graph_input, config=runnable_config, stream_mode=lg_modes, subgraphs=stream_subgraphs):
        if record.abort_event.is_set():
            break
        mode, chunk = _unpack_stream_item(item, lg_modes, stream_subgraphs)
        if mode is None:
            continue
        sse_event = _lg_mode_to_sse_event(mode)
        await bridge.publish(run_id, sse_event, serialize(chunk, mode=mode))
```

**关键点**：
- 每次 chunk 都检查 `abort_event.is_set()`
- `serialize()` 处理 LangChain 对象 → JSON

#### 步骤 6：最终状态处理

```python
if record.abort_event.is_set():
    action = record.abort_action
    if action == "rollback":
        await run_manager.set_status(run_id, RunStatus.error, error="Rolled back by user")
        # TODO(Phase 2): 实现 checkpoint 回滚
        logger.info("Run %s rolled back", run_id)
    else:
        await run_manager.set_status(run_id, RunStatus.interrupted)
else:
    await run_manager.set_status(run_id, RunStatus.success)
```

**rollback 的 TODO**：当前只记录状态，真正的 checkpoint 回滚是 Phase 2 工作。

#### 步骤 7：异常处理

```python
except asyncio.CancelledError:
    # Task 被 cancel() 取消
    action = record.abort_action
    if action == "rollback":
        await run_manager.set_status(run_id, RunStatus.error, error="Rolled back by user")
    else:
        await run_manager.set_status(run_id, RunStatus.interrupted)

except Exception as exc:
    # Agent 执行异常
    error_msg = f"{exc}"
    await run_manager.set_status(run_id, RunStatus.error, error=error_msg)
    await bridge.publish(run_id, "error", {"message": error_msg, "name": type(exc).__name__})

finally:
    await bridge.publish_end(run_id)
    asyncio.create_task(bridge.cleanup(run_id, delay=60))
```

---

## StreamBridge：SSE 流式响应

StreamBridge 解耦了 **生产者**（Worker）和 **消费者**（SSE Endpoint）。

### 抽象接口

```python
class StreamBridge(abc.ABC):
    @abc.abstractmethod
    async def publish(self, run_id: str, event: str, data: Any) -> None:
        """Enqueue a single event for *run_id*."""
    
    @abc.abstractmethod
    async def publish_end(self, run_id: str) -> None:
        """Signal that no more events will be produced."""
    
    @abc.abstractmethod
    def subscribe(self, run_id: str, *, last_event_id: str | None = None, heartbeat_interval: float = 15.0) -> AsyncIterator[StreamEvent]:
        """Async iterator yielding events for *run_id*."""
    
    @abc.abstractmethod
    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        """Release resources for *run_id*."""
```

### StreamEvent 数据结构

```python
@dataclass(frozen=True)
class StreamEvent:
    id: str          # 递增 ID，用于 SSE `id:` 字段
    event: str       # SSE event name: metadata/updates/values/messages/error/end
    data: Any        # JSON payload
```

两个特殊 Sentinel：

```python
HEARTBEAT_SENTINEL = StreamEvent(id="", event="__heartbeat__", data=None)  # 心跳
END_SENTINEL = StreamEvent(id="", event="__end__", data=None)              # 结束
```

### MemoryStreamBridge 实现

内存实现，基于 `asyncio.Condition` 实现生产者-消费者模式。

#### 核心数据结构

```python
@dataclass
class _RunStream:
    events: list[StreamEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    ended: bool = False
    start_offset: int = 0    # 因 buffer overflow 被丢弃的事件数
```

#### publish：入队

```python
async def publish(self, run_id: str, event: str, data: Any) -> None:
    stream = self._get_or_create_stream(run_id)
    entry = StreamEvent(id=self._next_id(run_id), event=event, data=data)
    
    async with stream.condition:
        stream.events.append(entry)
        # buffer 限制：超过 maxsize 删除旧事件
        if len(stream.events) > self._maxsize:
            overflow = len(stream.events) - self._maxsize
            del stream.events[:overflow]
            stream.start_offset += overflow
        stream.condition.notify_all()  # 唤醒等待的消费者
```

**buffer overflow 处理**：保留最近 256 个事件，旧事件被丢弃但 `start_offset` 记录偏移。

#### subscribe：消费

```python
async def subscribe(
    self,
    run_id: str,
    *,
    last_event_id: str | None = None,
    heartbeat_interval: float = 15.0,
) -> AsyncIterator[StreamEvent]:
    stream = self._get_or_create_stream(run_id)
    
    # 解析起始位置（支持 Last-Event-ID 重连）
    async with stream.condition:
        next_offset = self._resolve_start_offset(stream, last_event_id)
    
    while True:
        async with stream.condition:
            # 检查是否落后于 retained buffer
            if next_offset < stream.start_offset:
                logger.warning("subscriber fell behind; resuming from offset %s", stream.start_offset)
                next_offset = stream.start_offset
            
            local_index = next_offset - stream.start_offset
            if 0 <= local_index < len(stream.events):
                # 有事件：取出并前进
                entry = stream.events[local_index]
                next_offset += 1
            elif stream.ended:
                # 已结束：返回 END_SENTINEL
                entry = END_SENTINEL
            else:
                # 无事件：等待或超时返回心跳
                try:
                    await asyncio.wait_for(stream.condition.wait(), timeout=heartbeat_interval)
                except TimeoutError:
                    entry = HEARTBEAT_SENTINEL
                else:
                    continue  # 被唤醒，重新检查
        
        if entry is END_SENTINEL:
            yield END_SENTINEL
            return
        yield entry
```

**关键特性**：

1. **Last-Event-ID 重连**：客户端断开后重连，可从上次位置继续
2. **心跳保活**：15 秒无事件 → 返回 `HEARTBEAT_SENTINEL`，防止连接超时
3. **buffer overflow 处理**：客户端落后太多 → 从当前最早保留事件开始

#### SSE Endpoint 使用示例

```python
# Gateway 路由
@router.get("/threads/{thread_id}/runs/{run_id}/stream")
async def stream_run(thread_id: str, run_id: str, request: Request):
    last_event_id = request.headers.get("Last-Event-ID")
    
    async def generate():
        for event in bridge.subscribe(run_id, last_event_id=last_event_id):
            if event is HEARTBEAT_SENTINEL:
                yield ": heartbeat\n\n"  # SSE comment
            elif event is END_SENTINEL:
                yield "event: end\ndata: {}\n\n"
                return
            else:
                yield f"id: {event.id}\nevent: {event.event}\ndata: {json.dumps(event.data)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

## 序列化：LangChain 对象 → JSON

LangChain/LangGraph 对象（Message、State）不能直接 JSON 序列化，需要特殊处理。

### serialize() 函数

```python
def serialize(obj: Any, *, mode: str = "") -> Any:
    """Serialize LangChain objects with mode-specific handling."""
    
    if mode == "messages":
        # messages-tuple: (chunk, metadata)
        return serialize_messages_tuple(obj)
    
    if mode == "values":
        # values: full state dict，删除内部 __pregel_* keys
        return serialize_channel_values(obj)
    
    return serialize_lc_object(obj)
```

### serialize_lc_object：通用递归

```python
def serialize_lc_object(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: serialize_lc_object(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_lc_object(item) for item in obj]
    
    # Pydantic v2
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # Pydantic v1
    if hasattr(obj, "dict"):
        return obj.dict()
    # Fallback
    return str(obj)
```

### serialize_channel_values：过滤内部键

```python
def serialize_channel_values(channel_values: dict) -> dict:
    result = {}
    for key, value in channel_values.items():
        # 删除 LangGraph 内部键
        if key.startswith("__pregel_") or key == "__interrupt__":
            continue
        result[key] = serialize_lc_object(value)
    return result
```

`__pregel_*` 是 LangGraph 的内部状态键（如 `__pregel_task_id`），不应暴露给前端。

---

## 状态流转与取消机制

### 完整状态流转图

```
                    create()
                      ↓
                  ┌─────────┐
                  │ pending │
                  └─────────┘
                      ↓ set_status(running)
                  ┌─────────┐
                  │ running │ ←─────────────────────┐
                  └─────────┘                        │
           ┌──────────┼──────────┬──────────┐       │
           ↓          ↓          ↓          ↓       │
     ┌─────────┐ ┌─────────┐ ┌───────────┐ ┌──────┐ │
     │ success │ │  error  │ │interrupted│ │timeout│ │
     └─────────┘ └─────────┘ └───────────┘ └──────┘ │
                          ↑                        │
                          │ cancel()               │
                          └────────────────────────┘
```

### 取消机制详解

取消涉及两个层面：

1. **Task 层面**：`asyncio.Task.cancel()` → 抛 `CancelledError`
2. **Agent 层面**：`abort_event.set()` → 在 astream 循环中检测并退出

**为什么需要两种？**

- `Task.cancel()` 是强制中断，Agent 可能正在 LLM 调用中
- `abort_event.set()` 是优雅中断，Agent 可以完成当前 chunk 再退出

DeerFlow 采用 **混合策略**：

```python
async def cancel(self, run_id: str, *, action: str = "interrupt") -> bool:
    record.abort_event.set()        # 先设置信号
    if record.task and not record.task.done():
        record.task.cancel()        # 再取消 Task
```

Worker 处理：

```python
async for chunk in agent.astream(...):
    if record.abort_event.is_set():  # 每次循环检查
        break                        # 优雅退出

except asyncio.CancelledError:       # Task 强制取消
    # 处理状态
```

### interrupt vs rollback

| 动作 | checkpoint 处理 | 适用场景 |
|------|-----------------|----------|
| `interrupt` | 保留当前 checkpoint | 用户想暂停后继续 |
| `rollback` | 回滚到 pre-run checkpoint | 用户想完全取消 |

当前 rollback 实现是 TODO（Phase 2），核心思路：

```python
# Phase 2: 回滚到 pre_run_checkpoint_id
if checkpointer and pre_run_checkpoint_id:
    # 调用 checkpointer.adelete() 或类似 API
    # 删除 run 期间产生的所有 checkpoint
    pass
```

---

## 总结

### 核心设计亮点

1. **三层解耦**：Manager 负责状态、Worker 负责执行、Bridge 负责传输
2. **原子性并发控制**：`create_or_reject()` 在锁内完成检查+创建，避免 TOCTOU
3. **优雅中断**：`abort_event` + `Task.cancel()` 双重机制
4. **SSE 流式**：基于 `asyncio.Condition` 的生产者-消费者模式
5. **断线重连**：`Last-Event-ID` + buffer retention

### 对比：DeerFlow Runtime vs LangGraph Platform API

| 特性 | DeerFlow Runtime | LangGraph Platform |
|------|------------------|-------------------|
| Run 状态管理 | 自定义 RunManager | LangGraph Server 内置 |
| 多任务策略 | reject/interrupt/rollback | 仅 reject |
| SSE 流式 | 自定义 StreamBridge | 内置 Queue + StreamManager |
| 断线重连 | Last-Event-ID + buffer | 同样支持 |
| 取消机制 | interrupt + rollback | 仅 interrupt |
| Checkpoint 回滚 | TODO (Phase 2) | 内置支持 |

### 关键文件索引

| 文件 | 核心类/函数 | 作用 |
|------|------------|------|
| `runs/manager.py` | `RunManager`, `RunRecord` | 状态管理 |
| `runs/worker.py` | `run_agent()` | 执行引擎 |
| `runs/schemas.py` | `RunStatus`, `DisconnectMode` | 状态枚举 |
| `stream_bridge/base.py` | `StreamBridge` | 抽象接口 |
| `stream_bridge/memory.py` | `MemoryStreamBridge` | 内存实现 |
| `serialization.py` | `serialize()` | LangChain → JSON |

### 学习建议

1. **跟踪一次完整请求**：从 Gateway POST → RunManager → Worker → SSE
2. **理解 asyncio 并发**：`Condition`, `Event`, `Task.cancel()` 的配合
3. **尝试并发请求**：观察 `multitask_strategy=reject` 的冲突处理
4. **测试断线重连**：关闭 SSE 连接，用 `Last-Event-ID` 重连

---

## 后续预告

下一篇将深入 **Subagents 并行执行**，包括：
- `task()` 工具的调用机制
- `SubagentExecutor` 的线程池管理
- 并发控制（max 3，timeout 15min）
- 结果合并与错误处理

> [!NOTE]
> 本系列笔记持续更新中，欢迎关注 [Zewang's Blog](https://zewang0217.github.io/) 获取最新内容。