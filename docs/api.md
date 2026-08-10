# Xiaoasi Mail Gateway API 接口文档

## 1. 基本信息

- 生产协议：HTTPS
- 数据格式：JSON
- 生产地址：`https://cloudmail.xiaoasi.xyz`
- 管理端：`https://cloudmail.xiaoasi.xyz/admin/`
- 所有业务接口：必须提供管理端创建的 `X-API-Key`
- 邮箱后续操作：同时使用 `X-API-Key` 和创建时返回的 `mailboxToken`
- 管理接口：使用 HttpOnly Cookie 登录会话

## 2. 接口总览

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/healthz` | 健康检查 | 无 |
| POST | `/v1/mailboxes` | 创建邮箱 | `X-API-Key`，建议 `Idempotency-Key` |
| GET | `/v1/mailboxes/{id}` | 查询邮箱状态 | `X-API-Key` + `Mailbox` 凭证 |
| POST | `/v1/mailboxes/{id}/verification-code` | 查询验证码 | `X-API-Key` + `Mailbox` 凭证 |
| DELETE | `/v1/mailboxes/{id}` | 释放邮箱会话 | `X-API-Key` + `Mailbox` 凭证 |
| POST | `/admin-api/auth/login` | 管理端登录 | 管理账号密码 |
| GET | `/admin-api/auth/session` | 查询管理会话 | Cookie，可匿名检查 |
| POST | `/admin-api/auth/logout` | 管理端退出 | Cookie |
| GET | `/admin-api/overview` | 管理概览 | Cookie |
| GET/POST | `/admin-api/instances` | 查询或新增实例 | Cookie |
| GET/PATCH/DELETE | `/admin-api/instances/{id}` | 查询、编辑或删除实例 | Cookie |
| POST | `/admin-api/instances/{id}/test` | 测试实例连接和管理员凭据 | Cookie |
| GET/POST | `/admin-api/domains` | 查询或新增域名 | Cookie |
| PATCH/DELETE | `/admin-api/domains/{id}` | 编辑或删除域名 | Cookie |
| POST | `/admin-api/domains/{id}/clear-cooldown` | 解除域名冷却 | Cookie |
| GET/POST | `/admin-api/client-keys` | 查询或新增调用密钥 | Cookie |
| PATCH/DELETE | `/admin-api/client-keys/{id}` | 启停或删除调用密钥 | Cookie |
| POST | `/admin-api/client-keys/{id}/regenerate` | 重新生成调用密钥 | Cookie |
| GET | `/admin-api/mailboxes` | 邮箱记录 | Cookie |
| GET | `/admin-api/request-logs` | 请求日志 | Cookie |

## 3. 创建邮箱

调用密钥在管理端“调用密钥”页面创建。按当前产品要求，密钥以明文保存在 PostgreSQL，并在管理端完整显示和复制；重新生成后旧密钥立即失效，停用或删除后相关调用立即被拒绝。

```http
POST /v1/mailboxes
Content-Type: application/json
Idempotency-Key: register-task-123
X-API-Key: xmk_xxxxxxxxx
```

自动域名：

```json
{
  "purpose": "openai"
}
```

指定单域名：

```json
{
  "purpose": "openai",
  "domain": "mail-a.example.com",
  "addressPattern": "name_digits_4",
  "name": "kirox"
}
```

指定候选域名：

```json
{
  "purpose": "grok",
  "domains": ["mail-a.example.com", "mail-b.example.com"],
  "addressPattern": "name_random_6",
  "name": "kirox"
}
```

规则：

- `domain` 与 `domains` 不能同时传；
- `addressPattern` 非必填，默认 `name_digits_4`；
- `name` 非必填；未提供 `name` 和兼容字段 `prefix` 时，网关随机选择内置英文名；
- `prefix` 是旧客户端兼容字段，新接入统一使用 `name`；
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
    "address": "kirox4821@mail-a.example.com",
    "domain": "mail-a.example.com",
    "mailboxToken": "eyJ...signature",
    "createdAt": "2026-08-10T08:00:00+00:00",
    "expiresAt": "2026-08-10T08:30:00+00:00"
  }
}
```

用户名生成规则：

| `addressPattern` | 示例 | 说明 |
| --- | --- | --- |
| `name_digits_4` | `olivia4821` | 默认规则，姓名基础值加 4 位数字 |
| `name_digits_6` | `olivia482193` | 姓名基础值加 6 位数字 |
| `name_random_6` | `oliviak3m8x2` | 姓名基础值加 6 位小写字母或数字 |
| `random_12` | `k3m8x2p9q4vd` | 纯 12 位随机小写字母或数字 |
| `legacy_prefix_random` | `image2api-k3m8x2p9q4vd` | 兼容旧版“前缀-12位随机串”格式 |

`name` 会转为小写，只保留 ASCII 字母和数字，最长使用 16 个字符。空值、中文或保留名称会自动替换为内置英文名。短数字规则存在理论碰撞概率，网关检测到地址已存在时会自动重新生成，最多尝试 5 次，不会把已有邮箱当作新邮箱返回。

## 4. Mailbox 鉴权

后续接口请求头：

```http
Authorization: Mailbox <mailboxToken>
X-API-Key: <创建该邮箱的调用密钥>
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
    "address": "kirox4821@mail-a.example.com",
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
- `openai` 只从“输入此临时验证码以继续 / Enter this temporary verification code to continue”上下文提取 6 位数字；
- `kiro` 支持中文、英文和日文的验证码上下文，提取 6 位数字；
- `cursor` 从“一次性验证码 / one-time verification code”上下文提取 6 位数字；
- `grok` 只提取 `NVK-5XZ` 形式的 3-3 位带连字符短码；
- 其他用途使用带验证码上下文的 4～8 位数字通用规则；
- 邮件必须具有可靠收件时间，并且不得早于邮箱创建时间 15 秒以上；无时间邮件和历史邮件不会用于完成验证码查询；
- HTML 中的 `style`、`script` 和标签会先清理，避免把颜色值、年份等误识别为验证码。

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
| 401 | `CLIENT_KEY_INVALID` | 调用密钥缺失、无效或已停用 |
| 403 | `MAILBOX_ACCESS_DENIED` | 调用密钥与邮箱所属调用方不匹配 |
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
