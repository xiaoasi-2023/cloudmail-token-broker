# Xiaoasi Mail Gateway API 接口文档

## 1. 基本信息

- 生产协议：HTTPS；POP3 使用独立 TCP `18110`；
- 生产 API：`https://cloudmail.xiaoasi.xyz`；
- 管理端：`https://cloudmail.xiaoasi.xyz/admin/`；
- 用户中心：`https://cloudmail.xiaoasi.xyz/user/`；
- 默认入口：`https://cloudmail.xiaoasi.xyz/`，自动跳转用户中心，未登录时显示登录/注册页；
- POP3：`pop.cloudmail.xiaoasi.xyz:18110`；
- `110` 和 `995` 映射暂时保留，但当前服务器厂商禁止使用；
- `/admin/` 和 `/user/` 都是同一 FastAPI 容器提供的静态入口，不是 HTTP 模拟的 POP 服务；
- 业务 API 使用用户自己的 `X-API-Key`；
- 邮箱查询、验证码和释放接口同时使用 `X-API-Key` 与 `mailboxToken`；
- 管理端和用户中心使用 HttpOnly Cookie 会话。

## 2. 接口总览

### 用户中心

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/user-api/auth/registration-config` | 查询是否开放自助注册及验证码时间配置 |
| POST | `/user-api/auth/register-code` | 向注册邮箱发送 6 位验证码 |
| POST | `/user-api/auth/register` | 校验邮箱验证码并创建普通用户 |
| POST | `/user-api/auth/login` | 用户登录 |
| POST | `/user-api/auth/logout` | 用户退出 |
| PUT | `/user-api/auth/password` | 修改登录密码 |
| POST | `/user-api/auth/sessions/revoke-all` | 撤销全部会话 |
| GET | `/user-api/me` | 当前用户信息 |
| GET/POST | `/user-api/api-keys` | 查询或创建用户调用密钥 |
| POST | `/user-api/api-keys/{keyId}/regenerate` | 重新生成调用密钥并使旧值失效 |
| DELETE | `/user-api/api-keys/{keyId}` | 撤销调用密钥 |
| GET/PUT | `/user-api/auth-code` | 查询或保存用户 POP 授权码明文及 POP3 连接参数 |
| GET | `/user-api/credits` | 查询积分余额和流水摘要 |
| GET | `/user-api/mailboxes` | 查询自己的邮箱记录 |
| POST | `/user-api/mailboxes/batch` | 批量创建 1 至 50 个自己的 POP 邮箱 |

### 普通业务 API

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/healthz` | 健康检查 | 无 |
| POST | `/v1/mailboxes` | 创建邮箱 | 用户 `X-API-Key`，建议 `Idempotency-Key` |
| GET | `/v1/mailboxes/{id}` | 查询邮箱状态 | `X-API-Key` + `Mailbox` |
| POST | `/v1/mailboxes/{id}/verification-code` | 查询验证码 | `X-API-Key` + `Mailbox` |
| DELETE | `/v1/mailboxes/{id}` | 释放邮箱会话 | `X-API-Key` + `Mailbox` |

### 管理端 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/admin-api/auth/login` | 管理员登录 |
| POST | `/admin-api/auth/logout` | 管理员退出 |
| GET | `/admin-api/users` | 用户列表 |
| POST | `/admin-api/users` | 创建普通用户 |
| PATCH | `/admin-api/users/{userId}` | 启停用户 |
| POST | `/admin-api/users/{userId}/reset-auth-code` | 重置用户 POP 授权码 |
| POST | `/admin-api/users/{userId}/credits/adjust` | 调整用户积分 |
| GET | `/admin-api/users/{userId}/credit-transactions` | 用户积分流水 |
| GET/PUT | `/admin-api/credit-rules` | 查询或修改积分规则 |
| GET/PUT | `/admin-api/pop-auth-code` | 查询、设置或修改管理员全局 POP 授权码明文 |
| GET | `/admin-api/mailboxes` | 查看全部邮箱 |
| GET | `/admin-api/instances` | CloudMail 实例 |
| POST | `/admin-api/instances` | 新增 CloudMail 实例 |
| GET/PATCH/DELETE | `/admin-api/instances/{instanceId}` | 查询、修改或删除实例 |
| POST | `/admin-api/instances/{instanceId}/test` | 测试实例连接 |
| GET/POST/PATCH/DELETE | `/admin-api/domains` | 邮箱域名 |
| POST | `/admin-api/domains/{domainId}/clear-cooldown` | 清除域名冷却 |
| GET | `/admin-api/overview` | 管理端概览 |
| GET | `/admin-api/request-logs` | 请求日志 |

