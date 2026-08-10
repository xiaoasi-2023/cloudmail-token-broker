# Xiaoasi Mail 调用方接入指南

本文档可以直接提供给图片站、Kirox、Windows EXE 或其他项目的开发人员。

## 1. 生产环境

```text
API Base URL: https://cloudmail.xiaoasi.xyz
管理端:       https://cloudmail.xiaoasi.xyz/admin/
健康检查:     https://cloudmail.xiaoasi.xyz/healthz
```

调用方只接入 Xiaoasi Mail API，不需要配置或获取 CloudMail 地址、管理员账号、管理员密码、Token 和内部邮箱密码。

## 2. 接入流程

```text
创建邮箱
  → 保存 mailboxId、address、mailboxToken
  → 使用 address 完成第三方注册或触发验证码邮件
  → 使用 mailboxId + mailboxToken 查询验证码
  → 业务结束后释放邮箱会话
```

调用方需要向网关管理员申请一个长期 `X-API-Key`。所有业务接口都必须携带该密钥；查询、状态和释放接口还必须携带创建结果中的短期 `mailboxToken`。

## 3. 创建邮箱

```http
POST https://cloudmail.xiaoasi.xyz/v1/mailboxes
Content-Type: application/json
Idempotency-Key: 每次注册任务的唯一键
X-API-Key: 管理端为调用方创建的密钥
```

最简请求：

```json
{
  "purpose": "openai"
}
```

没有传用户名规则时，默认生成“随机英文名 + 4 位数字”，例如：

```text
olivia4821@可用域名
```

完整请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `purpose` | string | 否 | `openai` | 用途，影响验证码提取规则，例如 `openai`、`grok` |
| `domain` | string | 否 | 无 | 指定一个邮箱域名 |
| `domains` | string[] | 否 | 无 | 限定可选择的邮箱域名范围 |
| `addressPattern` | string | 否 | `name_digits_4` | 邮箱用户名生成规则 |
| `name` | string | 否 | 随机内置英文名 | 用户名基础值，例如 `kirox`、`image2api` |
| `prefix` | string | 否 | 空 | 旧客户端兼容字段；新项目使用 `name` |

`domain` 和 `domains` 不能同时传。不传时，网关根据实例状态、域名状态和权重自动选择。

### 3.1 用户名生成规则

| 规则 | 示例 | 适用场景 |
| --- | --- | --- |
| `name_digits_4` | `olivia4821` | 默认，地址简短自然 |
| `name_digits_6` | `olivia482193` | 需要更低碰撞概率 |
| `name_random_6` | `oliviak3m8x2` | 字母数字混合后缀 |
| `random_12` | `k3m8x2p9q4vd` | 不需要可读名称 |
| `legacy_prefix_random` | `image2api-k3m8x2p9q4vd` | 兼容旧版格式 |

示例：指定姓名基础值和候选域名：

```json
{
  "purpose": "openai",
  "domains": ["mail-a.example.com", "mail-b.example.com"],
  "addressPattern": "name_digits_4",
  "name": "kirox"
}
```

上面的域名仅用于展示请求格式。调用方不知道生产域名池时应省略 `domain` 和 `domains`，让网关自动选择；只有网关管理员明确提供了允许域名后才传指定范围。

`name` 会转为小写，只保留 ASCII 字母和数字，最长使用 16 个字符。空值、中文或 `admin`、`root`、`support` 等保留名称会自动替换为随机英文名。

如果生成地址已存在，网关会自动重新生成，最多尝试 5 次，不会把已有邮箱返回给本次任务。

### 3.2 幂等键

调用方每次注册任务应生成一个稳定且唯一的 `Idempotency-Key`，例如：

```text
image2api-register-任务ID-第几次尝试
```

- 网络超时后使用相同请求参数和相同幂等键重试，会返回原邮箱；
- 同一个幂等键不能配合不同请求参数使用，否则返回 `409 IDEMPOTENCY_CONFLICT`；
- 不同注册任务不能共用幂等键；
- 最大长度为 256 个字符。

### 3.3 创建响应

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

调用方必须保存：

- `mailboxId`：后续接口路径参数；
- `address`：实际用于接收邮件的邮箱地址；
- `mailboxToken`：只允许访问当前邮箱的短期凭证；
- `expiresAt`：邮箱会话到期时间。

不要在普通业务日志中打印完整 `mailboxToken`。

## 4. 查询验证码

```http
POST https://cloudmail.xiaoasi.xyz/v1/mailboxes/{mailboxId}/verification-code
Authorization: Mailbox <mailboxToken>
X-API-Key: <创建该邮箱的调用密钥>
Content-Type: application/json
```

推荐请求：

```json
{
  "purpose": "openai",
  "waitSeconds": 20,
  "pollIntervalSeconds": 2
}
```

