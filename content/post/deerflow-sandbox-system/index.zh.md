---
title: "DeerFlow Sandbox 系统详解：从抽象接口到容器隔离"
description: "深入剖析 DeerFlow 的 Sandbox 执行引擎，包括 Sandbox/SandboxProvider 抽象设计、LocalSandbox 本地模式、AioSandbox 容器隔离、路径映射机制、以及 7 个 Sandbox Tools 的实现"
date: 2026-04-15
slug: "deerflow-sandbox-system"
tags:
    - AI
    - Agent
    - Docker
    - DeerFlow
    - 架构设计
categories:
    - 技术笔记
---

## 背景

Sandbox 是 DeerFlow 的"执行引擎"，让 Agent 真能做事——不只是聊天，还能：

- 执行 bash 命令
- 读写文件
- 搜索文件内容
- 编写代码并运行

核心问题：**如何给 Agent 一个安全、隔离、可重复的执行环境？**

DeerFlow 的答案是 **Sandbox  abstraction + Provider 模式 + 路径映射**：

- `Sandbox`：抽象接口，定义能做什么
- `SandboxProvider`：工厂模式，负责创建和管理 Sandbox 实例
- `LocalSandbox`：本地模式，直接在宿主机执行
- `AioSandbox`：容器模式，隔离的 Docker 环境

---

## 架构总览

### 三层设计

```
┌─────────────────────────────────────────────┐
│           Sandbox Tools (tools.py)          │
│  bash / read_file / write_file / grep / ... │
│           ↑ 调用 Sandbox 实例                │
├─────────────────────────────────────────────┤
│           Sandbox (抽象基类)                 │
│  execute_command / read_file / write_file   │
│  list_dir / glob / grep                     │
├─────────────────────────────────────────────┤
│         SandboxProvider (抽象工厂)          │
│  acquire() / get() / release()              │
├──────────┬──────────┬───────────────────────┤
│ Local    │   Aio    │   (其他实现)           │
│ Provider │ Provider │   K8s/Remote...       │
└──────────┴──────────┴───────────────────────┘
```

### 核心文件位置

| 文件 | 路径 | 职责 |
|------|------|------|
| `sandbox.py` | `deerflow/sandbox/sandbox.py` | Sandbox 抽象基类 |
| `sandbox_provider.py` | `deerflow/sandbox/sandbox_provider.py` | SandboxProvider 抽象工厂 |
| `local_sandbox.py` | `deerflow/sandbox/local/local_sandbox.py` | LocalSandbox 实现 |
| `local_sandbox_provider.py` | `deerflow/sandbox/local/local_sandbox_provider.py` | LocalSandboxProvider 实现 |
| `aio_sandbox.py` | `deerflow/community/aio_sandbox/aio_sandbox.py` | AioSandbox 实现 |
| `aio_sandbox_provider.py` | `deerflow/community/aio_sandbox/aio_sandbox_provider.py` | AioSandboxProvider 实现 |
| `tools.py` | `deerflow/sandbox/tools.py` | 7 个 Sandbox Tools |

---

## Sandbox 抽象基类

`Sandbox` 是抽象基类，定义了所有 Sandbox 必须实现的接口：

```python
class Sandbox(ABC):
    """Abstract base class for sandbox environments"""

    _id: str

    def __init__(self, id: str):
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    # === 7 个抽象方法 ===

    @abstractmethod
    def execute_command(self, command: str) -> str:
        """执行 bash 命令"""
        pass

    @abstractmethod
    def read_file(self, path: str) -> str:
        """读取文件内容"""
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """写入文件"""
        pass

    @abstractmethod
    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """列出目录内容"""
        pass

    @abstractmethod
    def glob(self, path: str, pattern: str, ...) -> tuple[list[str], bool]:
        """glob 模式搜索"""
        pass

    @abstractmethod
    def grep(self, path: str, pattern: str, ...) -> tuple[list[GrepMatch], bool]:
        """文件内容搜索"""
        pass

    @abstractmethod
    def update_file(self, path: str, content: bytes) -> None:
        """更新文件（二进制）"""
        pass
```

### 7 个核心方法

| 方法 | 用途 | Tool 对应 |
|------|------|----------|
| `execute_command` | 执行 bash 命令 | `bash` tool |
| `read_file` | 读取文件内容 | `read_file` tool |
| `write_file` | 写入文件 | `write_file` tool |
| `list_dir` | 列出目录结构 | `ls` tool |
| `glob` | glob 模式匹配 | `glob` tool |
| `grep` | 文件内容搜索 | `grep` tool |
| `update_file` | 二进制写入 | 内部使用 |

