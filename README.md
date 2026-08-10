# CloudMail Token Broker

CloudMail Token Broker 是一个轻量 Token 中转服务。它统一调用 CloudMail 的 `/api/public/genToken`，在进程内缓存 Token，并向图片站、Kirox、Windows EXE 等客户端提供稳定的获取接口，避免多个项目互相覆盖 CloudMail 全局 Token。

当前默认采用公开调用模式：客户端只需要知道 Broker 地址，不需要为图片站、Kirox、EXE 分别配置密钥。

## 工作流程

```text
图片站 / Kirox / EXE
        |
        | POST /api/public/genToken
        v
CloudMail Token Broker
        |
        | 缓存未到期：直接返回
        | 缓存到期：只刷新一次
        v
CloudMail /api/public/genToken
```

## 本地配置

项目目录已提供 `.env.example`。实际部署使用本地 `.env`，该文件已被 Git 忽略，不会提交到仓库。

最小配置：

```dotenv
IMAGE_TAG=latest

CLOUDMAIL_BASE_URL=https://mail.example.com
CLOUDMAIL_ADMIN_EMAIL=admin@example.com
CLOUDMAIL_ADMIN_PASSWORD=替换为CloudMail管理员密码

BROKER_PUBLIC_ACCESS=true
BROKER_ADMIN_KEY=
```

其中必须填写：

- `CLOUDMAIL_BASE_URL`：CloudMail 服务地址，不要带末尾 `/`。
- `CLOUDMAIL_ADMIN_EMAIL`：用于调用 CloudMail `genToken` 的管理员邮箱。
- `CLOUDMAIL_ADMIN_PASSWORD`：CloudMail 管理员密码。
- `BROKER_PUBLIC_ACCESS=true`：业务接口公开调用，不检查 Authorization。
- `BROKER_ADMIN_KEY=`：留空时关闭 Broker 管理接口。

不需要配置 `BROKER_CLIENT_KEYS_JSON`，也不需要所谓的“图片站密钥”“Kirox 密钥”或“EXE 密钥”。这些原本只是 Broker 自己用于区分调用方的访问密钥，并不是图片站、Kirox 或 CloudMail 已有的密钥。

## 启动

### 本地运行

```powershell
uv sync --extra test
uv run uvicorn app.main:create_app --factory --env-file .env --host 127.0.0.1 --port 8788
```

### Docker Compose

```bash
docker compose pull
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 cloudmail-token-broker
```

默认镜像：

```text
registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker:latest
```

发布流程：提交并推送 GitHub，由阿里云自动构建镜像；服务器只负责拉取并重建容器。

## 客户端调用

### 兼容旧 CloudMail 客户端

只把原来的 `genToken` 地址改成 Broker 地址即可，不传 Authorization：

```http
POST https://broker.example.com/api/public/genToken
Content-Type: application/json

{}
```

响应：

```json
{
  "code": 200,
  "data": {
    "token": "cloudmail-token"
  }
}
```

### 标准接口

```http
POST https://broker.example.com/v1/token
```

响应额外包含 `version` 和 `expiresAt`，便于新版客户端报告失效并刷新。

完整接口见 [docs/api.md](docs/api.md)，宝塔部署见 [docs/deployment.md](docs/deployment.md)。

## 公开模式的含义

公开模式下：

- `/v1/token` 无需认证。
- `/v1/token/refresh` 无需认证。
- `/api/public/genToken` 无需认证。
- 所有调用者共享 Broker 内存缓存和限流计数。
- 任何知道公网域名的人都可能获取 CloudMail Token。

因此必须使用 HTTPS，并建议通过宝塔网站、Nginx 或 CDN 设置访问频率限制。如果以后想恢复鉴权，可设置：

```dotenv
BROKER_PUBLIC_ACCESS=false
BROKER_CLIENT_KEYS_JSON={"image2api":"至少32字符的密钥","kirox":"至少32字符的另一条密钥"}
```

这只是可选安全模式，不是当前默认部署方式。

## 管理接口

`BROKER_ADMIN_KEY` 留空时，以下接口返回 `403 ADMIN_DISABLED`：

- `GET /admin/status`
- `POST /admin/token/refresh`

确实需要管理接口时，再配置一条至少 32 个字符的独立管理密钥，并使用 `Authorization: Bearer <管理密钥>` 调用。管理接口不会返回完整 CloudMail Token、管理员密码或客户端密钥。

## 缓存和刷新

- Broker 首次请求时向 CloudMail 获取 Token。
- 缓存有效期由 `TOKEN_CACHE_SECONDS` 控制，默认 1500 秒。
- 到达刷新窗口时只允许一个并发请求访问 CloudMail。
- `/v1/token/refresh` 是公开接口时可能被滥用，因此默认每分钟仅允许 5 次。
- Broker 当前为单实例内存缓存，不要同时运行多个副本，否则每个副本仍会分别获取 Token。

## 测试

```powershell
uv run --locked --extra test pytest
python -m compileall -q app test
```

## 安全提醒

- `.env` 不得提交到 Git。
- CloudMail 管理员密码不会返回给客户端，也不会写入普通日志。
- 对公网开放后，Broker 返回的 Token 等同于 CloudMail API 凭据。
- 如果公开域名被滥用，应立即开启反向代理限流，或切换回可选鉴权模式。
