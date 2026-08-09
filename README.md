# CloudMail Token Broker 独立服务

> 状态：第一阶段已实现，已完成自动化测试和 Docker 部署配置。
> 定位：可通过 Docker 独立部署、允许公网 EXE 客户端访问的 CloudMail Token 中心服务。

- GitHub：<https://github.com/xiaoasi-2023/cloudmail-token-broker>
- 阿里云镜像：`registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker`

## 快速开始

详细服务器部署见 [`docs/deployment.md`](./docs/deployment.md)，接口接入见 [`docs/api.md`](./docs/api.md)，镜像发布见 [`docs/release.md`](./docs/release.md)。

变更记录见 [`CHANGELOG.md`](./CHANGELOG.md)。

### 本地运行

进入本目录后执行：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少填写 CloudMail 地址、管理员账号密码、Broker 管理密钥和客户端密钥。然后启动：

```powershell
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8788 --workers 1
```

健康检查：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8788/healthz
```

运行测试：

```powershell
uv run --extra test pytest
```

### Docker 运行

Linux 服务器执行：

```bash
git clone https://github.com/xiaoasi-2023/cloudmail-token-broker.git
cd cloudmail-token-broker
cp .env.example .env
# 编辑 .env 后再启动
docker compose pull
docker compose up -d
docker compose ps
curl http://127.0.0.1:8788/healthz
```

默认拉取：

```text
registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker:latest
```

生产环境建议在 `.env` 中将 `IMAGE_TAG` 固定为明确版本号。

获取 Token：

```bash
curl -X POST 'http://127.0.0.1:8788/v1/token' \
  -H 'Authorization: Bearer <BROKER_CLIENT_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

查询管理状态：

```bash
curl 'http://127.0.0.1:8788/admin/status' \
  -H 'Authorization: Bearer <BROKER_ADMIN_KEY>'
```

管理状态接口只返回 Token 版本摘要、缓存时间和刷新统计，不返回 Token 明文。

## 1. 背景与目标

CloudMail 当前的 `/api/public/genToken` 会更新全局 `public_key:`。多个项目分别调用该接口时，新 Token 会覆盖旧 Token，导致其他项目正在使用的 Token 收到 401/403。

本项目在所有业务客户端与 CloudMail `genToken` 之间增加一个 Token Broker：

```text
Python 项目 ─┐
其他服务    ─┼── HTTPS ──> CloudMail Token Broker ──> CloudMail /api/public/genToken
Windows EXE ─┘                         │
                                      └── 共享缓存、并发锁、统一刷新

业务客户端仍然直接调用 CloudMail：
addUser / emailList ─────────────────────────────────────────────> CloudMail
```

目标：

- 只有 Broker 可以调用 CloudMail `genToken`。
- 多个项目共享同一个当前 Token，不再互相覆盖。
- Windows EXE、不同服务器和 Docker 项目均可通过公网 HTTPS 获取 Token。
- 客户端原有本地缓存、`addUser`、`emailList` 和邮件轮询逻辑保持不变。
- 客户端只改造 `getToken` 的来源，以及 401/403 后的刷新入口。
- CloudMail 管理员邮箱和密码只保存在 Broker 服务端。
- Token、管理员密码、Broker 客户端密钥不得进入普通日志。

## 2. 非目标

首期不实现：

- 不代理 `addUser` 和 `emailList`。
- 不修改 CloudMail 服务端鉴权逻辑。
- 不实现管理员 RBAC 或可视化管理后台。
- 不允许客户端直接指定 CloudMail 管理员账号或强制无限刷新。
- 不把 CloudMail Token 写进 Docker 镜像、Git 仓库或公开配置文件。

## 3. 推荐技术栈

首期建议使用：

- Python 3.13。
- FastAPI。
- Uvicorn，固定单 worker 运行。
- `httpx` 或项目统一 HTTP 客户端访问 CloudMail。
- Docker Compose 部署。
- Nginx 或宝塔反向代理负责公网 HTTPS。
- Cloudflare 可选负责域名代理、WAF 和频率限制。

