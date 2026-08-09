# CloudMail Token Broker API 接口文档

本文面向需要接入 CloudMail Token Broker 的图片站、Windows EXE、Python 服务和其他项目开发人员。

服务源码：`https://github.com/xiaoasi-2023/cloudmail-token-broker`

## 1. 基本信息

- 生产 Base URL：由服务管理员提供，例如 `https://cloudmail-token.example.com`
- 传输协议：必须使用 HTTPS
- 字符集：UTF-8
- 请求体：JSON
- 推荐鉴权头：`Authorization: Bearer <BROKER_CLIENT_KEY>`
- 也兼容裸 Key：`Authorization: <BROKER_CLIENT_KEY>`

每个项目使用独立 Client Key。项目之间不能共用密钥，也不能使用 `BROKER_ADMIN_KEY` 调用业务接口。

## 2. 接口总览

| 方法 | 路径 | 鉴权 | 用途 |
| --- | --- | --- | --- |
| GET | `/healthz` | 无 | 健康检查 |
| POST | `/v1/token` | Client Key | 获取当前 Token |
| POST | `/v1/token/refresh` | Client Key | 根据旧版本报告失效并刷新 |
| POST | `/api/public/genToken` | Client Key | 兼容旧项目的 Token 获取入口 |
| GET | `/admin/status` | 管理密钥 | 查看缓存和刷新状态，不返回 Token |
| POST | `/admin/token/refresh` | 管理密钥 | 人工触发一次刷新，不返回 Token |

## 3. 健康检查

### 请求

```http
GET /healthz
```

### 成功响应 `200`

```json
{
  "ok": true,
  "service": "cloudmail-token-broker"
}
```

该接口只表示 Broker 进程正常，不代表 CloudMail 当前可访问。CloudMail 连通性需要通过 `/v1/token` 验证。

## 4. 获取当前 Token

### 请求

```http
POST /v1/token
Authorization: Bearer <BROKER_CLIENT_KEY>
Content-Type: application/json

{}
```

请求体可以为空对象，也可以不发送请求体。

### 成功响应 `200`

```json
{
  "code": 200,
  "data": {
    "token": "<CLOUDMAIL_TOKEN>",
    "version": "4b1f10c2a8d9",
    "expiresAt": "2026-08-08T18:00:00+00:00"
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | number | 成功固定为 `200` |
| `data.token` | string | CloudMail 当前公共 Token，客户端用于后续 `addUser`、`emailList` 等请求 |
| `data.version` | string | Token 的 SHA-256 前 12 位摘要，不是 Token 明文 |
| `data.expiresAt` | string | Broker 本地缓存预计过期时间，ISO 8601 UTC |

正常情况下客户端应缓存 `token`、`version` 和 `expiresAt`，不要每次业务请求都访问 Broker。

## 5. 失效报告和刷新

当客户端使用 CloudMail Token 调用业务接口收到 `401` 或 `403` 时，使用本地缓存的 `version` 调用此接口：

### 请求

```http
POST /v1/token/refresh
Authorization: Bearer <BROKER_CLIENT_KEY>
Content-Type: application/json

{
  "version": "4b1f10c2a8d9"
}
```

### 处理规则

```text
version != Broker 当前版本：直接返回 Broker 当前 Token，不调用 CloudMail genToken
version == Broker 当前版本：进入全局刷新锁，最多一次调用 CloudMail genToken
```

因此多个项目同时收到 401/403 时，只有第一个项目真正刷新，其他项目复用刷新后的 Token。

### 成功响应

响应结构与 `/v1/token` 相同：

```json
{
  "code": 200,
  "data": {
    "token": "<NEW_CLOUDMAIL_TOKEN>",
    "version": "9c54e2d13a61",
    "expiresAt": "2026-08-08T18:30:00+00:00"
  }
}
```

客户端只应针对原始业务请求重试一次，避免异常时无限循环。

## 6. 兼容旧项目的获取接口

### 请求

```http
POST /api/public/genToken
Authorization: Bearer <BROKER_CLIENT_KEY>
Content-Type: application/json