> [!NOTE]
> 所有方法都是同步的。AioSandbox 通过 HTTP API 调用远程服务，但接口保持同步语义。

---

## SandboxProvider 抽象工厂

`SandboxProvider` 是工厂模式，负责创建和管理 Sandbox 实例：

```python
class SandboxProvider(ABC):
    """Abstract base class for sandbox providers"""

    @abstractmethod
    def acquire(self, thread_id: str | None = None) -> str:
        """获取 sandbox，返回 sandbox_id"""
        pass

    @abstractmethod
    def get(self, sandbox_id: str) -> Sandbox | None:
        """根据 ID 获取 Sandbox 实例"""
        pass

    @abstractmethod
    def release(self, sandbox_id: str) -> None:
        """释放 sandbox"""
        pass
```

### 生命周期

```
acquire(thread_id) → sandbox_id
    │
    ├─► 如果已存在：返回现有 sandbox_id
    │   （同一 thread_id 复用）
    │
    └─► 如果不存在：创建新 sandbox

get(sandbox_id) → Sandbox 实例
    │
    └─► 用于执行具体操作

release(sandbox_id)
    │
    └─► 释放资源，清理 sandbox
```

### 单例模式

全局单例 + 配置驱动：

```python
_default_sandbox_provider: SandboxProvider | None = None

def get_sandbox_provider(**kwargs) -> SandboxProvider:
    global _default_sandbox_provider
    if _default_sandbox_provider is None:
        config = get_app_config()
        # 从 config.sandbox.use 解析类名
        cls = resolve_class(config.sandbox.use, SandboxProvider)
        _default_sandbox_provider = cls(**kwargs)
    return _default_sandbox_provider
```

**配置示例** (`config.yaml`)：

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider  # 容器模式
  # use: deerflow.sandbox.local:LocalSandboxProvider      # 本地模式
  image: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
  port: 8080
  idle_timeout: 600  # 10分钟无活动自动清理
  replicas: 3        # 最大并发 sandbox 数
```

### 辅助函数

| 函数 | 用途 |
|------|------|
| `get_sandbox_provider()` | 获取单例 |
| `reset_sandbox_provider()` | 重置单例（测试用） |
| `shutdown_sandbox_provider()` | 关闭并清理所有 sandbox |
| `set_sandbox_provider(provider)` | 注入自定义 provider（测试用） |

---

## LocalSandbox：本地模式

LocalSandbox 直接在宿主机执行，适合开发调试。

### PathMapping：路径映射

核心设计是 **虚拟路径 → 本地路径** 的映射：

```python
@dataclass(frozen=True)
class PathMapping:
    container_path: str   # Agent 看到的路径（虚拟）
    local_path: str       # 实际物理路径
    read_only: bool = False
```

**典型映射**：

| 虚拟路径 | 本地路径 | 只读 |
|----------|----------|------|
| `/mnt/skills` | `deer-flow/skills/` | True |
| `/mnt/user-data/workspace` | `.deer-flow/threads/{id}/user-data/workspace` | False |
| `/mnt/custom-mount` | `/home/user/my-data` | 自定义 |

### 双向路径转换

```python
class LocalSandbox(Sandbox):
    def _resolve_path(self, path: str) -> str:
        """虚拟路径 → 本地路径"""
        for mapping in sorted(self.path_mappings, key=lambda m: len(m.container_path), reverse=True):
            if path.startswith(mapping.container_path + "/"):
                relative = path[len(mapping.container_path):].lstrip("/")
                return str(Path(mapping.local_path) / relative)
        return path

    def _reverse_resolve_path(self, path: str) -> str:
        """本地路径 → 虚拟路径"""
        for mapping in sorted(self.path_mappings, key=lambda m: len(m.local_path), reverse=True):
            local_resolved = str(Path(mapping.local_path).resolve())
            if path.startswith(local_resolved + "/"):
                relative = path[len(local_resolved):].lstrip("/")
                return f"{mapping.container_path}/{relative}"
        return path
