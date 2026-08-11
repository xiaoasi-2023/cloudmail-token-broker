# Xiaoasi Mail Gateway 宝塔部署手册

本文档描述 HTTPS API、管理端、用户中心和 POP3 `18110` 的部署方式。容器内部仍监听 `8110`。

> 当前仓库已接入 POP3 监听器及容器启动生命周期。服务器厂商当前禁用 `110` 和 `995`，因此生产邮件客户端统一连接 `18110/tcp`。

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
POP3_PUBLIC_HOST=pop.cloudmail.xiaoasi.xyz
POP3_PUBLIC_PORT=18110
POP3_MAX_CONNECTIONS=100
POP3_MAX_AUTH_FAILURES=3
POP3_MAX_MESSAGES=20
```

`DATA_ENCRYPTION_KEY` 和 `MAILBOX_SESSION_SECRET` 必须不同，生产环境不能随意修改。`ADMIN_PASSWORD_HASH` 与 `ADMIN_PASSWORD` 二选一，不能同时配置，生产优先使用哈希。当前 `18110` 是普通明文 POP3，不启用 STLS 或隐式 TLS。

开启 `USER_REGISTRATION_ENABLED=true` 时，SMTP 六项配置必须完整。`SMTP_TLS=true` 在 `465` 端口使用 SSL 连接；`SMTP_PASSWORD` 填邮箱服务商生成的 SMTP 授权码，不能提交到 Git。若不开放注册，将开关改为 `false`，用户仍可由唯一管理员创建。

根域名 `/` 默认跳转到 `/user/`。普通用户未登录时显示用户登录/注册页，已登录时直接进入用户中心；唯一管理员仍通过 `/admin/` 登录。

`POP3_PORT=8110` 只控制容器内监听端口；`POP3_PUBLIC_HOST` 和 `POP3_PUBLIC_PORT=18110` 控制用户中心展示的客户端连接参数。Compose 同时映射 `110`、`18110` 和 `995` 到容器 `8110`，当前实际只开放并使用 `18110`。`995:8110` 只是保留端口映射，不提供 POP3S/TLS。

数据库密码包含 `@`、`:`、`/`、`?`、`#` 等字符时需要 URL 编码。PostgreSQL 不由 Docker Compose 创建，必须提前创建数据库并允许 Docker 网桥访问。

## 3. Docker Compose 端口

Compose 至少需要以下端口映射：

```yaml
ports:
  - "127.0.0.1:8788:8080"  # HTTPS API 由宝塔反向代理
  - "110:8110"             # 暂时保留，当前服务器厂商禁用
  - "18110:8110"           # 当前对外 POP3 端口
  - "995:8110"             # 暂时保留，不代表支持 POP3S/TLS
```

容器内部统一使用 `8110`。用户中心和外部邮件客户端配置 `18110`；防火墙和云安全组只需开放 `18110/tcp`。不要把 `995` 当作加密 POP3 端口使用。

## 4. 已有线上部署升级

本节用于已经运行 `cloudmail-token-broker` 的服务器。本次是原地升级，不是首次部署，不需要重新创建数据库，也不要再次执行 `TRUNCATE`、`DROP TABLE` 或旧数据清理脚本。

### 4.1 等待镜像构建完成

GitHub `main` 推送后，先在阿里云容器镜像服务确认 `latest` 自动构建成功。构建未完成时不要在服务器执行更新，否则可能仍拉取到旧镜像。

### 4.2 备份线上配置和数据库

```bash
cd /www/docker/cloudmail-token-broker

cp -a .env ".env.backup-$(date +%Y%m%d-%H%M%S)"

export DATABASE_URL="$(awk -F= '$1=="DATABASE_URL"{sub(/^[^=]*=/,""); print; exit}' .env)"
test -n "$DATABASE_URL" || { echo "DATABASE_URL 未配置"; exit 1; }

pg_dump "$DATABASE_URL" -Fc \
  -f "xiaoasi-mail-before-v5-$(date +%Y%m%d-%H%M%S).dump"
```

本次数据库升级是增量升级，但生产更新前仍必须保留 PostgreSQL 备份和 `.env` 备份。

### 4.3 补齐注册和 SMTP 配置

保留现有数据库、加密密钥、管理员配置和 POP3 配置，在服务器 `.env` 中确认以下配置存在：

```dotenv
USER_REGISTRATION_ENABLED=true
USER_REGISTRATION_CODE_TTL_SECONDS=600
USER_REGISTRATION_CODE_COOLDOWN_SECONDS=60
USER_REGISTRATION_RATE_LIMIT_PER_MINUTE=10

SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USERNAME=<实际发件邮箱>
SMTP_PASSWORD=<实际 SMTP 授权码>
SMTP_FROM=<实际发件邮箱>
SMTP_TLS=true
```

