---
title: "HelloAgents 第八章学习笔记：记忆与检索系统详解"
description: "深入学习HelloAgents框架的记忆系统和RAG系统，理解认知科学启发的记忆模型、四层记忆架构、智能文档问答助手的实现"
date: 2026-05-18
slug: hello-agents-chapter8-memory-and-retrieval
tags:
    - 学习笔记
    - AI Agent
    - HelloAgents
    - RAG
    - 记忆系统
categories:
    - 技术笔记
---

## 背景

前面的章节我们构建了HelloAgents框架的基础架构，实现了多种智能体范式和工具系统。但有一个关键能力一直缺失：**记忆**。

如果智能体无法记住之前的交互内容，无法从历史经验中学习，在连续对话或复杂任务中表现将受到极大限制。

本章在第七章的基础上，为HelloAgents增加了两个核心能力：
- **记忆系统（Memory System）**
- **检索增强生成（RAG）**

## 1. 为什么智能体需要记忆与RAG

### 1.1 局限一：无状态导致的对话遗忘

大语言模型设计上是**无状态的**。每一次请求都是独立的计算，模型不会自动"记住"上一次对话的内容。

这带来几个问题：
- **上下文丢失**：长对话中早期重要信息可能因窗口限制而丢失
- **个性化缺失**：无法记住用户偏好、习惯或特定需求
- **学习能力受限**：无法从过往成功或失败经验中学习
- **一致性问题**：多轮对话可能出现前后矛盾

### 1.2 局限二：模型内置知识的局限性

LLM的知识是**静态的、有限的**，完全来自训练数据，带来：
- **知识时效性**：无法获取最新信息
- **专业领域知识**：通用模型在特定领域深度不足
- **事实准确性**：存在幻觉问题
- **可解释性**：缺乏信息来源

RAG（检索增强生成）技术应运而生，核心思想是在模型生成回答之前，先从外部知识库检索相关信息作为上下文。

## 2. 记忆系统架构设计

### 2.1 四层架构

HelloAgents记忆系统采用类似人类记忆的层次结构：

```
记忆系统
├── 基础设施层 (Infrastructure Layer)
│   ├── MemoryManager - 记忆管理器（统一调度）
│   ├── MemoryItem - 记忆数据结构
│   ├── MemoryConfig - 配置管理
│   └── BaseMemory - 记忆基类
├── 记忆类型层 (Memory Types Layer)
│   ├── WorkingMemory - 工作记忆（临时信息，TTL管理）
│   ├── EpisodicMemory - 情景记忆（事件序列）
│   ├── SemanticMemory - 语义记忆（图谱关系）
│   └── PerceptualMemory - 感知记忆（多模态数据）
├── 存储后端层 (Storage Backend Layer)
│   ├── QdrantVectorStore - 向量存储
│   ├── Neo4jGraphStore - 图存储
│   └── SQLiteDocumentStore - 文档存储
└── 嵌入服务层 (Embedding Service Layer)
    ├── DashScopeEmbedding - 通义千问嵌入
    ├── LocalTransformerEmbedding - 本地嵌入
    └── TFIDFEmbedding - TFIDF嵌入
```

### 2.2 四种记忆类型对比

| 类型 | 存储方式 | 生命周期 | 特点 | 评分公式 |
|------|----------|----------|------|----------|
| **工作记忆** | 纯内存 | 临时(TTL) | 容量有限、快速访问 | `(相似度×0.7+关键词×0.3) × 时间衰减 × (0.8+重要性×0.4)` |
| **情景记忆** | SQLite+Qdrant | 持久 | 事件序列、会话关联 | `(向量相似度×0.8+时间近因性×0.2) × (0.8+重要性×0.4)` |
| **语义记忆** | Neo4j+Qdrant | 长期 | 概念知识、知识图谱 | `(向量相似度×0.7+图相似度×0.3) × (0.8+重要性×0.4)` |
| **感知记忆** | 分模态向量 | 动态 | 多模态、跨模态检索 | `(向量相似度×0.8+时间近因性×0.2) × (0.8+重要性×0.4)` |

### 2.3 记忆系统工作流程

```
添加记忆 → 编码 → 存储 → 检索 → 整合 → 遗忘
```

