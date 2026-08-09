# CloudMail Token Broker 部署手册

本文用于服务器管理员部署 CloudMail Token Broker。服务负责集中调用 CloudMail 的 `genToken`，并向图片站、Windows EXE 和其他项目提供统一 Token。

- GitHub：`https://github.com/xiaoasi-2023/cloudmail-token-broker`
- 阿里云镜像：`registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker`

## 1. 部署前准备

准备以下信息：

- 一台可以访问 CloudMail 服务的 Linux 服务器。
- 一个已经解析到服务器的独立域名，例如 `cloudmail-token.example.com`。
- CloudMail 服务地址、管理员邮箱和管理员密码。
- 一个 Broker 管理密钥，以及每个接入项目独立的 Client Key。
- 宝塔面板的 Docker、容器编排和网站反向代理功能。

Broker 首期为单实例内存缓存服务，不能同时启动多个副本。容器重启后会在第一次 `/v1/token` 请求时重新向 CloudMail 获取 Token。

## 2. 获取部署文件

建议目录：

```text
/www/docker/cloudmail-token-broker/
├── app/
├── docs/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
├── .env.example
└── .env
```

推荐直接克隆独立仓库：

```bash
cd /www/docker
git clone https://github.com/xiaoasi-2023/cloudmail-token-broker.git
cd cloudmail-token-broker
```

也可以只上传 `docker-compose.yml` 和 `.env.example`。服务器默认从阿里云拉取已构建镜像，不需要在生产服务器编译源码。`.env` 只在服务器上创建，不得提交真实密钥。

## 3. 生成密钥并填写环境变量

进入目录并复制配置模板：

```bash
cd /www/docker/cloudmail-token-broker
cp .env.example .env
```

生成随机密钥：

```bash
openssl rand -hex 48
```

至少填写以下配置：

```dotenv
IMAGE_TAG=latest

CLOUDMAIL_BASE_URL=https://mail.example.com
CLOUDMAIL_ADMIN_EMAIL=admin@example.com
CLOUDMAIL_ADMIN_PASSWORD=CloudMail管理员密码

BROKER_ADMIN_KEY=一条独立的管理密钥
BROKER_CLIENT_KEYS_JSON={"image2api":"图片站独立密钥","windows-exe":"EXE独立密钥"}
```

安全要求：

- `BROKER_ADMIN_KEY` 和每个 Client Key 至少 32 个字符，建议使用 `openssl rand -hex 48` 生成。
- 管理密钥不能与任何 Client Key 相同。
- 不要把管理员密码、管理密钥、Client Key 或 CloudMail Token 写入 Git、截图和普通日志。
- `BROKER_CLIENT_KEYS_JSON` 必须是单行 JSON 对象，键名是项目标识，值是该项目密钥。
- 如果 CloudMail 只能通过代理访问，在 `.env` 中填写 `CLOUDMAIL_PROXY=http://mihomo:11004` 或可访问的代理地址。
- 生产环境建议把 `IMAGE_TAG` 固定为发布版本，例如 `1.0.0`；测试环境可以使用 `latest`。

限制 `.env` 权限：

```bash
chmod 600 .env
```

## 4. 登录镜像仓库并启动

如果阿里云镜像仓库是私有仓库，先登录：

```bash
docker login registry.cn-hangzhou.aliyuncs.com
```

登录用户名和密码使用阿里云容器镜像服务提供的访问凭据，不是阿里云控制台登录密码。

在终端执行：

```bash
docker compose config
docker compose pull
docker compose up -d
docker compose ps
```

确认实际镜像：

```bash
docker inspect -f '{{.Config.Image}}' cloudmail-token-broker
```

预期以以下地址开头：

```text
registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker:
```

Compose 默认将容器端口绑定为：

```text
127.0.0.1:8788 -> 容器 8080
```

这意味着容器不会直接暴露公网，公网请求必须经过宝塔网站的 HTTPS 反向代理。

查看启动日志：

```bash
docker compose logs --tail=100 cloudmail-token-broker
```

## 5. 宝塔面板操作流程

### 5.1 容器编排

1. 打开宝塔“Docker → 容器编排”。
2. 新建编排或导入 `/www/docker/cloudmail-token-broker/docker-compose.yml`。
3. 确认编排目录是 `/www/docker/cloudmail-token-broker`，这样 `env_file: .env` 能正确读取。
4. 如果镜像仓库为私有，在服务器终端先登录阿里云镜像仓库。
5. 点击拉取镜像并启动，不需要在宝塔中从源码构建。
6. 确认容器状态为运行中，健康检查没有连续失败。