```

> [!TIP]
> Agent 看到的是虚拟路径，但实际操作的是本地路径。输出结果再转回虚拟路径，保持一致性。

### execute_command 实现

跨平台 shell 检测 + 路径替换：

```python
def execute_command(self, command: str) -> str:
    # 1. 替换命令中的虚拟路径
    resolved_command = self._resolve_paths_in_command(command)
    
    # 2. 检测可用的 shell
    shell = self._get_shell()  # zsh > bash > sh > PowerShell > cmd
    
    # 3. 执行命令
    result = subprocess.run(
        resolved_command,
        executable=shell,
        shell=True,
        capture_output=True,
        text=True,
        timeout=600,  # 10 分钟超时
    )
    
    # 4. 输出中转回虚拟路径
    return self._reverse_resolve_paths_in_output(output)
```

**路径替换逻辑**：

```python
def _resolve_paths_in_command(self, command: str) -> str:
    """用正则替换命令中的虚拟路径"""
    patterns = [re.escape(m.container_path) + r"(?=/|$|\s)" for m in self.path_mappings]
    pattern = re.compile("|".join(f"({p})" for p in patterns))
    return pattern.sub(lambda m: self._resolve_path(m.group(0)), command)
```

例如：`ls /mnt/skills/public/` → `ls /path/to/deer-flow/skills/public/`

### 文件操作方法

```python
def read_file(self, path: str) -> str:
    resolved_path = self._resolve_path(path)
    with open(resolved_path, encoding="utf-8") as f:
        return f.read()

def write_file(self, path: str, content: str, append: bool = False) -> None:
    resolved_path = self._resolve_path(path)
    
    # 检查只读路径
    if self._is_read_only_path(resolved_path):
        raise OSError(errno.EROFS, "Read-only file system", path)
    
    os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
    with open(resolved_path, "a" if append else "w", encoding="utf-8") as f:
        f.write(content)

def glob(self, path: str, pattern: str, ...) -> tuple[list[str], bool]:
    resolved_path = Path(self._resolve_path(path))
    matches, truncated = find_glob_matches(resolved_path, pattern, ...)
    # 转回虚拟路径
    return [self._reverse_resolve_path(m) for m in matches], truncated
```

---

## LocalSandboxProvider：单例工厂

LocalSandboxProvider 使用**单例模式**，所有 thread 共享同一个 sandbox：

```python
_singleton: LocalSandbox | None = None

class LocalSandboxProvider(SandboxProvider):
    def __init__(self):
        self._path_mappings = self._setup_path_mappings()
    
    def acquire(self, thread_id: str | None = None) -> str:
        global _singleton
        if _singleton is None:
            _singleton = LocalSandbox("local", path_mappings=self._path_mappings)
        return _singleton.id  # 永远返回 "local"
    
    def get(self, sandbox_id: str) -> Sandbox | None:
        if sandbox_id == "local":
            return _singleton
        return None
    
    def release(self, sandbox_id: str) -> None:
        # 单例模式，无需清理
        pass
```

### 路径映射配置

从 `config.yaml` 加载映射：

```python
def _setup_path_mappings(self) -> list[PathMapping]:
    mappings: list[PathMapping] = []
    
    # 1. Skills 目录（只读）
    skills_path = config.skills.get_skills_path()
    mappings.append(PathMapping(
        container_path="/mnt/skills",
        local_path=str(skills_path),
        read_only=True,
    ))
    
    # 2. 自定义挂载
    for mount in config.sandbox.mounts:
        mappings.append(PathMapping(
            container_path=mount.container_path,
            local_path=mount.host_path,
            read_only=mount.read_only,
        ))
    
    return mappings
```

**配置示例**：

```yaml
sandbox:
  mounts:
    - host_path: /home/user/projects
      container_path: /mnt/projects
      read_only: false
```

> [!NOTE]
> LocalSandbox 是单例，所有 thread 共享。适合开发，不适合生产（无隔离）。

---

## AioSandbox：容器模式

AioSandbox 通过 HTTP API 连接到 Docker 容器，实现真正的隔离环境。

### 架构

```
┌──────────────────────┐
│    AioSandbox        │
│  (Python 客户端)      │
├──────────────────────┤
│  HTTP API 调用        │
│  ↓                   │
├──────────────────────┤
│  agent-infra/sandbox │
│  (Docker 容器)        │
│  - Shell 执行        │
│  - 文件读写          │
│  - 搜索功能          │
└──────────────────────┘
```

### 初始化

```python
class AioSandbox(Sandbox):
    def __init__(self, id: str, base_url: str, home_dir: str | None = None):
        super().__init__(id)
        self._base_url = base_url
        self._client = AioSandboxClient(base_url=base_url, timeout=600)
        self._home_dir = home_dir
        self._lock = threading.Lock()  # 序列化并发请求
