---
title: "HTTP 全解：报文、头部、方法、CORS 与状态码"
description: "Sriniously「Backend from first principles」第 5 集前 55 分钟忠实转写：无状态与客户端-服务器两个前提、报文与四类头部、方法的意图与幂等性、simple 与 preflighted 两条 CORS 路径、1xx–5xx 状态码逐条语义，附 Burp 实机报文。"
date: 2026-10-30
slug: "backend-first-principles-03-http"
tags:
    - 后端
    - HTTP
    - 学习笔记
categories:
    - 学习笔记
math: false
draft: false
---

# HTTP 全解：报文、头部、方法、CORS 与状态码

第 5 集全长 78 分钟，是全系列最长的一集，也是唯一一集用 Burp Suite 做全程实机演示的。开场他先划范围：后端太大，"if we start discussing every single component that could be part of it, we'd be stuck here for years"，所以只讲**大多数代码库里会出现的 90%**。

这篇覆盖前 55 分钟，一直到状态码演示结束：两个底层前提、传输层位置、报文结构、头部的作用与分类、方法语义与幂等性、CORS 的两条路径与实机验证、状态码逐条语义。最后 23 分钟（缓存、压缩、协议版本细节、内容协商）单独一篇。

## 两个底层想法

![第 5 集 00:40：提纲只有两行，1. Stateless、2. Client-server model](f09-http-concept.png)

### 一、无状态

他的定义只有一句："it has no memory of past interactions"。

**每个请求自带服务器需要的全部信息。** headers、URL、method 都在请求里，服务器不必回忆上一次。

**服务器响应后就把这个请求忘了。** 客户端再发一次，服务器把它当作全新的、无关的事件处理。

**因此请求相互独立。** 因为不记得上次，每个请求都必须自带凭证。他的例子是访问用户资料：客户端要在**每一次**请求里带 cookies 或 tokens，服务器才知道这次是谁在要数据。

这样设计换来两个好处：

**简单。** 服务器不用存 session，省掉相应的资源与复杂度。

**可扩展。** 请求可以分发到任意一台服务器，因为没有任何一台需要跟踪会话；而且**某台服务器挂了，客户端交互的状态不受影响**，因为压根没有会话或请求记忆需要重建。

代价他也说了：正因为 HTTP 无状态，开发者才需要自己实现状态管理，cookies、sessions、tokens 干的就是这件事，用在登录、购物车这类需要连续性的场景。这部分系列后面单独讲。

### 二、客户端–服务器模型

**客户端**通常是浏览器或应用，负责**发起**连接、发出请求，并提供服务器需要的全部信息（资源 URL、headers 等）。

**服务器**持有资源（网站、API 或其他内容），等待请求；收到后处理并返回合适的响应：网页、数据、错误信息、JSON、文本文件。

他额外强调一条协议层约定：**连接总是由客户端发起**，去换取某个特定响应。

还有一个简化约定：整段讨论里可以把 HTTP 和 HTTPS 视为互换。HTTPS 就是 HTTP 加上加密与安全证书（TLS）的版本，基本原理相同，"which borders too much on the realm of network engineering"。

## HTTP 站在哪一层

客户端和服务器得先建立某种连接机制，否则无从通信。HTTP 选择的介质是 **TCP**。

这里有个容易忽略的细节：HTTP 本质上**不要求**底层协议是面向连接的，它只要求**可靠、不丢消息**（真丢了至少以错误形式暴露）。互联网上最常见的两个传输协议是 TCP 与 UDP，TCP 更可靠，所以 HTTP 建立在 TCP 之上。

![第 5 集 05:20：OSI 七层图，讲者指出后端工程师日常打交道的范围是 Application (Layer 7)](f11-osi.png)

他顺手把 **OSI 模型**摆出来定位：后端日常活动在**第七层（应用层）**。TCP 三次握手、连接建立、TLS 加密这些偏网络工程，"it's going to be a rabbit hole"，所以他只做必要回顾。他那句话里也承认这些边界"确实值得知道"，只是不值得在这个系列里展开。

