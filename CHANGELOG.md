# Changelog

## Unreleased

- 管理员全局 POP 授权码改为数据库明文存储；管理端可随时读取、显示、复制和修改当前值，旧版仅哈希记录在管理员重新保存前仍可用于 POP3 校验。
- 新增用户邮箱验证码注册闭环：用户中心支持发送 6 位验证码、自助注册并自动登录；验证码使用服务端密钥哈希保存，支持有效期、同邮箱发送冷却、失败次数限制和来源限流。
- 新增通用 SMTP 注册邮件发送，支持 `smtp.163.com:465` SSL 配置；SMTP 授权码仅从环境变量读取，不写入数据库、日志或前端。
- 用户登录支持使用用户账号或注册邮箱；注册用户仍只能创建 `role=user`，初始积分继续使用管理端积分规则。
- 邮箱记录新增验证码持久化字段，管理端直接展示实际验证码并支持点击复制，不再仅显示“已收到”。
- 邮箱记录支持按邮箱、域名或调用方模糊搜索，并可按 OpenAI、Kiro、Cursor、Grok 用途筛选；创建时间列加宽并固定单行显示。
- 创建邮箱接口新增内置用户名生成规则，默认使用“随机英文名 + 4 位数字”。
- 支持调用方通过 `addressPattern` 和 `name` 选择邮箱用户名格式，并保留 `prefix` 兼容字段。
- 遇到上游邮箱地址已存在时自动重新生成，避免把已有邮箱误判为创建成功。
- 管理端去除页面顶部重复标题，并明确域名运行状态来自真实创建调用。
- 文档统一使用生产地址 `https://cloudmail.xiaoasi.xyz`。
- 删除调用方自报的 `source` 和 `X-Client-Source`，改为管理端签发的明文 `X-API-Key`。
- 新增调用密钥管理页面、启停、重新生成和删除能力，并限制邮箱只能由所属调用密钥访问。
- 参考 EmailTool 合并 OpenAI、Kiro、Cursor、Grok 项目专属验证码规则，收紧历史邮件时间窗口并过滤 HTML/CSS 噪声。
- 修复 CloudMail 邮件已经到达但验证码查询超时：兼容 `created_at`、`date`、`time`、`text_body`、`html_body`、`verification_code` 等部署字段，并允许新建唯一邮箱识别无时间邮件。
- 修复 OpenAI HTML 邮件多层表格排版产生大量空白，导致验证码超出规则上下文距离而无法识别的问题。
- 对齐 EmailTool 的完整提码链路：先校验项目邮件身份，再执行项目专属正则，失败后按项目验证码格式进行通用兜底；上游候选码也不得绕过邮件身份校验。

- 将服务升级为 Xiaoasi Mail Gateway 0.3.0，支持多个 CloudMail 实例及每实例多个邮箱域名，并彻底移除旧 Token Broker 对外能力。
- 新增统一邮箱 API，支持指定域名、域名范围和自动加权路由，调用方不再接触 CloudMail Token。
- 新增每实例独立 Token 缓存、401/403 比较刷新、失败切换、域名健康和冷却统计；并发鉴权失败只生成一次新 Token，避免再次互相覆盖。
- 新增幂等邮箱创建、随机邮箱地址、短期 `mailboxToken`、邮箱状态、释放和验证码提取接口。
- 新增 PostgreSQL 持久化、CloudMail 管理员密码加密、管理会话和请求审计。
- 新增 React + Ant Design 可视化管理端，覆盖概览、实例、域名、邮箱记录、请求日志和系统设置说明。
- CloudMail 实例抽屉新增所属邮箱域名列表，可在创建实例后直接添加、编辑和删除域名，并自动绑定当前实例。
- 邮箱域名页面改为独立加载实例与域名数据，单个接口失败时保留另一部分已加载内容和可操作入口。
- 管理会话鉴权热路径改为只读校验，避免并发读取产生不必要的数据库写入。
- 生产数据库由 SQLite 切换为服务器 PostgreSQL，引入 SQLAlchemy 连接池和 psycopg 驱动；Docker Compose 不创建数据库容器，也不再挂载本地数据库目录。
- Docker 改为 Node/Python 多阶段构建，通过 `DATABASE_URL` 连接服务器 PostgreSQL。
- 新增网关密钥生成和数据保留清理脚本，清理支持 dry-run 和 apply。
- 新增多实例、路由、管理 API、公开 API、应用集成和清理测试；浏览器完成桌面及移动端验收。
- 限制 `Idempotency-Key` 最大 256 字符，并回收使用完毕的进程内幂等锁，避免公开接口高基数 Key 长期占用内存。
- 新增管理端登录来源限流；修正 apply 模式下清理脚本实际删除数量统计。
- 新增 `docs/xiaoasi-mail-gateway-development-plan.md`，确定多 CloudMail 实例、多域名路由、统一邮箱 API、短期邮箱凭证、PostgreSQL 持久化和可视化管理端的完整升级方案。
- 删除旧 Token Broker 的 Token 外发接口、单实例环境变量、Client Key 鉴权代码及对应测试。
- 精简 `.env`、部署说明和接口文档，CloudMail 实例统一由管理端维护。
- 仓库迁移到 `https://github.com/xiaoasi-2023/cloudmail-token-broker`。
- 默认部署镜像改为 `registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker`。
- 发布流程收敛为“提交推送 GitHub → 阿里云自动构建 → 服务器拉取镜像”。
- 删除不需要的 GitHub Actions 阿里云登录和本地手工推送配置。
- 更新 README、部署手册、API 文档和发布说明。
