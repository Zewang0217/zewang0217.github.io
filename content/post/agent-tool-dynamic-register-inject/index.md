---
title: "Agent Tool 动态注册、发现、注入：一个工业级方案"
description: "从硬编码写死到动态注册中心+MCP双链路，系统拆解大规模Agent系统的工具管理架构"
date: 2026-07-13
slug: "agent-tool-dynamic-register-inject"
tags:
  - Agent
  - Tool Calling
  - MCP
  - 架构设计
categories:
  - 技术笔记
image: cover.png
---

## 背景：硬编码工具的困境

传统 Agent 的工具调用层，最常见的做法是把工具列表硬编码在代码里：

```python
tools = [get_weather, search_web, send_email, ...]
```

这套模式在小规模场景下还能用，但一旦进入生产环境，问题就暴露出来了：

- **新增工具要改代码、重启服务**，迭代效率极低
- **全量注入导致 Token 爆炸**，工具从几十个增长到几百个后，每一次对话都把全部 Schema 塞进 LLM 上下文
- **模型错选幻觉频发**，工具太多，LLM 选错工具的概率直线上升
- **运维成本高**，无灰度、无权限管控、无熔断

解决方案是建立一套 **动态注册、动态发现、动态注入** 的三位一体机制，覆盖本地插件化工具与 MCP 远程工具两条链路。

---

## 顶层架构设计

### 核心设计目标

1. **动态注册** — 本地文件新增、接口推送、MCP 服务接入三种方式，无需修改 Agent 核心代码
2. **动态发现** — 启动自动扫描存量工具，运行时热感知工具的增删改
3. **动态注入** — 拒绝全量灌入，支持全局常驻、意图匹配、权限过滤、会话指定四种注入模式
4. **双端统一** — Local 和 MCP 工具经注册中心归一化为标准接口，上层无感知
5. **全生命周期管控** — 启用/禁用、灰度、权限、熔断、回滚、审计

### 五大核心模块

![](architecture.png)

*图：五大核心模块与全局流程关系*

1. **ToolRegisterCenter** — 全局唯一注册中心，存储所有工具元数据、Schema、来源类型、分组标签、权限白名单、启用状态
2. **LocalToolPluginLoader** — 本地工具插件加载器，扫描、解析、实例化、注册
3. **MCPClientPool** — MCP 客户端连接池，维护远程服务长连接，主动拉取工具列表
4. **ToolOrchestrator** — 调用网关，统一拦截、路由、容错
5. **AgentInjector** — 注入控制器，按会话维度筛选工具子集

### 全局流程

```
工具新增 → 注册中心录入元数据
         → 发现模块感知变更，更新内存索引
         → 注入控制器按需筛选工具集合
         → 封装 Function Calling Schema 送入 LLM
         → Agent 发起调用
         → 网关路由分发至本地执行器或 MCP RPC
         → 结果标准化回执
         → 会话结束后回收临时注入工具
```

---

## 第一链路：本地 Local 工具

### 动态注册

约定一个固定插件目录 `./tools/plugins/`，开发者只需新建 Python 文件、继承基类、加上注册注解，零侵入注册。

```python
# base_tool.py — 基础父类与注册中心

class ToolRegisterCenter:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls.tool_registry: dict[str, ToolMeta] = {}
            cls.group_index: dict[str, list[str]] = {}
            cls.version: int = 0
        return cls._instance

    def register(self, meta: "ToolMeta"):
        if meta.name in self.tool_registry:
            raise Exception(f"工具 {meta.name} 重复注册")
        self.tool_registry[meta.name] = meta
        self.group_index.setdefault(meta.group, []).append(meta.name)
        self.version += 1


class ToolMeta:
    name: str          # 全局唯一
    description: str
    schema: dict       # Function Calling Schema
    source: str = "local"
    group: str         # 业务分组
    enabled: bool = True
    permission: list[str]


# 注册装饰器
def register_tool(group: str, permission: list):
    def decorator(cls):
        meta = ToolMeta(
            name=cls.tool_name,
            description=cls.tool_desc,
            schema=cls.build_schema(),
            group=group,
            permission=permission
        )
        ToolRegisterCenter().register(meta)
        return cls
    return decorator
```

开发者侧的使用方式：

```python
@register_tool(group="text", permission=["user", "admin"])
class TextSummaryTool(BaseLocalTool):
    tool_name = "text_extract_summary"
    tool_desc = "对长文本进行精简摘要"

    @classmethod
    def build_schema(cls):
        return {
            "type": "function",
            "function": {
                "name": cls.tool_name,
                "description": cls.tool_desc,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"}
                    },
                    "required": ["content"]
                }
            }
        }

    def run(self, params: dict) -> dict:
        return {"ok": True, "data": {"summary": params["content"][:300]}}
```

### 启动时批量发现

`LocalToolPluginLoader` 在初始化阶段递归遍历插件目录，动态 import 所有 `.py` 文件，触发装饰器自动执行注册：

