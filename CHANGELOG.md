# Changelog

## Unreleased

- 增加 `BROKER_PUBLIC_ACCESS` 公开调用模式，客户端无需配置独立密钥即可获取和刷新 Token。
- `BROKER_ADMIN_KEY` 改为可选；留空时管理接口明确返回未启用。
- 保留原 Client Key 鉴权模式，关闭公开模式后仍可按需启用。
- 更新本地 `.env`、部署说明和接口示例，默认采用公开调用方式。
- 仓库迁移到 `https://github.com/xiaoasi-2023/cloudmail-token-broker`。
- 默认部署镜像改为 `registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker`。
- 发布流程收敛为“提交推送 GitHub → 阿里云自动构建 → 服务器拉取镜像”。
- 删除不需要的 GitHub Actions 阿里云登录和本地手工推送配置。
- 更新 README、部署手册、API 文档和发布说明。