### 5.2 网站和 HTTPS

1. 在宝塔“网站”中新建独立域名，例如 `cloudmail-token.example.com`。
2. 为该域名申请并启用 HTTPS 证书。
3. 设置反向代理目标：

```text
http://127.0.0.1:8788
```

4. 保留 `Host`、`X-Real-IP`、`X-Forwarded-For` 请求头。
5. 不要将 `Authorization` 请求头写入自定义访问日志。
6. 如果使用 Cloudflare，建议开启代理、HTTPS 强制跳转和基础 WAF 规则。

不要把 `0.0.0.0:8788`、容器 `8080` 或 CloudMail 管理接口直接开放到公网。

## 6. 部署验证

先在服务器本机验证健康检查：

```bash
curl --fail http://127.0.0.1:8788/healthz
```

预期返回：

```json
{"ok":true,"service":"cloudmail-token-broker"}
```

使用项目 Client Key 获取 Token：

```bash
curl --fail-with-body -X POST 'http://127.0.0.1:8788/v1/token' \
  -H 'Authorization: Bearer <项目 Client Key>' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

再从公网域名验证：

```bash
curl --fail-with-body -X POST 'https://cloudmail-token.example.com/v1/token' \
  -H 'Authorization: Bearer <项目 Client Key>' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

管理状态验证：

```bash
curl --fail-with-body 'https://cloudmail-token.example.com/admin/status' \
  -H 'Authorization: Bearer <Broker 管理密钥>'
```

管理状态只显示版本摘要、时间和统计，不会显示 Token 明文。

## 7. 日常运维

查看状态和日志：

```bash
docker compose ps
docker compose logs --tail=200 cloudmail-token-broker
```

重启服务：

```bash
docker compose restart cloudmail-token-broker
```

修改 `.env` 后重新加载：

```bash
docker compose up -d --force-recreate
```

更新镜像：

```bash
docker compose pull
docker compose up -d --force-recreate
```

如果使用 `latest`，只执行 `restart` 不会拉取新镜像。生产环境建议修改 `IMAGE_TAG` 到明确版本后再更新。

## 8. 密钥轮换

推荐按项目逐个轮换：

1. 生成新的 Client Key。
2. 将新 Key 以新的项目键名加入 `BROKER_CLIENT_KEYS_JSON`，例如 `image2api-v2`。
3. 重新创建 Broker 容器。
4. 将对应项目切换到新 Key 并验证 `/v1/token`。
5. 删除旧项目键名，再次重新创建 Broker 容器。

轮换 CloudMail 管理员密码时，先修改 `.env`，再执行 `docker compose up -d --force-recreate`。Broker 会在下一次刷新时使用新密码。

## 9. 常见故障

| 现象 | 检查方法 | 处理方式 |
| --- | --- | --- |
| 容器反复重启 | `docker compose logs` | 检查必填环境变量、JSON 格式和密钥长度 |
| `/healthz` 正常但 `/v1/token` 返回 502 | 查看 Broker 日志并从服务器访问 CloudMail | 检查 CloudMail 地址、管理员凭据、TLS 和代理 |
| 返回 401 | 检查 Authorization 是否为对应项目 Client Key | 不要使用 Broker 管理密钥代替项目密钥 |
| 公网访问失败 | 检查宝塔反代、证书和 DNS | 反代目标必须是 `http://127.0.0.1:8788` |
| 获取到旧 Token | 检查是否仍有项目直接调用 CloudMail `genToken` | 迁移所有项目，禁止非 Broker 来源调用 `genToken` |
| 拉取镜像提示未授权 | 执行 `docker login` 并检查仓库权限 | 使用阿里云容器镜像服务登录凭据 |
| 更新后仍是旧版本 | 检查 `IMAGE_TAG` 和容器镜像地址 | 执行 `docker compose pull` 后强制重建容器 |

## 10. 下线和回滚

停止但保留容器和配置：

```bash
docker compose stop
```

删除容器但保留项目文件：

```bash
docker compose down
```

回滚镜像时，把 `.env` 的 `IMAGE_TAG` 改为上一可用版本，然后执行：

```bash
docker compose pull
docker compose up -d --force-recreate
```

不要删除包含 `.env` 的目录，除非已经完成密钥备份和服务迁移。
