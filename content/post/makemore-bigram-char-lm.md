---
title: "用 makemore 理解语言模型：Bigram 字符级生成"
description: "Karpathy makemore 系列第一课：从最简单的 Bigram 模型开始，用统计方法生成看起来像名字的字符串，理解语言模型的核心思想"
date: 2026-07-04
slug: "makemore-bigram-char-lm"
tags:
  - 语言模型
  - Bigram
  - PyTorch
  - 生成模型
  - Deep Learning
math: true
categories:
  - 技术笔记
---

# 用 makemore 理解语言模型：Bigram 字符级生成

> 视频：[The spelled-out intro to language modeling: building makemore](https://www.youtube.com/watch?v=PaCmpygFfXo) by Andrej Karpathy
> 代码：[karpathy/makemore](https://github.com/karpathy/makemore)

---

## 1. 什么是 makemore

makemore 是一个字符级语言模型：给它一组名字（32,000 个真实人名），它能学会生成"听起来像名字"的全新字符串。

这不是检索——它生成的名字是训练集中没有的全新组合，比如 `Dontal`、`Irot`、`Zendy`。

整个 makemore 系列从最简单的 Bigram 模型开始，逐步演进到 Transformer，完整覆盖了现代语言模型的技术栈。

---

## 2. Bigram 模型：最简语言模型

### 核心思想

Bigram 的假设极其简单：**下一个字符只和当前字符有关**。

用概率语言描述：给定当前字符 $c$，生成下一个字符 $c'$ 的概率是 $P(c' | c)$。

这显然是个过于简化的假设——真实语言中下一个字符往往和前面很多字符都相关。但 Bigram 是个好起点：它足够简单，能让我们先理解语言模型的基本框架，再逐步加入复杂度。

### 从数据中学习概率

数据集是 32,000 个名字的文本文件，每行一个名字。

我们需要从数据中学习两个东西：
1. **词表**：所有出现的字符（英文字母 + 一个特殊结束符 `.`，共 27 个字符）
2. **转移概率表**：每个字符后面出现各个字符的频率

### 第一步：统计计数

用 Python 字典统计每个字符后面跟着各个字符的次数：

```python
# 遍历所有名字，统计 bigram 频率
bigram_counts = {}
for name in names:
    name = '.' + name + '.'  # 加上开始和结束标记
    for ch1, ch2 in zip(name, name[1:]):
        key = (ch1, ch2)
        bigram_counts[key] = bigram_counts.get(key, 0) + 1
```

`('.', 'a')` 的计数就是在所有名字中，字符 `.` 后面出现字符 `a` 的次数——也就是以 `a` 开头的名字的数量。

### 第二步：转成概率

用 Softmax 把计数转成概率分布：

```python
import torch

# 创建 27x27 的计数表
N = torch.zeros((27, 27), dtype=torch.int32)

# 填充计数...
for (c1, c2), count in bigram_counts.items():
    N[stoi[c1]][stoi[c2]] = count

# 归一化成概率（按行 softmax）
P = N.float()
P = P / P.sum(dim=1, keepdim=True)  # 每行加起来等于 1
```

现在 `P[i, j]` 就是当当前字符是 `i` 时，下一个字符是 `j` 的概率。

---

## 3. 生成名字：采样

有了概率表，生成一个名字很简单：

```python
def generate_name():
    name = []
    ix = 0  # 从开始符 '.' 开始
    while True:
        p = P[ix]  # 当前字符对应的概率分布
        ix = torch.multinomial(p, num_samples=1, replacement=True).item()
        if ix == 0:  # 0 是结束符 '.'
            break
        name.append(itos[ix])
    return ''.join(name)
```

`torch.multinomial(p, 1)` 按概率分布 $P$ 采样一个字符。这就是语言模型的"自回归"生成——每一步的输出作为下一步的输入。

生成结果示例：`Dontal`、`Irot`、`Zendy`、`Raxwin`、`Faydra`。

---

## 4. 评估模型：交叉熵损失

我们需要一个指标来衡量模型的好坏。

### 似然（likelihood）

对于一个名字（比如 `"alex"`），模型认为它有多合理？

$$L = \prod_{t} P(x_t | x_{t-1})$$

即每个 bigram 的概率乘积。概率越高，模型越"信任"这个名字。

### 负对数似然（Negative Log Likelihood）

连乘不好算，转成对数相加：

$$\text{NLL} = -\sum_{t} \log P(x_t | x_{t-1})$$

这个值叫做**负对数似然（NLL）**，是深度学习中最常见的损失函数形式。

### 交叉熵（Cross Entropy）

实际训练中，我们用**平均**负对数似然——除以 token 数量，消除序列长度的影响：

```python
log_likelihood = 0.0
count = 0
for name in names:
    name = '.' + name + '.'
    for ch1, ch2 in zip(name, name[1:]):
        prob = P[stoi[ch1]][stoi[ch2]]
        log_likelihood += torch.log(prob)
        count += 1

nll = -log_likelihood / count
print(f"Average NLL: {nll:.4f}")
```

NLL 越低，模型越好。NLL 的物理含义是：平均每个字符需要用多少"nats"（或 bits）来编码。

---

## 5. 从统计到神经网络

上面的方法是纯统计的——直接数频次，没有可学习的参数。下面把它改写成神经网络的形式。

### 一个神经元的视角

神经网络的 Bigram 本质上和一个神经元等效：

```python
# 单个神经元：W 是 27x27 的权重矩阵
logits = x @ W  # x 是 one-hot 向量 (27,)，W 是 (27, 27)
probs = F.softmax(logits, dim=0)
```

这里的 $W$ 相当于概率表的可参数化版本——不是直接存储概率，而是通过学习得到。

### 神经网络版本

```python
import torch.nn as nn

class BigramLM(nn.Module):
    def __init__(self, vocab_size):
        super().__init__()
        self.W = nn.Parameter(torch.randn(vocab_size, vocab_size) * 0.1)

    def forward(self, x):
        # x: (batch,)，token indices
        logits = self.W[x]  # (batch, vocab_size)
        return logits

    def generate(self, x):
        probs = F.softmax(self.W[x], dim=-1)
        return torch.multinomial(probs, num_samples=1)
```

训练循环：

```python
model = BigramLM(27)
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)

for step in range(5000):
    optimizer.zero_grad()

    # 前向：计算负对数似然
    xb, yb = get_batch()
    logits = model(xb)
    loss = F.cross_entropy(logits, yb)

    # 反向传播
    loss.backward()
    optimizer.step()
```

这就是语言模型训练的标准范式：前向 → 计算损失 → 反向 → 更新参数。

### 正向传播、反向传播与梯度下降

训练一个神经网络，就是不断重复以下三步：

**第一步：正向传播（Forward Pass）**

数据从输入流向输出。对于 Bigram，输入是字符 id 序列，输出是每个位置对下一个字符的预测分数（logits）：

```python
logits = W[xb]                  # (batch, 27)，每行是当前字符的 27 个分数
probs = F.softmax(logits, dim=-1)   # (batch, 27)，归一化成概率
loss = F.cross_entropy(logits, yb)  # 标量，loss 越大模型越差
```

**第二步：反向传播（Backpropagation）**

从 loss 出发，反向走一遍计算图，利用链式法则算出每个参数对 loss 的贡献——即梯度：

```python
loss.backward()   # PyTorch 自动维护计算图
                  # 沿着 .grad 属性填充 W 的梯度
print(W.grad)     # (27, 27)，形状同 W
```

梯度 $\frac{\partial \text{loss}}{\partial W}$ 的物理含义：**如果把 $W$ 的某个元素稍微增大一点，loss 会变大多少**。

- 梯度为正 → 该权重增加，loss 会变大（这个方向是"错的"）
- 梯度为负 → 该权重增加，loss 会变小（这个方向是"对的"，应该往这里走）

**梯度是怎么算出来的——链式法则**

反向传播的本质是**从 loss 出发，沿着计算图倒着求偏导**，利用链式法则把每一步的梯度乘起来。

以一个最简神经元为例：

```python
x = 1.0
w = torch.tensor([3.0], requires_grad=True)
y_true = 5.0

z = w * x        # 前向：z = 3
loss = (z - y_true) ** 2   # loss = (3-5)² = 4
```

反向传播（手算）：

```
loss 对 w 的梯度 = ∂loss/∂ŷ × ∂ŷ/∂z × ∂z/∂w
                 = 2(ŷ - 5)    ×    1      ×    x
                 = 2(3 - 5)    ×    1      ×    1
                 = -4
```

PyTorch 的 `backward()` 就是自动做了这件事——它维护了计算图（computation graph），知道每一步是怎么算的，链式法则一路传回去，`w.grad` 里就是 `-4`。

对应到 Bigram 的 W，计算图一样，只是更宽（27x27 的矩阵乘法），逻辑完全相同：

```
loss
  ↑
cross_entropy(logits, yb)
  ↑
softmax(logits)
  ↑
logits = W[xenc]   ← W 是 (27, 27)，xenc 是 (batch, 27)
  ↑
W (requires_grad=True)
```

`loss.backward()` 触发后，梯度沿这条链反向流回 W，填充 `W.grad`。

**第三步：梯度下降（Gradient Descent）**

用梯度来更新参数，往 loss 下降的方向走：

```python
W = W - learning_rate * W.grad
```

- 梯度指向 loss **增加**最快的方向，所以减梯度是往**下降**方向走
- 学习率（lr）控制每一步迈多大：太大容易震荡，太小收敛慢

```python
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)

for step in range(5000):
    optimizer.zero_grad()   # 清零上一步累积的梯度
    xb, yb = get_batch()
    logits = model(xb)
    loss = F.cross_entropy(logits, yb)
    loss.backward()         # 反向传播
    optimizer.step()         # 更新参数
```

**学习率（learning rate）**

```python
W = W - learning_rate * W.grad   # lr = 0.1 时，-0.1 * (-4) = +0.4
                                 # W 新值 = 3 + 0.4 = 3.4，loss 下降
```

`-0.1` 的**符号是固定的**（必须是负的，代表往梯度反方向走），但**具体大小是人为设定的超参数**。

| 学习率 | 效果 |
|--------|------|
| 太大（e.g. 1.0） | 容易跳过最优点，在最低点附近震荡，甚至发散 |
| 太小（e.g. 1e-6） | 能收敛，但极慢 |
| 合适（e.g. 1e-3） | 较快收敛到最优附近 |

实际训练中一般用 **AdamW** 优化器（自适应调整每个参数的有效学习率），不需要手动调 lr：

```python
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=1000)  # 学习率先升后降
```

---

## 7. 统计方法 vs 神经网络：对比

| 维度 | 统计方法（Counting） | 神经网络方法（Gradient） |
|------|---------------------|------------------------|
| **参数来源** | 直接从数据中数频次 | 随机初始化，通过梯度下降学习 |
| **概率表示** | $P(c'\|c) = \frac{N(c,c')}{N(c)}$ | $P = \text{softmax}(W[x])$，W 是可学习的 |
| **表达能力** | 受限于统计样本量，小样本有稀疏问题 | 可以泛化，没见过的 bigram 也能预测 |
| **更新方式** | 一次性计算，用新数据要重新统计 | 随时梯度更新，可以增量学习 |
| **参数量** | 固定 $27 \times 27 = 729$ | 也是 $27 \times 27 = 729$（Bigram 恰好同规模）|
| **核心思想** | 最大化似然（Maximum Likelihood） | 同样是最小化 NLL，但用梯度近似搜索 |