```

> [!WARNING]
> 容器内只有一个持久 shell session。并发请求会互相干扰，需要用 `threading.Lock` 序列化。

### execute_command 实现

```python
def execute_command(self, command: str) -> str:
    with self._lock:
        try:
            result = self._client.shell.exec_command(command=command)
            output = result.data.output if result.data else ""

            # 检测错误签名（并发干扰导致的 ErrorObservation）
            if "ErrorObservation" in output:
                logger.warning("Session corrupted, retrying with fresh session")
                fresh_id = str(uuid.uuid4())
                result = self._client.shell.exec_command(command=command, id=fresh_id)
                output = result.data.output if result.data else ""

            return output if output else "(no output)"
        except Exception as e:
            return f"Error: {e}"
```

### 文件操作

```python
def read_file(self, path: str) -> str:
    result = self._client.file.read_file(file=path)
    return result.data.content if result.data else ""

def write_file(self, path: str, content: str, append: bool = False) -> None:
    with self._lock:
        if append:
            existing = self.read_file(path)
            content = existing + content
        self._client.file.write_file(file=path, content=content)
```

### glob / grep 实现

```python
def glob(self, path: str, pattern: str, ...) -> tuple[list[str], bool]:
    result = self._client.file.find_files(path=path, glob=pattern)
    files = result.data.files or []
    return files[:max_results], len(files) > max_results

def grep(self, path: str, pattern: str, ...) -> tuple[list[GrepMatch], bool]:
    regex = f"(?i){pattern}" if not case_sensitive else pattern
    # 1. 先找候选文件（glob 或 list_path）
    # 2. 逐文件调用 search_in_file
    for file_path in candidate_paths:
        result = self._client.file.search_in_file(file=file_path, regex=regex)
        # 构建 GrepMatch...
    return matches, truncated
```

---

## AioSandboxProvider：容器池管理

AioSandboxProvider 是复杂的容器生命周期管理器，核心特性：

1. **多层缓存**：in-process → warm pool → backend discovery
2. **确定性 ID**：同一 thread_id 总是得到相同 sandbox_id
3. **Warm pool**：release 不销毁容器，下次可快速复用
4. **Idle timeout**：后台线程定期清理空闲容器
5. **Backend 抽象**：支持本地 Docker 和远程 K8s

### 缓存层次

```
acquire(thread_id)
    │
    ├─► Layer 1: in-process cache（最快）
    │   _thread_sandboxes[thread_id] → sandbox_id
    │
    ├─► Layer 1.5: warm pool（容器还在运行）
    │   _warm_pool[sandbox_id] → (info, release_ts)
    │
    └─► Layer 2: backend discovery + create
    │   跨进程文件锁保护
    │   _backend.discover() 或 _backend.create()
```

### 确定性 sandbox_id

```python
@staticmethod
def _deterministic_sandbox_id(thread_id: str) -> str:
    """从 thread_id 生成确定性 sandbox_id"""
    return hashlib.sha256(thread_id.encode()).hexdigest()[:8]
```

**意义**：多个进程访问同一 thread_id 时，生成的 sandbox_id 相同，可以发现对方创建的容器。

### Warm Pool 机制

```python
def release(self, sandbox_id: str) -> None:
    """释放 sandbox 到 warm pool（容器继续运行）"""
    info = self._sandbox_infos.pop(sandbox_id)
    self._sandboxes.pop(sandbox_id)
    
    # 不销毁容器，放入 warm pool
    if info:
        self._warm_pool[sandbox_id] = (info, time.time())

def acquire(self, thread_id: str) -> str:
    # 先检查 warm pool
    if sandbox_id in self._warm_pool:
        info, _ = self._warm_pool.pop(sandbox_id)
        sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
        self._sandboxes[sandbox_id] = sandbox
        return sandbox_id  # 无冷启动
```

**效果**：下次访问同一 thread 时，直接从 warm pool 取回，无需创建新容器。

### 跨进程文件锁

```python
def _discover_or_create_with_lock(self, thread_id: str, sandbox_id: str) -> str:
    lock_path = paths.thread_dir(thread_id) / f"{sandbox_id}.lock"
    
    with open(lock_path, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)  # 跨进程锁
        
        # 再次检查缓存（可能其他进程刚创建）
        discovered = self._backend.discover(sandbox_id)
        if discovered:
            return discovered.sandbox_id
        
        # 确实需要创建
        return self._create_sandbox(thread_id, sandbox_id)
