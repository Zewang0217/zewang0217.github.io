---
title: "安全教材：从网络与系统安全到模型与 Agent 安全（目录）"
description: "面向模型安全研究准备的学习路线，覆盖网络、系统、软件、供应链、测试，以及 LLM、Skill 和 Agent 安全。"
date: "2026-10-15T00:00:00+08:00"
lastmod: "2026-10-15T00:00:00+08:00"
slug: "security-textbook"
tags: ["网络安全", "系统安全", "模型安全", "Agent"]
categories: ["学习笔记"]
series: ["安全教材"]
math: false
draft: false
toc: true
---

这个系列从网络与系统安全出发，逐步研究模型、Skill 和 Agent 的安全问题。关键概念采用中英双语，正文配合架构图、论文、工业案例与研究练习。

从 [第 1 章：一个恶意 Skill 究竟攻破了什么？](/p/security-textbook-01-security-model/) 开始阅读。本页作为固定目录，后续更新沿用相同网址。

本教材以网络与系统安全建立共同基础，以模型、Skill 和 Agent 系统检验这些基础的适用范围。读者学过操作系统和计算机网络，已有 skill 安全研究经验。

当前完成第 1、2 章，其余条目为写作计划。章节编号表示知识结构，实际阅读顺序可以随研究需要调整。

## 从案例进入安全建模

1. [一个恶意 Skill 究竟攻破了什么？](/p/security-textbook-01-security-model/)：资产、安全属性、威胁模型、信任边界与可验证的要求。已完成。
2. [怎样刻画攻击者？](/p/security-textbook-02-attacker-model/)：攻击面、控制能力、黑盒与白盒、预算、入口与影响。已完成。
3. 权限怎样分配：最小权限、完全中介、默认拒绝、可信计算基。
4. 人与组织怎样影响安全：激励、可用性、风险管理、安全经济学。

