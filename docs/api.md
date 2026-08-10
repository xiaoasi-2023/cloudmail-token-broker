# CloudMail Token Broker API 接口文档

## 1. 基本信息

- 协议：HTTPS
- 数据格式：JSON
- 默认模式：公开调用，不需要 Authorization
- 示例地址：`https://broker.example.com`

接口总览：

| 方法 | 路径 | 用途 | 默认鉴权 |
| --- | --- | --- | --- |
| GET | `/healthz` | 健康检查 | 无 |
| POST | `/v1/token` | 获取当前 Token | 无 |
| POST | `/v1/token/refresh` | 报告当前 Token 失效并刷新 | 无 |
| POST | `/api/public/genToken` | 兼容旧 CloudMail 客户端 | 无 |
| GET | `/admin/status` | 查询缓存状态 | 默认关闭 |
| POST | `/admin/token/refresh` | 管理员强制刷新 | 默认关闭 |

## 2. 健康检查

```http
GET /healthz
```

成功响应：

```json
{
  "ok": true,
  "service": "cloudmail-token-broker"
}
```

## 3. 获取当前 Token

```http
POST /v1/token
```

不需要请求体，不需要 Authorization。

成功响应：

```json
{
  "code": 200,
  "data": {
    "token": "cloudmail-token",
    "version": "a1b2c3d4e5f6",
    "expiresAt": "2026-08-10T08:30:00+00:00"
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `token` | CloudMail 公共 API Token |
| `version` | Token 的短版本标识，不是 Token 本身 |
| `expiresAt` | Broker 本地缓存过期时间 |

## 4. 报告失效并刷新

```http
POST /v1/token/refresh
Content-Type: application/json

{
  "version": "a1b2c3d4e5f6"
}
```

客户端在使用 Token 调用 CloudMail 收到 401 或 403 时，可以把当前 Token 的 `version` 传给该接口。

处理规则：

- 报告的版本等于 Broker 当前版本：Broker 向 CloudMail 获取新 Token。
- 报告的版本落后于 Broker 当前版本：直接返回较新的缓存 Token，不重复刷新。
- 并发刷新由进程内锁合并，避免同一时刻重复访问 CloudMail。

成功响应格式与 `/v1/token` 相同。

该接口在公开模式下也无需认证，因此生产环境必须保留较低的 `REFRESH_RATE_LIMIT_PER_MINUTE`，并建议在宝塔反向代理或 CDN 再增加限流。

## 5. 兼容接口

```http
POST /api/public/genToken
Content-Type: application/json

{}
```

成功响应：

```json
{
  "code": 200,
  "data": {
    "token": "cloudmail-token"
  }
}
```

该接口用于让旧项目只修改 `genToken` URL，不必重写原来的 Token 解析逻辑。客户端请求体中即使继续携带原管理员邮箱和密码，Broker 也不会使用这些字段。

## 6. Python 示例

```python
import requests


BROKER_BASE_URL = "https://broker.example.com"


def get_token() -> dict:
    response = requests.post(
        f"{BROKER_BASE_URL}/v1/token",
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["data"]


def refresh_token(version: str) -> dict:
    response = requests.post(
        f"{BROKER_BASE_URL}/v1/token/refresh",
        json={"version": version},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["data"]
```

## 7. JavaScript/TypeScript 示例

```ts
const brokerBaseUrl = "https://broker.example.com";

export async function getCloudMailToken() {
  const response = await fetch(`${brokerBaseUrl}/v1/token`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(`Broker 请求失败: HTTP ${response.status}`);
  }

  const payload = await response.json();
  return payload.data as {
    token: string;
    version: string;
    expiresAt: string;
  };
}
```

## 8. 错误响应

统一格式：

```json
{
  "code": "CLOUDMAIL_TOKEN_FAILED",
  "message": "CloudMail genToken 请求超时"
}
```

常见错误：

| HTTP | code | 说明 |
| --- | --- | --- |
| 403 | `ADMIN_DISABLED` | 管理接口未配置管理密钥 |
| 401 | `BROKER_UNAUTHORIZED` | 仅在可选鉴权模式下出现 |
| 429 | `RATE_LIMITED` | 超过进程内接口限流 |
| 502 | `CLOUDMAIL_TOKEN_FAILED` | Broker 获取 CloudMail Token 失败 |

## 9. 管理接口

默认配置 `BROKER_ADMIN_KEY=`，因此管理接口关闭。

启用后使用：

```http
Authorization: Bearer <BROKER_ADMIN_KEY>
```

### 查询状态

```http
GET /admin/status
```

状态响应只包含缓存状态、版本、刷新次数和时间，不返回完整 Token 或 CloudMail 管理员密码。

### 强制刷新

```http
POST /admin/token/refresh
```

该接口忽略当前版本并立即访问 CloudMail，必须限制调用频率。

## 10. 可选鉴权模式

如果以后不想让所有人调用，可以关闭公开模式：

```dotenv
BROKER_PUBLIC_ACCESS=false
BROKER_CLIENT_KEYS_JSON={"image2api":"至少32字符的密钥","kirox":"至少32字符的另一条密钥"}
```

此时业务接口要求：

```http
Authorization: Bearer <对应客户端密钥>
```

当前部署不需要使用此模式。