协议版本也在这里一次讲完：

| 版本 | 变化 |
|---|---|
| HTTP/1.0 | 每个请求新开一条连接，请求与响应各建一次、关一次，性能差 |
| HTTP/1.1 | **持久连接**（同一条 TCP 连接上跑多个请求响应）、chunked transfer encoding、改进的缓存机制 |
| HTTP/2.0 | **多路复用**（单连接并发多个请求）、**二进制分帧**代替文本、**HPACK** 头压缩、server push |
| HTTP/3.0 | 建在 **QUIC**（跑在 UDP 上）之上：建连更快、延迟更低、丢包处理更好，并解决 HTTP/2 仍然存在的**队头阻塞** |

收束句是："all we need to remember is that client and servers establish some kind of network connection, and messages are sent and received"。

## 报文：两份原文

他用的是一份**故意写复杂**的报文，"so that we could cover the different components one by one"。下面是这块幻灯片的原文。

请求报文：

```http
PUT /api/users/12345 HTTP/1.1
Host: example.com
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36
Content-Type: application/json
Content-Length: 123
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Accept: application/json
Accept-Encoding: gzip, deflate, br
Connection: keep-alive
Referer: https://example.com/dashboard
Cookie: sessionId=abc123xyz456; lang=en-US

// a blank line here means, everything has been sent

{
  "firstName": "John",
  "lastName": "Doe",
  "email": "john.doe@example.com",
  "age": 30
}
```

响应报文：

```http
HTTP/1.1 200 OK
Date: Fri, 20 Sep 2024 12:00:00 GMT
Content-Type: application/json
Content-Length: 85
Server: Apache/2.4.41 (Ubuntu)
Cache-Control: no-store
X-Request-ID: abcdef123456
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
Set-Cookie: sessionId=abc123xyz456; Path=/; Secure; HttpOnly
Vary: Accept-Encoding
Connection: keep-alive

// a blank line here means, everything has been sent

{
  "message": "User updated successfully",
  "userId": 12345,
  "status": "success"
}
```

![第 5 集 08:00：左右两栏对照 REQUEST 与 RESPONSE，每个构件都标了注释，包括空行的含义](f12-messages.png)

按他的讲解顺序拆开：

**请求行**：方法是 `PUT`，资源是 `/api/users/12345`，HTTP 版本 1.1（他说这是目前用得最广的版本）。

**头部**：逐行都是 key-value，`Host` 是目标域名。

**空行**：他特意指出这一行的作用，"to signify that the headers are complete and the body begins"。

**请求体**：客户端要送出去的数据，这里是 JSON。

响应报文对称：状态行由 HTTP 版本、状态码、原因短语组成（`200` 表示 OK），然后响应头、空行、响应体。

## 头部为什么要单独一层

![第 5 集 11:30：请求头一栏，User-Agent、Authorization、Cookie、Accept 各有注释](f13-request-headers.png)

他先给定义：头部就是**键值对**，"key-value pairs of various parameters that are sent via a request or received via a response"。

接着他自问：为什么不把这些值塞进 URL 或请求体，为什么要多一层抽象？

回答用的是包裹的类比：寄包裹时，收件人地址、电话写在**包裹外面**，不塞进去。因为中转的人（快递、分拣、转运）需要这些信息才能送货；写在里面，每个经手的人都要拆开看一遍，别人想看地址又得再拆一次。写在表面，任何人扫一眼就能确认元数据。

HTTP 头部就是报文表面的那层标注：**元数据与载荷分离，中间环节不解析正文也能读懂这个请求**。他补了一句，头部的作用比包裹标签更多，下面四类就是。

## 四类头部