```

### Idle Timeout 管理

```python
def _idle_checker_loop(self) -> None:
    while not self._idle_checker_stop.wait(timeout=60):
        self._cleanup_idle_sandboxes(idle_timeout)

def _cleanup_idle_sandboxes(self, idle_timeout: float) -> None:
    current_time = time.time()
    
    # 检查 active sandboxes
    for sandbox_id, last_activity in self._last_activity.items():
        if current_time - last_activity > idle_timeout:
            self.destroy(sandbox_id)
    
    # 检查 warm pool
    for sandbox_id, (info, release_ts) in self._warm_pool.items():
        if current_time - release_ts > idle_timeout:
            self._backend.destroy(info)
```

### Backend 抽象

```python
def _create_backend(self) -> SandboxBackend:
    provisioner_url = self._config.get("provisioner_url")
    
    if provisioner_url:
        # 远程模式：K8s Provisioner 动态创建 Pod
        return RemoteSandboxBackend(provisioner_url=provisioner_url)
    
    # 本地模式：直接管理 Docker 容器
    return LocalContainerBackend(
        image=self._config["image"],
        base_port=self._config["port"],
        container_prefix=self._config["container_prefix"],
    )
```

**两种 Backend**：

| Backend | 场景 | 实现方式 |
|---------|------|----------|
| LocalContainerBackend | 本地开发 | `docker run` 启动容器 |
| RemoteSandboxBackend | 生产部署 | Provisioner API 创建 K8s Pod |

### 配置示例

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  image: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
  port: 8080
  container_prefix: deer-flow-sandbox
  idle_timeout: 600      # 10 分钟无活动自动清理
  replicas: 3            # 最大并发容器数（LRU 淘汰）
  mounts:
    - host_path: /home/user/projects
      container_path: /mnt/projects
      read_only: false
  environment:
    NODE_ENV: production
    API_KEY: $MY_API_KEY  # 支持环境变量引用
  provisioner_url: ""    # 留空用本地模式
```

---

## Sandbox Tools：Agent 可调用的工具

Agent 通过 7 个工具与 Sandbox 交互：

| 工具 | 功能 | 核心参数 |
|------|------|----------|
| `bash` | 执行命令 | `command` |
| `ls` | 列出目录 | `path` |
| `glob` | 搜索文件 | `pattern`, `path` |
| `grep` | 搜索内容 | `pattern`, `path` |
| `read_file` | 读取文件 | `path`, `start_line`, `end_line` |
| `write_file` | 写入文件 | `path`, `content`, `append` |
| `str_replace` | 替换内容 | `path`, `old_str`, `new_str` |

### bash 工具

```python
@tool("bash", parse_docstring=True)
def bash_tool(runtime, description: str, command: str) -> str:
    """Execute a bash command in a Linux environment."""
    
    sandbox = ensure_sandbox_initialized(runtime)
    
    if is_local_sandbox(runtime):
        # 1. 验证路径权限
        validate_local_bash_command_paths(command, thread_data)
        # 2. 替换虚拟路径
        command = replace_virtual_paths_in_command(command, thread_data)
        # 3. 执行并遮蔽真实路径
        output = sandbox.execute_command(command)
        return mask_local_paths_in_output(output, thread_data)
    
    # 容器模式：直接执行
    return sandbox.execute_command(command)
```

**路径替换逻辑**：

Agent 写的命令：`ls /mnt/user-data/workspace/`
实际执行：`ls /path/to/.deer-flow/threads/{id}/user-data/workspace/`

**安全限制**：

```python
# 检查路径是否在允许范围内
def validate_local_bash_command_paths(command: str, thread_data) -> None:
    for path in extract_absolute_paths(command):
        validate_local_tool_path(path, thread_data)
```

### glob / grep 工具

```python
@tool("glob", parse_docstring=True)
def glob_tool(runtime, description, pattern, path, include_dirs=False, max_results=200):
    sandbox = ensure_sandbox_initialized(runtime)
    
    if is_local_sandbox(runtime):
        path = _resolve_local_read_path(path, thread_data)
    
    matches, truncated = sandbox.glob(path, pattern, max_results=max_results)
    
    # 遮蔽真实路径
    if thread_data:
        matches = [mask_local_paths_in_output(m, thread_data) for m in matches]
    
    return _format_glob_results(requested_path, matches, truncated)

@tool("grep", parse_docstring=True)
def grep_tool(runtime, description, pattern, path, glob=None, literal=False, ...):
    matches, truncated = sandbox.grep(path, pattern, glob=glob, ...)
    return _format_grep_results(requested_path, matches, truncated)
```