管理员接口只使用管理员会话，不需要用户 `X-API-Key` 或 `mailboxToken`。当前 HTTP 管理 API 提供全部邮箱记录和请求日志查询；管理员查看邮件正文使用 POP3 `18110` + 管理员全局 POP 授权码，不提供独立的 HTTP 邮件内容、刷新、释放或邮箱 POP 开关接口。用户释放自己的邮箱仍使用普通业务 API 的 `DELETE /v1/mailboxes/{id}`。

管理员执行 `POST /admin-api/users/{userId}/reset-auth-code` 时，只会立即使该用户旧授权码失效并清除“已配置”状态，不向管理员返回新授权码明文。普通用户需要登录用户中心点击按钮重新生成自己的 `userAuthCode`；这样管理员拥有全量邮箱访问权限，但不会接触普通用户授权码明文。

`GET /user-api/auth-code` 只允许当前登录用户访问，返回该用户自己的 `user_auth_code`、公网 `pop_host`、由 `POP3_PUBLIC_PORT` 配置的 `pop_port` 和该用户可用的邮箱地址列表；列表同时包含状态为 `active` 或 `expired` 且启用 POP 的邮箱。当前生产配置为 `18110`。普通用户授权码按明文保存，因此用户下次登录后仍可查看和复制；从旧版哈希字段升级的授权码无法反推，需要用户重置一次。用户调用密钥同样按明文保存并在 `GET /user-api/api-keys` 中返回给所属用户；旧哈希密钥需要调用重新生成接口后才能完整显示。

列表查询补充：

- `GET /user-api/mailboxes` 支持 `keyword`、`purpose`、`status`、`verification_status`，只查询当前登录用户的邮箱；返回字段包含当前用户有权查看的 `verification_code`，用户中心可直接复制已识别验证码。
- `GET /admin-api/request-logs` 支持 `keyword` 和 `status_group`；`keyword` 可匹配接口、错误码、调用密钥名称、用户名或用户邮箱，`status_group` 可取 `success`、`client_error`、`server_error`。
- 请求日志返回 `user_id`、`user_username`、`user_email` 和调用密钥名称，便于管理员确认实际调用人；日志仍不记录授权码、Token、验证码或邮件正文。

### 邮箱验证码注册

部署配置 `USER_REGISTRATION_ENABLED=true` 后，用户中心 `/user/` 会显示注册入口。先发送验证码：

```http
POST /user-api/auth/register-code
Content-Type: application/json

{"email":"user@example.com"}
```

再提交注册：

```http
POST /user-api/auth/register
Content-Type: application/json

{
  "username": "user001",
  "email": "user@example.com",
  "password": "至少10位登录密码",
  "code": "123456"
}
```

注册只能创建普通 `user`，初始积分读取管理端 `create_mailbox` 规则中的新用户初始积分。验证码默认 10 分钟有效，同一邮箱默认 60 秒内不能重复发送，连续输错 5 次后失效；验证码明文不会写入数据库或日志。注册成功后可使用账号或邮箱登录。

## 3. 创建邮箱

```http
POST /v1/mailboxes
Content-Type: application/json
Idempotency-Key: register-task-123
X-API-Key: xmk_user_key
```

请求：

```json
{
  "purpose": "openai",
  "domain": "mail-a.example.com",
  "addressPattern": "name_digits_4",
  "name": "kirox"
}
```

规则：

