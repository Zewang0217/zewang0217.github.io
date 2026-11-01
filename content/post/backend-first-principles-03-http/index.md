---
title: "HTTP 全解：从报文结构到缓存与大文件传输"
description: "Sriniously「Backend from first principles」第 5 集全篇（78 分钟）忠实转写：无状态与客户端-服务器两个前提、报文与四类头部、方法与幂等、CORS 两条路径、1xx–5xx 状态码、ETag 缓存往返、内容协商、gzip、Keep-Alive、multipart 上传与 text/event-stream 流式响应。"
date: 2026-11-01
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

# HTTP 全解：从报文结构到缓存与大文件传输

第 5 集 78 分钟只讲一件事：HTTP。这是全系列最长的一集，也是唯一全程用 Burp Suite 做实机验证的一集。开场他先划范围：后端太大，"if we start discussing every single component that could be part of it, we'd be stuck here for years"，所以只讲**大多数代码库里会出现的 90%**。

本文按他的讲述顺序走完这一集：两个底层前提 → 传输层与版本 → 报文 → 头部 → 方法 → CORS → 状态码 → 缓存 → 内容协商 → 压缩 → 持久连接 → 大文件 → TLS。所有报文都照屏幕原文抄录。

## 一、两个底层想法

### 无状态

他的定义只有一句："it has no memory of past interactions"。

**每个请求自带服务器需要的全部信息**：headers、URL、method 都在请求里，服务器不必回忆上一次。

**服务器响应后就把这个请求忘了**。客户端再发一次，服务器当作全新的、无关的事件处理。

**因此请求相互独立**。因为不记得上次，每个请求都必须自带凭证；他的例子是访问用户资料，客户端要在**每一次**请求里带 cookies 或 tokens，服务器才知道这次是谁在要数据。

两个好处：**简单**（服务器不存 session，省资源省复杂度）、**可扩展**（请求能分发到任意一台服务器，某台挂了客户端状态也不受影响，因为压根没有会话记忆需要重建）。

代价他也直说了：正因为 HTTP 无状态，开发者才要自己实现状态管理，cookies、sessions、tokens 干的就是这件事，用在登录、购物车这类需要连续性的场景。

### 客户端–服务器模型

**客户端**通常是浏览器或应用，负责**发起**连接、发出请求，并提供服务器需要的全部信息（资源 URL、headers 等）。

**服务器**持有资源（网站、API 或其他内容），等待请求，处理完返回合适的响应：网页、数据、错误信息、JSON、文本文件。

一条协议层约定：**连接总是由客户端发起**，去换取某个特定响应。

还有一个简化约定：整段讨论可以把 HTTP 和 HTTPS 视为互换。HTTPS 就是 HTTP 加上加密与安全证书（TLS）的版本，基本原理相同，"which borders too much on the realm of network engineering"。

## 二、传输层与版本演进

客户端和服务器得先建立连接机制才能通信。HTTP 选择的介质是 **TCP**。

一个容易忽略的细节：HTTP 本质上**不要求**底层协议面向连接，它只要求**可靠、不丢消息**（真丢了至少以错误形式暴露）。互联网上最常见的两个传输协议是 TCP 与 UDP，TCP 更可靠，所以 HTTP 建立在 TCP 之上。

OSI 模型里后端日常活动在**第七层（应用层）**。TCP 三次握手、连接建立、TLS 加密这些偏网络工程，"it's going to be a rabbit hole"，他只做必要回顾。

版本演进他一并讲完了：

| 版本 | 变化 |
|---|---|
| HTTP/1.0 | 每个请求新开一条连接，请求与响应各建一次、关一次，性能差 |
| HTTP/1.1 | **持久连接**（同一 TCP 连接跑多个请求响应）、chunked transfer encoding、改进的缓存机制 |
| HTTP/2.0 | **多路复用**（单连接并发多请求）、**二进制分帧**代替文本、**HPACK** 头压缩、server push |
| HTTP/3.0 | 建在 **QUIC**（跑在 UDP 上）之上：建连更快、延迟更低、丢包处理更好，解决 HTTP/2 仍存在的**队头阻塞** |

## 三、报文：两份原文

他用的是一份**故意写复杂**的报文，"so that we could cover the different components one by one"。

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

按他的讲解拆开：

**请求行**：方法 `PUT`、资源 `/api/users/12345`、HTTP 版本 1.1（他说这是目前用得最广的版本）。