**输出格式**：

```
Found 5 paths under /mnt/user-data/workspace
1. /mnt/user-data/workspace/main.py
2. /mnt/user-data/workspace/utils.py
...
Results truncated. Narrow the path or pattern to see fewer matches.
```

### read_file / write_file 工具

```python
@tool("read_file", parse_docstring=True)
def read_file_tool(runtime, description, path, start_line=None, end_line=None):
    content = sandbox.read_file(path)
    
    # 支持行范围读取
    if start_line and end_line:
        content = content.splitlines()[start_line-1:end_line]
    
    return _truncate_read_file_output(content, max_chars=50000)

@tool("write_file", parse_docstring=True)
def write_file_tool(runtime, description, path, content, append=False):
    # 文件操作锁（防止并发写入冲突）
    with get_file_operation_lock(sandbox, path):
        sandbox.write_file(path, content, append)
    return "OK"
```

### str_replace 工具

```python
@tool("str_replace", parse_docstring=True)
def str_replace_tool(runtime, description, path, old_str, new_str, replace_all=False):
    """Replace a substring in a file with another substring."""
    
    with get_file_operation_lock(sandbox, path):
        content = sandbox.read_file(path)
        
        if old_str not in content:
            return f"Error: String to replace not found in file: {path}"
        
        if replace_all:
            content = content.replace(old_str, new_str)
        else:
            content = content.replace(old_str, new_str, 1)  # 只替换第一个
        
        sandbox.write_file(path, content)
    
    return "OK"
```

> [!NOTE]
> `replace_all=False` 时，`old_str` 必须在文件中**唯一**出现。否则可能误改其他位置。

---

## 路径遮蔽：防止泄露宿主机信息

Local Sandbox 模式下，Agent 看到的路径与实际路径不同：

| Agent 看到的 | 实际路径 |
|-------------|----------|
| `/mnt/user-data/workspace` | `.deer-flow/threads/{id}/user-data/workspace` |
| `/mnt/skills/public` | `deer-flow/skills/public` |
| `/mnt/acp-workspace` | `.deer-flow/acp-workspace` |

### 双向遮蔽

```python
def mask_local_paths_in_output(output: str, thread_data) -> str:
    """将输出中的真实路径替换为虚拟路径"""
    
    # 1. 遮蔽 skills 路径
    skills_host = "/path/to/deer-flow/skills"
    skills_container = "/mnt/skills"
    output = re.sub(skills_host, skills_container, output)
    
    # 2. 遮蔽 user-data 路径
    for virtual, actual in thread_mappings.items():
        output = re.sub(actual, virtual, output)
    
    return output
```

**效果**：

- Agent 执行 `ls /mnt/user-data/workspace/`
- 输出：`/mnt/user-data/workspace/main.py`（而非 `/home/user/.deer-flow/...`）

---

## 文件操作锁：防止并发冲突

多个 Agent 同时写入同一文件时，需要锁机制：

```python
#deerflow/sandbox/file_operation_lock.py

_locks: dict[str, threading.Lock] = {}

def get_file_operation_lock(sandbox: Sandbox, path: str) -> threading.Lock:
    """获取文件级别的操作锁"""
    lock_key = f"{sandbox.id}:{path}"
    if lock_key not in _locks:
        _locks[lock_key] = threading.Lock()
    return _locks[lock_key]
```

**使用方式**：

```python
with get_file_operation_lock(sandbox, path):
    content = sandbox.read_file(path)
    content = content.replace(old_str, new_str)
    sandbox.write_file(path, content)
```

---

## 输出截断：防止超大输出

所有工具都有输出截断机制，防止 Agent 崩溃：

```python
def _truncate_bash_output(output: str, max_chars: int = 20000) -> str:
    if len(output) <= max_chars:
        return output
    
    kept = max_chars - 200  # 留空间给提示信息
    return f"{output[:kept]}\n... [truncated: showing first {kept} of {len(output)} chars] ..."
```

**默认限制**：

| 工具 | 默认最大输出 |
|------|-------------|
| `bash` | 20000 字符 |
| `ls` | 20000 字符 |
| `read_file` | 50000 字符 |
| `glob` | 200 条结果 |
| `grep` | 100 条结果 |

---

## 总结

