# Xiaoasi Mail Gateway 宝塔部署手册

## 1. 准备目录

```bash
mkdir -p /www/docker/cloudmail-token-broker
cd /www/docker/cloudmail-token-broker
```

上传：

- `docker-compose.yml`
- `.env`

目录：

```text
/www/docker/cloudmail-token-broker/
├── docker-compose.yml
└── .env
```

镜像由 GitHub 推送触发阿里云自动构建，服务器无需上传源码。

## 2. 环境变量

```dotenv
IMAGE_NAME=registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker:latest

REQUEST_TIMEOUT_SECONDS=15
LOG_LEVEL=INFO

GATEWAY_ENABLED=true
DATABASE_URL=postgresql://数据库用户:数据库密码@host.docker.internal:5432/数据库名?connect_timeout=10

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

`DATABASE_URL` 连接服务器已经安装的 PostgreSQL。本项目不会创建 PostgreSQL 容器。数据库密码包含 `@`、`:`、`/`、`?`、`#` 等字符时，需要先进行 URL 编码。

服务器 PostgreSQL 需要允许 Docker 网桥访问。推荐让容器通过 `host.docker.internal` 连接宿主机，并在 PostgreSQL 中确认：

- `listen_addresses` 包含 Docker 网桥可访问的监听地址；
- `pg_hba.conf` 允许实际 Docker 网段连接指定数据库；
- 服务器防火墙不需要向公网开放 5432，只需允许本机 Docker 网桥。

数据库尚未创建时，可由 PostgreSQL 管理员执行：

```sql
CREATE USER gateway_user WITH PASSWORD '替换为高强度数据库密码';
CREATE DATABASE xiaoasi_mail OWNER gateway_user;
```

## 3. 宝塔容器编排

进入：

```text
宝塔面板 → Docker → 容器编排 → 添加编排
```

建议：

- 名称：`cloudmail-token-broker`
- 目录：`/www/docker/cloudmail-token-broker`
- Compose：使用项目中的 `docker-compose.yml`

容器启动后以非 root 用户运行应用，并通过 SQLAlchemy 连接池连接服务器 PostgreSQL。

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

服务首次连接空 PostgreSQL 数据库时会自动创建数据表、索引和结构版本记录。当前不迁移旧 SQLite 数据，CloudMail 实例和邮箱域名需要在管理端重新配置。

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

业务数据存放在服务器 PostgreSQL。重建网关容器不会删除数据库数据。

## 8. 备份

升级前备份 `.env`，并使用 PostgreSQL 自带工具备份数据库：

```bash
cd /www/docker/cloudmail-token-broker
cp -a .env ".env.backup-$(date +%Y%m%d-%H%M%S)"
PGPASSWORD='数据库密码' pg_dump -h 127.0.0.1 -U 数据库用户 -d 数据库名 \
  -Fc -f "xiaoasi-mail-$(date +%Y%m%d-%H%M%S).dump"
```

`.env` 中的数据加密密钥必须与 PostgreSQL 备份一起保留，否则恢复数据库后无法解密实例密码。

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

### PostgreSQL 无法连接

检查 `DATABASE_URL`、数据库用户名和密码、PostgreSQL 监听地址、`pg_hba.conf`、Docker 网段及容器日志。容器内的 `127.0.0.1` 指向容器自身，连接宿主机数据库应使用 `host.docker.internal` 或服务器可达 IP。

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

PostgreSQL 已支持并发数据库访问，但 CloudMail Token 缓存和刷新锁仍在进程内。当前仍建议保持一个网关容器、一个 Uvicorn worker；后续如需多副本，需要再增加跨进程 Token 协调。