记忆形成经历：
1. **编码（Encoding）**：将信息转换为可存储形式
2. **存储（Storage）**：保存在记忆系统中
3. **检索（Retrieval）**：从记忆中提取相关信息
4. **整合（Consolidation）**：将短期记忆转化为长期记忆
5. **遗忘（Forgetting）**：删除不重要或过时的信息

## 3. MemoryTool核心操作

MemoryTool作为统一入口，通过`execute`方法提供以下操作：

### 3.1 add - 添加记忆

```python
# 添加工作记忆
memory_tool.execute("add",
    content="用户刚才问了关于Python函数的问题",
    memory_type="working",
    importance=0.6
)

# 添加情景记忆
memory_tool.execute("add",
    content="用户完成了第一个Python项目",
    memory_type="episodic",
    importance=0.8,
    event_type="milestone"
)

# 添加语义记忆
memory_tool.execute("add",
    content="Python是一种解释型、面向对象的编程语言",
    memory_type="semantic",
    importance=0.9,
    knowledge_type="factual"
)
```

### 3.2 search - 搜索记忆

```python
# 基础搜索
result = memory_tool.execute("search", query="Python编程", limit=5)

# 指定类型搜索
result = memory_tool.execute("search",
    query="学习进度",
    memory_type="episodic",
    limit=3
)
```

### 3.3 forget - 遗忘策略

支持三种遗忘策略：

```python
# 基于重要性 - 删除重要性低于阈值
memory_tool.execute("forget", strategy="importance_based", threshold=0.2)

# 基于时间 - 删除超过指定天数的记忆
memory_tool.execute("forget", strategy="time_based", max_age_days=30)

# 基于容量 - 超限时删除最不重要的
memory_tool.execute("forget", strategy="capacity_based", threshold=0.3)
```

### 3.4 consolidate - 记忆整合

将短期记忆提升为长期记忆：

```python
# 将重要工作记忆转为情景记忆
memory_tool.execute("consolidate",
    from_type="working",
    to_type="episodic",
    importance_threshold=0.7
)
```

## 4. RAG系统详解

### 4.1 RAG发展历程

```
第一阶段：朴素RAG（Naive RAG, 2020-2021）
├── 检索：TF-IDF/BM25关键词匹配
└── 生成：直接拼接检索结果到Prompt

第二阶段：高级RAG（Advanced RAG, 2022-2023）
├── 检索：稠密嵌入（Dense Embedding）语义检索
└── 生成：查询重写、文档分块、重排序

第三阶段：模块化RAG（Modular RAG, 2023-至今）
├── 检索：混合检索、MQE、HyDE
└── 生成：思维链推理、自我反思修正
```

### 4.2 处理管道：任意格式 → Markdown → 分块 → 向量

RAG系统的核心处理流程：

```
任意格式文档 → MarkItDown转换 → Markdown文本 → 智能分块 → 向量化 → 存储检索
```

**MarkItDown**是微软开源的通用文档转换工具，支持：
- 文档：PDF、Word、Excel、PowerPoint
- 图像：JPG、PNG、GIF（OCR）
- 音频：MP3、WAV、M4A（转录）
- 文本：TXT、CSV、JSON、XML、HTML

### 4.3 Markdown智能分块策略

分块流程：
```
标准Markdown文本 → 标题层次解析 → 段落语义分割 → Token计算分块 → 重叠策略优化 → 向量化
```

关键特性：
- **标题层次感知**：利用#、##、###结构
- **Token精确控制**：支持中英文混合Token估算
- **智能重叠**：避免信息在边界丢失

```python
def _is_cjk(ch: str) -> bool:
    """判断是否为CJK字符"""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or   # CJK统一汉字
        0x3400 <= code <= 0x4DBF or   # CJK扩展A
        # ... 更多CJK范围
    )
```

### 4.4 高级检索策略

#### 多查询扩展（MQE）

通过生成语义等价的多样化查询提高召回率：

```python
# 例如，原始查询："如何学习Python"
# 扩展为：
# - "Python入门教程"
# - "Python学习方法"
# - "Python编程指南"
```

#### 假设文档嵌入（HyDE）

核心思想是"用答案找答案"：

1. 让LLM生成假设性答案段落
2. 用这个答案段落去检索真实文档
3. 假设答案与真实答案在语义空间更接近