本篇的学习成果是一份能被其他研究者复核的系统描述和威胁模型。以 CyBOK 定位知识范围，以 Anderson 的教材连接技术和现实约束。[1](#ref-1)[2](#ref-2)

## 网络与分布式系统怎样建立信任

5. 密码学构件怎样组合：加密、认证、签名、随机性和密钥管理。
6. TLS 为什么这样设计：身份、握手、信道、重放和协议假设。
7. 名称、路由和流量：DNS、路由安全、流量分析与拒绝服务。
8. Web、API 与分布式身份：源、会话、跨站边界、服务身份和委托。

本篇从 TLS 的具体协议推导到服务之间的信任，借 BeyondCorp 研究访问控制怎样摆脱对网络位置的过度依赖。[3](#ref-3)[4](#ref-4)

## 系统怎样约束已经运行的组件

9. 内存安全与利用链：越界、释放后使用、控制流与缓解机制。
10. 内核、进程与权限：用户态、内核态、对象和系统调用。
11. Capability 与代理混淆：命名、权限、委托与权限衰减。
12. 沙箱、容器与虚拟机：隔离对象、接口暴露、逃逸与资源限制。
13. 信息流与侧信道：保密性、完整性、显式与隐式流、非干扰。

Chromium 和 gVisor 用于分析真实隔离架构；信息流综述用于理解“允许读”和“允许传播”之间的关系。[5](#ref-5)[6](#ref-6)[7](#ref-7)

## 软件怎样进入产品，并在运行中被维护

14. 输入、解析和业务逻辑：注入、语义不一致、路径与状态错误。
15. 供应链：依赖、构建、来源证明、签名、更新和撤销。
16. 安全开发与漏洞管理：设计审查、修复、回归与披露。
17. 检测、响应与恢复：日志、攻击行为、告警、取证和恢复目标。

Sigstore 与 SLSA 用于区分来源可信与行为安全；ATT&CK 用于组织攻击行为和检测案例。[8](#ref-8)[9](#ref-9)[10](#ref-10)

## 怎样寻找失败，并评价安全证据

18. 测试什么：安全属性、判定标准、覆盖范围与测试预言机。
19. 程序分析：静态分析、污点分析、符号执行与混合方法。
20. Fuzzing：生成、变异、覆盖率、语法、状态与差分测试。
21. 红队与形式化方法：攻击展示、系统性搜索、验证与证明假设。
22. 可信评测：随机性、预算、公平比较、去重、泛化与复现。

从 fuzzing 综述了解方法空间，用评测方法论文检查证据质量，再看 OSS-Fuzz 如何把测试变成持续工程流程。[11](#ref-11)[12](#ref-12)[13](#ref-13)

## 模型与 Agent 增加了哪些攻击面

23. 对抗机器学习全景：逃逸、投毒、后门、隐私攻击与模型窃取。
24. LLM 应用：越狱、间接提示注入、RAG、上下文和资源滥用。
25. Skill 与工具：说明、脚本、依赖、发现、加载、更新和协议生态。
26. Agent 工作流：身份、权限、记忆、多 agent 消息与复合副作用。
27. 运行时防御：工具代理、策略执行、凭据、网络和文件边界。
28. Agent 评测：攻击可达性、适应性攻击、正常任务表现与真实副作用。

NIST 报告提供分类；间接提示注入论文和 AgentDojo 提供应用与评测视角；安全设计模式用于讨论架构约束及其功能代价。[14](#ref-14)[15](#ref-15)[16](#ref-16)[17](#ref-17)

## 怎样形成一个可以推进的研究问题

29. 读论文：问题、假设、机制、证据、相关工作与结论范围。
30. 综合项目：为合成研究助手建立威胁模型、权限设计和评测方案。

每章的研究练习围绕当前机制提出问题。先能描述失败，再设计对照，随后讨论可以推广的结论。AI 用于漏洞发现、测试或防守作为应用支线，和 AI 系统自身安全分别讨论。

## 建议阅读顺序

先读第 1 至 3 章，随后进入权限委托、信息流、运行时隔离和评测。网络、密码学、内存安全与运营章节按全书顺序补齐。每篇首次出现的新概念都有解释，不要求先把所有参考书读完。

硬件、移动、物联网与工控、恶意软件分析、数字取证、隐私技术将设扩展章。这些主题先在全景中定位，需要时再深入，不把“知道名称”记作掌握机制。

## 参考文献

以下为教材骨架书目，不表示每篇已全文精读；具体阅读范围见各章文末与资料记录。动态资料核查日期为 2026-10-15。

<a id="ref-1"></a>
1. CyBOK. [Cyber Security Body of Knowledge](https://www.cybok.org/). 全局知识覆盖与分领域参考。

<a id="ref-2"></a>
2. Ross Anderson. [Security Engineering, Third Edition](https://www.cl.cam.ac.uk/archive/rja14/book.html), 2020. 主教材，作者页面提供章节。

<a id="ref-3"></a>
3. Eric Rescorla. [RFC 8446: The Transport Layer Security (TLS) Protocol Version 1.3](https://www.rfc-editor.org/rfc/rfc8446), 2018. 协议案例。

<a id="ref-4"></a>
4. Rory Ward, Betsy Beyer. [BeyondCorp: A New Approach to Enterprise Security](https://research.google/pubs/beyondcorp-a-new-approach-to-enterprise-security/), 2014. 企业访问控制案例。

<a id="ref-5"></a>
5. Chromium Project. [Secure Architecture](https://www.chromium.org/Home/chromium-security/guts/). 进程和隔离设计。

<a id="ref-6"></a>
6. gVisor Authors. [Security Model](https://gvisor.dev/docs/architecture_guide/security/). 威胁模型、保护范围与残余风险。

<a id="ref-7"></a>
7. Andrei Sabelfeld, Andrew C. Myers. [Language-Based Information-Flow Security](https://www.cs.cornell.edu/andru/papers/jsac/sm-jsac03.pdf), 2003. 信息流安全综述。

<a id="ref-8"></a>
8. Sigstore. [Documentation](https://docs.sigstore.dev/). 制品签名与透明日志。

<a id="ref-9"></a>
9. SLSA. [Specification v1.2](https://slsa.dev/spec/v1.2/). 供应链来源证明。

<a id="ref-10"></a>
10. MITRE. [ATT&CK](https://attack.mitre.org/). 攻击行为知识库。

<a id="ref-11"></a>
11. Valentin J. M. Manès et al. [The Art, Science, and Engineering of Fuzzing: A Survey](https://arxiv.org/abs/1812.00140), 2018 起始预印本. Fuzzing 方法空间。

<a id="ref-12"></a>
12. George Klees et al. [Evaluating Fuzz Testing](https://arxiv.org/abs/1808.09700), CCS 2018. 实验设计与评价有效性。

<a id="ref-13"></a>
13. Google. [OSS-Fuzz](https://github.com/google/oss-fuzz). 持续 fuzzing 工业项目。

<a id="ref-14"></a>
14. Apostol Vassilev et al. [Adversarial Machine Learning: A Taxonomy and Terminology of Attacks and Mitigations](https://csrc.nist.gov/pubs/ai/100/2/e2025/final), NIST AI 100-2 E2025. 模型攻击分类。

<a id="ref-15"></a>
15. Kai Greshake et al. [Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection](https://arxiv.org/abs/2302.12173), 2023. 间接提示注入。

<a id="ref-16"></a>
16. Edoardo Debenedetti et al. [AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents](https://arxiv.org/abs/2406.13352), 2024. 任务环境中的攻防评测。

<a id="ref-17"></a>
17. Luca Beurer-Kellner et al. [Design Patterns for Securing LLM Agents against Prompt Injections](https://arxiv.org/abs/2506.08837), 2025. 受约束架构中的安全设计。
