# Xiaoasi Mail Gateway

Xiaoasi Mail Gateway 是一个统一邮箱网关，负责管理多个 CloudMail 实例、邮箱域名、用户、调用密钥、积分和 POP3 邮件访问。

> 当前仓库已实现用户中心、积分和 POP3 `110` 监听；上线前仍需使用真实 CloudMail 环境完成验收，并按部署文档放行 `110/tcp`。`995` 不开放。

图片站、Kirox、Windows EXE 和其他调用方只接入网关，不保存 CloudMail 管理员账号、密码、Token 或内部接口路径。

## 核心能力

- 多个 CloudMail 实例和多个邮箱域名；
- 自动、指定单域名和候选域名创建邮箱；
- 用户中心、用户级 `X-API-Key` 和用户级 `userAuthCode`；
- 可选的邮箱验证码自助注册，支持账号或邮箱登录；
- 创建邮箱按管理端配置扣除积分；
- 唯一管理员管理全部用户、邮箱、日志、实例、域名和积分；
- 管理员独立 POP 授权码，可以读取全部未物理删除且上游仍存在的邮箱；
- 固定 POP3 `110` 端口只读取信，不开放 `995`；
- `Idempotency-Key` 幂等创建和短期 `mailboxToken`；
- 统一验证码查询和 CloudMail Provider 适配；
- PostgreSQL 持久化和一次性旧数据清理迁移。

## 调用链

```text
用户登录用户中心
      ↓ 创建自己的 X-API-Key
POST /v1/mailboxes
      ↓ 积分预扣、选择域名和 CloudMail 实例
CloudMail addUser
      ↓ 返回邮箱地址和 mailboxToken
普通用户：POP3 110 + 邮箱地址 + userAuthCode
管理员：POP3 110 + 任意邮箱地址 + 管理员 POP 授权码
      ↓
网关调用 CloudMail emailList 并转换为 POP 邮件
```

## 快速部署

默认镜像：

```text
registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker:latest
```

部署目录至少包含：

```text
cloudmail-token-broker/
├── docker-compose.yml
└── .env
```

关键环境变量：

```dotenv
GATEWAY_ENABLED=true
DATABASE_URL=postgresql://数据库用户:数据库密码@host.docker.internal:5432/数据库名?connect_timeout=10
DATA_ENCRYPTION_KEY=<至少32字节随机值>
MAILBOX_SESSION_SECRET=<另一条至少32字节随机值>

ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=<推荐：pbkdf2_sha256 格式的管理员密码哈希>
ADMIN_COOKIE_SECURE=true
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

POP3_ENABLED=true
POP3_BIND_HOST=0.0.0.0
POP3_PORT=8110
POP3_PUBLIC_HOST=pop.cloudmail.xiaoasi.xyz
POP3_MAX_CONNECTIONS=100
POP3_MAX_AUTH_FAILURES=3
POP3_MAX_MESSAGES=20
```

`POP3_PORT=8110` 是容器内监听端口；对外 `110` 由 `docker-compose.yml` 的 `110:8110` 映射提供，不配置 `POP3_PUBLIC_PORT`。首期不启用 STLS/POP3S，不能通过环境变量打开 `995`。

外部服务地址：

```text
HTTPS API： https://cloudmail.xiaoasi.xyz
默认入口： https://cloudmail.xiaoasi.xyz/ （自动进入用户中心，未登录时显示登录/注册页）
管理端：   https://cloudmail.xiaoasi.xyz/admin/
用户中心： https://cloudmail.xiaoasi.xyz/user/
POP3：     pop.cloudmail.xiaoasi.xyz:110
```

POP3 `110` 是独立 TCP 服务，不能通过普通 HTTP 反向代理；宿主机应将 `110` 映射到容器内部的 `8110`，并在防火墙放行 `110/tcp`。首期普通 `USER/PASS` 不经过 TLS，必须限制访问来源；`995` 不开放。

管理端和用户中心都由同一个 FastAPI 容器提供静态入口：根路径 `/` 默认跳转 `/user/`，管理端为 `/admin/`，用户中心为 `/user/`，不需要单独部署第二个前端容器。

### 已有线上部署更新