不要把实际 `SMTP_PASSWORD` 发到群聊、提交到 Git 或写入部署日志。

### 4.4 拉取镜像并重建现有容器

```bash
cd /www/docker/cloudmail-token-broker
docker compose pull
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=200 cloudmail-token-broker
```

应用启动时会自动将数据库结构升级到版本 `7`，新增普通用户 POP 授权码和用户调用密钥明文字段。该升级不会删除现有用户、积分、调用密钥、邮箱记录、请求日志、实例或域名；旧版哈希授权码和调用密钥仍可继续使用，但无法回显，用户分别重置或重新生成一次后即可长期查看。

可以确认数据库版本：

```bash
export DATABASE_URL="$(awk -F= '$1=="DATABASE_URL"{sub(/^[^=]*=/,""); print; exit}' .env)"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c \
  "SELECT version FROM gateway_schema"
```

预期版本为 `7`。

### 4.5 升级后验证

```bash
curl -fsS http://127.0.0.1:8788/healthz
curl -fsS http://127.0.0.1:8788/user-api/auth/registration-config
curl -fsSI https://cloudmail.xiaoasi.xyz/user/
nc -vz 127.0.0.1 18110
printf 'QUIT\r\n' | nc -v 127.0.0.1 18110
```

健康检查应继续返回 `pop3Listening: true`，注册配置应返回 `enabled: true`，POP3 欢迎语应正常返回。

随后按以下业务顺序点验：

1. 管理员登录 `/admin/`，进入“积分/POP 设置”。
2. 如果页面提示当前管理员 POP 授权码是旧版哈希数据，重新输入原授权码或自动生成新值并保存；保存后可随时显示和复制明文。
3. 打开 `/user/`，点击“没有账号？使用邮箱注册”，使用一个真实收件邮箱验证 SMTP 验证码邮件。
4. 注册成功后确认用户自动登录、初始积分正确，并设置用户级 POP 授权码和创建用户调用密钥。
5. 使用该用户调用密钥创建一个测试邮箱，确认积分扣除和邮箱归属正确。
6. 使用测试邮箱地址、端口 `18110` 和用户 POP 授权码完成一次真实 POP3 登录取信。
7. 使用管理员全局 POP 授权码读取该测试邮箱，确认管理员仍可访问全部邮箱。

容器应继续以非 root 用户运行。POP3 服务和 FastAPI 必须是独立的 TCP/HTTP 生命周期，不能使用 HTTP 路由模拟 POP3。FastAPI 同时挂载 `/admin/` 和 `/user/` 静态入口；宝塔只需将 HTTPS API 域名反向代理到 `127.0.0.1:8788`。

### 4.6 本次版本回滚注意事项

数据库版本 `7` 的新增表和字段属于增量结构，旧镜像通常会忽略它们。但是普通用户重置 POP 授权码、重新生成调用密钥或管理员重新保存全局 POP 授权码后，对应旧哈希值会被替换；如果再回滚到只支持旧字段的镜像，相关登录或接口调用将不可用。

因此需要回滚到旧镜像时，应同时恢复本次更新前的 PostgreSQL 备份和 `.env` 备份；不要只切换镜像后继续使用已经升级并写入新数据的数据库。

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

服务器防火墙和云安全组必须允许业务来源访问 `18110/tcp`，并且必须只允许已知业务服务器或办公网段访问；禁止将普通明文 POP3 对全公网开放。`110/tcp` 和 `995/tcp` 当前不作为业务入口。管理端、API 和数据库仍按最小来源范围限制。

## 6. 首次配置

1. 使用 `.env` 中的管理员账号登录 `/admin/`。
2. 新增 CloudMail 实例并填写管理员邮箱、密码、API 地址和 TLS 设置。
3. 为实例添加邮箱域名并测试连接。
4. 设置管理员全局 POP 授权码；当前版本按明文存入数据库，可在管理端随时查看和复制。
5. 创建普通用户并配置初始积分。
6. 普通用户登录 `/user/`，点击按钮自动生成自己的 `userAuthCode`，并创建 `X-API-Key`。
7. 使用用户密钥调用 `/v1/mailboxes` 验证邮箱创建和积分扣费。
8. 使用普通用户授权码和管理员全局授权码分别验证 POP3 18110 的访问范围。

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
nc -vz 127.0.0.1 18110
```

检查 POP3 欢迎语：

```bash
printf 'QUIT\r\n' | nc -v pop.cloudmail.xiaoasi.xyz 18110
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

### POP3 18110 无法连接

检查容器端口映射是否包含 `18110:8110`、主机防火墙、云安全组、DNS 是否指向正确服务器，以及 POP3 进程是否监听容器内 `8110`。同时检查应用启动日志中 POP3 监听器已启动、停止时已释放端口。`110` 和 `995` 当前受服务器厂商限制，不用于业务验收。

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