- `domain` 与 `domains` 不能同时传；
- 不传域名时由网关自动选择健康域名；
- 指定单域名失败时不切换其他域名；
- 候选域名和自动模式允许跨实例切换；
- `addressPattern` 默认是 `name_digits_4`；
- 邮箱完整地址由网关生成，不接受调用方提交完整 `email`；
- 创建前校验用户状态、积分余额和用户 POP 授权码配置；
- 预扣积分后调用 CloudMail，成功确认扣费，明确失败退款；
- 网络超时保持 `pending`，不得直接退款后重复创建；
- 同一用户、同一幂等键和相同参数返回原邮箱，不重复扣费；
- 不同用户使用相同幂等键互不影响。

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
    "expiresAt": "2026-08-10T08:30:00+00:00",
    "remainingCredits": 99
  }
}
```

`mailboxToken` 只在创建成功响应中返回，不包含 CloudMail Token、管理员信息或邮箱内部密码。响应中的 `expiresAt` 是 HTTP 临时会话期限，不是 POP3 邮箱过期时间。

### 3.1 用户中心批量创建

```http
POST /user-api/mailboxes/batch
Content-Type: application/json
Idempotency-Key: batch-task-20260812-001
Cookie: xiaoasi_user_session=<用户登录会话>
```

```json
{
  "count": 10,
  "purpose": "openai",
  "domain": "mail-a.example.com"
}
```

- `count` 范围为 1 至 50；
- 必须先配置用户级 `userAuthCode`；
- 不传 `domain` 时自动选择健康域名；
- 服务端最多同时创建 5 个，每一项都复用单邮箱的归属、积分和退款规则；
- 同一用户使用相同 `Idempotency-Key` 和相同参数重试时，不重复创建或扣费；
- 允许部分成功，成功邮箱直接进入当前用户的“我的邮箱”列表，失败项在 `errors` 中逐条返回；
- 网络超时后先刷新邮箱和积分列表确认结果，不要立即使用新的幂等键重复提交。

响应示例：

```json
{
  "ok": true,
  "data": {
    "requested": 10,
    "succeeded": 9,
    "failed": 1,
    "created": [{ "mailboxId": "mbx_example", "address": "user1234@mail-a.example.com" }],
    "errors": [{ "index": 9, "code": "INSUFFICIENT_CREDITS", "message": "积分余额不足" }]
  }
}
```

## 4. HTTP 邮箱鉴权

```http
X-API-Key: <用户自己的调用密钥>
Authorization: Mailbox <mailboxToken>
```

普通用户请求必须同时满足：

- 调用密钥有效且属于当前用户；
- `mailboxToken` 与 `mailboxId` 匹配且未过期；
- 邮箱 `owner_user_id` 与调用密钥用户一致。

管理员不使用这些凭证访问管理 API。管理员访问全部邮箱使用管理员会话，POP 客户端访问全部邮箱使用管理员全局 POP 授权码。

## 5. 查询邮箱状态

```http
GET /v1/mailboxes/{mailboxId}
X-API-Key: <用户自己的调用密钥>
Authorization: Mailbox <mailboxToken>
```

常见状态：`active`、`expired`、`released`、`failed`。

## 6. 查询验证码

```http
POST /v1/mailboxes/{mailboxId}/verification-code
X-API-Key: <用户自己的调用密钥>
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

`pending` 是正常业务状态，不代表接口异常。调用方应控制轮询频率，直到收到验证码、业务超时或邮箱过期。

## 7. 释放邮箱

```http
DELETE /v1/mailboxes/{mailboxId}
X-API-Key: <用户自己的调用密钥>
Authorization: Mailbox <mailboxToken>
```

该接口将网关记录标记为 `released`，不保证删除 CloudMail 上游账号。

## 8. POP3 18110

### 普通用户

```text
服务器：pop.cloudmail.xiaoasi.xyz
端口：18110
安全性：普通 POP3
用户名：邮箱 address
密码：该邮箱所属用户的 userAuthCode
```

普通用户授权码只能访问该用户自己的邮箱。用户重置授权码后，旧授权码立即失效。

POP3 生命周期与 HTTP `mailboxToken` 解耦：普通用户可读取自己名下状态为 `active` 或 `expired` 且 `pop_enabled=true` 的邮箱，不检查 `expiresAt`。状态为 `released`、关闭 POP、邮箱归属不匹配或上游邮箱已物理删除时仍拒绝访问。HTTP 状态和验证码接口继续要求未过期的 `mailboxToken`。

### 管理员

```text
服务器：pop.cloudmail.xiaoasi.xyz
端口：18110
安全性：普通 POP3
用户名：任意未物理删除且上游仍存在的邮箱 address
密码：管理员全局 POP 授权码
```