![第 5 集 13:00：表示头（Content-Type、Content-Length、Content-Encoding、ETag）与安全头（HSTS、CSP、X-Frame-Options、X-Content-Type-Options、Set-Cookie）两栏对照](f14-rep-security-headers.png)

**请求头（request headers）**：客户端发给服务器，描述请求本身。`User-Agent` 说明客户端类型（浏览器、邮件客户端、服务端、移动应用）；`Authorization` 携带凭证，比如 bearer token，用来标识用户；`Accept` 系列说明期望拿到的内容类型（JSON、文本、HTML）。作用是让服务器理解客户端的**环境、偏好与能力**。

**通用头（general headers）**：请求与响应都会用，描述报文自身。消息日期、缓存控制（`no-cache`、`max-age`）、连接控制（`keep-alive`、`close`）。

**表示头（representation headers）**：只关心被传输资源的表示形式。`Content-Type` 是媒体类型（JSON 或 HTML）；`Content-Length` 是字节数；`Content-Encoding` 是编码方式（gzip、deflate）；`ETag` 是唯一标识，主要给缓存用。它们保证双方都知道"这段正文该怎么解释"。

**安全头（security headers）**：通过控制浏览器行为提升安全性。`HSTS` 强制只走 HTTPS，防协议降级攻击；`Content-Security-Policy` 限制 JS、CSS、图片能从哪里加载，缓解 XSS；`X-Frame-Options` 禁止页面被嵌进 iframe，缓解点击劫持；`X-Content-Type-Options` 阻止浏览器猜 MIME 类型，防类型嗅探；带 `HttpOnly` / `Secure` 的 cookie 让 JavaScript 读不到、且只走 HTTPS。

## 头部带来的三种能力

**可扩展性。** 加头部不需要改协议本身：加一层元数据，交互流程就变了。开发者还能定义自己的 `X-` 头满足特定业务需求。他给的正例就是安全头这一路的演进：协议没改，防护能力一路加上去。

**内容协商。** `Accept`、`Accept-Language`、`Accept-Encoding` 让服务器按客户端偏好返回同一份内容的不同版本。

**远程控制。** 他把头部形容成客户端对服务器的"遥控"：客户端用 `Accept` 指定格式，服务器就返回该格式（要 HTML 给 HTML，要 JSON 给 JSON）；服务器用 `Cache-Control` / `Expires` 决定客户端能缓存多久；客户端用 `Authorization` 影响服务端的访问控制决策。

## 方法：承载"意图"

![第 5 集 17:50：白板列出 GET、POST、PUT、PATCH、DELETE，旁边圈出 Intent](f15-methods-table.png)

他对方法的定位是一个词：**意图**（intent）。"Instead of every request doing the same thing, methods define intent"，这是交互的意图，给每类动作一个明确的语义。

| 方法 | 意图 | 他的补充 |
|---|---|---|
| `GET` | 取数据 | **不应改变服务器上的任何东西** |
| `POST` | 创建数据 | 有请求体，否则没法把用户数据传上去 |
| `PATCH` | 更新数据 | 请求体带要改的字段，比如改用户资料里的名字 |
| `PUT` | 更新数据 | 请求体**完整替换**旧实例；`PATCH` 是追加或选择性替换 |
| `DELETE` | 删除资源 | 按名字理解 |
| `OPTIONS` | 询问服务器能力 | 开发者很少直接调，会在浏览器 network 面板里看到，它就是 CORS 预检用的 |

`PATCH` 与 `PUT` 那段他说得挺直：很多开发者在该用 `PATCH` 的地方用了 `PUT`，违背语义。他的经验法则是**除非有明确的 `PUT` 场景，否则用 `PATCH`**。

这个规矩在状态码那节还会回头咬人：`405` 的常见成因就是前端把 `PUT` 写成了 `PATCH`，或者把 `POST` 写成了 `PUT`。

### 幂等性

