# Xiaoasi Mail Gateway 宝塔部署手册

## 1. 准备目录

```bash
mkdir -p /www/docker/cloudmail-token-broker/data
cd /www/docker/cloudmail-token-broker
```

上传：

- `docker-compose.yml`
- `.env`

目录：

```text
/www/docker/cloudmail-token-broker/
├── docker-compose.yml
├── .env
└── data/
```

镜像由 GitHub 推送触发阿里云自动构建，服务器无需上传源码。

## 2. 环境变量

```dotenv
IMAGE_TAG=latest

REQUEST_TIMEOUT_SECONDS=15
LOG_LEVEL=INFO

GATEWAY_ENABLED=true
GATEWAY_DATABASE_PATH=/app/data/xiaoasi-mail.db

DATA_ENCRYPTION_KEY=<至少32字节随机值>
MAILBOX_SESSION_SECRET=<另一条至少32字节随机值>
MAILBOX_SESSION_TTL_SECONDS=1800

ADMIN_USERNAME=admin
ADMIN_PASSWORD=<强管理密码>
ADMIN_PASSWORD_HASH=
ADMIN_SESSION_TTL_SECONDS=28800
ADMIN_COOKIE_SECURE=true
ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE=10

MAILBOX_CREATE_RATE_LIMIT_PER_MINUTE=120
MAILBOX_POLL_RATE_LIMIT_PER_MINUTE=600
```

`DATA_ENCRYPTION_KEY` 和 `MAILBOX_SESSION_SECRET` 必须不同，且不能在部署后随意修改：

- 修改数据加密密钥后，数据库内已保存的 CloudMail 管理员密码无法解密；
- 修改邮箱会话密钥后，已签发的 `mailboxToken` 全部失效。

本地项目的 `.env` 已生成随机值，但上传前仍应确认管理员密码。CloudMail 实例地址、管理员凭据、代理和 TLS 配置全部在 `/admin/` 页面维护，不写入 `.env`。

## 3. 宝塔容器编排

进入：

```text
宝塔面板 → Docker → 容器编排 → 添加编排
```

建议：

- 名称：`cloudmail-token-broker`
- 目录：`/www/docker/cloudmail-token-broker`
- Compose：使用项目中的 `docker-compose.yml`

容器启动脚本会自动调整 `/app/data` 权限，然后以非 root 用户运行应用。

启动：

```bash
cd /www/docker/cloudmail-token-broker
docker compose pull
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 cloudmail-token-broker
```

## 4. 配置 HTTPS 网站

宝塔新建网站，例如：

```text
mail-api.example.com
```

反向代理：

```text
http://127.0.0.1:8788
```

启用 SSL 并强制 HTTPS。不要直接把 8788 开放到公网。

管理端：

```text
https://mail-api.example.com/admin/
```

建议给 `/admin/` 和 `/admin-api/` 再增加宝塔访问限制、Cloudflare Access 或固定来源 IP。

## 5. 首次配置

1. 使用 `.env` 中的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 登录管理端。
2. 进入“CloudMail 实例”，新增第一个实例。
3. 填写 API 地址、管理员邮箱、管理员密码、代理和 TLS 设置。
4. 创建成功后不要关闭抽屉，在“当前实例的邮箱域名”区域添加一个或多个域名；这里新增的域名会自动绑定当前实例。
5. 设置域名启用状态和调度权重。也可以进入独立“邮箱域名”页面进行跨实例集中维护。
6. 点击实例列表中的“测试”，确认 `genToken` 成功。
7. 使用 `/v1/mailboxes` 测试创建邮箱。
8. 触发测试邮件后验证验证码查询。

不同 CloudMail 实例分别新增，每个实例可以维护多个域名。

服务启动时会自动检查并升级持久化 SQLite 表结构。旧镜像创建的数据库缺少域名状态、统计或实例关联字段时，会补齐字段并升级数据库版本，不需要删除 `/app/data/xiaoasi-mail.db`。

## 6. 验证命令

健康检查：

```bash
curl -fsS http://127.0.0.1:8788/healthz
```

创建邮箱：

```bash
curl -sS -X POST 'https://mail-api.example.com/v1/mailboxes' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: deploy-test-001' \
  -H 'X-Client-Source: deploy-test' \
  -d '{"purpose":"openai","prefix":"deploytest","source":"deploy-test"}'
```

保存返回的 `mailboxId` 和 `mailboxToken`，再查询状态或验证码。

## 7. 更新镜像

阿里云自动构建完成后：

```bash
cd /www/docker/cloudmail-token-broker
docker compose pull
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 cloudmail-token-broker
```

SQLite 数据位于宿主机：

```text
/www/docker/cloudmail-token-broker/data/xiaoasi-mail.db
```

重建容器不会删除该文件。

## 8. 备份

升级前备份：

```bash
cd /www/docker/cloudmail-token-broker
cp -a data "data-backup-$(date +%Y%m%d-%H%M%S)"
cp -a .env ".env.backup-$(date +%Y%m%d-%H%M%S)"
```

`.env` 中的数据加密密钥必须与数据库备份一起保留，否则恢复数据库后无法解密实例密码。

## 9. 数据清理定时任务

先执行 dry-run：

```bash
docker exec -w /app cloudmail-token-broker \
  python scripts/gateway_retention_cleanup.py \
  --request-log-retention-days 30 \
  --mailbox-retention-days 30
```

确认数量后正式执行：

```bash
docker exec -w /app cloudmail-token-broker \
  python scripts/gateway_retention_cleanup.py \
  --request-log-retention-days 30 \
  --mailbox-retention-days 30 \
  --apply
```

宝塔计划任务建议每天凌晨执行一次正式命令。脚本会输出中文摘要。

清理范围：

- 过期幂等记录；
- 过期管理会话；
- 将过期 active 邮箱标记为 expired；
- 超过保留期的请求日志；
- 超过保留期且已 released、expired 或 failed 的邮箱记录。

不会删除：

- 未过期 active 邮箱；
- CloudMail 上游邮箱账号；
- CloudMail 实例和域名配置。

## 10. 常见问题

### 容器提示网关密钥配置错误

确认 `DATA_ENCRYPTION_KEY` 和 `MAILBOX_SESSION_SECRET` 已替换占位符且至少 32 字节。

### 管理端登录后立即返回登录页

生产 HTTPS 应设置：

```dotenv
ADMIN_COOKIE_SECURE=true
```

如果只在本机 HTTP 测试，可临时设置为 `false`。

### 数据库无法写入

检查宿主机 `data/` 目录和容器日志。镜像入口会自动把挂载目录调整为应用用户可写。

### 实例测试失败

检查：

- CloudMail API 地址；
- 管理员邮箱和密码；
- 容器到 CloudMail 的网络；
- `proxy_url`；
- TLS 证书设置。

### 自动模式提示没有可用域名

确认至少存在一个：

- 已启用的 CloudMail 实例；
- 已启用的邮箱域名；
- 不处于异常或冷却状态的域名。

### 能否运行多个网关副本

当前版本使用 SQLite、进程内 Token 缓存和进程内并发锁，只支持单容器副本。不要设置多 worker 或多副本。