首期采用单实例、单 worker，Token 保存在进程内存中。Broker 重启后第一次请求重新获取 Token；客户端收到旧 Token 的 401/403 后重新向 Broker取 Token即可恢复。

如果以后需要多个 Broker 副本，再引入 Redis 缓存和分布式锁。在没有共享缓存与分布式锁之前，禁止同时启动多个 Broker 实例。

## 4. 公网访问与安全边界

由于存在 Windows EXE 和跨服务器调用，Broker 可以开放公网访问，但必须满足：

1. 只允许 HTTPS，禁止直接公开 HTTP。
2. 每个项目使用独立的 Broker Client Key，不共用一个公开密钥。
3. Client Key 只保存哈希；原始 Key 只在创建和分发时保存于客户端安全配置。
4. 支持按 Client Key 启用、禁用和轮换。
5. 对 `/v1/token` 和 `/v1/token/refresh` 配置频率限制。
6. 请求日志不记录 `Authorization`、CloudMail Token、管理员邮箱密码和完整请求体。
7. 错误响应不回显任何密钥。
8. Broker 容器端口只绑定服务器本机，由 Nginx/宝塔反向代理暴露 443。
9. 如果 CloudMail 入口支持来源限制，应限制 `/api/public/genToken` 只允许 Broker 服务器出口 IP 访问。

推荐公网链路：

```text
客户端
  -> https://cloudmail-token.example.com
  -> Cloudflare（可选）
  -> 宝塔/Nginx HTTPS 反向代理
  -> 127.0.0.1:8788
  -> cloudmail-token-broker 容器
```

Docker 不直接映射公网地址：

```yaml
ports:
  - "127.0.0.1:8788:8080"
```

## 5. 配置设计

Broker 使用环境变量或 Docker Secret：

```text
CLOUDMAIL_BASE_URL=https://mail.example.com
CLOUDMAIL_ADMIN_EMAIL=admin@example.com
CLOUDMAIL_ADMIN_PASSWORD=<secret>

BROKER_ADMIN_KEY=<高强度管理密钥>
BROKER_CLIENT_KEYS_JSON={"image2api":"<独立密钥>","windows-exe":"<独立密钥>"}
TOKEN_CACHE_SECONDS=1500
TOKEN_REFRESH_SKEW_SECONDS=120
REQUEST_TIMEOUT_SECONDS=15
CLOUDMAIL_VERIFY_TLS=true
CLOUDMAIL_PROXY=
TOKEN_RATE_LIMIT_PER_MINUTE=60
REFRESH_RATE_LIMIT_PER_MINUTE=10
ADMIN_RATE_LIMIT_PER_MINUTE=2
LOG_LEVEL=INFO
```

要求：

- `CLOUDMAIL_ADMIN_PASSWORD`、`BROKER_ADMIN_KEY` 和原始 Client Key 不得提交到 Git。
- `.env` 已加入子项目 `.gitignore` 和 `.dockerignore`，但服务器文件权限仍应限制为仅管理员可读。
- Broker 启动时从环境变量读取原始 Client Key，鉴权表只保存 SHA-256 摘要；进程环境本身仍属于敏感信息。
- 每个密钥至少使用 32 字节随机值，建议 48 字节。
- Broker Client Key 与 CloudMail Token 必须是两种不同密钥。
- 客户端只能拿到 CloudMail Token，不能拿到管理员邮箱或密码。

## 6. API 设计

### 6.1 健康检查

```http
GET /healthz
```

不返回 Token，只返回服务状态：

```json
{
  "ok": true,
  "service": "cloudmail-token-broker"
}
```

### 6.2 获取当前 Token

```http
POST /v1/token
Authorization: Bearer <BROKER_CLIENT_KEY>
Content-Type: application/json
```

请求体可以为空：

```json
{}
```

响应：