![第 5 集 19:50：白板把幂等与非幂等分成两栏，GET / PUT / DELETE 归幂等，POST 归非幂等](f16-idempotent-table.png)

幂等（idempotent）的意思是：可以调用多次，结果与调用一次相同。

**幂等的三个**：

`GET` 取多少次数据都一样，本来就不该改服务器；`PUT` 完整替换，替换多少次结果都一样；`DELETE` 删第一次就没了，再删同一个资源结果仍然一致。

**非幂等的一个**：`POST`。他举的例子是发笔记：第一次 POST 创建一条笔记，第二次同样的 POST 又创建一条，同一个请求产生两个不同结果。

这个划分的实际意义在于重试：网络抖动时客户端想重发，幂等方法重发是安全的，`POST` 重发就可能多出一条记录。

## CORS：浏览器替你拦

方法讲完，他把 `OPTIONS` 和 CORS 的关系摆出来，作为下一段的引子。

![第 5 集 21:50：白板标题 CORS — same origin，下面两条分支 ① Simple request、② Preflighted request](f18-cors-types.png)

先给定义：浏览器默认遵循**同源策略**（same-origin policy），限制网页向"提供这个页面的域"以外的域发请求。CORS 是浏览器用来控制这类跨源交互的**安全机制**。没有它，浏览器会以安全为由拦掉从一个源（如 `example.com`）发往另一个源（如 `api.example.com`）的请求；有了它，服务器就能声明"谁能访问我的资源、怎么访问"。

他给了两个域名做对照：前端 `example.com`，API `api.example.com`，然后分成两条路径讲。

### 路径一：简单请求

![第 5 集 23:00：Simple Request 幻灯片，蓝色 example.com 与橙色 api.example.com 各一段报文](f19-simple-request.png)

流程按他的讲解拆开：

1. 客户端发请求，浏览器**自动加上 `Origin` 头**，标明请求来自哪里
2. 请求用的是"简单方法"（通常是 `GET`、`POST`、`HEAD`）
3. 服务器拿 `Origin` 和自己的 CORS 策略比对
4. 如果允许，服务器在响应里带上 `Access-Control-Allow-Origin`
5. 浏览器检查这个头：值等于客户端 origin，或者是 `*`（允许所有源），才把响应交给发请求的 JavaScript；否则**阻止客户端读取响应**

幻灯片原文：

```http
GET /api/products/123 HTTP/1.1
Host: api.anotherdomain.com
Origin: https://example.com
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Access-Control-Allow-Origin: https://example.com

{
  "product": {
    "id": 123,
    "name": "Example Product",
    "price": 29.99
  }
}
```

他特别指出拦截发生的时机：服务器**并没有拒绝处理请求**，是被浏览器在解析响应时挡下的。表现是浏览器控制台报错、network 面板里标成 CORS 错误。

### 路径二：预检请求

![第 5 集 25:30：Preflighted Request 的三个触发条件，第二条被红笔圈出](f20-preflight-request.png)

浏览器在发真实请求之前要先确认服务器能力，判断依据是三个条件，**满足任意一个**就要预检：

1. 方法不是 `GET`、`POST`、`HEAD`（例如 `PUT`、`DELETE`）
2. 请求带了非简单头（例如 `Authorization`、`X-Custom-Header`）
3. `Content-Type` 不是 `application/x-www-form-urlencoded`、`multipart/form-data`、`text/plain` 之一

他顺手点出一个后果：因为前后端大量用 JSON 通信，`application/json` 不在允许列表里，所以**日常大多数请求都会触发预检**。

预检请求本身长这样（幻灯片原文）：

```http
OPTIONS /api/resource HTTP/1.1
Host: api.anotherdomain.com
Origin: https://example.com
Access-Control-Request-Method: PUT
Access-Control-Request-Headers: Authorization
```

```http
HTTP/1.1 204 No Content
Access-Control-Allow-Origin: https://example.com
Access-Control-Allow-Methods: PUT, DELETE
Access-Control-Allow-Headers: Authorization
Access-Control-Max-Age: 86400
```