管理员全局 POP 授权码可以读取全部用户、过期和已释放邮箱，但不能读取已经物理清理或 CloudMail 上游已删除的邮箱。当前 `18110` 使用普通明文 POP3，不支持 STLS 或隐式 TLS；虽然 Compose 保留 `995` 映射，但它不是 POP3S 服务端口。

首期命令：`CAPA`、`USER`、`PASS`、`STAT`、`LIST`、`UIDL`、`RETR`、`TOP`、`NOOP`、`RSET`、`QUIT`。其中 `CAPA`、`NOOP`、`RSET` 和 `TOP` 用于兼容常见邮件客户端；`DELE`、SMTP、IMAP、附件和完整原始 MIME 不在首期范围内。客户端必须关闭“从服务器删除邮件”，网关对 `DELE` 返回只读错误。

## 9. 错误格式和错误码

```json
{
  "code": "INSUFFICIENT_CREDITS",
  "message": "积分余额不足"
}
```

| HTTP/协议 | code | 说明 |
| --- | --- | --- |
| 400 | `DOMAIN_SELECTOR_CONFLICT` | 同时传入 `domain` 与 `domains` |
| 400 | `DOMAIN_NOT_ALLOWED` | 域名不在允许列表 |
| 400 | `EMAIL_INVALID` | 注册邮箱格式无效 |
| 400 | `USERNAME_INVALID` | 注册账号格式无效 |
| 400 | `REGISTER_CODE_INVALID` | 注册验证码错误、过期或输错次数过多 |
| 401 | `API_KEY_INVALID` | 用户调用密钥无效或已撤销 |
| 401 | `MAILBOX_TOKEN_INVALID` | 邮箱凭证无效 |
| 401 | `MAILBOX_SESSION_EXPIRED` | HTTP 邮箱会话凭证过期；不影响符合条件的 POP3 读取 |
| 401 | `USER_AUTH_CODE_INVALID` | 普通用户 POP 授权码错误 |
| POP `-ERR` | `ADMIN_POP_AUTH_CODE_INVALID` | 管理员全局 POP 授权码错误 |
| 403 | `USER_FORBIDDEN` | 普通用户访问其他用户资源 |
| 404 | `MAILBOX_NOT_FOUND` | 邮箱记录不存在 |
| 409 | `IDEMPOTENCY_CONFLICT` | 幂等键对应不同参数 |
| 409 | `USER_AUTH_CODE_REQUIRED` | 创建邮箱前未设置用户授权码 |
| 409 | `USER_CONFLICT` | 注册账号或邮箱已存在 |
| 402 | `INSUFFICIENT_CREDITS` | 积分不足 |
| 502 | `MAILBOX_CREATE_FAILED` | CloudMail 创建失败 |
| 502 | `POP_QUERY_FAILED` | POP 查询上游邮件失败 |
| 503 | `NO_AVAILABLE_DOMAIN` | 没有可用域名 |
| 429 | `RATE_LIMITED` | 超过限流 |
| 429 | `REGISTER_CODE_TOO_FREQUENT` | 同一邮箱发送验证码过于频繁 |
| 502 | `EMAIL_SEND_FAILED` / `SMTP_AUTH_FAILED` | SMTP 发信或认证失败 |

## 10. 安全要求

- 用户登录密码、普通用户 POP 授权码、管理员全局 POP 授权码和调用密钥分别存储；POP 授权码和用户调用密钥按明文保存，并只通过对应受鉴权页面回显；
- 用户可以长期查看和复制自己的完整调用密钥及 POP 授权码；
- 管理员不能通过用户列表查看普通用户授权码明文，普通用户只能通过自己的用户会话读取自身授权码；
- 管理员全局 POP 授权码按产品要求直接以明文存入数据库，仅允许管理员会话通过 `/admin-api/pop-auth-code` 查询和修改；
- 管理员用户、积分、授权码、实例和域名等 HTTP 管理操作必须审计；POP3 邮件读取通过独立 TCP 会话完成，当前不提供独立的 HTTP POP 读取或 POP 会话审计接口；
- 日志不得记录授权码、调用密钥、邮箱内部密码、CloudMail Token、验证码明文或完整邮件正文；
- 18110 明文模式必须限制网络来源；
- 旧数据迁移必须先备份，使用显式 `--apply` 执行。