```python
def _prompt_hyde(query: str) -> str:
    """生成假设性文档用于改善检索"""
    # 根据用户问题，先写一段可能的答案性段落
    prompt = [
        {"role": "system", "content": "根据用户问题，先写一段可能的答案性段落，用于向量检索的查询文档（不要分析过程）。"},
        {"role": "user", "content": f"问题：{query}\n请直接写一段中等长度、客观、包含关键术语的段落。"}
    ]
    return llm.invoke(prompt)
```

## 5. 实战：智能文档问答助手

### 5.1 核心类实现

```python
class PDFLearningAssistant:
    def __init__(self, user_id: str = "default_user"):
        self.user_id = user_id
        self.session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 初始化工具
        self.memory_tool = MemoryTool(user_id=user_id)
        self.rag_tool = RAGTool(rag_namespace=f"pdf_{user_id}")
        
        # 学习统计
        self.stats = {
            "session_start": datetime.now(),
            "documents_loaded": 0,
            "questions_asked": 0,
            "concepts_learned": 0
        }
```

### 5.2 完整工作流程

```
┌─────────────────────────────────────────────────────────┐
│ 步骤1: 加载PDF文档 (RAGTool处理)                          │
│   MarkItDown转换 → 智能分块 → 向量化存储                    │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤2: 记录到情景记忆                                     │
│   memory_tool.execute("add", memory_type="episodic")      │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤3: 智能问答 (RAGTool + MemoryTool)                   │
│   用户提问 → MQE/HyDE扩展 → 向量检索 → LLM生成 → 回答       │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤4: 记录学习历史                                      │
│   问题记录到工作记忆                                       │
│   问答记录到情景记忆                                       │
│   笔记保存到语义记忆                                       │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤5: 生成学习报告                                      │
│   整合统计信息、记忆摘要、RAG状态                           │
└─────────────────────────────────────────────────────────┘
```

### 5.3 核心方法

```python
def load_document(self, pdf_path: str) -> Dict:
    # RAGTool处理PDF
    result = self.rag_tool.execute("add_document", 
                                   file_path=pdf_path,
                                   chunk_size=1000,
                                   chunk_overlap=200)
    
    # 记录到情景记忆
    self.memory_tool.execute("add",
        content=f"加载了文档《{self.current_document}》",
        memory_type="episodic",
        importance=0.9,
        event_type="document_loaded"
    )
    return result

def ask(self, question: str, use_advanced_search: bool = True) -> str:
    # 记录到工作记忆
    self.memory_tool.execute("add",
        content=f"提问: {question}",
        memory_type="working",
        importance=0.6
    )
    
    # RAGTool高级检索
    answer = self.rag_tool.execute("ask",
        question=question,
        enable_mqe=use_advanced_search,
        enable_hyde=use_advanced_search
    )
    
    # 记录到情景记忆
    self.memory_tool.execute("add",
        content=f"关于'{question}'的学习",
        memory_type="episodic",
        importance=0.7,
        event_type="qa_interaction"
    )
    
    return answer
```

## 6. 总结

### 核心设计亮点

1. **认知科学启发**：借鉴人类记忆系统，分层记忆设计更符合人类认知规律

2. **专业化分工**：四种记忆类型各有专长，存储和检索策略针对优化

3. **统一接口设计**：MemoryTool和RAGTool通过统一`execute`方法简化调用

4. **RAG管道化**：任意格式→Markdown→分块→向量化，流程清晰可扩展

5. **高级检索**：MQE和HyDE显著提升检索召回率和精度

### 技术选型

| 组件 | 方案 | 特点 |
|------|------|------|
| 向量数据库 | Qdrant | 高性能向量检索 |
| 图数据库 | Neo4j | 知识图谱关系推理 |
| 文档存储 | SQLite | 结构化持久化 |
| 嵌入服务 | DashScope/Local/TF-IDF | 多种方案兜底 |

### 扩展方向

- 跟踪前沿memory、rag仓库的优秀实现
- 探索多模态RAG（文本+图像）或跨模态场景
- 参与HelloAgents开源项目贡献

> [!TIP]
> 本章代码示例位于 `code/chapter8/` 目录，完整案例可参考 `11_Q&A_Assistant.py`