**核心相同点**：两者都在做同一件事——**最小化负对数似然（NLL）**。统计方法直接算解析解，神经网络用梯度迭代逼近。神经网络的 W 收敛后，和统计方法算出的概率表在数值上应该非常接近。

> 也正因为两者本质相同，当神经网络学习率过大时，最终 loss 也会停在一个和统计方法相近的位置（约 2.4~2.5），因为它们的表达能力上限是一样的。

**关键差异**：神经网络可以通过更深层的结构扩展上下文——从只看前 1 个字符，变成看前 N 个字符。这是二元统计方法无法做到的。

> 换个角度理解：二元方法的 W 是直接从数据中数出来的，神经网络的 W 是随机初始化后通过梯度优化"搜索"出来的。梯度下降的过程，本质上是把一个随机 W 不断调整，让它逐渐逼近 count 方法直接算出的概率分布。神经网络的代价更大（要迭代），但它的架构可以扩展到更长的上下文——这是统计方法永远做不到的。

---

## 8. 正则化

如果模型在训练集上的 loss 太低（接近 0），说明它开始"背诵"数据，泛化能力会变差。

**正则化**通过在损失函数中加入对模型参数的惩罚，防止模型过度拟合：

```python
# L2 正则化：惩罚大的权重
reg_loss = loss + reg_lambda * (W ** 2).mean()
```

