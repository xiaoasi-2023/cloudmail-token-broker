# Xiaoasi Mail 在线 POP3 网关开发文档

## 1. 文档目的

本文档定义将 POP3 适配能力直接集成到 `cloudmail-token-broker` 的方案。

目标是废弃桌面端本地 Python POP3 脚本，让桌面程序直接连接线上 POP3 服务：

```text
桌面端主程序
        |
        | POP3 / POP3S
        v
Xiaoasi Mail 在线 POP3 网关
        |
        | 查询 PostgreSQL 中的邮箱记录
        | 复用 mailboxId、邮箱用途和 Provider 路由
        v
CloudMail Provider
        |
        v
CloudMail 实例
```

桌面端不再需要：

- 本地启动 `cloud_mail_helper.py` 的 POP3 服务；
- 本地监听 `127.0.0.1:110`；
- 本地查询 Xiaoasi Mail HTTP API；
- 本地保存 `mailbox_sessions.json`；
- 保存 CloudMail 管理员账号、密码或 Token。

## 2. 当前项目基础

当前项目已经具备在线 POP3 网关所需的大部分业务能力：

- 多 CloudMail 实例；
- 多邮箱域名和域名路由；
- 邮箱创建；
- 邮箱生命周期和过期时间；
- PostgreSQL 邮箱记录；
- `mailboxId` 和短期 `mailboxToken`；
- CloudMail Provider Registry；
- 邮件查询；
- 验证码提取；
- 管理端和请求日志。

主要复用模块：

| 模块 | 复用内容 |
| --- | --- |
| `app/gateway/mailbox_service.py` | 邮箱状态、实例路由、验证码查询 |
| `app/gateway/cloudmail_provider.py` | CloudMail 邮件查询和 Token 管理 |
| `app/gateway/database_business_store.py` | 邮箱记录和实例查询 |
| `app/gateway/database.py` | PostgreSQL 数据库 |
| `app/gateway/verification.py` | 验证码提取规则 |
| `app/gateway/mailbox_token.py` | 短期邮箱凭证校验 |

POP3 是新增的协议出口，不应复制一套新的邮箱查询逻辑。

## 3. POP3 与 HTTP API 的关系

现有 HTTP API 面向图片站、Kirox、EXE 等可以直接调用 HTTP 的客户端：

```text
POST /v1/mailboxes
POST /v1/mailboxes/{mailboxId}/verification-code
GET  /v1/mailboxes/{mailboxId}
DELETE /v1/mailboxes/{mailboxId}
```

新增 POP3 服务面向只能填写邮箱服务器地址的桌面程序：

```text
POP3:  110
POP3S: 995
```

POP3 服务内部不重新访问 HTTP API，也不需要调用方提供 `X-API-Key`。
它直接调用同一个 `MailboxGatewayService` 和 `CloudMailProviderRegistry`。

## 4. 桌面端使用方式

桌面端的辅助邮箱设置填写：

```text
连接方式：pop3
邮箱地址：pop3.cloudmail.xiaoasi.xyz
端口：995
SSL/TLS：开启
```

不能填写：

```text
127.0.0.1?auth=xxxx
https://pop3.cloudmail.xiaoasi.xyz?auth=xxxx
```

POP3 是 TCP 协议，不支持在服务器地址后面拼接 HTTP GET 参数。

桌面端导入数据继续使用现有格式：

```text
主账号----主密码----辅助邮箱----POP3授权码
```

其中：

```text
第 1 段：主账号
第 2 段：主账号密码
第 3 段：POP3 用户名，即线上生成的辅助邮箱地址
第 4 段：POP3 PASS 参数，即提前配置的 POP3 授权码
```

本地辅助邮箱工具在生成文件前配置一次授权码。它把该值写入每一行的第 4 段，桌面端收到验证码时会按 POP3 协议发送：

```text
USER <第 3 段辅助邮箱>
PASS <第 4 段 POP3 授权码>
```

线上 POP3 服务必须校验该授权码。密码错误时不得允许继续执行 `STAT`、`LIST` 或 `RETR`。
第一阶段可以使用调用方级统一授权码；它不是 CloudMail 管理员密码，也不是辅助邮箱的真实邮箱登录密码。

