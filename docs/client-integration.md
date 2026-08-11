# Xiaoasi Mail 调用方接入指南

本文档提供给图片站、Kirox、Windows EXE 或其他业务调用方。调用方只接入 Xiaoasi Mail Gateway，不直接访问 CloudMail。

## 1. 接入前准备

普通调用方需要先拥有一个普通用户账号：

1. 登录用户中心；
2. 设置用户级 `userAuthCode`；
3. 创建自己的 `X-API-Key`；
4. 确认积分余额；
5. 使用该密钥调用网关创建邮箱。

生产地址：

```text
API Base URL: https://cloudmail.xiaoasi.xyz
用户中心：    https://cloudmail.xiaoasi.xyz/user/
健康检查：    https://cloudmail.xiaoasi.xyz/healthz
POP3：        pop.cloudmail.xiaoasi.xyz:110
```

调用方不需要配置 CloudMail 地址、管理员账号、管理员密码、Token 或内部邮箱密码。

## 2. 接入流程

```text
用户中心设置 userAuthCode 和 X-API-Key
  → 使用 X-API-Key 创建邮箱
  → 保存 mailboxId、address、mailboxToken
  → 使用 address 触发第三方验证邮件
  → 通过 HTTP mailboxToken 查询验证码，或通过 POP3 110 读取邮件
  → 任务结束后释放邮箱会话
```

## 3. 创建邮箱

```http
POST https://cloudmail.xiaoasi.xyz/v1/mailboxes
Content-Type: application/json
Idempotency-Key: 每次注册任务的唯一键
X-API-Key: 用户自己创建的调用密钥
```

最简请求：

```json
{
  "purpose": "openai"
}
```

完整字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `purpose` | string | 否 | `openai` | 用途，例如 `openai`、`grok` |
| `domain` | string | 否 | 无 | 指定一个邮箱域名 |
| `domains` | string[] | 否 | 无 | 限定候选域名范围 |
| `addressPattern` | string | 否 | `name_digits_4` | 用户名生成规则 |
| `name` | string | 否 | Faker 英文名 | 用户名基础值 |
| `prefix` | string | 否 | 空 | 旧客户端兼容字段 |

`domain` 和 `domains` 不能同时传。不传时由网关根据实例健康状态、域名状态和权重自动选择。

创建邮箱前，网关校验：

- `X-API-Key` 属于有效普通用户；
- 用户状态为可用；
- 用户已经设置 `userAuthCode`；
- 用户积分余额足够；
- 请求参数和幂等键一致。

创建过程是“积分预扣 → CloudMail 创建 → 成功确认或失败退款”。网络超时会保留 `pending` 状态，调用方不要立刻换新幂等键重复创建。

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

调用方必须保存：

- `mailboxId`；
- `address`；
- `mailboxToken`；
- `expiresAt`。

不要在普通日志中打印完整 `X-API-Key`、`mailboxToken`、`userAuthCode`、邮件正文或验证码。

## 4. 查询验证码

```http
POST https://cloudmail.xiaoasi.xyz/v1/mailboxes/{mailboxId}/verification-code
X-API-Key: 用户自己创建的调用密钥
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

`pending` 是正常业务状态，不应当作接口异常。建议服务端单次等待 15～20 秒，调用方不要高频并发轮询同一邮箱。

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

暂未收到：

```json
{
  "code": 200,
  "data": {
    "status": "pending",
    "verificationCode": ""
  }
}
```

## 5. 查询状态和释放邮箱

查询状态：

```http
GET https://cloudmail.xiaoasi.xyz/v1/mailboxes/{mailboxId}
X-API-Key: 用户自己创建的调用密钥
Authorization: Mailbox <mailboxToken>
```

释放邮箱：

```http
DELETE https://cloudmail.xiaoasi.xyz/v1/mailboxes/{mailboxId}
X-API-Key: 用户自己创建的调用密钥
Authorization: Mailbox <mailboxToken>
```

释放只会把网关记录标记为 `released`，不保证删除 CloudMail 上游邮箱账号。

## 6. POP3 110 读取邮件

普通用户在邮件客户端中配置：

```text
服务器：pop.cloudmail.xiaoasi.xyz
端口：110
安全性：普通 POP3
用户名：创建成功返回的完整 address
密码：当前用户设置的 userAuthCode
```

网关收到：

```text
USER 邮箱地址
PASS 用户 userAuthCode
```

后按邮箱归属用户校验授权，并调用该邮箱记录绑定的 CloudMail 实例查询邮件。

首期支持：

- `USER`；
- `PASS`；
- `STAT`；
- `LIST`；
- `UIDL`；
- `RETR`；
- `QUIT`。

首期不支持 `995`、SMTP、IMAP、`DELE`、附件和完整原始 MIME。为兼容常见邮件客户端，首期支持 `CAPA`、`NOOP`、`RSET` 和 `TOP`；客户端必须关闭“从服务器删除邮件”，网关对 `DELE` 返回只读错误。

## 7. 幂等键和重试

调用方每次注册任务应生成稳定且唯一的 `Idempotency-Key`：

- 相同用户、相同参数和相同幂等键重试，返回原邮箱；
- 相同幂等键配合不同参数，返回 `409 IDEMPOTENCY_CONFLICT`；
- 不同用户可以使用相同幂等键；
- CloudMail 明确失败可以按错误策略重试；
- 网络超时不能直接换新幂等键，否则可能造成重复邮箱和重复扣费。

## 8. 错误处理

| HTTP | code | 处理建议 |
| --- | --- | --- |
| 400 | `DOMAIN_SELECTOR_CONFLICT` | 只保留 `domain` 或 `domains` |
| 400 | `DOMAIN_NOT_ALLOWED` | 使用允许域名或不指定域名 |
| 401 | `API_KEY_INVALID` | 检查用户调用密钥 |
| 401 | `MAILBOX_TOKEN_INVALID` | 检查邮箱 Token 和 mailboxId |
| 401 | `MAILBOX_SESSION_EXPIRED` | 重新创建邮箱 |
| 403 | `USER_FORBIDDEN` | 确认邮箱属于当前用户 |
| 409 | `USER_AUTH_CODE_REQUIRED` | 先在用户中心设置 userAuthCode |
| 409 | `IDEMPOTENCY_CONFLICT` | 为不同参数使用新幂等键 |
| 402 | `INSUFFICIENT_CREDITS` | 联系管理员增加积分 |
| 429 | `RATE_LIMITED` | 降低请求频率并退避 |
| 502 | `MAILBOX_CREATE_FAILED` | 按幂等策略重试 |
| 503 | `NO_AVAILABLE_DOMAIN` | 联系管理员检查实例和域名 |

## 9. 调用方边界

调用方不得：

- 获取或保存 CloudMail 管理员凭据；
- 获取 CloudMail Token；
- 直接调用 CloudMail `genToken`、`addUser`、`emailList`；
- 把用户 POP 授权码写入普通日志；
- 把邮箱内容和验证码写入长期日志；
- 把普通用户的 `X-API-Key` 当作管理员凭证使用。
