# Xiaoasi Mail Gateway 发布流程

本项目使用阿里云容器镜像服务的自动构建能力，不在 GitHub Actions、本地电脑或生产服务器推送镜像。

发布链路只有三步：

```text
提交并推送 GitHub
    -> 阿里云自动拉取源码并构建镜像
    -> 服务器拉取阿里云镜像并重建容器
```

## 1. 仓库信息

- GitHub：`https://github.com/xiaoasi-2023/cloudmail-token-broker`
- 阿里云镜像：`registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker`
- Dockerfile：仓库根目录 `Dockerfile`
- 构建上下文：仓库根目录

## 2. 阿里云自动构建规则

在阿里云容器镜像服务中将镜像仓库关联到 GitHub 仓库，并配置自动构建规则：

```text
代码仓库：xiaoasi-2023/cloudmail-token-broker
Dockerfile：/Dockerfile
构建上下文：/
代码分支：main
镜像版本：latest
```

如果需要正式版本标签，可以再增加 Git Tag 构建规则。具体标签映射以阿里云控制台中的自动构建规则为准。

## 3. 发布新版本

本地完成开发和测试后：

```bash
git add <本次文件>
git commit
git push origin main
```

推送完成后，到阿里云容器镜像服务查看自动构建状态。只有自动构建成功后，服务器才执行更新。

本项目不需要：

- GitHub Actions 登录阿里云。
- 在 GitHub 中保存阿里云账号密码。
- 本地执行 `docker push`。
- 生产服务器执行 `docker build`。

## 4. 服务器更新

阿里云自动构建成功后，在服务器项目目录执行：

```bash
docker compose pull
docker compose up -d --force-recreate
docker compose ps
```

验证：

```bash
curl --fail http://127.0.0.1:8788/healthz
docker inspect -f '{{.Config.Image}}' cloudmail-token-broker
```

如果使用 `latest`，必须先执行 `docker compose pull`，只执行 `restart` 不会更新镜像。

## 5. 回滚

如果阿里云保留了上一版本标签，将 `.env` 中的 `IMAGE_NAME` 改为上一版本的完整镜像地址，再执行：

```bash
docker compose pull
docker compose up -d --force-recreate
```

如果当前只配置了 `latest` 自动构建，建议在阿里云增加 Git Tag 构建规则后再用于正式生产，便于按明确版本回滚。