```json
{
  "code": 200,
  "data": {
    "token": "<CLOUDMAIL_TOKEN>",
    "version": "4b1f10c2a8d9",
    "expiresAt": "2026-08-08T18:00:00Z"
  }
}
```

`version` 使用 Token 哈希摘要生成，不能包含 Token 明文。

### 6.3 报告失效并刷新

```http
POST /v1/token/refresh
Authorization: Bearer <BROKER_CLIENT_KEY>
Content-Type: application/json
```

请求：

```json
{
  "version": "4b1f10c2a8d9"
}
```

Broker 处理规则：

```text
客户端版本 != Broker 当前版本：
    说明其他客户端已经刷新
    直接返回当前 Token
    不调用 CloudMail genToken

客户端版本 == Broker 当前版本：
    获取全局刷新锁
    再次比较版本
    仍一致时才调用 CloudMail genToken
    更新缓存后返回新 Token
```

这样多个客户端同时收到 401/403 时，最多只有一次真实 `genToken` 请求。

### 6.4 兼容接口

为了降低旧项目改造量，可以提供与 CloudMail 相似的兼容入口：

```http
POST /api/public/genToken
Authorization: Bearer <BROKER_CLIENT_KEY>
```

响应保持旧结构：

```json
{
  "code": 200,
  "data": {
    "token": "<CLOUDMAIL_TOKEN>"
  }
}
```

兼容接口只返回缓存 Token，不允许每次调用都强制生成。新客户端应优先使用带 `version` 的 `/v1/token` 和 `/v1/token/refresh`。

### 6.5 管理接口

首期只提供必要的只读状态和人工刷新：

```text
GET  /admin/status
POST /admin/token/refresh
```

使用独立的 `BROKER_ADMIN_KEY`，不能使用普通 Client Key。状态接口只返回：

- 是否已缓存 Token。
- Token 版本摘要。
- 缓存创建时间和预计过期时间。
- 最近一次 CloudMail 请求结果。
- 刷新次数、失败次数和最后错误摘要。

任何管理接口都不能返回 Token 明文。

## 7. Token 缓存与并发控制

Broker 内部维护：

```text
token
version
created_at
expires_at
refresh_lock
last_error
```

获取流程：

```text
收到 /v1/token
  -> 校验 Broker Client Key
  -> 当前 Token 距离过期时间仍大于 refresh skew
       -> 直接返回缓存
  -> 获取刷新锁
  -> 再检查缓存
  -> 调用 CloudMail /api/public/genToken
  -> 校验 HTTP 状态和 JSON 业务码
  -> 原子更新 Token、version 和过期时间
  -> 返回
```

禁止行为：

- 每个请求都调用 `genToken`。
- 多线程无锁刷新。
- 客户端不带旧版本就强制刷新。
- 刷新失败时清空仍可能有效的旧 Token。
- 将 Token 写入异常文本或结构化日志。

## 8. 客户端接入

客户端增加：

```text
tokenBrokerUrl
tokenBrokerKey
```

Python 项目可使用：

```text
token_broker_url
token_broker_key
```

客户端逻辑：

```text
getToken():
    本地缓存有效 -> 返回本地 Token
    否则请求 Broker /v1/token
    保存 token、version、expiresAt
    返回 Token

addUser/emailList 收到 401 或 403：
    使用本地 version 请求 Broker /v1/token/refresh
    Broker 返回当前或新 Token
    只重试原请求一次
```

不能继续调用 CloudMail 原始 `genToken`。如果客户端仍存在任何直接 `genToken` 路径，Token 竞争问题仍然存在。

### 8.1 旧客户端的最小改造

如果旧项目暂时只想少改代码，可以把原来的：

```text
POST https://mail.example.com/api/public/genToken
```

改成：

```text
POST https://cloudmail-token.example.com/api/public/genToken
Authorization: Bearer <该项目的 BROKER_CLIENT_KEY>
```