{
  "email": "旧项目原来的管理员邮箱",
  "password": "旧项目原来的管理员密码"
}
```

### 响应

```json
{
  "code": 200,
  "data": {
    "token": "<CLOUDMAIL_TOKEN>"
  }
}
```

Broker 不使用兼容接口请求体中的管理员账号密码，只按 Client Key 鉴权并返回缓存 Token。旧项目最少需要修改两处：

1. 将 `genToken` URL 改为 Broker 的 `/api/public/genToken`。
2. 增加 `Authorization: Bearer <BROKER_CLIENT_KEY>` 请求头。

新项目不要依赖兼容接口的刷新语义，应使用 `/v1/token` 和 `/v1/token/refresh`。

## 7. 管理接口

### 7.1 查询状态

```http
GET /admin/status
Authorization: Bearer <BROKER_ADMIN_KEY>
```

响应示例：

```json
{
  "ok": true,
  "service": "cloudmail-token-broker",
  "token": {
    "cached": true,
    "version": "4b1f10c2a8d9",
    "createdAt": "2026-08-08T17:35:00+00:00",
    "expiresAt": "2026-08-08T18:00:00+00:00",
    "refreshCount": 3,
    "refreshFailureCount": 0,
    "lastRefreshAt": "2026-08-08T17:35:00+00:00",
    "lastError": "",
    "refreshing": false
  }
}
```

`token` 对象中的 `version` 是摘要，接口不会返回 Token 明文、管理员密码或 Client Key。

### 7.2 人工刷新

```http
POST /admin/token/refresh
Authorization: Bearer <BROKER_ADMIN_KEY>
```

成功时只返回状态摘要。人工刷新后，已经缓存旧 Token 的客户端应重新调用 `/v1/token` 获取新版本。

## 8. 错误响应

统一错误结构：

```json
{
  "code": "BROKER_UNAUTHORIZED",
  "message": "Broker Client Key 无效"
}
```

| HTTP 状态码 | `code` | 说明 |
| --- | --- | --- |
| 401 | `BROKER_UNAUTHORIZED` | Client Key 或管理密钥缺失、错误 |
| 422 | 无固定 code | JSON 或 `version` 字段校验失败 |
| 429 | `RATE_LIMITED` | 当前 Key 超过接口频率限制 |
| 502 | `CLOUDMAIL_TOKEN_FAILED` | CloudMail 网络、HTTP、JSON 或业务状态失败 |

客户端处理建议：

- `401`：停止重试，检查项目密钥是否正确或已轮换。
- `429`：按退避策略重试，不要立即并发重试。
- `502`：短暂退避后重试；如果持续失败，联系 Broker 管理员检查上游连通性。
- 业务接口收到 CloudMail `401/403`：只调用一次 `/v1/token/refresh`，随后只重试原请求一次。

## 9. Python 接入示例

```python
from __future__ import annotations

import requests


class CloudMailTokenBroker:
    def __init__(self, base_url: str, client_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_key = client_key
        self.token = ""
        self.version = ""

    def get_token(self) -> str:
        response = requests.post(
            f"{self.base_url}/v1/token",
            headers={"Authorization": f"Bearer {self.client_key}"},
            json={},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()["data"]
        self.token = data["token"]
        self.version = data["version"]
        return self.token

    def refresh_after_401(self) -> str:
        response = requests.post(
            f"{self.base_url}/v1/token/refresh",
            headers={"Authorization": f"Bearer {self.client_key}"},
            json={"version": self.version},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()["data"]
        self.token = data["token"]
        self.version = data["version"]
        return self.token
```

## 10. JavaScript/TypeScript 接入示例

```typescript
type BrokerTokenData = {
  token: string;
  version: string;
  expiresAt: string;
};

async function getBrokerToken(baseUrl: string, clientKey: string): Promise<BrokerTokenData> {
  const response = await fetch(`${baseUrl}/v1/token`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${clientKey}`,
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  if (!response.ok) throw new Error(`Broker HTTP ${response.status}`);
  const payload = await response.json();
  return payload.data as BrokerTokenData;
}

async function refreshBrokerToken(
  baseUrl: string,
  clientKey: string,
  version: string,
): Promise<BrokerTokenData> {
  const response = await fetch(`${baseUrl}/v1/token/refresh`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${clientKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ version }),
  });
  if (!response.ok) throw new Error(`Broker HTTP ${response.status}`);
  const payload = await response.json();
  return payload.data as BrokerTokenData;
}
```

## 11. 推荐客户端流程

```text
启动或本地 Token 不存在
    -> POST /v1/token
    -> 缓存 token、version、expiresAt

调用 CloudMail addUser/emailList
    -> 成功：继续业务流程
    -> 401/403：POST /v1/token/refresh，传本地 version
    -> 使用响应中的新 Token 重试原请求一次
    -> 仍失败：记录错误并结束本次业务，不要无限重试
```

客户端日志只能记录 Broker URL、接口状态、项目内部任务 ID 和 `version` 摘要，不得记录 Client Key、CloudMail Token 或管理员密码。

## 12. 版本和密钥轮换配合

当管理员修改 Broker Client Key 或 CloudMail 管理员密码时，项目方需要：

1. 接收管理员提供的新 Client Key。
2. 更新项目安全配置，不要写入源码。
3. 重启或重新加载项目配置。
4. 调用 `/v1/token` 验证新密钥。

当 Broker Token 版本变化时，客户端不需要手工处理，只要按 `expiresAt` 缓存并在业务接口收到 `401/403` 时走刷新流程即可。