![第 5 集 27:40：预检请求与响应原文，服务器用 204 作答，四个 Access-Control-* 头逐一列出](f21-options-response.png)

四个响应头各管一件事：

| 头 | 作用 |
|---|---|
| `Access-Control-Allow-Origin` | 允许哪个源，或者 `*` 表示全部 |
| `Access-Control-Allow-Methods` | 这个资源允许哪些方法 |
| `Access-Control-Allow-Headers` | 允许哪些非简单头 |
| `Access-Control-Max-Age` | 这套结论缓存多久（秒），期间不必重复预检 |

他解释 `Max-Age` 的价值：如果每个请求前都预检一次，服务端和客户端都要多花一份带宽；缓存住授权结论就能省掉重复问询。预检只用 `OPTIONS`，不带请求体也不该有响应体，这就是 `204` 的由来。

## 实机验证：Burp 加两个本地端口

![第 5 集 30:00：左边演示页只有两个按钮（Fetch Product 触发简单请求、Update Resource 触发预检），右边 Burp 的 HTTP history 还是空的](f22-burp.png)

他先立规矩：这一集和后面所有演示**都不看代码**，只用 Burp 观察 HTTP 流量，"it doesn't matter what language the server is written in or what framework"，重点在机制本身。

演示环境是两个本地端口：前端 `localhost:5173`，API `localhost:3001`。他强调这在浏览器眼里就是**跨源**：同源要求协议、域、端口三者一致，端口不同即不同源。

**简单请求那一轮**：先跑一次普通请求，响应正常渲染；然后在请求里确认两件东西，`Origin`（前端来源）和 `Host`（要连的 API）；再在响应里确认 `Access-Control-Allow-Origin` 的值是 `5173` 端口或 `*`。

**摘掉响应头那一轮**：他改服务端，删掉 `Access-Control-Allow-Origin`，清掉网络面板历史后再发同一个请求。结果浏览器直接拦下，报错原因是跨源被阻断，因为请求跨源而响应没有那个头。

**预检那一轮**：把 CORS 恢复后重发，网络面板里**先出现 `OPTIONS`，再出现原始请求**。逐个点开看：

- 预检：方法 `OPTIONS`，跨源，服务器回 `204`（无内容，因为预检只是问能力，没有 body）
- 预检响应头：`Access-Control-Allow-Origin` 给出前端端口；`Access-Control-Allow-Methods` 列出 `GET, POST, PUT, DELETE`；`Access-Control-Allow-Headers` 列出 `content-type` 与 `authorization`；`Access-Control-Max-Age` 他故意设成 `0` 方便反复测试（设大了预检就不会重复发生）
- 原始请求：`PUT`，带 `Origin`、`Authorization`、`Host` 和请求体

他顺带解释为什么这一轮必然走预检：方法不是简单方法（`PUT`）、带了 `Authorization`、`Content-Type` 是 `application/json`，**三个条件全中，任一条就够**。

## 状态码：先分五位，再逐条

![第 5 集 41:50：白板把 1xx–5xx 摆成一张分类图，Information / Success / Redirection / Client error / Server error](f24-code-grid.png)

他给状态码的定位是"标准化地表达结果"：客户端不用读 body 去猜这次是成功、失败还是服务器挂了；`401` 就直接触发重新登录，`400` 就提示用户改表单再提交；而且这套数字在所有语言、所有平台上是**同一个标准**，Python、Go、Rust、JS、Ruby 写出来的服务都得守。他也补了历史：在状态码出现之前，客户端只能靠响应内容猜结果，于是各家做法不一。

分类靠首位数字：`1xx` 信息、`2xx` 成功、`3xx` 重定向、`4xx` 客户端错误、`5xx` 服务端错误。

### 1xx