原来的 JSON 请求体可以暂时保留，兼容接口不会使用其中的管理员邮箱和密码；迁移完成后应删除客户端中的 CloudMail 管理员凭据。需要处理 401/403 并获得“立即刷新”语义的项目，应改用 `/v1/token/refresh` 并传递本地 `version`，不要依赖兼容接口强制刷新。

Windows EXE 的配置示例：

```json
{
  "cloudMailBaseUrl": "https://mail.example.com",
  "tokenBrokerUrl": "https://cloudmail-token.example.com",
  "tokenBrokerKey": "<CLIENT_KEY>"
}
```

## 9. 错误码

| HTTP | code | 说明 |
| --- | --- | --- |
| 401 | `BROKER_UNAUTHORIZED` | Client Key 缺失、无效或已禁用 |
| 429 | `RATE_LIMITED` | 请求过于频繁 |
| 502 | `CLOUDMAIL_TOKEN_FAILED` | CloudMail `genToken` 返回失败 |
| 422 | FastAPI 校验错误 | 请求 JSON 或 `version` 字段不符合格式 |

日志只记录 `client_id`、接口、状态、耗时、Token 版本摘要和错误码，不记录任何原始密钥。

## 10. Docker 部署设计

当前目录：

```text
cloudmail-token-broker/
├── README.md
├── app/
│   ├── main.py
│   ├── config.py
│   ├── auth.py
│   ├── errors.py
│   ├── rate_limit.py
│   ├── cloudmail_client.py
│   ├── token_service.py
│   └── schemas.py
├── test/
│   ├── __init__.py
│   ├── test_token_service.py
│   └── test_api.py
├── Dockerfile
├── docker-compose.yml
├── docs/
│   ├── deployment.md
│   ├── api.md
│   └── release.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .dockerignore
└── .gitignore
```

Compose 的核心配置：

```yaml
services:
  cloudmail-token-broker:
    image: registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker:${IMAGE_TAG:-latest}
    pull_policy: always
    container_name: cloudmail-token-broker
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "127.0.0.1:8788:8080"
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3
```

公网域名由宝塔/Nginx反向代理到：

```text
http://127.0.0.1:8788
```

容器本身不保存 `.env`，服务器上的 `.env` 权限应限制为仅管理员可读。

镜像由阿里云容器镜像服务关联 GitHub 仓库后自动构建。本地和生产服务器都不需要执行 `docker build` 或 `docker push`。

### 10.1 宝塔部署步骤

1. 克隆 `https://github.com/xiaoasi-2023/cloudmail-token-broker.git`，或只上传 Compose 和配置模板到 `/www/docker/cloudmail-token-broker`。
2. 复制 `.env.example` 为 `.env`，填写真实配置，不要把 `.env` 提交到 Git。
3. 私有镜像仓库先执行 `docker login registry.cn-hangzhou.aliyuncs.com`。
4. 在宝塔“Docker → 容器编排”中导入本目录的 `docker-compose.yml`，或执行 `docker compose pull && docker compose up -d`。
5. 确认容器健康检查通过，并在服务器执行 `curl http://127.0.0.1:8788/healthz`。
6. 在宝塔“网站”中新建 Broker 域名，申请 HTTPS 证书。
7. 将域名反向代理到 `http://127.0.0.1:8788`，不要把容器的 8080 或宿主机的 8788 直接监听到公网地址。
8. 用公网 HTTPS 域名调用 `/v1/token`，确认 Windows EXE 所在网络可以访问。

宝塔反向代理的目标只需要填写：

```text
目标 URL：http://127.0.0.1:8788
```

并保留 `Host`、`X-Real-IP` 和 `X-Forwarded-For` 请求头。不要在反代配置中记录 `Authorization` 请求头。

建议关闭该域名的普通访问日志，或者确认日志格式不会记录 `Authorization` 请求头。Nginx 默认访问日志通常不记录该请求头，但不要额外加入 `$http_authorization`。

### 10.2 生成密钥

每个客户端和管理接口应分别生成独立密钥。在 Linux 服务器上可执行：

```bash
openssl rand -hex 48
```