```python
class LocalToolPluginLoader:
    def scan_and_register(self, plugin_root: str):
        for path in Path(plugin_root).rglob("*.py"):
            if path.name == "__init__.py":
                continue
            spec = importlib.util.spec_from_file_location(path.stem, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # 触发装饰器 → 自动注册
```

### 运行时热发现

基于 `watchdog` 监听插件目录文件变更：

| 事件 | 行为 |
|------|------|
| 新增 `.py` | 动态导入 → 触发注册 |
| 修改 `.py` | 删除旧注册 → 重新导入覆盖 |
| 删除 `.py` | 标记 `enabled=False`，不再注入 |

同时注册中心启动后台定时任务（每 30s），从 Redis 拉取远程配置同步启用/禁用状态，实现集群级同步。

### 动态注入四层策略

注入行为由 `AgentInjector` 统一管控，**永不一次性全量灌入**：

**模式 1：全局常驻注入**

高频基础工具（时间获取、文本清洗等）在 Agent 初始化时永久挂载，每一轮对话默认携带。

```python
class AgentInjector:
    def __init__(self):
        self.global_fixed: list[dict] = []
        center = ToolRegisterCenter()
        for name in center.group_index.get("core", []):
            meta = center.tool_registry[name]
            if meta.enabled:
                self.global_fixed.append(meta.schema)
```

**模式 2：意图驱动动态注入（主流方案）**

每一轮用户 query 进入后，先调轻量意图分类器识别业务标签，匹配分组索引拉取对应工具，合并全局常驻工具后生成**本轮专属工具列表**，会话结束自动销毁。

```python
def inject_by_intent(self, query: str, role: str) -> list[dict]:
    tags = self.classifier.predict(query)
    tools = self.global_fixed.copy()

    for tag in tags:
        for name in self.center.group_index.get(tag, []):
            meta = self.center.tool_registry[name]
            if meta.enabled and role in meta.permission:
                tools.append(meta.schema)

    return deduplicate(tools)
```

意图分类器推荐**双阶段混合**架构：

- **阶段 1（高速）**：正则规则匹配（如 `/订单/` → `order`）
- **阶段 2（兜底）**：轻量 BERT 模型 ONNX Runtime 部署

命中正则直接返回，未命中才走模型，延迟控制在 5ms 以内。

**模式 3：权限过滤注入**

注入前校验用户角色是否在工具 `permission` 白名单内，防止越权调用高危工具。

**模式 4：会话手动指定注入**

多 Agent 协同场景，上层编排层精确指定工具名数组，注入控制器精准取出，最小化幻觉范围。

### 调用路由

LLM 输出工具调用后，`ToolOrchestrator` 根据工具名匹配注册表，实例化对应类执行 `run()`：

```python
class ToolOrchestrator:
    def dispatch(self, tool_name: str, params: dict, ctx: dict) -> dict:
        center = ToolRegisterCenter()
        if tool_name not in center.tool_registry:
            return {"ok": False, "error": "tool_not_found"}

        meta = center.tool_registry[tool_name]

        # 权限拦截
        if ctx["role"] not in meta.permission:
            return {"ok": False, "error": "permission_denied"}

        # 本地执行
        instance = meta.tool_cls()
        try:
            result = instance.run(params)
            return {"ok": True, "data": result}
        except Exception as e:
            return {"ok": False, "error": str(e)}
```

---

## 第二链路：MCP 远程工具

MCP（Model Context Protocol）原生面向分布式工具治理，Agent 侧客户端主动完成全生命周期感知。

### 顶层角色

- **Host** — Agent 主进程
- **Client** — `MultiServerMCPClient` 连接池
- **Server** — 独立进程或 HTTP 服务，提供工具

### 动态注册

读取 MCP 配置文件，建立连接后通过标准 RPC `list_tools` 拉取全部工具 Schema，归一化为 `ToolMeta` 写入注册中心：

```python
async def connect_all(self, config_path: str):
    configs = json.load(open(config_path))
    for server_id, conf in configs.items():
        client = MCPClient(server_id, conf)
        await client.connect()

        tools = await client.rpc_call("list_tools", {})
        for t in tools:
            meta = ToolMeta(
                name=f"{server_id}_{t['name']}",
                description=t["description"],
                schema=t["inputSchema"],
                source=f"mcp:{server_id}",
                group=conf["group"],
                permission=conf["permission"],
            )
            ToolRegisterCenter().register(meta)
```

配置示例：

```json
{
  "mcp_servers": {
    "order_query": {
      "type": "http",
      "url": "http://127.0.0.1:8002/mcp/v1",
      "group": "mcp_order",
      "permission": ["user", "admin"]
    }
  }
}
```

### 动态发现三大机制

1. **心跳检测断线重连** — 每 10s ping，重连后重新 `list_tools` 增量对比注册表
2. **定时轮询** — 每 60s 对所有存活 Server 拉取 `list_tools`，感知内部增删改
3. **配置热更新** — 监听 Nacos 配置变更，新增 Server 节点自动连接注册，删除则禁用工具

### 注入与调用

MCP 工具注册后与本地工具共用同一个注册中心和 `AgentInjector`，四种注入模式完全复用。唯一区别在网关路由阶段：