`100 Continue`：客户端先发头，服务器表示同意接收，客户端再发 body。典型场景是**大负载上传**，先探路再传数据。

`101 Switching Protocols`：服务器按客户端请求切换协议，比如从 HTTP 切到 WebSocket。

他说这两个日常很少见，重点在后面四类。

### 2xx

`200 OK`：请求成功，服务器返回了资源或执行了动作。最常见的那个。

`201 Created`：请求完成并**创建了新资源**，用于提交表单、发帖这类操作。

`204 No Content`：成功但没有内容。他给两个场景：CORS 预检（前面刚见过），以及删除请求——资源删了，没有内容要返回。

### 3xx

`301 Moved Permanently`：资源永久搬到新 URL，后续请求都该用新地址。他的例子是把 `/user` 改成 `/person`，为了不让老客户端炸掉，给旧路由加 301 跳过去。

`302 Found`（临时重定向）：资源暂时在别处，但客户端**后续仍该用原 URL**。场景是活动期间把某个路由临时导向新页面，活动结束就撤掉。

`304 Not Modified`：资源自上次请求以来没变。它和**条件 GET** 配合：客户端带 `If-None-Match`（ETag）去问，服务器回 304 表示"没改，用你本地缓存的那份"，省掉一次正文传输。他明确说这个后面看缓存演示时会再见到。

### 4xx

![第 5 集 51:45：白板左列 4xx 逐个写下来（400、401、403、404、405、409、429），右列 5xx（500 与 503 被圈出）](f26-5xx.png)

他先说了句实话：作为后端工程师，日常处理最多的是 4xx，因为那是客户端行为引起的。

`400 Bad Request`：数据本身有问题。他举的例子是类型不符：你期望一个数字，客户端发了数组或字符串；你期望 email，客户端发了电话号码。

`401 Unauthorized`：请求需要认证，但客户端没提供有效凭证，或者根本没认证。典型是期望 JWT，结果 token 过期或压根没带。

`403 Forbidden`：服务器理解请求但**拒绝授权**，而且**在客户端已认证的情况下也会发生**。例子：你是用户 A，去删用户 B 的资源。

`404 Not Found`：请求的资源不存在，URL 错了或者资源已被删除。他说这是最有名的状态码。

`405 Method Not Allowed`：用了不合适的方法，比如向一个只接受 `GET`/`POST` 的资源发 `POST`。他补了一个很真实的成因：前端写错，本该 `PUT` 写成了 `PATCH`，该 `POST` 写成了 `PUT`。

`409 Conflict`：冲突。例子是应用允许用户建文件夹且要求名字唯一，用户提交一个已存在的名字，服务器就回 409，让客户端换个名字。

`429 Too Many Requests`：限流。比如服务端配置了每个客户端每秒最多 60 个请求，超了就回这个码。

### 5xx

`500 Internal Server Error`：服务器出现未预料的情况，某个流程崩了、抛了没人接的异常。他的说法是：与其返回空响应、直接中止或者一直挂着，不如回 500 让客户端知道是**服务端**出了问题。

`501 Not Implemented`：服务器不支持请求的方法或功能，但计划近期支持。用这个码把"还没做"的意图传达出去。

`502 Bad Gateway`：服务器在充当代理（负载均衡、反向代理）时，从上游拿到无效响应。他强调这通常不是业务代码主动返回的，而是代理层、负载均衡层产生。

`503 Service Unavailable`：服务暂时不可用，比如流量高峰或正在维护，让客户端稍后再试。

`504 Gateway Timeout`：和 502 类似，但专指上游**在等待时间内没有响应**。他的例子是 nginx 等不到背后的服务，于是由 nginx 返回 504。

他说这组加起来覆盖了 95% 的使用场景。

## 状态码演示：真实报文

![第 5 集 53:40：演示页按状态码排了一列按钮，右边是 Burp 里同一个请求的原始报文（POST /api/create 得到 201 Created）](f27-demo-status.png)