### 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         Agent Layer                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │   bash   │ │   glob   │ │   grep   │ │read_file │ ...         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘             │
│                         │                                        │
│                    Tool Runtime                                  │
│                         │                                        │
│              ensure_sandbox_initialized()                        │
│                         │                                        │
├─────────────────────────────────────────────────────────────────┤
│                      Provider Layer                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              SandboxProvider (抽象)                       │   │
│  │  - acquire(thread_id) → sandbox_id                        │   │
│  │  - get(sandbox_id) → Sandbox                              │   │
│  │  - release(sandbox_id)                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│           │                              │                       │
│           │                              │                       │
│  ┌────────────────┐          ┌────────────────────────────┐     │
│  │LocalSandboxProv│          │   AioSandboxProvider       │     │
│  │  (单例模式)    │          │   (容器池管理)             │     │
│  │                │          │  - Warm Pool               │     │
│  │                │          │  - Idle Timeout            │     │
│  │                │          │  - Backend 抽象            │     │
│  └────────────────┘          └────────────────────────────┘     │
│           │                              │                       │
├─────────────────────────────────────────────────────────────────┤
│                       Sandbox Layer                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Sandbox (抽象接口)                           │   │
│  │  - execute_command(command) → output                      │   │
│  │  - read_file(path) → content                               │   │
│  │  - write_file(path, content)                               │   │
│  │  - glob(path, pattern) → matches                           │   │
│  │  - grep(path, pattern) → matches                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│           │                              │                       │
│  ┌────────────────┐          ┌────────────────────────────┐     │
│  │  LocalSandbox  │          │     AioSandbox             │     │
│  │  (宿主机执行)  │          │   (HTTP API → 容器)        │     │
│  │                │          │                            │     │
│  │  PathMapping   │          │  threading.Lock            │     │
│  │  虚拟路径映射  │          │  (序列化并发请求)          │     │
│  └────────────────┘          └────────────────────────────┘     │
│                                        │                        │
├─────────────────────────────────────────────────────────────────┤
│                       Backend Layer                              │
│                         │                                        │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              SandboxBackend (抽象)                         │ │
│  │  - create(thread_id, sandbox_id) → SandboxInfo             │ │
│  │  - discover(sandbox_id) → SandboxInfo | None               │ │
│  │  - destroy(info)                                           │ │
│  └────────────────────────────────────────────────────────────┘ │
│           │                              │                       │
│  ┌────────────────┐          ┌────────────────────────────┐     │
│  │LocalContainer  │          │  RemoteSandboxBackend      │     │
│  │   Backend      │          │  (Provisioner API)         │     │
│  │  (docker run)  │          │  (K8s Pod 动态创建)        │     │
│  └────────────────┘          └────────────────────────────┘     │
│                                        │                        │
│                                        ▼                        │
│                         ┌─────────────────────┐                 │
│                         │  Docker Container   │                 │
│                         │  (agent-infra/      │                 │
│                         │   sandbox)          │                 │
│                         │  - Shell 执行       │                 │
│                         │  - 文件操作         │                 │
│                         └─────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

### 核心设计亮点

1. **抽象分层**：Sandbox → Provider → Backend，三层解耦，易于扩展

2. **双模式支持**：
   - LocalSandbox：开发调试，零依赖，单例模式
   - AioSandbox：生产部署，容器隔离，池化管理

3. **Warm Pool 机制**：release 不销毁容器，下次可快速复用，减少冷启动

4. **确定性 ID**：`sha256(thread_id)[:8]`，跨进程发现同一容器

5. **路径遮蔽**：Agent 只看到虚拟路径，不知道宿主机布局

6. **输出截断**：防止超大输出导致 Agent 崩溃

7. **文件操作锁**：防止并发写入冲突

### 两种 Provider 对比

| 特性 | LocalSandboxProvider | AioSandboxProvider |
|------|---------------------|--------------------|
| 执行环境 | 宿主机 | Docker 容器 |
| 隔离性 | 无 | 完全隔离 |
| 冷启动 | 无 | 约 60 秒 |
| Warm Pool | 不支持 | 支持 |
| Idle Timeout | 不支持 | 支持 |
| 跨进程共享 | 单例（同一进程） | 确定性 ID |
| 适用场景 | 开发调试 | 生产部署 |

### 扩展新 Sandbox

只需实现 Sandbox 接口和对应 Provider：

```python
class MySandbox(Sandbox):
    def execute_command(self, command: str) -> str:
        # 自定义实现...
    
    def read_file(self, path: str) -> str:
        # ...
    
    # 其他方法...

class MySandboxProvider(SandboxProvider):
    def acquire(self, thread_id: str | None) -> str:
        # 创建/获取 sandbox...
    
    def get(self, sandbox_id: str) -> Sandbox | None:
        # ...
    
    def release(self, sandbox_id: str) -> None:
        # ...
```

