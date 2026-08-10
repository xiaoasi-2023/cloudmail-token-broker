# CloudMail Token Broker 宝塔部署手册

## 1. 部署文件

在服务器创建目录：

```bash
mkdir -p /www/docker/cloudmail-token-broker
cd /www/docker/cloudmail-token-broker
```

把本地项目中的两个文件上传到该目录：

- `docker-compose.yml`
- `.env`

最终结构：

```text
/www/docker/cloudmail-token-broker/
├── docker-compose.yml
└── .env
```

无需把完整源码上传服务器。GitHub 推送后由阿里云自动构建镜像，宝塔只拉取镜像。

## 2. 填写 `.env`

上传前必须替换以下三项：

```dotenv
CLOUDMAIL_BASE_URL=https://你的CloudMail域名
CLOUDMAIL_ADMIN_EMAIL=你的CloudMail管理员邮箱
CLOUDMAIL_ADMIN_PASSWORD=你的CloudMail管理员密码
```

公开调用配置保持：

```dotenv
BROKER_PUBLIC_ACCESS=true
BROKER_ADMIN_KEY=
```

这表示图片站、Kirox、EXE 等客户端调用时不需要 Authorization，也不需要分别生成项目密钥。

其余推荐值：

```dotenv
IMAGE_TAG=latest
TOKEN_CACHE_SECONDS=1500
TOKEN_REFRESH_SKEW_SECONDS=120
REQUEST_TIMEOUT_SECONDS=15
CLOUDMAIL_VERIFY_TLS=true
CLOUDMAIL_PROXY=
TOKEN_RATE_LIMIT_PER_MINUTE=600
REFRESH_RATE_LIMIT_PER_MINUTE=5
ADMIN_RATE_LIMIT_PER_MINUTE=2
LOG_LEVEL=INFO
```

## 3. 在宝塔创建容器编排

进入：

```text
宝塔面板 → Docker → 容器编排 → 添加编排
```

建议：

- 编排名称：`cloudmail-token-broker`
- 编排目录：`/www/docker/cloudmail-token-broker`
- Compose 内容直接使用上传的 `docker-compose.yml`

当前端口映射是：

```yaml
ports:
  - "127.0.0.1:8788:8080"
```

它只允许服务器本机访问 8788，外部程序通过宝塔网站反向代理和 HTTPS 域名访问，不直接暴露容器端口。

## 4. 配置公网 HTTPS 域名

在宝塔中新建网站，例如：

```text
broker.example.com
```

反向代理目标：

```text
http://127.0.0.1:8788
```

然后申请并启用 SSL，强制 HTTPS。

建议在反向代理或 CDN 上增加频率限制，尤其是：

- `POST /v1/token/refresh`
- `POST /api/public/genToken`

公开模式意味着任何知道域名的人都能请求 Token，公网限流是必要保护。

## 5. 启动与更新

首次启动：

```bash
cd /www/docker/cloudmail-token-broker
docker compose pull
docker compose up -d --force-recreate
docker compose ps
```

GitHub 推送并等待阿里云构建成功后，在服务器更新：

```bash
cd /www/docker/cloudmail-token-broker
docker compose pull
docker compose up -d --force-recreate
docker image prune -f
```

查看日志：

```bash
docker compose logs --tail=100 cloudmail-token-broker
```

## 6. 验证

服务器本机健康检查：

```bash
curl -fsS http://127.0.0.1:8788/healthz
```

预期：

```json
{"ok":true,"service":"cloudmail-token-broker"}
```

测试兼容接口：

```bash
curl -sS -X POST \
  -H 'Content-Type: application/json' \
  -d '{}' \
  https://broker.example.com/api/public/genToken
```

测试标准接口：

```bash
curl -sS -X POST https://broker.example.com/v1/token
```

两个接口均不需要 Authorization。

## 7. 客户端接入

旧项目原来调用：

```text
https://cloudmail.example.com/api/public/genToken
```

改成：

```text
https://broker.example.com/api/public/genToken
```

请求体可以继续传原来的邮箱和密码，也可以传 `{}`；Broker 不读取客户端传来的管理员账号密码，而是使用服务器 `.env` 中的 CloudMail 管理员凭据。

## 8. 管理接口

当前 `.env` 中：

```dotenv
BROKER_ADMIN_KEY=
```

表示管理接口关闭。若以后确实要使用 `/admin/status` 和 `/admin/token/refresh`，填写至少 32 个字符的随机密钥并重建容器即可。

## 9. 常见问题

### 容器启动失败并提示缺少环境变量

检查 `.env` 中以下三项是否仍是占位符或为空：

- `CLOUDMAIL_BASE_URL`
- `CLOUDMAIL_ADMIN_EMAIL`
- `CLOUDMAIL_ADMIN_PASSWORD`

### Token 接口返回 502

检查 Broker 容器能否访问 CloudMail 域名，CloudMail 管理员账号密码是否正确，以及 `CLOUDMAIL_VERIFY_TLS` 是否符合证书情况。

### 公网访问失败

检查宝塔网站反向代理是否指向 `http://127.0.0.1:8788`，SSL 证书和防火墙规则是否正确。无需把 8788 直接开放到公网。

### 多次请求是否会一直生成新 Token

不会。正常获取接口共享内存缓存。只有缓存进入刷新窗口、明确调用刷新接口或容器重启后首次请求时，才会访问 CloudMail。

### 能否运行多个容器副本

当前不建议。缓存和刷新锁都在单个进程内，多副本会各自获取 Token。部署时保持一个 Broker 容器。