## 5. POP3 登录和会话流程

### 5.1 客户端流程

桌面程序通常会发送：

```text
S: +OK Xiaoasi Mail POP3 ready
C: USER olivia4821@example.com
S: +OK user accepted
C: PASS 123456
S: +OK pass accepted
C: STAT
```

### 5.2 服务端流程

服务端收到 `USER` 后：

1. 标准化邮箱地址为小写；
2. 暂存当前连接的邮箱地址；
3. 不立即查询上游邮箱。

服务端收到 `PASS` 后：

1. 校验是否已经收到 `USER`；
2. 校验调用方 POP3 授权码；
3. 根据邮箱地址查询 `mailboxes`；
4. 校验邮箱状态为 `active`；
5. 校验邮箱会话没有过期；
6. 将当前连接标记为 authenticated。

只有 authenticated 连接可以执行：

```text
STAT
LIST
UIDL
RETR
DELE
NOOP
RSET
QUIT
```

未认证连接只能执行：

```text
USER
PASS
CAPA
QUIT
```

### 5.3 邮箱查询

通过邮箱地址查询数据库：

```sql
SELECT id, address, purpose, status, verification_status,
       created_at, expires_at, instance_id, domain_id
FROM mailboxes
WHERE lower(address) = lower(:address)
ORDER BY created_at DESC
LIMIT 1;
```

只允许使用状态为 `active` 且未过期的记录。

POP3 服务不应该从客户端提交的邮箱地址推导 CloudMail 地址、实例地址或管理员凭据。
所有内部路由都必须来自数据库记录。

## 6. 邮件返回策略

当前业务目标是接收验证码，不是提供完整邮箱客户端能力。

因此第一版只返回一封动态生成的验证码邮件：

```text
From: account-security-noreply@accountprotection.microsoft.com
To: 用户辅助邮箱
Subject: Microsoft account security code
Content-Type: text/plain; charset=utf-8
```

邮件正文可以包含：

```text
Security code: 123456
你的一次性代码为: 123456
验证码: 123456
```

### 6.1 STAT

如果尚未查询验证码：

1. 调用 `MailboxGatewayService.get_verification_code(..., wait_seconds=0)`；
2. 如果收到验证码，缓存生成的邮件；
3. 返回一封邮件的大小；
4. 如果没有验证码，返回 `+OK 0 0`。

### 6.2 LIST

如果缓存中有邮件：

```text
+OK scan listing follows
1 <octets>
.
```

如果没有邮件：

```text
+OK scan listing follows
.
```

### 6.3 RETR

如果缓存中有邮件：

```text
+OK <octets> octets
<RFC822 message>
.
```

如果没有收到验证码：

```text
-ERR no mail yet
```

`RETR` 可以使用配置的等待时间，例如 20 秒，以适配微软验证码邮件有延迟的情况。

### 6.4 缓存规则

每个 POP3 TCP 连接维护独立缓存：

```python
cached_message: bytes | None
has_mail: bool
```

避免同一连接在 `STAT`、`LIST`、`RETR` 之间重复请求上游。

不建议把完整邮件正文长期写入数据库。验证码查询结果可以只保留状态和时间，邮件内容在 POP3 连接中动态生成。

## 7. 推荐代码结构

建议新增以下模块：

```text
app/
├── gateway/
│   ├── mailbox_service.py
│   ├── cloudmail_provider.py
│   ├── database_business_store.py
│   └── ...
└── protocol/
    ├── __init__.py
    ├── pop3_server.py
    ├── pop3_session.py
    ├── pop3_auth.py
    └── message_builder.py
```

### 7.1 `pop3_server.py`

负责：

- 监听 TCP 端口；
- 接受客户端连接；
- 创建 `POP3Session`；
- 管理线程或 asyncio task；
- 优雅关闭。

### 7.2 `pop3_session.py`

负责：

- POP3 命令解析；
- 用户状态机；
- `USER/PASS`；
- `STAT/LIST/UIDL/RETR`；
- 单连接邮件缓存；
- 超时和异常响应。