```python
# ToolOrchestrator 内 MCP 分支
if meta.source.startswith("mcp:"):
    server_id = meta.source.split(":")[1]
    client = self.mcp_pool.get(server_id)
    if not client:
        return {"ok": False, "error": "mcp_server_offline"}

    resp = await client.rpc_call("call_tool", {
        "name": original_name,
        "arguments": params
    })
    return {"ok": True, "data": resp}
```

---

## 幻觉抑制与边界管控

| 策略 | 做法 |
|------|------|
| 数量硬上限 | 单次注入 ≤ 15 个工具，超出按匹配度截断 |
| 禁用过滤 | `enabled=False` 的工具不进入任何链路 |
| 权限强过滤 | 注入前校验用户角色是否在白名单 |
| 描述强约束 | Schema 的 `description` 写明禁用场景 |
| 负样本注入 | 附带"不要调用以下工具"示例 |
| 注入日志埋点 | 记录每轮注入清单，便于回溯根因 |

---

## 全链路容错

| 场景 | 处理 |
|------|------|
| 工具重名 | 抛出异常，避免静默覆盖 |
| MCP 服务失联 | 自动剔除对应工具，返回标准化提示 |
| 本地插件语法错误 | 跳过该文件，告警但不影响全局启动 |
| 参数校验前置 | 网关调用前做 JSON Schema 校验 |
| 调用超时 | 本地 500ms / MCP 3000ms，超时熔断 |
| 临时注入泄漏 | 会话结束自动清空引用 |

---

## 思考与延伸：从 Tools 到 Skills

这篇文章讨论的是 **Tool（工具）** 的动态管理，但细想一下，这套架构的适用范围远不止工具调用层。

### 一个更深层的问题

当前 Agent 系统面临一个与 Tools 高度相似的问题，发生在 **Skills（技能）** 层面：

| Tools 痛点 | Skills 对应问题 | 当前做法 |
|-----------|----------------|---------|
| 全量工具 Schema 注入 → Token 爆炸 | 所有 Skills 描述列在 prompt 里 | 一次性注入 100+ 条 skill 元信息 |
| 工具太多 → LLM 选错 | Skills 太多 → Agent 可能忽略正确 skill | 依赖模型注意力，无保障 |
| 新增工具需重启注册 | 新增 skill 自动可用 | 已解决（skills 文件即注册） |

文章中的"意图驱动动态注入"思路完全可以迁移过来：

### Skills 动态注入架构设想

```
用户 query
    │
    ▼
轻量意图分类器（关键词 + embedding 双阶段）
    │
    ├─ 置信度高 → 只注入 Top-3/5 匹配 skills → prompt 节省 80%+
    │
    └─ 置信度低 → 退化为全量 skill 列表（兜底）
```

**关键组件：**

1. **Skill 元数据增强** — 每个 skill 除了 `name`/`description`，增加 `keywords` 字段（如 `tdd, unittest, pytest`）和 `domain` 分类（如 `development`, `devops`, `design`），为分类器提供结构化特征。

2. **双阶段分类器** — 与文章中的工具分类器同构：
   - **阶段 1（高速）**：关键词匹配用户 query → 命中 skills 名称/关键词/描述
   - **阶段 2（兜底）**：embedding 向量相似度，匹配不中 keywords 但语义相近的 skills

3. **全局常驻 Skills** — 一小部分基础 skills 永远在 prompt 里：
   - 记忆管理（`memory-management`）
   - Skills 搜索入口（`find-skills`）
   - 全局开发规范（`dev-style`）

4. **Skills Hub 作为"远程注册中心"** — 本地 skills 类似 Local 工具，skills.sh 上的远程 skills 类似 MCP 工具。需要时才拉取，不用本地囤积。

### 与本文架构的对应关系

| 本文工具架构 | Skills 映射 |
|-------------|------------|
| ToolRegisterCenter | Skills 元数据索引 |
| Intent-based injection | 用户 query → skill 匹配 |
| 全局常驻工具 | 全局常驻 skills |
| 权限过滤 | 项目上下文/用户偏好过滤 |
| 数量硬上限（15个） | Top-K 技能数限制 |

这套迁移告诉我们一件事：**"按需注入"不是工具层的专属模式，而是 Agent 系统处理大量可选项时的通用范式。** 无论可选项是工具、技能、知识库文档还是 API 端点，当候选集超过模型的有效注意力范围时，就需要一个前置的分类/检索层来缩小范围。

---

## 总结

这套架构的核心思路可以用一句话概括：**所有工具统一注册中心，按需注入，分层隔离**。

- 本地工具靠**插件目录 + 注解 + 文件监听**实现零侵入上线
- MCP 工具靠 **list_tools 协议 + 心跳轮询 + 配置热更**实现自动发现
- 注入层靠**意图分类 + 权限过滤 + 数量硬限**抑制幻觉
- 调用层靠**统一网关**实现路由、容错、审计统一收口

这套方案不只是面试题的答案，它是生产环境大规模 Agent 系统真正在用的架构模式。