字段规则：

- `purpose` 留空时沿用创建邮箱时的值；
- `waitSeconds` 范围为 0～30 秒；
- `pollIntervalSeconds` 范围为 0.2～10 秒；
- 建议由服务端单次等待 15～20 秒，调用方不要高频并发轮询同一邮箱；
- 网关按 `openai`、`kiro`、`cursor`、`grok` 使用独立的强匹配规则并直接返回验证码；
- OpenAI、Kiro、Cursor 返回 6 位数字，Grok 保留 `NVK-5XZ` 形式的连字符；
- 网关会过滤历史邮件、无可靠收件时间的邮件和 HTML/CSS 噪声，避免误提取年份或颜色值。

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

`pending` 是正常业务状态，不应当作接口异常。调用方可以等待后继续查询，直到收到验证码、业务超时或邮箱会话过期。

## 5. 查询邮箱状态

```http
GET https://cloudmail.xiaoasi.xyz/v1/mailboxes/{mailboxId}
Authorization: Mailbox <mailboxToken>
X-API-Key: <创建该邮箱的调用密钥>
```

常见状态：

- `active`：邮箱会话有效；
- `expired`：邮箱会话已到期；
- `released`：调用方已主动释放。

## 6. 释放邮箱

```http
DELETE https://cloudmail.xiaoasi.xyz/v1/mailboxes/{mailboxId}
Authorization: Mailbox <mailboxToken>
X-API-Key: <创建该邮箱的调用密钥>
```

当前释放操作会把网关记录标记为 `released`，不会删除 CloudMail 上游邮箱账号。

## 7. cURL 完整示例

创建邮箱：

```bash
curl -sS -X POST 'https://cloudmail.xiaoasi.xyz/v1/mailboxes' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: kirox-register-10001-1' \
  -H 'X-API-Key: 替换为调用密钥' \
  -d '{"purpose":"openai","addressPattern":"name_digits_4","name":"kirox"}'
```

查询验证码：

```bash
curl -sS -X POST 'https://cloudmail.xiaoasi.xyz/v1/mailboxes/替换为mailboxId/verification-code' \
  -H 'Authorization: Mailbox 替换为mailboxToken' \
  -H 'X-API-Key: 替换为调用密钥' \
  -H 'Content-Type: application/json' \
  -d '{"purpose":"openai","waitSeconds":20,"pollIntervalSeconds":2}'
```

## 8. 调用方实现要求

1. 配置 API Base URL 和管理端签发的 `X-API-Key`。
2. 不再保留 CloudMail 管理员账号、密码、Token 获取和 Token 刷新逻辑。
3. 为每次注册任务生成唯一幂等键。
4. 创建成功后保存 `mailboxId`、`address`、`mailboxToken` 和 `expiresAt`。
5. 后续请求使用 `Authorization: Mailbox <mailboxToken>`。
6. HTTP 超时、502、503 可以按业务策略退避重试；400、401、409 通常需要修正请求或重新创建邮箱。
7. 不记录完整邮箱凭证、验证码或邮件正文。

## 9. 常见错误

| HTTP | code | 处理建议 |
| --- | --- | --- |
| 400 | `DOMAIN_SELECTOR_CONFLICT` | 只保留 `domain` 或 `domains` 其中一个 |
| 400 | `DOMAIN_NOT_ALLOWED` | 改用管理端已配置的域名，或不指定域名 |
| 401 | `MAILBOX_TOKEN_INVALID` | 检查凭证格式及 mailboxId 是否匹配 |
| 401 | `CLIENT_KEY_INVALID` | 检查调用密钥是否正确、启用 |
| 403 | `MAILBOX_ACCESS_DENIED` | 必须使用创建该邮箱时的调用密钥 |
| 401 | `MAILBOX_SESSION_EXPIRED` | 重新创建邮箱 |
| 404 | `MAILBOX_NOT_FOUND` | 重新创建邮箱并检查本地状态 |
| 409 | `IDEMPOTENCY_CONFLICT` | 为不同参数使用新的幂等键 |
| 422 | FastAPI 参数校验错误 | 检查字段类型、枚举值和长度 |
| 429 | `RATE_LIMITED` | 降低请求频率并退避重试 |
| 502 | `MAILBOX_CREATE_FAILED` | 稍后重试创建，建议使用新的任务尝试编号 |
| 502 | `MAILBOX_QUERY_FAILED` | 稍后继续查询验证码 |
| 503 | `DOMAIN_UNAVAILABLE` | 指定域名不可用，改用域名范围或自动选择 |
| 503 | `NO_AVAILABLE_DOMAIN` | 联系网关管理员检查实例及域名状态 |

更完整的字段和管理接口说明见 [API 接口文档](api.md)。