**头部**：逐行都是 key-value，`Host` 是目标域名。

**空行**：这一行是分隔符，"to signify that the headers are complete and the body begins"。

**请求体**：客户端要送出去的数据，这里是 JSON。

响应报文对称：状态行 = HTTP 版本 + 状态码 + 原因短语（`200` 表示 OK），然后响应头、空行、响应体。

## 四、头部

### 为什么要单独一层

头部就是**键值对**，"key-value pairs of various parameters that are sent via a request or received via a response"。

他自问：为什么不把这些值塞进 URL 或请求体？回答是包裹的类比：寄包裹时收件人地址写在**包裹外面**，因为中转的人（快递、分拣、转运）需要靠它送货；写在里面每个环节都要拆开看，别人想看地址又得再拆一次。HTTP 头部就是报文表面那层标注：**元数据与载荷分离，中间环节不解析正文也能读懂这个请求**。

### 四类

**请求头**：客户端发给服务器，描述请求本身。`User-Agent` 说明客户端类型；`Authorization` 携带 bearer token 标识用户；`Accept` 系列说明期望的内容类型。作用是让服务器理解客户端的**环境、偏好与能力**。

**通用头**：请求与响应都会用。消息日期、缓存控制（`no-cache`、`max-age`）、连接控制（`keep-alive`、`close`）。

**表示头**：只关心资源的表示形式。`Content-Type` 是媒体类型；`Content-Length` 是字节数；`Content-Encoding` 是编码方式（gzip、deflate）；`ETag` 是唯一标识，主要给缓存用。

**安全头**：通过控制浏览器行为提升安全性。`HSTS` 强制只走 HTTPS 防降级；`Content-Security-Policy` 限制 JS/CSS/图片的来源，缓解 XSS；`X-Frame-Options` 禁止被嵌进 iframe，缓解点击劫持；`X-Content-Type-Options` 阻止浏览器猜 MIME 类型；带 `HttpOnly` / `Secure` 的 cookie 让 JS 读不到且只走 HTTPS。

### 三种能力

**可扩展性**：加头部不需要改协议，加一层元数据交互流程就变了；开发者还能定义 `X-` 头。他给的正例就是安全头这一路的演进。

**内容协商**：`Accept`、`Accept-Language`、`Accept-Encoding` 让服务器按偏好返回不同版本。

**远程控制**：他把头部形容成客户端对服务器的"遥控"。客户端用 `Accept` 指定格式，服务器就返回该格式；服务器用 `Cache-Control` / `Expires` 决定客户端能缓存多久；客户端用 `Authorization` 影响访问控制决策。

## 五、方法：承载"意图"

他的定位是一个词：**意图**。"Instead of every request doing the same thing, methods define intent"。

| 方法 | 意图 | 他的补充 |
|---|---|---|
| `GET` | 取数据 | **不应改变服务器上的任何东西** |
| `POST` | 创建数据 | 有请求体，否则没法把用户数据传上去 |
| `PATCH` | 更新数据 | 请求体带要改的字段 |
| `PUT` | 更新数据 | 请求体**完整替换**旧实例；`PATCH` 是追加或选择性替换 |
| `DELETE` | 删除资源 | 按名字理解 |
| `OPTIONS` | 询问服务器能力 | 开发者很少直接调，会在 network 面板里看到，它就是 CORS 预检用的 |

`PATCH` 与 `PUT` 他说得挺直：很多开发者在该用 `PATCH` 的地方用了 `PUT`，违背语义。经验法则是**除非有明确的 `PUT` 场景，否则用 `PATCH`**。这个规矩在状态码那节还会回头咬人：`405` 的常见成因就是前端把 `PUT` 写成了 `PATCH`。

### 幂等性

幂等（idempotent）：可以调用多次，结果与调用一次相同。

**幂等的三个**：`GET`（取多少次都一样，本来就不该改服务器）、`PUT`（完整替换，替换多少次结果都一样）、`DELETE`（删第一次就没了，再删同一资源结果仍一致）。

**非幂等的**：`POST`。他的例子是发笔记：第一次 POST 创建一条，第二次同样的 POST 又创建一条，同一个请求产生两个不同结果。

实际意义在重试：网络抖动时客户端想重发，幂等方法重发安全，`POST` 重发就可能多一条记录。

## 六、CORS