`reg_lambda` 是正则化强度（通常 1e-4 到 1e-2）。这让权重不要太大，使模型输出更"平滑"。

### 正则化的物理图像：两股力量同时拉 W

正则化项 `λ * (W²).mean()` 的效果是**把 W 向 0 拉**——这和给统计计数加伪计数（pseudo-count）本质相同。

```
总损失 = 数据损失（让 W 匹配真实统计） + 正则化损失（把 W 拉向 0）
```

- 当 λ 很大时，正则化项主导，W 被迫趋近 0，softmax 输出趋近均匀分布（每个字符 1/27）
- 当 λ 很小时，数据项主导，W 可以自由学习真实分布

Andrej 的原话：**"这就像一个弹簧力，把 W 拉向 0，同时数据损失在拉 W 学真实分布。"**

这和统计方法里"给计数表加一个常数"的效果相同——都是让分布更平滑，避免对少量样本过度置信。

### 为什么 W 大了不好

softmax 的公式：

$$P_i = \frac{e^{W_i}}{\sum_j e^{W_j}}$$

- W 很大 → $e^{W_i}$ 巨大 → 某个概率接近 1 → **极度自信**
- W = 0 → 所有 $e^0 = 1$ → 概率完全均匀 → **完全不自信**

**根本问题**：语料中有些 bigram 只出现 1-2 次，统计概率极端，但这只是采样噪声，不代表真实分布。正则化惩罚大 W，迫使分布平滑——等价于给计数加伪计数。

