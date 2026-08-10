# Xiaoasi Mail Gateway API 接口文档

## 1. 基本信息

- 生产协议：HTTPS
- 数据格式：JSON
- 示例地址：`https://mail-api.example.com`
- 业务创建接口：当前公开，通过 IP 限流保护
- 邮箱后续操作：使用创建时返回的 `mailboxToken`
- 管理接口：使用 HttpOnly Cookie 登录会话

## 2. 接口总览

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/healthz` | 健康检查 | 无 |
| POST | `/v1/mailboxes` | 创建邮箱 | 无，建议 `Idempotency-Key` |
| GET | `/v1/mailboxes/{id}` | 查询邮箱状态 | `Mailbox` 凭证 |
| POST | `/v1/mailboxes/{id}/verification-code` | 查询验证码 | `Mailbox` 凭证 |
| DELETE | `/v1/mailboxes/{id}` | 释放邮箱会话 | `Mailbox` 凭证 |
| POST | `/admin-api/auth/login` | 管理端登录 | 管理账号密码 |
| GET | `/admin-api/auth/session` | 查询管理会话 | Cookie，可匿名检查 |
| POST | `/admin-api/auth/logout` | 管理端退出 | Cookie |
| GET | `/admin-api/overview` | 管理概览 | Cookie |
| GET/POST/PATCH/DELETE | `/admin-api/instances` | 实例管理 | Cookie |
| GET/POST/PATCH/DELETE | `/admin-api/domains` | 域名管理 | Cookie |
| GET | `/admin-api/mailboxes` | 邮箱记录 | Cookie |
| GET | `/admin-api/request-logs` | 请求日志 | Cookie |

## 3. 创建邮箱

```http
POST /v1/mailboxes
Content-Type: application/json
Idempotency-Key: register-task-123
X-Client-Source: image2api
```

自动域名：

```json
{
  "purpose": "openai",
  "prefix": "image2api",
  "source": "image2api"
}
```

指定单域名：

```json
{
  "purpose": "openai",
  "domain": "mail-a.example.com",
  "prefix": "kirox",
  "source": "kirox"
}
```

指定候选域名：

```json
{
  "purpose": "grok",
  "domains": ["mail-a.example.com", "mail-b.example.com"],
  "prefix": "kirox",
  "source": "kirox"
}
```

规则：

- `domain` 与 `domains` 不能同时传；
- 指定单域名失败时不切换其他域名；
- 候选范围和自动模式可以跨 CloudMail 实例失败切换；
- 同一 `Idempotency-Key` 和相同参数返回原邮箱；
- 同一幂等键配合不同参数返回 `409 IDEMPOTENCY_CONFLICT`；
- `Idempotency-Key` 最大 256 个字符；
- 响应不返回实际 CloudMail 实例和上游 Token。

成功响应：

```json
{
  "code": 200,
  "data": {
    "mailboxId": "mbx_01k2example",
    "address": "image2apiabc123@mail-a.example.com",
    "domain": "mail-a.example.com",
    "mailboxToken": "eyJ...signature",
    "createdAt": "2026-08-10T08:00:00+00:00",
    "expiresAt": "2026-08-10T08:30:00+00:00"
  }
}
```

## 4. Mailbox 鉴权

后续接口请求头：

```http
Authorization: Mailbox <mailboxToken>
```

凭证规则：

- 只允许访问对应的一个 `mailboxId`；
- 到期后返回 `MAILBOX_SESSION_EXPIRED`；
- 邮箱 A 的凭证不能访问邮箱 B；
- 不要在客户端普通日志中打印完整值。

## 5. 查询邮箱状态

```http
GET /v1/mailboxes/{mailboxId}
Authorization: Mailbox <mailboxToken>
```

响应：

```json
{
  "code": 200,
  "data": {
    "mailboxId": "mbx_01k2example",
    "address": "image2apiabc123@mail-a.example.com",
    "domain": "mail-a.example.com",
    "status": "active",
    "verificationStatus": "pending",
    "createdAt": "2026-08-10T08:00:00+00:00",
    "expiresAt": "2026-08-10T08:30:00+00:00"
  }
}
```

## 6. 查询验证码

```http
POST /v1/mailboxes/{mailboxId}/verification-code
Authorization: Mailbox <mailboxToken>
Content-Type: application/json
```

请求：

```json
{
  "purpose": "openai",
  "waitSeconds": 20,
  "pollIntervalSeconds": 2
}
```

限制：

- `waitSeconds` 范围 0～30 秒；
- `pollIntervalSeconds` 范围 0.2～10 秒；
- `purpose` 为空时沿用创建邮箱时的用途；
- `openai` 默认提取 4～8 位数字验证码；
- `grok` 支持数字、字母数字及带连字符验证码；
- 自动过滤邮箱创建时间之前的历史邮件。

收到验证码：

```json
{
  "code": 200,
  "data": {
    "status": "received",
    "verificationCode": "123456"
  }
}
```

尚未收到：

```json
{
  "code": 200,
  "data": {
    "status": "pending",
    "verificationCode": ""
  }
}
```

## 7. 释放邮箱

```http
DELETE /v1/mailboxes/{mailboxId}
Authorization: Mailbox <mailboxToken>
```

该接口把网关记录标记为 `released`，目前不删除 CloudMail 上游账号。

## 8. 错误格式

```json
{
  "code": "NO_AVAILABLE_DOMAIN",
  "message": "当前没有可用邮箱域名"
}
```

常见错误：

| HTTP | code | 说明 |
| --- | --- | --- |
| 400 | `DOMAIN_SELECTOR_CONFLICT` | 同时传入 `domain` 与 `domains` |
| 400 | `DOMAIN_NOT_ALLOWED` | 指定域名不在域名池 |
| 401 | `MAILBOX_TOKEN_INVALID` | 邮箱凭证缺失、格式错误或跨邮箱使用 |
| 401 | `MAILBOX_SESSION_EXPIRED` | 邮箱会话已过期 |
| 404 | `MAILBOX_NOT_FOUND` | 邮箱记录不存在 |
| 409 | `IDEMPOTENCY_CONFLICT` | 幂等键对应不同参数 |
| 429 | `RATE_LIMITED` | 超过业务接口限流 |
| 502 | `MAILBOX_CREATE_FAILED` | 上游创建邮箱失败 |
| 502 | `MAILBOX_QUERY_FAILED` | 上游查询邮件失败 |
| 503 | `DOMAIN_UNAVAILABLE` | 指定域名当前不可用 |
| 503 | `NO_AVAILABLE_DOMAIN` | 没有可用域名 |
| 503 | `INSTANCE_UNAVAILABLE` | 邮箱所属实例不可用 |

## 9. 管理端登录

管理端登录按请求来源进行分钟级限流，默认每分钟最多 10 次，可通过 `ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE` 调整。

```http
POST /admin-api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "管理密码"
}
```

成功后服务端写入 HttpOnly Cookie，前端请求必须使用 `credentials: include`。

管理端 CRUD 请求和响应字段与页面表单一致。实例响应永远不包含管理员密码和 CloudMail Token。

## 10. 兼容接口

迁移阶段保留：

- `POST /v1/token`
- `POST /v1/token/refresh`
- `POST /api/public/genToken`

只有配置旧的 `CLOUDMAIL_BASE_URL`、`CLOUDMAIL_ADMIN_EMAIL` 和 `CLOUDMAIL_ADMIN_PASSWORD` 后才可使用；没有配置时返回 `LEGACY_BROKER_DISABLED`。