先给定义：浏览器默认遵循**同源策略**，限制网页向"提供这个页面的域"以外的域发请求。CORS 是浏览器控制这类跨源交互的**安全机制**，让服务器声明"谁能访问我的资源、怎么访问"。

他用 `example.com`（前端）与 `api.example.com`（API）做对照，分成两条路径。

### 路径一：简单请求

1. 客户端发请求，浏览器**自动加上 `Origin` 头**
2. 请求用"简单方法"（通常是 `GET`、`POST`、`HEAD`）
3. 服务器拿 `Origin` 和 CORS 策略比对
4. 允许则在响应里带 `Access-Control-Allow-Origin`
5. 浏览器检查该头的值是否等于客户端 origin 或 `*`，匹配才把响应交给 JS，否则**阻止读取响应**

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

{"product": {"id": 123, "name": "Example Product", "price": 29.99}}
```

拦截时机很关键：服务器**并没有拒绝处理请求**，是浏览器在解析响应时挡下的，表现为控制台报错、network 面板标 CORS 错误。

### 路径二：预检请求

三个触发条件，**满足任意一个**就预检：

1. 方法不是 `GET`、`POST`、`HEAD`（例如 `PUT`、`DELETE`）
2. 请求带了非简单头（例如 `Authorization`、`X-Custom-Header`）
3. `Content-Type` 不是 `application/x-www-form-urlencoded`、`multipart/form-data`、`text/plain`

因为前后端大量用 JSON，`application/json` 不在允许列表里，所以**日常大多数请求都会触发预检**。

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

| 头 | 作用 |
|---|---|
| `Access-Control-Allow-Origin` | 允许哪个源，或 `*` 表示全部 |
| `Access-Control-Allow-Methods` | 该资源允许哪些方法 |
| `Access-Control-Allow-Headers` | 允许哪些非简单头 |
| `Access-Control-Max-Age` | 结论缓存多久（秒），期间不必重复预检 |

`Max-Age` 的价值：不缓存结论的话，每个请求前都要多一次问询，服务端和客户端都要多花带宽。预检只用 `OPTIONS`，不带请求体也不该有响应体，这就是 `204` 的由来。

### 实机验证

演示环境是两个本地端口：前端 `localhost:5173`，API `localhost:3001`。这在浏览器眼里就是**跨源**：同源要求协议、域、端口三者一致。

**简单请求那一轮**：跑一次普通请求，响应正常渲染；在请求里确认 `Origin` 与 `Host`，在响应里确认 `Access-Control-Allow-Origin` 是 `5173` 或 `*`。

**摘掉响应头那一轮**：删掉 `Access-Control-Allow-Origin`，清历史后重发，浏览器直接拦下。

**预检那一轮**：恢复后重发，网络面板里**先 `OPTIONS` 再原始请求**。预检响应是 `204`，`Access-Control-Allow-Methods` 列出 `GET, POST, PUT, DELETE`，`Allow-Headers` 列出 `content-type` 与 `authorization`，`Max-Age` 他故意设成 `0` 方便反复测试。原始请求是 `PUT`，带 `Origin`、`Authorization`、`Host` 和请求体。三个触发条件全中。

## 七、状态码

定位是"标准化地表达结果"：客户端不用读 body 猜结果，`401` 就触发重登、`400` 就提示改表单；而且这套数字跨语言跨平台统一。历史上在状态码出现之前，客户端只能靠响应内容猜，各家做法不一。

分类靠首位：`1xx` 信息、`2xx` 成功、`3xx` 重定向、`4xx` 客户端错误、`5xx` 服务端错误。

**1xx**：`100 Continue`（客户端先发头，服务器同意后客户端再发 body，用于大负载上传）、`101 Switching Protocols`（按请求切协议，比如 HTTP → WebSocket）。日常少见。

**2xx**：`200 OK`、`201 Created`（创建成功，用于提交表单、发帖）、`204 No Content`（成功但无内容，预检与删除都用它）。

**3xx**：`301`（永久迁移，他把 `/user` 改成 `/person` 时给旧路由加 301 保兼容）、`302`（临时重定向，活动期导流，之后回原 URL）、`304 Not Modified`（配合条件 GET，让客户端用本地缓存）。

**4xx**：`400`（数据本身有问题，比如要数字给了数组、要 email 给了电话）、`401`（需要认证但没提供有效凭证，比如 JWT 过期）、`403`（已认证但无权，比如删别人的资源）、`404`（URL 错或资源已删，他说这是最有名的）、`405`（方法不对，常见成因是前端写错）、`409`（冲突，比如文件夹重名）、`429`（限流，比如每秒 60 个请求上限）。

**5xx**：`500`（未预料的异常；与其返回空响应或挂着，不如明说服务端出错）、`501`（暂未实现但计划支持）、`502`（代理/负载均衡从上游拿到无效响应，通常不是业务代码主动返回）、`503`（过载或维护，稍后重试）、`504`（上游在等待时间内没响应，比如 nginx 等不到后端）。

他说这组覆盖 95% 的使用场景。

### 演示里的真实报文

演示页列了一串按钮：`200`、`201`、`204`、`400`、`401`、`403`、`404`、`409`、`500`、`503`。他全点一遍再逐个对答案。第一个观察是：**每个原始请求前面都跟着一个 `OPTIONS`**，因为前端在 `5173`、API 在 `3001`，全是跨源。

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

{"message":"Resource created successfully","statusCode":201}
```