### 7.3 `pop3_auth.py`

负责：

- 校验调用方 POP3 授权码；
- 按邮箱地址查询邮箱记录；
- 校验邮箱 active/expired/released 状态；
- 返回已认证的 `MailboxRecord`。

### 7.4 `message_builder.py`

负责：

- 生成 RFC822 邮件；
- 生成 `From/To/Subject/Date`；
- 处理 CRLF；
- 处理 POP3 dot-stuffing；
- 限制邮件大小。

## 8. 业务层接口调整

### 8.1 Store 增加按地址查询

在 `GatewayBusinessStore` 增加：

```python
def get_mailbox_by_address(self, address: str) -> MailboxRecord | None: ...
```

PostgreSQL 实现需要按小写地址查询。

建议增加索引：

```sql
CREATE INDEX IF NOT EXISTS idx_mailboxes_address_lower
ON mailboxes (lower(address));
```

现有 `address` 已有唯一约束，但 PostgreSQL 的普通唯一索引不保证大小写不敏感查询效率。

### 8.2 提取验证码查询方法

当前 `MailboxGatewayService.get_verification_code` 已经接受：

```python
mailbox_id
token
VerificationCodeRequest
client_name
```

POP3 服务可以有两种接入方式：

#### 方案 A：内部复用现有 token 校验

POP3 根据邮箱记录生成或使用内部 mailbox token，再调用现有方法。

优点：

- 修改少；
- 复用现有过期和 Provider 逻辑。

缺点：

- POP3 协议层需要处理内部 token；
- 业务层接口语义不够自然。

#### 方案 B：增加内部邮箱地址查询方法，推荐

增加：

```python
async def get_verification_code_by_address(
    self,
    address: str,
    request: VerificationCodeRequest,
) -> VerificationCodeData:
    ...
```

该方法只允许由本地协议服务调用，不暴露为公网 HTTP 接口。

内部流程：

1. 根据地址查 `MailboxRecord`；
2. 检查 active 和 expires_at；
3. 获取 instance；
4. 使用 Provider 查询邮件；
5. 使用统一验证码提取器；
6. 更新 verification_status；
7. 返回验证码状态。

这样 POP3 只依赖邮箱地址，不需要接触 `X-API-Key` 或 `mailboxToken`。

## 9. SMTP 范围

第一阶段只实现 POP3/POP3S。

SMTP 是发信协议，而当前 CloudMail Provider 只具备：

- 创建邮箱；
- 查询邮件。

当前没有统一的：

```python
send_message(...)
```

因此暂不实现 SMTP。

未来增加 SMTP 前，需要确认 Provider 具备发信接口，并补充：

- SMTP AUTH；
- STARTTLS 或 SMTPS；
- 发件人校验；
- 收件人策略；
- 邮件大小限制；
- 队列和重试；
- 反滥发限流；
- SPF/DKIM/DMARC；
- 退信处理；
- 审计日志。

## 10. 端口和部署

### 10.1 推荐部署形态

POP3 不适合通过普通 HTTP 反向代理暴露。

推荐同一仓库、同一镜像、两个进程：

```text
cloudmail-token-broker
    HTTP API + Admin Web
    container port 8080

cloudmail-pop3
    POP3/POP3S
    container port 1110/9950
```

两个进程共享：

- PostgreSQL；
- 环境变量；
- 项目代码；
- CloudMail Provider；
- mailbox 业务数据。

### 10.2 Compose 端口示例

第一版可以先使用独立 POP3 容器：

```yaml
services:
  cloudmail-token-broker:
    image: ${IMAGE_NAME:?please set IMAGE_NAME in .env}
    ...
    ports:
      - "127.0.0.1:8788:8080"

  cloudmail-pop3:
    image: ${IMAGE_NAME:?please set IMAGE_NAME in .env}
    ...
    command:
      - python
      - -m
      - app.protocol.pop3_server
    ports:
      - "110:1110"
    depends_on:
      - cloudmail-token-broker
```

