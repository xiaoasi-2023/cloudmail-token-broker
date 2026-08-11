# Xiaoasi Mail Gateway 宝塔部署手册

本文档描述 HTTPS API、管理端、用户中心和 POP3 `110` 的部署方式。`995` 不开放。

> 当前仓库已接入 POP3 监听器及容器启动生命周期。生产邮件客户端接入前，仍需使用真实 CloudMail 环境完成验收，并确认宿主机防火墙放行 `110/tcp`；`995` 不开放。

## 1. 准备目录

```bash
mkdir -p /www/docker/cloudmail-token-broker
cd /www/docker/cloudmail-token-broker
```

上传：

- `docker-compose.yml`；
- `.env`。

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
ADMIN_PASSWORD_HASH=<推荐：pbkdf2_sha256 格式的管理员密码哈希>
# 旧部署兼容项：如实现保留明文引导，可与 ADMIN_PASSWORD_HASH 二选一，生产优先使用哈希
# ADMIN_PASSWORD=<仅用于本地或一次性初始化的强密码>
ADMIN_SESSION_TTL_SECONDS=28800
ADMIN_COOKIE_SECURE=true
ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE=10
USER_REGISTRATION_ENABLED=true
USER_REGISTRATION_CODE_TTL_SECONDS=600
USER_REGISTRATION_CODE_COOLDOWN_SECONDS=60
USER_REGISTRATION_RATE_LIMIT_PER_MINUTE=10

SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USERNAME=<发件邮箱>
SMTP_PASSWORD=<SMTP 授权码，不是邮箱登录密码>
SMTP_FROM=<发件邮箱>
SMTP_TLS=true

MAILBOX_CREATE_RATE_LIMIT_PER_MINUTE=120
MAILBOX_POLL_RATE_LIMIT_PER_MINUTE=600

POP3_ENABLED=true
POP3_BIND_HOST=0.0.0.0
POP3_PORT=8110
POP3_MAX_CONNECTIONS=100
POP3_MAX_AUTH_FAILURES=3
POP3_MAX_MESSAGES=20
```

`DATA_ENCRYPTION_KEY` 和 `MAILBOX_SESSION_SECRET` 必须不同，生产环境不能随意修改。`ADMIN_PASSWORD_HASH` 与 `ADMIN_PASSWORD` 二选一，不能同时配置，生产优先使用哈希。普通 POP3 `110` 首期不启用 TLS，`995` 不开放；如果未来启用 `STLS`，再挂载证书和私钥。

开启 `USER_REGISTRATION_ENABLED=true` 时，SMTP 六项配置必须完整。`SMTP_TLS=true` 在 `465` 端口使用 SSL 连接；`SMTP_PASSWORD` 填邮箱服务商生成的 SMTP 授权码，不能提交到 Git。若不开放注册，将开关改为 `false`，用户仍可由唯一管理员创建。

`POP3_PORT=8110` 只控制容器内监听端口；对外 `110` 由 Compose 的 `110:8110` 映射提供。当前代码没有 `POP3_PUBLIC_PORT`、`POP3_STLS_ENABLED` 或证书路径环境变量，不能通过环境变量打开 `995` 或 STLS。

数据库密码包含 `@`、`:`、`/`、`?`、`#` 等字符时需要 URL 编码。PostgreSQL 不由 Docker Compose 创建，必须提前创建数据库并允许 Docker 网桥访问。

## 3. Docker Compose 端口

Compose 至少需要以下端口映射：

```yaml
ports:
  - "127.0.0.1:8788:8080"  # HTTPS API 由宝塔反向代理
  - "110:8110"             # 对外 POP3，客户端固定连接 110
```

容器内部使用 `8110` 是为了避免非 root 进程直接绑定特权端口；用户和外部邮件客户端仍然只配置 `110`。不要映射或开放 `995`。

## 4. 启动容器

```bash
cd /www/docker/cloudmail-token-broker
docker compose pull
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 cloudmail-token-broker
```

容器应继续以非 root 用户运行。POP3 服务和 FastAPI 必须是独立的 TCP/HTTP 生命周期，不能使用 HTTP 路由模拟 POP3。

FastAPI 同时挂载 `/admin/` 和 `/user/` 静态入口；宝塔只需将 HTTPS API 域名反向代理到 `127.0.0.1:8788`，不需要为用户中心单独配置站点或容器。

## 5. HTTPS 和 POP3 DNS

宝塔 HTTPS 网站：

```text
cloudmail.xiaoasi.xyz  →  http://127.0.0.1:8788
```

POP3 建议使用独立域名：

```text
pop.cloudmail.xiaoasi.xyz  →  服务器公网 IP
```