把生成结果分别写入 `BROKER_ADMIN_KEY` 和 `BROKER_CLIENT_KEYS_JSON`。不要在群聊、工单截图或普通日志中发送完整密钥。

## 11. 限流建议

Broker 内部与反向代理都需要限流：

- `/v1/token`：单 Client Key 每分钟最多 60 次。
- `/v1/token/refresh`：单 Client Key 每分钟最多 10 次。
- `/admin/token/refresh`：每分钟最多 2 次。
- 认证连续失败超过阈值后短暂封禁来源 IP。

不能只依赖 IP 限流，因为 Windows EXE 可能处于动态 IP、NAT 或代理网络中；正式身份必须以 Client Key 为准。

## 12. 部署与迁移顺序

1. 部署 Broker，但暂不修改任何客户端。
2. 在 Broker 中配置 CloudMail 地址、管理员邮箱和密码。
3. 创建每个项目独立的 Broker Client Key。
4. 调用 `/healthz` 和 `/v1/token` 验证 Broker 可以获取并缓存 Token。
5. 逐个客户端增加 `tokenBrokerUrl` 和 `tokenBrokerKey`。
6. 客户端把动态 `getToken` 来源切换到 Broker。
7. 验证客户端不再直接请求 CloudMail `genToken`。
8. 所有客户端迁移完成后，限制 CloudMail `genToken` 只允许 Broker 调用。
9. 观察 401/403、Broker 刷新次数、CloudMail 请求次数和客户端成功率。

迁移期间未升级的客户端仍可能覆盖 Token。因此，在最后一个客户端迁移完成前，不能认为竞争问题已经完全解决。

## 13. 验收标准

- 两个独立项目和一个 Windows EXE 同时获取到相同 Token。
- 多客户端并发首次请求时，CloudMail `genToken` 实际只调用一次。
- 任意客户端重复调用 `/v1/token` 不会触发新的 `genToken`。
- 多客户端同时报告同一 Token 401/403 时，只刷新一次。
- 客户端报告旧版本时，Broker 直接返回当前 Token，不再次刷新。
- `addUser` 和 `emailList` 仍由客户端直接调用 CloudMail并成功。
- 禁用某个 Client Key 后，只影响对应项目。
- Broker 日志和错误响应中不存在 CloudMail Token、管理员密码和完整 Client Key。
- Broker 重启后可以重新获取 Token，客户端最多重试一次后恢复。
- CloudMail 原始 `genToken` 限制为只有 Broker 可以调用后，不再发生跨项目 Token 抢占。

## 14. 开发阶段划分

### 第一阶段：基础 Broker（已完成）

- FastAPI 服务和 Docker 部署。
- Client Key 鉴权。
- 单实例内存缓存。
- 全局并发刷新锁。
- `/healthz`、`/v1/token`、`/v1/token/refresh`。
- 日志脱敏和离线测试。
- Docker Compose、只读容器、非 root 用户和健康检查。

### 第二阶段：客户端接入

- 当前图片站 CloudMail Provider 增加 Broker 配置。
- 保留原动态 `genToken` 作为未配置 Broker 时的兼容流程。
- Windows EXE 和其他项目逐个接入。

### 第三阶段：生产加固

- 宝塔/Nginx HTTPS 反向代理。
- Cloudflare WAF 和频率限制。
- Client Key 独立轮换和禁用。
- CloudMail `genToken` 来源限制。
- 监控刷新次数、错误率和上游耗时。

### 第四阶段：可选高可用

- Redis Token 缓存。
- Redis 分布式锁。
- 多 Broker 副本。
- 审计记录和管理后台。

## 15. 最终决策

首期采用“公网 HTTPS Token Broker + 每项目独立 Client Key + 单实例内存缓存 + 单次刷新锁”。

该方案比把固定 CloudMail Token复制到所有项目更容易集中轮换，也比代理全部邮件接口改动更小。代价是 Broker 成为注册链路的基础服务，因此必须配置 Docker 自动重启、健康检查、HTTPS、鉴权和限流。