推荐 POP3 进程监听容器内 `1110`，宿主机映射到 `110`，避免容器内非 root 用户绑定特权端口。

生产环境优先使用 POP3S：

```text
公网端口：995
TLS：服务端证书
```

普通 `110` 只建议用于内网、VPN 或受防火墙限制的网络。

### 10.3 DNS

建议单独使用：

```text
pop3.cloudmail.xiaoasi.xyz
```

如果使用 Cloudflare，该 DNS 记录必须设置为“仅 DNS”，不能依赖普通 HTTP 反向代理代理 POP3 TCP 流量。

## 11. 配置项

建议增加以下环境变量：

```dotenv
POP3_ENABLED=true
POP3_HOST=0.0.0.0
POP3_PORT=1110
POP3_AUTH_CODE=<调用方 POP3 授权码>
POP3_TLS_ENABLED=false
POP3_TLS_CERT_FILE=/run/secrets/pop3.crt
POP3_TLS_KEY_FILE=/run/secrets/pop3.key
POP3_MAX_CONNECTIONS=100
POP3_COMMAND_TIMEOUT_SECONDS=60
POP3_MAX_MESSAGE_BYTES=1048576
```

其中：

| 配置 | 说明 |
| --- | --- |
| `POP3_ENABLED` | 是否启动 POP3 服务 |
| `POP3_HOST` | 监听地址 |
| `POP3_PORT` | 容器内监听端口 |
| `POP3_AUTH_CODE` | 第一阶段调用方统一 POP3 授权码；必须与本地工具配置的授权码一致 |
| `POP3_TLS_ENABLED` | 是否启用 TLS |
| `POP3_TLS_CERT_FILE` | TLS 证书路径 |
| `POP3_TLS_KEY_FILE` | TLS 私钥路径 |
| `POP3_MAX_CONNECTIONS` | 最大并发连接数 |
| `POP3_COMMAND_TIMEOUT_SECONDS` | 单命令最大处理时间 |
| `POP3_MAX_MESSAGE_BYTES` | 返回邮件大小上限 |

`POP3_AUTH_CODE` 不应写入普通日志。生产环境应通过密钥或 Secret 注入，不要提交到 Git。

## 12. 安全要求

最低要求：

1. POP3 服务不得监听到 HTTP 反向代理地址；
2. 公网优先使用 POP3S 995；
3. 普通 POP3 110 必须限制来源 IP；
4. 未完成 `USER/PASS` 鉴权不得执行查询；
5. 用户名必须对应数据库中的邮箱记录；
6. 过期、released、failed 邮箱必须拒绝查询；
7. 不记录完整密码、token、验证码和邮件正文；
8. 限制单 IP 并发连接数；
9. 限制单邮箱查询频率；
10. 限制单次返回邮件大小；
11. 处理 `QUIT`、连接断开和服务关闭；
12. POP3 错误信息不得回显数据库结构或 CloudMail 凭据。

调用方级统一授权码只是兼容现有桌面程序的第一版方案。后续可以改为：

- 每个调用方独立 POP3 授权码；
- 每个邮箱独立 POP3 授权码；
- POP3 用户名使用邮箱地址，密码使用短期协议 token。

## 13. 状态机

POP3 单连接状态：

```text
AUTHORIZATION
    |
    | USER
    v
USER_ACCEPTED
    |
    | PASS 正确
    v
TRANSACTION
    |
    | STAT/LIST/RETR
    v
查询邮箱记录和验证码
```

错误状态：

```text
PASS 错误        -> -ERR authentication failed
邮箱不存在       -> -ERR mailbox not found
邮箱已释放/POP关闭 -> -ERR authentication failed
上游查询失败     -> -ERR mailbox query failed
等待内无验证码   -> +OK 0 0 或 -ERR no mail yet
```

## 14. 测试计划

### 14.1 协议单元测试