POP3 是原始 TCP 协议，不能通过普通 HTTP 反向代理转发。若使用 Cloudflare，POP3 域名必须使用 DNS only，除非另行购买并配置 TCP 代理能力。

服务器防火墙必须允许业务来源访问 `110/tcp`，并且必须只允许已知业务服务器或办公网段访问；禁止将普通明文 POP3 对全公网开放。管理端、API 和数据库仍按最小来源范围限制。

## 6. 首次配置

1. 使用 `.env` 中的管理员账号登录 `/admin/`。
2. 新增 CloudMail 实例并填写管理员邮箱、密码、API 地址和 TLS 设置。
3. 为实例添加邮箱域名并测试连接。
4. 设置管理员全局 POP 授权码；当前版本按明文存入数据库，可在管理端随时查看和复制。
5. 创建普通用户并配置初始积分。
6. 普通用户登录 `/user/`，设置自己的 `userAuthCode` 并创建 `X-API-Key`。
7. 使用用户密钥调用 `/v1/mailboxes` 验证邮箱创建和积分扣费。
8. 使用普通用户授权码和管理员全局授权码分别验证 POP3 110 的访问范围。

## 7. 验证命令

健康检查：

```bash
curl -fsS http://127.0.0.1:8788/healthz
```

检查用户中心静态入口：

```bash
curl -fsSI https://cloudmail.xiaoasi.xyz/user/
```

检查端口：

```bash
nc -vz 127.0.0.1 110
```

检查 POP3 欢迎语：

```bash
printf 'QUIT\r\n' | nc -v pop.cloudmail.xiaoasi.xyz 110
```

创建邮箱：

```bash
curl -sS -X POST 'https://cloudmail.xiaoasi.xyz/v1/mailboxes' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: deploy-test-001' \
  -H 'X-API-Key: 用户自己创建的调用密钥' \
  -d '{"purpose":"openai","addressPattern":"name_digits_4","name":"deploytest"}'
```

## 8. 一次性数据迁移

本次改版不兼容旧调用密钥、邮箱记录、幂等记录和请求日志。迁移前：

1. 停止业务容器；
2. 备份 `.env` 和 PostgreSQL；
3. 运行迁移脚本 dry-run；
4. 确认删除范围后使用 `--apply`；
5. 重建新用户、唯一管理员、用户密钥、用户会话、积分规则、积分流水和审计表；
6. 设置管理员全局 POP 授权码，并确认管理端可以回显和复制当前明文值；
7. 重新创建普通用户调用密钥和用户授权码；
8. 分别验收普通用户和管理员 POP3 访问。

迁移必须删除或重建旧业务表，不能只清空数据行。旧 CloudMail 上游邮箱不会因为本地记录删除而自动消失，是否删除取决于 Provider 能力。

## 9. 备份

```bash
cd /www/docker/cloudmail-token-broker
cp -a .env ".env.backup-$(date +%Y%m%d-%H%M%S)"
PGPASSWORD='数据库密码' pg_dump -h 127.0.0.1 -U 数据库用户 -d 数据库名 \
  -Fc -f "xiaoasi-mail-$(date +%Y%m%d-%H%M%S).dump"
```

`.env` 中的数据加密密钥必须与 PostgreSQL 备份一起保留，否则恢复数据库后无法解密 CloudMail 实例密码。

## 10. 常见问题

### POP3 110 无法连接

检查容器端口映射是否为 `110:8110`、主机防火墙、云安全组、DNS 是否指向正确服务器，以及 POP3 进程是否监听容器内 `8110`。同时检查应用启动日志中 POP3 监听器已启动、停止时已释放端口；不要检查 `995`，本项目不开放该端口。

### 普通用户能访问其他用户邮箱

检查 POP 登录是否按 `owner_user_id` 校验，以及管理员全局授权码是否被错误地配置到了普通用户字段。普通用户只能使用自己的 `userAuthCode`。

### 管理员无法读取全部邮箱

确认管理员已设置全局 POP 授权码，并使用任意未物理删除且上游仍存在的邮箱地址作为用户名。管理员 POP 授权码不等于管理员登录密码。

### 管理端登录后立即返回登录页

生产 HTTPS 应设置：

```dotenv
ADMIN_COOKIE_SECURE=true
```

### PostgreSQL 无法连接

检查 `DATABASE_URL`、数据库用户名和密码、PostgreSQL 监听地址、`pg_hba.conf`、Docker 网段和容器日志。容器内的 `127.0.0.1` 指向容器自身，宿主机数据库应使用 `host.docker.internal` 或服务器可达 IP。
