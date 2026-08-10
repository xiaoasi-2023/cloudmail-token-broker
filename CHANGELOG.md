# Changelog

## Unreleased

- 将服务升级为 Xiaoasi Mail Gateway 0.3.0，支持多个 CloudMail 实例及每实例多个邮箱域名，并彻底移除旧 Token Broker 对外能力。
- 新增统一邮箱 API，支持指定域名、域名范围和自动加权路由，调用方不再接触 CloudMail Token。
- 新增每实例独立 Token 缓存、401/403 比较刷新、失败切换、域名健康和冷却统计；并发鉴权失败只生成一次新 Token，避免再次互相覆盖。
- 新增幂等邮箱创建、随机邮箱地址、短期 `mailboxToken`、邮箱状态、释放和验证码提取接口。
- 新增 SQLite 持久化、CloudMail 管理员密码加密、管理会话和请求审计。
- 新增 React + Ant Design 可视化管理端，覆盖概览、实例、域名、邮箱记录、请求日志和系统设置说明。
- CloudMail 实例抽屉新增所属邮箱域名列表，可在创建实例后直接添加、编辑和删除域名，并自动绑定当前实例。
- 修复旧 SQLite 持久化数据库不会自动补齐表字段的问题；启动时执行版本 2 结构升级，避免域名管理接口因旧表结构返回 HTTP 500。
- 邮箱域名页面改为独立加载实例与域名数据，单个接口失败时保留另一部分已加载内容和可操作入口。
- Docker 改为 Node/Python 多阶段构建，并挂载 `/app/data` 持久化数据库。
- 新增网关密钥生成和数据保留清理脚本，清理支持 dry-run 和 apply。
- 新增多实例、路由、管理 API、公开 API、应用集成和清理测试；浏览器完成桌面及移动端验收。
- 限制 `Idempotency-Key` 最大 256 字符，并回收使用完毕的进程内幂等锁，避免公开接口高基数 Key 长期占用内存。
- 新增管理端登录来源限流；修正 apply 模式下清理脚本实际删除数量统计。
- 新增 `docs/xiaoasi-mail-gateway-development-plan.md`，确定多 CloudMail 实例、多域名路由、统一邮箱 API、短期邮箱凭证、SQLite 持久化和可视化管理端的完整升级方案。
- 删除旧 Token Broker 的 Token 外发接口、单实例环境变量、Client Key 鉴权代码及对应测试。
- 精简 `.env`、部署说明和接口文档，CloudMail 实例统一由管理端维护。
- 仓库迁移到 `https://github.com/xiaoasi-2023/cloudmail-token-broker`。
- 默认部署镜像改为 `registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker`。
- 发布流程收敛为“提交推送 GitHub → 阿里云自动构建 → 服务器拉取镜像”。
- 删除不需要的 GitHub Actions 阿里云登录和本地手工推送配置。
- 更新 README、部署手册、API 文档和发布说明。