![第 5 集 53:40：演示页左侧按状态码排了一列按钮，右边 Burp 里是同一个 POST /api/create 的真实请求与 201 响应](f27-demo-status.png)

这份报文把前面所有概念接上了：`201` 表示创建成功；`X-Powered-By: Express` 泄露了框架；`Access-Control-Allow-Origin: *` 是服务端放行；`ETag` 供下次条件请求；`Keep-Alive: timeout=5` 是持久连接的存活窗口；响应体里连 `statusCode` 又写了一遍。

其余几个：`400` 回 `bad request, missing required data`；`401` 是没带 token/cookie 或已失效；`403` 无权操作；`404` 没找到；`409` 资源已存在；`500` 只说内部错误、**不向客户端透露细节**（理由是安全）；`503` 提示稍后再试。

## 八、缓存：三个头加一次往返

定义很朴素：把响应存一份、之后复用，"reusing old data if the data has not changed"。收益是加载更快、省带宽、降服务器负载。

### 第一轮：拿到三个头

```http
HTTP/1.1 200 OK
X-Powered-By: Express
Access-Control-Allow-Origin: *
Cache-Control: max-age=10, public
ETag: 3141
Last-Modified: Fri, 27 Sep 2024 13:48:33 GMT
Content-Type: application/json; charset=utf-8
Content-Length: 112
Connection: keep-alive
Keep-Alive: timeout=5

{"content":"This is the updated resource content.","lastModified":"Fri, 27 Sep 2024 13:48:33 GMT","etag":"3141"}
```

`Cache-Control: max-age=10`：最多缓存 10 秒。

`ETag: 3141`：本质是**哈希**。演示用随机数，真实场景是服务器对响应内容做哈希再发出去，让客户端下次能问"我这份还新吗"。

`Last-Modified`：资源最后一次修改时间，客户端也可据此判断是否过期。

![第 5 集 56:40：第一次 GET /api/resource，响应里的三个缓存头都在，页面显示 ETag 3141](f29-cache-headers.png)

### 第二轮：条件请求换 304

![第 5 集 59:00：第二次 GET 带 If-None-Match: 3141 与 If-Modified-Since，响应只有 304 和几个头，没有响应体](f30-conditional-request.png)

```http
GET /api/resource HTTP/1.1
Host: localhost:3001
Cache-Control: max-age=0
If-None-Match: 3141
If-Modified-Since: Fri, 27 Sep 2024 13:48:33 GMT
Origin: http://[::1]:5173
Accept-Encoding: gzip, deflate, br
Connection: keep-alive
```

```http
HTTP/1.1 304 Not Modified
X-Powered-By: Express
Access-Control-Allow-Origin: *
Cache-Control: max-age=10, public
Date: Fri, 27 Sep 2024 13:52:45 GMT
Connection: keep-alive
Keep-Alive: timeout=5
```

`If-None-Match` 带**上次的 ETag**，`If-Modified-Since` 带**上次的修改时间**。服务器对比后若无变化就回 `304`，**不带响应体**，客户端直接用本地缓存。页面显示"Resource not modified, using cached version"，内容还是那份，ETag 还是 `3141`。

省流量的点就在这里：省掉的正文在真实场景里常常是几百 KB。

### 第三轮：更新之后

他把资源改了一次（演示用 `POST /api/update-resource`，他顺口承认"ideally we should have made a `PATCH` or a `PUT` request"，为了演示方便才用 POST），响应带回**新 ETag `2943`**。

