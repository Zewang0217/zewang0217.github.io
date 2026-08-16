---
title: "从零构建 GPT：Andrej Karpathy 视频笔记"
description: "跟随 Andrej Karpathy 从零手写一个 NanoGPT，理解 Transformer 核心机制：Self-Attention、Multi-Head Attention、LayerNorm、Residual Connection"
date: 2026-07-03
slug: "nanogpt-from-scratch"
tags:
  - Transformer
  - GPT
  - Deep Learning
  - NLP
categories:
  - 技术笔记
---

# 从零构建 GPT：Andrej Karpathy 视频笔记

> 视频：[Let's build GPT: from scratch, in code, spelled out.](https://www.youtube.com/watch?v=kCc8FmEb1nY) by Andrej Karpathy
> 时长：1 小时 56 分钟
> 代码：nanoGPT（GitHub: karpathy/nanoGPT）

---

## 视频结构速览

```
00:00  - 开场：ChatGPT 是什么（概率语言模型）
04:00  - Tokenization：BPE（Byte Pair Encoding）
10:00  - 数据：Shakespeare 数据集
15:00  - 第一个模型：Bigram Language Model（基线）
25:00  - Self-Attention 机制（核心）
40:00  - Multi-Head Attention（多个注意力头并行）
50:00  - LayerNorm 与 Residual Connection
60:00  - Feed-Forward Network
70:00  - Transformer Block 组合
80:00  - Cross-Attention（翻译任务示例）
95:00  - 收尾与总结
```

---

## 1. 语言模型基础

### 什么是语言模型

语言模型的核心任务是：**给定一个词序列，预测下一个词**。

ChatGPT 是一个概率系统——同一个 Prompt，每次生成的内容略有不同，因为它在每一步都在做概率采样。语言模型建模的是词（token）序列的联合概率分布。

### Tokenization：GPT 用 BPE

传统的字符级模型把每个字符当作一个 token，词汇表只有几十个。GPT-2 使用的是 **BPE（Byte Pair Encoding）**，通过统计合并频率，把常见字符序列合并成子词单元。

GPT-2 的词汇表有 50,257 个 token，编码工具是 `tiktoken`（OpenAI 开源库）。

```python
import tiktoken
enc = tiktoken.get_encoding("gpt2")
ids = enc.encode("hello world")  # → [31373, 1011]
```

BPE 的 trade-off：**词汇表越大，序列越短；但嵌入表也越大**。

---

## 2. 第一个基线模型：Bigram

在进入 Transformer 之前，Karpathy 先实现了一个 Bigram 模型作为性能基线。

Bigram 极其简单：根据当前 token 查表，直接预测下一个 token。没有上下文窗口，没有注意力机制。

```python
# Bigram: 就是一个超大查表
logits = token_embedding_table[idx]  # B,T → B,T,V
```

在 Shakespeare 数据集上，Bigram 的交叉熵损失约 2.4。

---

## 3. Self-Attention：核心中的核心

### 为什么需要 Attention

RNN 的问题是：**信息从左到右顺序传递，长序列难以处理**。Attention 的核心思想是：**序列中每个位置都可以直接关注序列中任意其他位置**，不依赖顺序传递。

### Attention 的三个向量：Query、Key、Value

每个 token 有三个向量：
- **Query（查询）**：我在找什么
- **Key（键）**：我包含什么信息
- **Value（值）**：如果匹配，我提供什么信息

```python
# 简化版自注意力
q = x @ W_q  # Query
k = x @ W_k  # Key
v = x @ W_v  # Value

affinities = q @ k.T  # 所有 token 之间的关联强度
scores = softmax(affinities / sqrt(d_k))  # 缩放，防止梯度消失
out = scores @ v  # 加权聚合
```

### 因果掩码（Causal Mask）

GPT 是一个 **Decoder-Only** 模型，生成时只能看到前面的 token，不能窥视未来。因此需要在 Softmax 之前把"未来位置"的得分设为负无穷。

```python
# 下三角掩码
tril = torch.tril(torch.ones(T, T))
scores = scores.masked_fill(tril == 0, float('-inf'))
```

### 缩放（Scaled Attention）

`sqrt(d_k)` 的作用是：**防止点积结果过大，导致 Softmax 梯度趋近于 0**。维度越高，点积值越大，缩放越必要。

---

## 4. Multi-Head Attention

单一注意力头只学到一种"关注模式"。多个头并行，可以学到多种不同的关联方式。

```python
class MultiHeadAttention(nn.Module):
    def __init__(self, n_heads, d_model):
        self.heads = nn.ModuleList([
            SelfAttention(d_model // n_heads)
            for _ in range(n_heads)
        ])
        self.proj = nn.Linear(d_model, d_model)

    def forward(self, x):
        out = torch.cat([h(x) for h in self.heads], dim=-1)
        return self.proj(out)
```

实验中，加了 Multi-Head Attention 后，损失从 2.4 降到 2.28——多通信通道确实有帮助：token 可以同时学习"寻找元音""寻找特定语义关系"等多种模式。

---

## 5. Feed-Forward Network（FFN）

每个位置（token）独立经过同一个两层的全连接网络：

```python
# 典型 FFN
x = x @ W1 + b1
x = F.relu(x)
x = x @ W2 + b2
```

FFN 的作用：**在 Self-Attention 聚合完上下文信息之后，对每个位置做非线性变换，增强模型的表达能力**。Attention 做信息路由，FFN 做特征提炼。

---

## 6. LayerNorm 与 Residual Connection

### LayerNorm

LayerNorm 对**每一行**（即每个 token 的向量）做归一化：

```python
x = (x - mean) / std
x = x * gamma + beta  # 可学习的缩放和偏移
```

对比 BatchNorm：BatchNorm 跨 batch 归一化，LayerNorm 在每个样本内部归一化。Transformer 用 LayerNorm，因为序列长度可变，且训练/推理行为一致。

### Residual Connection

`x = x + Sublayer(x)`——在把数据送入注意力层和 FFN 之前，原始输入被保留下来，直接加到输出上。

Residual Connection 的核心作用：**让深层网络更容易训练**。梯度可以无衰减地传回浅层，解决了深层网络退化的问题。

---

## 7. Transformer Block

把以上所有组件组合在一起，就是一个完整的 **Transformer Block**：

```
Input
  ↓
LayerNorm
  ↓
Multi-Head Self-Attention
  ↓ (+) Residual
LayerNorm
  ↓
Feed-Forward Network
  ↓ (+) Residual
Output
```

GPT 由多个这样的 Block 堆叠而成。原始 Transformer 论文中，Attention 和 FFN 之前都有 LayerNorm，且采用了 Pre-Norm 残差布局（现在的主流做法）。

---

## 8. Cross-Attention（示例：翻译）

在翻译任务中，解码器的每一层还有 **Cross-Attention**：Query 来自解码器，Key 和 Value 来自编码器（源语言）。这让解码器可以"查询"源语言的信息。

GPT（Decoder-Only）不需要 Cross-Attention，因为它做的是续写（completion），而不是翻译。

---

## 9. 完整训练流程

```python
# 典型训练循环
for step in range(max_steps):
    xb, yb = get_batch()           # 采样数据
    logits = model(xb)             # 前向传播
    loss = F.cross_entropy(logits.view(-1, V), yb.view(-1))  # 交叉熵损失
    model.zero_grad()
    loss.backward()                 # 反向传播
    optimizer.step()               # 参数更新
```

训练技巧：
- **学习率调度**：先用小学习率预热，再退火
- **评估时求多个 batch 的平均损失**，单 batch 波动大
- **梯度裁剪**：防止梯度爆炸

---

## 10. 几个值得记住的设计决策

| 设计 | 决策 | 原因 |
|------|------|------|
| 因果掩码 | 下三角矩阵 | GPT 是自回归模型，不能看未来 |
| Pre-Norm | LayerNorm 在残差分支内 | 训练更稳定，是当前主流 |
| 缩放因子 | `1/sqrt(d_k)` | 防止点积过大导致 Softmax 梯度消失 |
| 多头并行 | 多个 Self-Attention 头 | 让 token 能同时学习多种关联模式 |
| FFN 独立 | 每个 token 共享同一 FFN | 在 Attention 聚合后做非线性变换 |

---

## 附：nanoGPT 代码结构

```
nanoGPT/
├── model.py    # GPT 模型定义（Transformer、MLP、LayerNorm 等）
└── train.py    # 训练脚本（数据加载、优化器、训练循环）
```

两个文件各约 300 行，代码极度精简，适合作为学习 Transformer 的起点。

---

## 总结

这个视频的核心价值：**用最少的代码把 GPT 的骨架讲清楚**。

注意力机制本质是一个**加权聚合**操作——每个 token 通过 Query-Key 的相似度决定从其他 token 那里聚合多少信息。多头注意力让聚合通道多样化，FFN 做非线性提炼，Residual + LayerNorm 保证深层网络可训练。

理解了这个数据流，就理解了 Transformer 乃至 GPT 的本质。