- `USER` 保存邮箱地址；
- `PASS` 正确和错误；
- 未认证时拒绝 `STAT/LIST/RETR`；
- 邮箱不存在；
- 普通用户读取自己名下已过期但仍启用 POP 的邮箱；
- 已释放或已关闭 POP 的邮箱不能读取；
- 邮箱 released；
- `QUIT`；
- `CAPA`；
- `STAT` 无邮件；
- `STAT` 有邮件；
- `LIST`；
- `UIDL`；
- `RETR`；
- dot-stuffing；
- 客户端断开；
- 单命令超时。

### 14.2 业务集成测试

- POP3 地址查询正确复用 `MailboxGatewayService`；
- 正确找到对应 CloudMail 实例；
- 多实例邮箱不会串号；
- 验证码提取复用现有规则；
- 验证码状态写入 `mailboxes.verification_status`；
- 同一连接缓存邮件，避免重复请求；
- 不同连接不会共享错误的邮件缓存。

### 14.3 部署验收

```bash
nc -vz pop3.cloudmail.xiaoasi.xyz 110
```

或：

```bash
openssl s_client -connect pop3.cloudmail.xiaoasi.xyz:995
```

桌面端填写：

```text
连接方式：pop3
邮箱地址：pop3.cloudmail.xiaoasi.xyz
```

然后使用真实注册流程触发验证码，确认桌面端可以收到由线上网关动态生成的邮件。

## 15. 开发阶段

### 阶段一：业务接口

- 增加按邮箱地址读取 `MailboxRecord`；
- 增加内部 `get_verification_code_by_address`；
- 增加协议专用认证函数；
- 增加 POP3 消息构造器。

### 阶段二：POP3 服务

- 实现 asyncio TCP Server；
- 实现 POP3 状态机；
- 实现 `USER/PASS/CAPA/STAT/LIST/UIDL/RETR/DELE/NOOP/RSET/QUIT`；
- 接入邮箱状态和验证码查询；
- 增加连接、命令和错误日志；
- 增加并发和超时限制。

### 阶段三：TLS 和部署

- 增加 POP3S；
- 增加证书配置；
- 增加独立容器或 sidecar；
- 增加 Compose 端口；
- 增加健康检查；
- 配置 DNS 和防火墙。

### 阶段四：桌面端迁移

- 删除本地 POP3 服务；
- 删除本地 `mailbox_sessions.json`；
- 创建邮箱时只调用线上 HTTP API；
- 输出真实辅助邮箱地址；
- POP3 服务器改为线上域名；
- 把调用方 POP3 授权码写入导入文本第 4 段；
- 不启动本地 `cloud_mail_helper.py` 的 POP3 服务；
- 不依赖本地 `mailbox_sessions.json` 进行 POP3 查询。

## 16. 验收标准

1. 桌面程序不启动本地 Python POP3 脚本也能收验证码。
2. 桌面程序连接线上 POP3 域名成功。
3. POP3 根据邮箱地址找到正确的 PostgreSQL 邮箱记录。
4. 不同邮箱不会串用 mailboxId 或 CloudMail 实例。
5. 普通用户可以查询自己名下状态为 `active` 或 `expired` 且 `pop_enabled=true` 的邮箱；HTTP 邮箱会话过期不影响 POP3 查询。
6. POP3 密码错误时不能执行邮箱查询。
7. `STAT/LIST/RETR` 行为符合基本 POP3 客户端要求。
8. 验证码查询复用现有 Provider 和验证码提取逻辑。
9. HTTP API 与 POP3 服务可以同时运行。
10. POP3 服务异常不会导致 HTTP API 进程崩溃。
11. 不向日志输出密码、邮箱 token、验证码和邮件正文。
12. POP3S 995 可以通过 TLS 正常连接。
13. 桌面端只需要把服务器从本地地址改成线上 POP3 域名，并按配置启用 SSL/TLS。

## 17. 明确不做的事情

第一阶段不实现：

- 在 POP3 服务器地址后拼接 GET 参数；
- 把 HTTP `X-API-Key` 放进 POP3 用户名；
- 把 CloudMail 管理员账号密码暴露给桌面端；
- 把完整 CloudMail API 透传给 POP3 客户端；
- SMTP 发信；
- IMAP；
- 完整邮件历史和完整正文服务；
- 让 POP3 客户端直接访问 PostgreSQL。
