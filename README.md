# Xiaoasi Mail Gateway

Xiaoasi Mail Gateway 是一个支持多 CloudMail 实例、多邮箱域名和可视化管理端的统一邮箱网关。

图片站、Kirox、Windows EXE 和其他调用方只调用网关的创建邮箱、查询验证码接口，不再保存 CloudMail 管理员账号、密码和 Token，也不需要理解 `genToken`、`addUser`、`emailList` 等内部接口。

## 核心能力

- 多个 CloudMail 实例，每个实例配置多个邮箱域名；
- 每实例独立 Token 缓存和刷新锁，互不覆盖；
- 支持指定单域名、指定域名范围和自动加权选择；
- 自动生成邮箱地址和内部密码；
- 使用 `Idempotency-Key` 避免网络重试重复建箱；
- 创建邮箱后返回短期、单邮箱范围的 `mailboxToken`；
- 统一查询 OpenAI、Grok 等验证码；
- SQLite 持久化实例、域名、邮箱、请求日志和管理会话；
- CloudMail 管理员密码加密保存；
- React + Ant Design 管理端；
- 保留旧 Token Broker 接口供迁移阶段使用；
- 提供 dry-run/apply 数据保留清理脚本。

## 调用链

```text
图片站 / Kirox / EXE
        |
        | POST /v1/mailboxes
        v
Xiaoasi Mail Gateway
        |
        | 选择域名及所属实例
        | 获取该实例独立 Token
        | 调用 addUser 创建邮箱
        v
CloudMail 实例 A / B / C
```

## 快速部署

项目默认镜像：

```text
registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker:latest
```

部署目录至少包含：

```text
cloudmail-token-broker/
├── docker-compose.yml
├── .env
└── data/
```

上传 `.env` 前必须确认：

```dotenv
GATEWAY_ENABLED=true
GATEWAY_DATABASE_PATH=/app/data/xiaoasi-mail.db

DATA_ENCRYPTION_KEY=<至少32字节随机值>
MAILBOX_SESSION_SECRET=<另一条至少32字节随机值>

ADMIN_USERNAME=admin
ADMIN_PASSWORD=<强管理密码>
ADMIN_COOKIE_SECURE=true
```

本地 `.env` 已被 Git 忽略，不会提交。

启动：

```bash
docker compose pull
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 cloudmail-token-broker
```

通过宝塔网站反向代理：

```text
https://你的网关域名  →  http://127.0.0.1:8788
```

管理端：

```text
https://你的网关域名/admin/
```

详细步骤见 [docs/deployment.md](docs/deployment.md)。

## 创建邮箱

自动选择域名：

```bash
curl -X POST 'https://mail-api.example.com/v1/mailboxes' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: register-task-123' \
  -H 'X-Client-Source: image2api' \
  -d '{"purpose":"openai","prefix":"image2api","source":"image2api"}'
```

指定单域名：

```json
{
  "purpose": "openai",
  "domain": "mail-a.example.com",
  "prefix": "kirox"
}
```

指定域名范围：

```json
{
  "purpose": "openai",
  "domains": ["mail-a.example.com", "mail-b.example.com"],
  "prefix": "image2api"
}
```

成功响应：

```json
{
  "code": 200,
  "data": {
    "mailboxId": "mbx_example",
    "address": "image2apiabc123@mail-a.example.com",
    "domain": "mail-a.example.com",
    "mailboxToken": "短期邮箱访问凭证",
    "createdAt": "2026-08-10T08:00:00+00:00",
    "expiresAt": "2026-08-10T08:30:00+00:00"
  }
}
```

## 查询验证码

```bash
curl -X POST 'https://mail-api.example.com/v1/mailboxes/mbx_example/verification-code' \
  -H 'Authorization: Mailbox <mailboxToken>' \
  -H 'Content-Type: application/json' \
  -d '{"purpose":"openai","waitSeconds":20}'
```

`mailboxToken` 只允许访问创建时对应的邮箱，不是图片站或 Kirox 的长期项目密钥。

完整接口见 [docs/api.md](docs/api.md)。

## 管理端

管理端提供：

- 运行概览；
- CloudMail 实例新增、编辑、启停、删除和连接测试；
- 邮箱域名新增、编辑、权重、启停和解除冷却；
- 邮箱记录；
- 请求日志；
- 安全边界和运行参数说明。

CloudMail 管理员密码保存后不会返回浏览器，管理端接口使用 HttpOnly Cookie 会话。

## 数据清理

预览：

```bash
docker exec -w /app cloudmail-token-broker \
  python scripts/gateway_retention_cleanup.py \
  --request-log-retention-days 30 \
  --mailbox-retention-days 30
```

正式执行：

```bash
docker exec -w /app cloudmail-token-broker \
  python scripts/gateway_retention_cleanup.py \
  --request-log-retention-days 30 \
  --mailbox-retention-days 30 \
  --apply
```

该脚本不会删除 CloudMail 上游邮箱账号；如果 CloudMail 支持删除用户，需要后续在 Provider 层补充上游清理。

## 本地开发

后端：

```powershell
uv sync --extra test
uv run uvicorn app.main:create_app --factory --env-file .env --host 127.0.0.1 --port 8788
```

管理端：

```powershell
cd admin-web
npm install
npm run dev
```

生产构建和测试：

```powershell
uv run --locked --extra test pytest
python -m compileall -q app scripts test
uv build

cd admin-web
npm run build
```

## 文档

- [API 接口文档](docs/api.md)
- [宝塔部署手册](docs/deployment.md)
- [完整开发方案](docs/xiaoasi-mail-gateway-development-plan.md)
- [发布流程](docs/release.md)

## 兼容说明

以下旧接口暂时保留：

- `POST /v1/token`
- `POST /v1/token/refresh`
- `POST /api/public/genToken`

它们只用于现有项目迁移。图片站、Kirox 和其他调用方全部切换到邮箱网关接口后，应关闭 Token 外发。