演示页左侧列着一串按钮：`200 OK`、`201 Created`、`204 No Content`、`400 Bad Request`、`401 Unauthorized`、`403 Forbidden`、`404 Not Found`、`409 Conflict`、`500 Internal Server Error`、`503 Service Unavailable`，服务端按不同路由返回对应状态码。

他全部点一遍，然后回网络面板逐个看。第一个观察是：**每个原始请求前面都跟着一个 `OPTIONS`**，因为前端在 `5173`、API 在 `3001`，全是跨源请求，浏览器都要预检。

其中一个 `201` 的完整报文（Burp 里逐字抄录）：

```http
POST /api/create HTTP/1.1
Host: localhost:3001
Content-Length: 0
Content-Type: application/json
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.120 Safari/537.36
Origin: http://[::1]:5173
Referer: http://[::1]:5173/
Connection: keep-alive
```

```http
HTTP/1.1 201 Created
X-Powered-By: Express
Access-Control-Allow-Origin: *
Content-Type: application/json; charset=utf-8
Content-Length: 60
ETag: W/"3c-dDQsTIZMddmlKkEqDpo8RNC/ty"
Date: Fri, 27 Sep 2024 13:32:42 GMT
Connection: keep-alive
Keep-Alive: timeout=5

{
  "message": "Resource created successfully",
  "statusCode": 201
}
```

这份报文把前面所有概念接上了：`201` 表示创建成功；`X-Powered-By: Express` 泄露了框架；`Access-Control-Allow-Origin: *` 是服务端给的放行；`ETag` 供下次条件请求用；`Keep-Alive: timeout=5` 是持久连接的存活窗口；响应体里连 `statusCode` 又写了一遍 201。

其余几个的状态他逐个对答案：`200` 成功；`400` 回 `bad request, missing required data`；`401` 是没带 token/cookie 或已失效；`403` 是无权操作；`404` 资源没找到；`409` 资源已存在（重名文件夹那个例子）；`500` 只说"内部错误"，**不向客户端透露细节**，理由是安全；`503` 提示稍后再试。

## 备注

- 时间戳：范围声明 00:00、两个想法 00:40、客户端–服务器 03:40、TCP 与 OSI 05:20、版本演进 05:48、报文 07:29、头部定义 09:11、四类头部 11:15、三种能力 14:14、方法 16:21、幂等性 18:05、CORS 定义 21:31、简单请求 22:00、预检三条件 24:40、预检报文 26:20、实机演示 29:41–38:49、状态码动机 38:52、五类划分 41:10、逐条 41:38–52:12、演示 52:20–55:18。
- 幻灯片、白板、Burp 报文均按画面原文抄录，字段值未改写；`// a blank line here means, everything has been sent` 也是幻灯片上原有的注释。
- 自动字幕错词按语义还原：`headlines`→headers、`presentation headers`→representation headers、`beer token`→bearer token、`fragment transfer encoding`→chunked transfer encoding、`STP 2.0`→HTTP/2.0、`HPAC`→HPACK、`row header`→head-of-line、`fast transport layer protocol`→QUIC、`D-flare`→deflate、`E tag`→ETag、`importance / non-adimpotent`→idempotent / non-idempotent、`course`→CORS、`pre-execution / pre-release / pre-initial query`→preflight request、`enginext / enginex`→nginx、`4 to 9`→429、`method is forbidden`→method not allowed。
- 他没讲 `PATCH` 的幂等性，也没用 "safe method" 这个术语；`Access-Control-Allow-Credentials`、`Vary: Origin` 与完整的 `304` 缓存策略同样没展开，这几处是他的省略，本文不代他补。

> 资料源：[Sriniously — Backend from first principles](https://www.youtube.com/playlist?list=PLui3EUkuMTPgZcV0QhQrOcwMPcBCcd_Q1)，第 5 集（1h18m13s）00:00–55:19。