然后在配置中启用：

```yaml
sandbox:
  use: my_package:MySandboxProvider
```

---

## 补充：Sandbox 生命周期管理

### Tool 注册 vs Sandbox 创建

Tool 是静态注册的，Sandbox 是动态创建的：

```python
# Tool 注册：Agent 启动时就存在
@tool("bash", parse_docstring=True)
def bash_tool(runtime, description, command):
    sandbox = ensure_sandbox_initialized(runtime)  # ← 这里才创建 Sandbox
    ...
```

**惰性初始化**：第一次调用任何 tool 时才创建容器，而不是预先创建。

```python
def ensure_sandbox_initialized(runtime):
    sandbox_id = runtime.state.get("sandbox_id")
    
    if sandbox_id:
        # 已存在 → 直接获取
        return provider.get(sandbox_id)
    
    # 不存在 → 创建新的
    sandbox_id = provider.acquire(thread_id)
    runtime.state["sandbox_id"] = sandbox_id
    return provider.get(sandbox_id)
```

---

### 容器生命周期流程图

```
┌─────────────────────────────────────────────────────┐
│                 Thread/Session                       │
│                                                     │
│  1. 用户发起对话                                     │
│     ↓                                               │
│  2. Agent 第一次调用 tool                           │
│     ↓                                               │
│  3. ensure_sandbox_initialized()                    │
│     → provider.acquire(thread_id)                   │
│     → 创建容器（或从 Warm Pool 取）                  │
│     ↓                                               │
│  4. 执行 tool 操作...                               │
│     ↓                                               │
│  5. 继续调用其他 tool                               │
│     → provider.get(sandbox_id) ← 直接返回已有容器   │
│     ↓                                               │
│  6. Session 结束                                    │
│     → provider.release(sandbox_id)                  │
│     → 放回 Warm Pool（不删除）                       │
│                                                     │
│  ─────────────────────────────────────────────────  │
│                                                     │
│  Warm Pool 中的容器：                                │
│  - 等待 idle_timeout（如 30 分钟）                   │
│  - 超时 → backend.destroy() → 删除容器              │
│  - 下次 acquire → 直接从池中取出（快速复用）         │
└─────────────────────────────────────────────────────┘
```

---

### AioSandboxProvider 的管理逻辑

```python
class AioSandboxProvider:
    _sandboxes: dict[str, AioSandbox] = {}  # 活跃的 sandbox
    _last_used: dict[str, float] = {}       # 最后使用时间
    
    def acquire(self, thread_id):
        sandbox_id = deterministic_id(thread_id)
        
        # 1. 检查是否已有活跃的
        if sandbox_id in self._sandboxes:
            return sandbox_id
        
        # 2. 尝试从 Warm Pool 恢复（容器可能还在运行）
        info = backend.discover(sandbox_id)
        if info:
            # 容器还在，直接复用
            self._sandboxes[sandbox_id] = AioSandbox(info)
            return sandbox_id
        
        # 3. 真正创建新容器
        info = backend.create(thread_id, sandbox_id)
        self._sandboxes[sandbox_id] = AioSandbox(info)
        return sandbox_id
    
    def release(self, sandbox_id):
        # 不删除，只是记录时间，等待下次复用
        self._last_used[sandbox_id] = time.now()
    
    def cleanup_idle(self):
        # 定期清理超时的容器
        for sandbox_id, last_used in self._last_used.items():
            if time.now() - last_used > idle_timeout:
                backend.destroy(self._sandboxes[sandbox_id].info)
                del self._sandboxes[sandbox_id]
                del self._last_used[sandbox_id]
```

---

### 生命周期关键时机

| 时机 | 操作 | 说明 |
|------|------|------|
| 第一次调用 tool | `acquire` | 创建容器（或从 Warm Pool 取） |
| 后续调用 tool | `get` | 返回已有容器 |
| Session 结束 | `release` | 放回 Warm Pool，不删除 |
| idle_timeout 超时 | `destroy` | 真正删除容器 |

**核心设计思想**：

1. **惰性创建**：不预先创建，第一次用才创建，节省资源
2. **Warm Pool**：release 不删，保留复用，减少下次的冷启动时间
3. **确定性 ID**：`sha256(thread_id)[:8]`，即使跨进程也能找到同一容器