本次版本会自动将数据库结构升级到版本 `7`，新增普通用户 POP 授权码和用户调用密钥明文字段。线上更新必须先备份 `.env` 和 PostgreSQL，再补齐 `POP3_PUBLIC_HOST`、用户注册与 SMTP 配置，最后执行 `docker compose pull` 和 `docker compose up -d --force-recreate`。不要再次清空调用密钥、邮箱记录或请求日志。旧版只保存哈希的授权码和调用密钥无法反推，分别重置或重新生成一次后即可在用户中心长期查看。完整流程见[宝塔部署手册](docs/deployment.md#4-已有线上部署升级)。

## 首次配置流程

1. 使用唯一管理员账号登录 `/admin/`。
2. 配置 CloudMail 实例和邮箱域名。
3. 在管理端设置管理员全局 POP 授权码；该值按明文保存，可在管理端随时查看、复制和修改。
4. 开启自助注册后，普通用户在 `/user/` 输入账号、邮箱和密码，获取邮箱验证码后完成注册；关闭时仍由管理员创建用户。
5. 普通用户使用账号或注册邮箱登录 `/user/`，点击按钮自动生成自己的 `userAuthCode`；生成后可长期查看和复制完整值，连接页会自动展示 POP 主机、110 端口及可用邮箱地址。
6. 普通用户在用户中心创建自己的 `X-API-Key`。
7. 使用用户密钥调用 `POST /v1/mailboxes` 创建邮箱。

## 创建邮箱

```bash
curl -X POST 'https://cloudmail.xiaoasi.xyz/v1/mailboxes' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: register-task-123' \
  -H 'X-API-Key: <用户自己创建的调用密钥>' \
  -d '{"purpose":"openai","addressPattern":"name_digits_4","name":"image2api"}'
```

成功响应会返回：

```json
{
  "code": 200,
  "data": {
    "mailboxId": "mbx_example",
    "address": "image2api4821@mail-a.example.com",
    "domain": "mail-a.example.com",
    "mailboxToken": "短期邮箱访问凭证",
    "createdAt": "2026-08-10T08:00:00+00:00",
    "expiresAt": "2026-08-10T08:30:00+00:00",
    "remainingCredits": 99
  }
}
```

## POP3 取信

普通用户邮件客户端配置：

```text
服务器：pop.cloudmail.xiaoasi.xyz
端口：110
安全性：普通 POP3
用户名：创建邮箱后返回的完整 address
密码：该邮箱所属用户的 userAuthCode
```

管理员邮件客户端配置：

```text
服务器：pop.cloudmail.xiaoasi.xyz
端口：110
安全性：普通 POP3
用户名：任意未物理删除的邮箱 address
密码：管理员全局 POP 授权码
```

只实现只读取信：`CAPA`、`USER`、`PASS`、`STAT`、`LIST`、`UIDL`、`RETR`、`TOP`、`NOOP`、`RSET`、`QUIT`。不支持 SMTP、IMAP、附件下载和 `DELE`；邮件客户端必须关闭“从服务器删除邮件”，并设置为保留服务器上的邮件。

## 查询验证码

```bash
curl -X POST 'https://cloudmail.xiaoasi.xyz/v1/mailboxes/mbx_example/verification-code' \
  -H 'X-API-Key: <用户自己创建的调用密钥>' \
  -H 'Authorization: Mailbox <mailboxToken>' \
  -H 'Content-Type: application/json' \
  -d '{"purpose":"openai","waitSeconds":20}'
```

## 数据迁移

本次改版不兼容旧调用密钥、旧邮箱记录和旧请求日志。迁移前必须备份 PostgreSQL，并停止业务容器；迁移脚本使用 `dry-run` 预览，确认后再使用 `--apply`。

旧 CloudMail 上游邮箱是否删除取决于 Provider 能力。本地删除网关记录不代表上游账号已删除。

## 文档

- [调用方接入指南](docs/client-integration.md)
- [API 接口文档](docs/api.md)
- [宝塔部署手册](docs/deployment.md)
- [完整开发方案](docs/xiaoasi-mail-gateway-development-plan.md)
- [发布流程](docs/release.md)
