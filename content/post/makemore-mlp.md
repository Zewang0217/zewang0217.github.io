---
title: "makemore Part 2：从 Bigram 到 MLP"
description: "跟着 Andrej Karpathy 一起从零搭建字符级神经网络语言模型，理解 embedding、MLP、训练循环与学习率调度"
date: 2026-07-05
slug: "makemore-mlp"
tags:
  - makemore
  - 语言模型
  - MLP
  - PyTorch
  - Andrej Karpathy
categories:
  - 技术笔记
---

# makemore Part 2：从 Bigram 到 MLP

> 资料源：[The spelled-out intro to neural networks and backpropagation: building micrograd](https://www.youtube.com/watch?v=TCH_1BHY58I)（Andrej Karpathy，访问于 2026-07-05）

## 视频概览

Part 2 是 makemore 系列的第二集。Part 1 用 bigram（只统计相邻两字符的共现频率）来生成名字，单次准确率天花板很低。本集升级到 **MLP（多层感知器）**：用上下文窗口内的多个字符作为输入，预测下一个字符。

具体路线：

1. **数据集构造**：滑动窗口取 `block_size` 个字符预测下一个
2. **Embedding 查表**：每个字符映射为一个低维向量
3. **MLP 前向**：embedding → 拼成向量 → 两层线性层 → softmax → 概率分布
4. **损失函数**：交叉熵（多分类）
5. **训练循环**：SGD 反向传播，更新参数
6. **学习率调度**：学习率扫描（LR range test），挑最优 LR
7. **过拟合与评估**：train/val/test 三分，监控 loss

最终目标：在名字数据集上把 validation loss 压到 2.17 以下。

---

## 一、数据集构造：滑动窗口

类比 Part 1 的 bigram，这里用 `block_size = 3`（上下文 3 个字符）预测第 4 个。

```python
block_size = 3  # 上下文长度

def build_dataset(words):
    X, Y = [], []
    for w in words:
        # 用 . 填充开头和结尾，让模型学会"在哪里开始"和"在哪里结束"
        context = [0] * block_size
        for ch in w + '.':
            ix = stoi[ch]
            X.append(context)
            Y.append(ix)
            context = context[1:] + [ix]  # 滚动窗口
    X = torch.tensor(X)
    Y = torch.tensor(Y)
    return X, Y
```

要点：

- 用 `.` 作为特殊的"开始/结束"标记，让模型知道什么时候该停止生成
- 每个样本 `X[i]` 是长度为 3 的整数序列，`Y[i]` 是下一个字符的整数索引
- 32 个 batch size × 3 字符 = 96 维的输入张量

---

## 二、Embedding Lookup Table

模型第一步：把每个字符的整数索引映射为低维向量。

```python
# vocab_size = 27 (26 字母 + .), embedding_dim = 2
C = torch.randn((27, 2))
```

`C` 是一个 `(27, 2)` 的查找表。给定字符索引 `i`，`C[i]` 就是它的 2 维向量。

**关键技巧：PyTorch 索引支持多维张量。**

```python
# 1D 索引
C[5]  # 第 5 个字符的 embedding (2,)

# 2D 索引 — 对 X (32, 3) 直接索引
emb = C[X]  # (32, 3, 2)
```

后者直接得到 `(32, 3, 2)` 的张量，每个位置是 `X[i,j]` 字符对应的 embedding。这一步不需要循环，完全向量化。

#### 深入理解 `C[X]`

`C[X]` 是 PyTorch 的**张量索引**（fancy indexing）——对 X 里**每个整数**取对应行，保持 X 的形状不变：

```python
X = torch.tensor([[5, 3, 7],   # 样本 0 的 3 个字符
                  [2, 8, 1]])  # 样本 1 的 3 个字符
emb = C[X]  # (2, 3, 2)
```

展开来看：

```
emb[0][0] = C[X[0][0]] = C[5]   # 样本0, 位置0的字符
emb[0][1] = C[X[0][1]] = C[3]
emb[0][2] = C[X[0][2]] = C[7]
emb[1][0] = C[X[1][0]] = C[2]
...
```

#### `C[X][i, j]` 的含义

`C[X]` 得到 `(32, 3, 2)` 张量后，用普通下标访问任意元素：

| 表达式 | 含义 | 形状 |
|--------|------|------|
| `C[X][13, 2]` | 第 13 个样本的第 2 个位置的字符向量 | `(2,)` |
| `C[X][13]` | 第 13 个样本的全部 3 个字符 | `(3, 2)` |
| `C[X][:, 2]` | **所有样本**的第 2 个位置的字符 | `(32, 2)` |
| `C[X][i, j]` | 本质等价于 `C[X[i, j]]` | `(2,)` |

最后一行尤其重要：`C[X][:, 2]` 这种"切某列"的操作非常常用，相当于一次性提取所有样本在某一上下文位置的字符向量。

### 为什么用 embedding？

- 字符本身没有"语义距离"的概念。'a' 和 'b' 的整数 ID 是相邻的，但 'a' 和 'z' 的"距离"也是相邻的——这不对
- 把字符映射到连续向量空间后，相似的字符（比如元音）可以聚在一起
- embedding 是**可学习**的，训练过程会自然把"用得上的"字符聚类

### C 表 vs One-hot：本质等价

**两种方式数学上完全等价**——这是个隐藏得很巧妙的等价关系：

```python
# One-hot 方式
x = torch.zeros(27)
x[5] = 1
v = x @ W  # W 形状 (27, 2) → 得到 2 维向量

# Embedding 方式
C = W  # 同一个矩阵
v = C[5]
```

`x @ W` 和 `C[5]` 结果**完全相同**。区别只在工程层面：

| 维度 | One-hot × W | C 表（Embedding） |
|------|-------------|-------------------|
| 效率 | 稀疏矩阵乘法 (27×27) | 直接索引 O(1) |
| 内存 | 临时 (27, 27) 向量 | 复用 (27, 2) 表 |
| 可读性 | `one_hot[5] @ W` | `C[5]` |

Karpathy 用 C 表不是为了引入新概念，而是把"one-hot × 权重矩阵"打包成更优雅的形式。**真正不同的设计选择**是 embedding 维度（比如 2 维），不是 lookup 这件事本身。

---

## 三、MLP 前向传播

把 `(32, 3, 2)` 的 embedding 拼成一个 `(32, 6)` 的向量，过两层线性层 + tanh：

```python
W1 = torch.randn((6, 100))  # hidden = 100
b1 = torch.randn(100)
W2 = torch.randn((100, 27))  # 输出 = vocab_size
b2 = torch.randn(27)

# 拼接
emb = C[X].view(-1, 6)  # (32, 6)

# hidden 层
h = torch.tanh(emb @ W1 + b1)  # (32, 100)

# 输出 logits
logits = h @ W2 + b2  # (32, 27)
```

### W1 形状的拆解

`W1 = torch.randn((6, 100))`：

- **6** = 输入特征数（每个样本展平后的维度 = `block_size * n_embd` = 3 × 2）
- **100** = 隐藏层神经元数量（输出维度）

也就是说：**输入 6 维向量 → 经过 W1 线性变换 → 变成 100 维向量**，再用 tanh 压缩到 `[-1, 1]`。

整条链：`x (6)` → `Wx + b (100)` → `tanh (100)` → `W₂h + b₂ (27)` → softmax → 概率

`h = tanh(...)` 这一步是**引入非线性**的关键——没有它，多层线性层会坍缩成单层（数学上等价）。

### 关键操作：`view(-1, 6)`

`view` 改变张量的视图（shape），不复制数据——只要内存连续、形状兼容。

```python
emb.shape == (32, 3, 2)
emb.view(-1, 6).shape == (32, 6)
```

更激进的写法：`emb.view(emb.shape[0], -1)`，让框架自动推断维度。

> 📝 **背景知识**：`view` vs `reshape`：`view` 要求内存连续（contiguous），`reshape` 在不连续时会自动复制。`view` 更快但条件严格。

---

## 四、损失函数：交叉熵

从 logits 到概率：softmax；然后和真实标签算 negative log likelihood。

```python
# 手写版（教学）
counts = logits.exp()           # (32, 27)
probs = counts / counts.sum(1, keepdim=True)
loss = -probs[torch.arange(32), Y].log().mean()
```

但是 `exp` 容易数值溢出。PyTorch 内置的 `F.cross_entropy` 内部做了数值稳定处理（减去 max），并把 softmax + NLL 合并：

```python
loss = F.cross_entropy(logits, Y)  # 一行搞定
```

**永远优先用 `F.cross_entropy`**，不要自己手写 softmax + NLL，除非在教学场景。

### `F.cross_entropy` 的两个核心好处

Karpathy 在视频里明确讲了（其实是三个，但核心两条）：

**1. 效率（forward + backward 都快）**

手写 softmax + NLL 每一步都创建中间张量（exp、/、log、mean...），内存读写多。`F.cross_entropy` 在底层把这些运算**融合（fused kernels）**——一次算完，少几次内存往返。forward 更快，**backward 也更快**（不用分别对 exp、log、div 求导再 chain 起来）。

**2. 数值稳定性**

手写版的隐患：

```
logits = [-2, 3, -3, 0, 100]   →  exp(100) = inf → NaN
```

`F.cross_entropy` 内部有个**关键技巧**：先减去 logits 的最大值，再做 softmax：

```python
counts = exp(logits - max(logits))  # max=100 → exp(0) = 1
```

数学上等价（归一化消掉 max），但数值上稳定。

---

## 五、训练循环

```python
for i in range(1000):
    # forward
    emb = C[Xtr]
    h = torch.tanh(emb.view(-1, 6) @ W1 + b1)
    logits = h @ W2 + b2
    loss = F.cross_entropy(logits, Ytr)

    # backward
    for p in parameters:
        p.grad = None
    loss.backward()

    # update
    lr = 0.1
    for p in parameters:
        p.data += -lr * p.grad
```

### 关于 `p.grad = None`

PyTorch 推荐 `p.grad = None` 而不是 `p.grad.zero_()`——前者更省内存。

### Mini-batch：真实工程的样子

Karpathy 演示时用 full-batch（一次算整个训练集的梯度），但**实际中几乎没人这么干**。

```python
batch_size = 32
for epoch in range(1000):
    # 随机抽 32 个样本的下标
    ix = torch.randint(0, Xtr.shape[0], (batch_size,))
    # 用这 32 个样本算 forward / backward
    emb = C[Xtr[ix]]
    h = torch.tanh(emb.view(-1, 6) @ W1 + b1)
    logits = h @ W2 + b2
    loss = F.cross_entropy(logits, Ytr[ix])
    loss.backward()
    # ... update
```

| 维度 | Full-batch（Karpathy 演示） | Mini-batch（实际工程） |
|------|---------------------------|----------------------|
| 每次梯度用多少样本 | 全部 | 32 / 64 / 256 |
| 单步速度 | 慢 | 快 |
| 内存占用 | 大 | 小 |
| 梯度方向 | 确定性 | 有噪声但无偏 |
| 收敛曲线 | 平滑 | 抖动 |

Mini-batch 的三个核心好处：

1. **快**：单步只算 32 个样本，能并行做很多次更新
2. **正则化**：带噪声的梯度能跳出尖锐的局部极小，泛化更好
3. **可扩展**：数据上千万级时必须分批

batch size 本身是个超参数——太小梯度太不稳，太大丧失噪声正则化。

---

## 六、学习率调度：LR Range Test

固定学习率（比如 0.1）跑一跑，loss 下降得不错，但**怎么知道这个 lr 是最优的？**

直觉上：

- 学习率太小，几乎不下降——参数原地踏步
- 学习率太高，明显波动，甚至完全失效——步子太大跳过最优点
- **所以**：先框定范围，然后逐步扫描，作图找最合适的地方

具体做法：**指数扫描**。

```python
lre = torch.linspace(-3, 0, 1000)  # 10^-3 到 10^0 = 0.001 到 1.0
lrs = 10 ** lre

for i in range(1000):
    lr = lrs[i]
    # ... train step
    # 记录 loss
```

### 为什么指数而不是线性？

lr 的有效范围通常跨好几个数量级（`0.0001` 到 `1`）。线性扫描的话，大部分采样点都集中在中间某个范围，**log 空间的尾部被浪费**。

```python
# 指数扫：lre 从 -3 到 0，1000 步
lre = torch.linspace(-3, 0, 1000)   # -3, -2.997, ..., 0
lrs = 10 ** lre                     # 0.001, 0.001003, ..., 1.0
```

这样 `0.001 → 1.0` 在 log 空间均匀分布，每个数量级都被等量采样。

画 loss vs lr 曲线（**x 轴必须 log 尺度**）：

```
loss
  ↑      ╱╲
  │     ╱  ╲      ← 爆炸区：lr 太大，loss 飙升
  │    ╱    ╲
  │   ╱  ★   ╲    ← ★ 最优 lr 附近
  │  ╱        ╲
  │ ╱          ╲
  │╱            ╲  ← 几乎不下降：lr 太小
  └─────────────────→ log10(lr)
      10^-3    10^0
```

挑谷底附近的 lr（一般选谷底左侧一点，更保守）。

Karpathy 实验里他从 `lre = lre[i]` 改成 `lre = lre[i/10]`（步进更慢），发现最优 lr 大约在 `0.001` 附近，比之前的 `0.1` 小一个数量级。

**关键洞见**：loss 不是单调下降的，**lr 不应该用固定的**，可以随训练变化（学习率衰减）。

---

## 七、过拟合与 Train/Val/Test Split

如果只看训练 loss 不断下降，就误以为模型越来越好。**真正能反映泛化能力的是 validation loss**。

```
数据集 (18 万)
    ↓ 划分
┌─────────────┬───────────┬────────┐
│ train (80%) │ dev (10%) │ test   │
│ 训参数       │ 调超参数   │ 最终评估│
└─────────────┴───────────┴────────┘
```

**三划分是对抗过拟合的诊断工具，不是过拟合本身。**

### 什么时候用哪个 split？

| 任务 | 用什么 |
|------|--------|
| 训练参数（W, b, C） | train |
| 调超参（hidden size, lr, block_size...） | **dev** |
| 选模型（MLP vs Transformer vs ...） | **dev** |
| 报告最终性能 | **test（只用一次）** |

> ⚠️ **常见错误**：在 test 上调超参 → test 沦为第二个 dev，污染了最终评估。

### Overfitting 信号

训练 loss 持续下降，但 validation loss 不再下降 → 过拟合。模型在背训练集，没有学到泛化规律。

```
loss
  ↑  train loss ──╲___
  │                ╲___        ← 应该在这里停
  │                    ╲___
  ↑  dev loss   ─────────╲___
  │                  ↑    ╲___
  │               过拟合开始  
```

Karpathy 在视频里做了一个**极端实验**：只取一个 batch 训练，让 loss 几乎为 0。模型完全记住了那几个样本，但 val loss 很差。

```python
# 常见比例 80/10/10
import random
random.seed(42)
random.shuffle(words)
n1 = int(0.8 * len(words))
n2 = int(0.9 * len(words))

Xtr, Ytr = build_dataset(words[:n1])
Xdev, Ydev = build_dataset(words[n1:n2])
Xte, Yte = build_dataset(words[n2:])
```

---

## 八、模型可视化

训练完后，把 `C`（embedding 表）画出来看：

```python
plt.figure(figsize=(4, 4))
plt.scatter(C[:, 0].data, C[:, 1].data, s=200)
for i in range(C.shape[0]):
    plt.text(C[i, 0].item(), C[i, 1].item(), itoi[i])
```

观察发现：

- 元音（a, e, i, o, u）聚成一簇
- 辅音分布在外圈
- 字符的"语义相似性"在 2 维空间里被自然学到了

---

## 九、调优实验记录

Karpathy 在视频末尾展示了一轮完整的调优流程——这不是事先设计好的实验，而是**边调边看、边看边改**的迭代过程。把过程如实记录下来很值得学习。

### Stage 1：识别瓶颈

lr 从 0.1 降到合适值后，train/dev loss 稳定在 2.23 / 2.24，再降不下去。

```python
# 上面 LR Range Test 发现 lr ≈ 0.001 是最优
# 但 Karpathy 实际用了稍大一点的 lr（兼顾收敛速度）
# 最终 lr 调度: 前半 0.1, 后半 0.01
```

降不动的常见原因：
- 模型容量不够 → 加宽/加深
- **embedding 维度太小（=2）** ← Karpathy 的判断

### Stage 2：可视化 embedding 验证假设

```python
plt.figure(figsize=(4, 4))
plt.scatter(C[:, 0].data, C[:, 1].data, s=200)
for i in range(C.shape[0]):
    plt.text(C[i, 0].item(), C[i, 1].item(), itoi[i])
```

观察到的结构：

- **元音 a/e/i/o/u** 自动聚成一簇 → 网络把它们当作"可互换"的相似字符
- **q** 远离主簇 → 因为训练集中 q 极少，模型学不到它的协同模式
- **`.`** 也远离主簇 → 特殊 token，行为独特
- 辅音散开成一片 → 模型认为它们之间也有差异

这正是反向传播自动涌现出来的"语义结构"——**没用任何监督信息，纯粹从下一字符预测的损失里浮现**。

### Stage 3：扩大 embedding 维度

```python
# 改前
n_embd = 2
n_hidden = 300
block_size = 3
# 输入维度 = block_size * n_embd = 6

# 改后
n_embd = 10
n_hidden = 200
block_size = 3
# 输入维度 = 30  ← hardcoded 6 要同步改
```

⚠️ 坑：上面把 `6` 当 hardcoded magic number 用，扩 embedding 后必须同步改。生产代码应该用 `block_size * n_embd` 自动算。

参数量从 ~3000 涨到 ~11K，train 50K steps：

- train loss ≈ 2.30
- dev loss ≈ 2.38（**涨了一点**——但更多 step 应该能下来）

### Stage 4：阶梯式学习率衰减

继续做了一步关键动作：**lr × 0.1**：

```python
# 总共 200K steps
# 前 100K steps: lr = 0.1
# 后 100K steps: lr = 0.01
```

结果：
- train loss ≈ 2.17
- dev loss ≈ 2.20
- 训练和 dev 开始"慢慢分离" → **刚刚开始过拟合**

这个阶梯式衰减虽然粗暴，但抓住了本质：**训练前期大步走、后期小步精修**。

### Stage 5：从模型采样

训练完怎么生成新名字？用 sampling：

```python
g = torch.Generator().manual_seed(2147483647 + 10)

for _ in range(20):
    out = []
    context = [0] * block_size  # 全 . 开始
    while True:
        emb = C[torch.tensor([context])]  # (1, block_size, n_embd)
        h = torch.tanh(emb.view(1, -1) @ W1 + b1)
        logits = h @ W2 + b2
        probs = F.softmax(logits, dim=1)  # 内置防溢出
        ix = torch.multinomial(probs, num_samples=1, generator=g).item()
        context = context[1:] + [ix]
        out.append(ix)
        if ix == 0:
            break
    print(''.join(itos[i] for i in out))
```

生成结果示例：`ham`, `joes` 等，已经"听起来像名字"了。

Karpathy 在这里特别提了一句：**采样和评估是两件事**。loss 是对数似然的均值，反映模型对所有可能下一个字符的预测质量；而 sampling 是从这个分布里"抽一个"出来看效果。

---

## 十、与 Part 1 的对比

| 维度 | Part 1 (Bigram) | Part 2 (MLP) |
|------|-----------------|---------------|
| 上下文长度 | 1 | 3（可调） |
| 参数量 | 27² ≈ 729 | ~3000+ |
| 概率分布来源 | 频率统计 | 神经网络学习 |
| 关键技巧 | 拉普拉斯平滑 | embedding + tanh |
| Val loss | ~2.45 | < 2.17 |

MLP 的核心优势：**参数共享 + 非线性**。同一个字符在不同上下文里出现，embedding 是同一个，但 MLP 会根据上下文产生不同的预测。

---

## 思考与延伸

> 每一个词，对应一个多维度的向量。
>
> 随机 → 反向传播 → 语义聚集。

这是 Embedding 最精炼的一句话概括——网络里"没有预设任何语义"，所有语义结构都是从损失函数的梯度里**涌现**出来的。元音聚类、q 远离主簇，这些都不是人告诉模型的。

> 多层神经网络。
>
> 例子：
> The cat is walking in the bedroom
> A dog was running in a room
> → the cat is running in a __
> → 语义，room？
>
> 之前的"概率的统计"可能没办法做到。

这是 MLP 相比 bigram 最根本的飞跃。bigram 只能看 `(a, room)` 出现频率高，**完全无法跨过 `(bedroom, room)` 的"语义等价"**。而 MLP 因为 embedding 把 `bedroom` 和 `room` 放在相近的位置，配合非线性层，就能推断出"in a room" 的 `room` 比 "the bedroom" 更通用。

> C 表是干什么的：look-up table。字符索引 → 查 C 表 → 得到这个字符的向量表示。

C 表的本质就是"用整数索引查向量"——和查字典是一个意思。它和 one-hot × W 在数学上完全等价，只是写法更直接。

> `W1 = torch.randn((6, 100))` → 6 是输入特征数，100 是隐藏层神经元数。输入 6 维 → 经过 W1 → 变成 100 维 → 再 tanh 压缩到 [-1, 1]。

W1 形状的两个数字决定了 MLP 的"宽度变换"：左边是输入维度，右边是输出维度。整条链 `6 → 100 → 27` 就是把"上下文"先扩到高维提炼特征，再压回词表大小做分类。

---

## 总结

Part 2 把 bigram 升级到了 MLP，迈出了"深度学习"的关键一步。几个核心要点：

1. **滑动窗口 + padding**：构造训练数据的基础范式
2. **Embedding lookup**：把离散符号映射到连续空间
3. **MLP = view + linear + tanh + linear**：看似简单的堆叠已经能做语言模型
4. **交叉熵**：永远用 `F.cross_entropy`，别手写
5. **LR range test**：指数扫描是找最优学习率的实用技巧
6. **Train/Val/Test**：过拟合是默认会发生的事，必须有独立评估

下一步（Part 3）会进入更深的网络：更深、更宽、更复杂的架构——但基本套路已经完全建立起来了。