> 注：在 Bigram 这个简单模型里，正则化效果不明显。它的威力在更大更深的模型（MLP、Attention）里才真正显现。

---

## 9. 采样：从模型生成名字

训练好 W 之后，从模型生成名字的过程和统计方法完全一致，只是概率来源从计数表变成了神经网络的 softmax 输出：

```python
def generate(model, itos, stoi, max_len=20):
    """从神经网络模型生成一个名字"""
    model.eval()  # 评估模式，关闭 dropout 等
    name = []
    ix = stoi['.']  # 从开始符 '.' 开始

    with torch.no_grad():  # 生成时不需梯度
        while len(name) < max_len:
            xenc = F.one_hot(torch.tensor([ix]), num_classes=27).float()
            logits = xenc @ model.W           # (1, 27)
            probs = F.softmax(logits, dim=-1)  # (1, 27)
            ix = torch.multinomial(probs[0], 1).item()  # 采样下一个字符
            if ix == 0:  # 遇到结束符，停止
                break
            name.append(itos[ix])

    return ''.join(name)

# 生成 5 个名字
for _ in range(5):
    print(generate(model, itos, stoi))
```

**自回归生成的循环**：

```
开始符 '.' (ix=0)
  ↓
one_hot([ix]) → (1, 27)
  ↓
@ W → logits → softmax → probs
  ↓
multinomial(probs) → 下一个字符 ix
  ↓
回到上一步，直到采样到 '.'（结束符）
```

### 两种方法殊途同归

Andrej 在视频最后演示了一件很有意思的事：神经网络训练收敛后，W 里的值和统计方法直接 count 出来的"对数计数"（log counts）完全相同。

这意味着：

- 统计方法：**一步直接算出概率表**
- 神经网络：**随机初始化 W，通过梯度下降迭代逼近同一个概率表**

两者生成的样本完全一样，因为它们本质上是同一个模型。神经网络的"代价"是绕了远路（迭代），但它的架构可以扩展——这是统计方法做不到的。

---

## 10. 几个关键概念的直观理解

| 概念 | 直观理解 |
|------|---------|
| Bigram | "今天吃了__"，填什么字只和"吃了"有关 |
| One-hot + W 相乘 | 从权重表里"查"出当前字符对应的行 |
| Softmax | 把原始分数变成概率分布（所有概率加起来 = 1）|
| 交叉熵损失 | 负对数似然的平均值，越小越好 |
| 正则化 | 惩罚大的权重，防止过拟合；等价于给计数加伪计数 |
| torch.multinomial | 按概率分布采样，概率高的字符更容易被选中 |
| 自回归生成 | 每一步的输出作为下一步的输入，循环直到采样到结束符 |

---

## 11. 总结

Bigram 是理解语言模型的最佳起点，因为它足够简单，能让我们看清楚整个框架：

1. **从数据中统计**字符转移概率
2. **用概率分布**生成新序列
3. **用交叉熵**衡量模型质量
4. **把统计表参数化**成神经网络，通过梯度下降学习

下一步就是把这个单字符模型扩展成更长的上下文——让模型不仅看前 1 个字符，而是看前 N 个字符。这就是 Attention 和 Transformer 要解决的问题。