**用旧 ETag 请求**：带 `3141` 去问，服务器发现资源变了，回 `200` 与完整正文。这就是"缓存失效"在协议层的样子。

**用新 ETag 请求**：带 `2943` 再问，确认是最新版本，回 `304`。

![第 5 集 1:00:00：更新资源的响应，页面上的 ETag 从 3141 变成 2943，Last-Modified 同步更新](f31-304.png)

### 他的两句实话

**生产代价**：这套东西要服务器**手工维护** ETag；改了资源忘更新 ETag，客户端就一直用旧缓存，"which is not a good idea"。

**他更偏好的方案**：React Query 这类**纯客户端缓存**，客户端自己决定何时复用、何时刷新、间隔多久，原话是 "which in my opinion is a much better solution compared to traditional HTTP-based caching"。他也留了余地：场景足够简单时，HTTP 缓存完全够用。

## 九、内容协商

定义是客户端与服务器就交换数据的最佳格式达成一致的机制：客户端说偏好（JSON、XML、HTML），服务器尽量按偏好返回，给不了就用 fallback。

三种：**媒体类型**（`Accept`：`application/json`、`application/xml`）、**语言**（`Accept-Language`：`en`、`es`）、**编码**（`Accept-Encoding`：`gzip`、`deflate`、`br`、`zstd`）。

![第 5 集 1:05:40：默认请求的报文，Accept-Language、Accept、Accept-Encoding 三个头都在，响应按这三个偏好生成](f34-negotiation-panes.png)

演示跑三轮，每轮只改一个头：默认（`en` + JSON + gzip）→ 语言换 `es`（只变语言，内容跟着变西班牙语）→ 再换 `Accept` 为 XML（响应体变 XML）。他的评语是"唯一变的就是客户端说它接受西班牙语"。

价值在于：客户端能表达格式与语言偏好，服务器据此生成内容，用户体验更好；成本极低，全靠头部。

## 十、压缩：3.8MB 与 26MB

它和内容协商共用 `Accept-Encoding`，所以紧接着讲。

演示里他把响应换成 **11,000 条记录**的大 JSON：服务端开 gzip 时响应 `3.8 MB`，关掉压缩后同一个文件 `26 MB`，差近 7 倍。

落点是带宽："imagine that every client has to download this file"，每个客户端都下 26MB 就是纯浪费；压缩后浏览器自动解压，内容一模一样。

他补了一句定位：这一层通常不用手写，服务器或框架（nginx、Express 中间件）已经处理，**知道它在背后发生就够了**。

## 十一、持久连接

三点：

**HTTP/1.1 里连接默认就是持久的**，不用额外做什么，除非显式关闭；一条连接可以跑多个请求响应，省掉反复建连。

**`Keep-Alive` 头**用于显式要求保持连接，也能带参数：`timeout` 是保持多久，`max` 是这条连接上最多发多少个请求。前面报文里的 `Keep-Alive: timeout=5` 就是它。

**`Connection: close`** 表示响应发完就关，这是 HTTP/1.0 的默认行为，在 1.1 里仍可显式指定。

他的态度很务实：默认值工作得很好，日常不需要动。

## 十二、大请求：multipart 与 boundary

![第 5 集 1:13:20：POST /api/upload 的原始报文，Content-Type 里带 boundary，正文是二进制分段](f37-multipart.png)

```http
POST /api/upload HTTP/1.1
Host: localhost:3001
Proxy-Connection: keep-alive
Content-Length: 912097
Content-Type: multipart/form-data; boundary=----WebKitFormBoundarycn7jAzmAvScc5fPB
Origin: http://[::1]:5173
Connection: keep-alive
```

```http
HTTP/1.1 200 OK
X-Powered-By: Express
Access-Control-Allow-Origin: *
Content-Type: application/json; charset=utf-8
Content-Length: 285
ETag: W/"11d-15780Hhf6SE+aJwh3VExxs6V8"

{"message":"File uploaded successfully","fileDetails":{"fieldname":"file","originalname":"Zenitsu-dark.png","encoding":"7bit","mimetype":"image/png","destination":"uploads/","size":911908}}
```

关键在 `boundary`。二进制数据是**分段**传的，所以必须声明分隔符，"we need some code that will separate the parts"。正文每段以 `------WebKitFormBoundarycn7jAzmAvScc5fPB` 开头，最后一段后再加闭合标记，服务端按分隔符把文件拼回去。这也解释了上传接口的 `Content-Type` 为什么不是 `application/json`。

## 十三、大响应：text/event-stream

样例是 Gutenberg 的《福尔摩斯探案集》纯文本，`6.4 MB`。

![第 5 集 1:14:20：同一个 /api/stream-data 被反复请求，响应头 Content-Type 是 text/event-stream，正文每行以 data: 开头](f38-event-stream.png)

```http
HTTP/1.1 200 OK
X-Powered-By: Express
Access-Control-Allow-Origin: *
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
Content-Length: 6489478

data: The Project Gutenberg EBook of The Adventures of Sherlock Holmes
data: by Sir Arthur Conan Doyle
...
```

三个要点：`Content-Type: text/event-stream` 声明这是**事件流**，数据以事件形式陆续送达；`Connection: keep-alive` 让连接**在所有数据发完前保持打开**；正文每行以 `data:` 开头。客户端不断把收到的片段追加起来拼成完整文件。请求侧对应带 `Accept: text/event-stream` 与 `Cache-Control: no-cache`。

## 十四、SSL / TLS / HTTPS

收尾前他快速过了一遍三个名词："就算日常不直接碰，知道是什么也有用"。

**SSL** 是最初用于加密客户端与服务器通信的协议，加密数据让密码、卡号无法被拦截；它因安全漏洞已经**过时**，被 TLS 取代。

**TLS** 是现代版本，加密传输中的数据防窃听与篡改，用**证书**认证服务器并建立加密连接。版本持续更新，字幕在这里被截断成 "TLS 1"，按上下文应是当前推荐的 TLS 1.3。

**HTTPS** 就是 HTTP 加上 SSL/TLS 的安全层。早期是 SSL，现在是 TLS，所以 HTTPS 底下跑的是 TLS。

## 十五、收束

他的判断是：只要能把今天讲的这些组件在脑子里串成一条完整流程，就足以理解系统背后发生了什么、也能调试大部分问题；想深入当然还能读更多（协议本身、TLS、TCP 的细节）。

## 备注

- 时间戳：两个想法 00:40、客户端–服务器 03:40、TCP 与 OSI 05:20、版本演进 05:48、报文 07:29、头部 09:11、四类头部 11:15、三种能力 14:14、方法 16:21、幂等 18:05、CORS 21:31、简单请求 22:00、预检 24:40、实机 29:41–38:49、状态码 38:52–55:18、缓存 55:25–1:02:24、协商 1:02:32、压缩 1:07:00、持久连接 1:09:00、大请求 1:11:43、大响应 1:13:34、TLS 1:15:18、收束 1:17:19。
- Burp 报文按画面逐字抄录（`ETag: 3141` → `2943`、`boundary=----WebKitFormBoundarycn7jAzmAvScc5fPB`、`Content-Length: 6489478`）。幻灯片上的 `// a blank line here means, everything has been sent` 也保留了。
- 只保留真实操作画面（Burp 报文、浏览器演示）；纯标题页与纯板书没有截图，因为文字内容已在正文里。
- 自动字幕错词按语义还原：`headlines`→headers、`presentation headers`→representation headers、`beer token`→bearer token、`fragment transfer encoding`→chunked transfer encoding、`STP 2.0`→HTTP/2.0、`HPAC`→HPACK、`row header`→head-of-line、`fast transport layer protocol`→QUIC、`D-flare`→deflate、`E tag`→ETag、`importance / non-adimpotent`→idempotent / non-idempotent、`course`→CORS、`pre-execution / pre-release / pre-initial query`→preflight request、`enginext / enginex`→nginx、`4 to 9`→429、`method is forbidden`→method not allowed、`gizip`→gzip、`latest change`→Last-Modified、`if none match`→If-None-Match、`if changed`→If-Modified-Since、`border`/`limit parameter`→boundary、`multi-faceted`→multipart、`text event stream`→text/event-stream。
- 两处他没有展开、本文不代他补：`Access-Control-Allow-Credentials` 与 `Vary: Origin`；`PATCH` 的幂等性与 "safe method" 这个术语。TLS 1.3 那处是全文唯一按上下文补的推断。

> 资料源：[Sriniously — Backend from first principles](https://www.youtube.com/playlist?list=PLui3EUkuMTPgZcV0QhQrOcwMPcBCcd_Q1)，第 5 集（1h18m13s）全篇。
