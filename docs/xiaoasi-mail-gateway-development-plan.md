# Xiaoasi Mail Gateway 多实例邮箱网关开发方案

## 1. 文档状态

- 状态：核心网关、用户中心、邮箱验证码注册、用户级调用密钥、用户级 POP 授权码、管理员全局 POP 授权码、积分扣费、管理端权限入口和最小只读 POP3 `110` 已完成本地实现与自测；真实 SMTP/CloudMail 环境验收、生产部署点验及调用方迁移仍待完成
- 制定日期：2026-08-10
- 当前仓库：`cloudmail-token-broker`
- 当前镜像：`registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker`
- 目标产品名称：`Xiaoasi Mail Gateway`
- 客户端 Provider 建议标识：`xiaoasi_gateway`

### 当前实施状态（2026-08-11）

| 工作项 | 状态 | 说明 |
| --- | --- | --- |
| 用户模型、用户会话、用户调用密钥、用户级 POP 授权码、积分模型 | 已完成（本地验收） | 用户模型、会话、用户级调用密钥、用户级 POP 授权码、管理员 POP 授权码和积分流水已接入；用户中心页面已完成 |
| 用户归属邮箱 API、积分预扣/确认/退款、幂等迁移 | 已完成（本地验收） | 创建邮箱已绑定 `owner_user_id`；按规则原子预扣，成功确认、失败退款；用户作用域幂等键不重复扣费；聚焦后端测试已通过 |
| POP3 `110` 监听、CloudMail `emailList` 转换 | 已完成（本地验收） | 已接入 FastAPI lifespan，默认监听容器内 `8110`；普通用户/管理员授权、邮箱归属校验、CloudMail `emailList` 和 RFC822 转换已实现；POP3 聚焦测试已通过 |
| 管理员全量邮箱访问、积分规则和审计 | 已完成（本地验收） | 管理员全局 POP 授权可通过 POP3 `110` 读取全部可查询邮箱；用户停用/授权码清除、积分调整/规则配置和管理 API 审计已接入；当前 HTTP 管理 API 只提供邮箱记录和请求日志查询，不宣称存在邮件内容、刷新、释放或邮箱 POP 开关子接口 |
| 旧全局 `client-keys` 清理 | 已完成（本地验收） | 已删除历史 `/admin-api/client-keys`、`gateway_client_keys` 表初始化及索引、`GatewayRepository` 旧方法和仅服务于旧接口的管理员测试；当前仅保留用户级 `user_api_keys` |
| 用户中心页面与前端构建兼容 | 已完成（本地验收） | 用户中心已接入用户密钥、POP 授权码、积分和邮箱记录；用户 POP 授权码取消手动输入与确认表单，改为按钮自动生成或重置；邮箱列表支持搜索、用途/邮箱状态/验证码状态筛选，并按用户归属展示和复制验证码；Vite 已降级到 4.5.5，兼容当前 Node 16.19.1 |
| 邮箱验证码自助注册 | 已完成（本地验收） | 参考 `chatgpt2img` 注册闭环实现 SMTP 发码、6 位验证码哈希存储、有效期、同邮箱发送冷却、输错失效、来源限流和用户端注册表单；注册只能创建普通用户，支持账号或邮箱登录；真实 SMTP 发信仍需生产点验 |
| 用户默认入口与注册页改版 | 已完成（待线上验收） | 根域名默认跳转 `/user/`，未登录显示登录/注册页；注册表单采用间距适中的单列布局，登录/注册切换入口位于提交按钮下方，并修复验证码请求未携带邮箱的问题 |
| 管理端页面与权限入口 | 已完成（本地验收） | 管理端已增加用户管理、积分/POP 设置，保留实例、域名、邮箱记录和请求日志页面；用户、邮箱和日志表格已改为紧凑布局，邮箱用途/来源和域名/实例单行展示，请求日志支持关键词/状态筛选并展示用户邮箱、用户名、调用密钥名称和用户 ID；管理员全局 POP 授权码按明文保存，支持手动输入、明文显隐、留空自动生成，并可随时查看、复制和修改当前值；用户级调用密钥仅在用户中心管理 |
| 容器 `110:8110` 映射和镜像端口声明 | 已完成（本地验收） | `docker-compose.yml`、`Dockerfile`、POP3 lifespan 和健康检查已接通；`/healthz` 暴露 `pop3Listening`，Compose 同时检查 HTTP 与容器内 `8110`；生产仍需按部署文档放行 `110/tcp` 并验证监听 |
| 文档状态与验收记录 | 已完成（文档与自测） | 四份对外/规划文档已与当前路由、静态入口、Docker 映射、邮箱验证码注册和 POP3 `110` 运行方式对齐；后端全量测试、注册 API 闭环和前端构建均通过；真实 SMTP 发信、CloudMail 验收及生产部署点验仍单独保留 |

本方案建设一个独立的完整邮箱网关。图片站、Kirox、Windows EXE 及其他调用方只对接 Xiaoasi Mail Gateway，不了解 CloudMail 的管理员凭据、Token、接口路径和响应结构。

截至 2026-08-10 已完成：服务器 PostgreSQL 持久化、多实例独立 Token、域名路由、幂等建箱、邮箱会话凭证、验证码查询、管理端登录、实例和域名管理、邮箱记录、请求日志、Docker 多阶段构建及数据保留清理脚本。本次规划调整为引入独立用户体系：普通用户拥有自己的登录账号、用户级调用密钥、用户级 POP 授权码和积分余额；唯一管理员拥有独立的全局 POP 授权码，可以读取全部未物理删除且上游仍存在的邮箱；邮箱记录归属用户，创建邮箱按配置扣除积分；同时提供单一 POP3 `110` 只读代理，通过 CloudMail HTTP `emailList` 获取邮件。由于历史调用密钥、邮箱记录和请求日志不要求兼容，首版允许执行一次性数据清理并按新模型重新初始化。当前核心代码、用户中心、旧全局 `client-keys` 清理、POP3 `110`、Docker 映射和文档核对已完成，剩余工作是使用真实 CloudMail 环境验收、图片站/Kirox Provider 迁移以及生产宝塔点验。

当前仓库名称和镜像名称继续保留，避免破坏 GitHub 到阿里云自动构建及宝塔部署链路；产品名称统一使用 Xiaoasi Mail Gateway。

## 2. 已确认的产品决策

1. 不设计 `region` 或地域路由能力，当前没有该业务需求。
2. 系统必须支持多个 CloudMail 实例。
3. 每个 CloudMail 实例可以配置多个邮箱域名。
4. 一个启用状态的邮箱域名只能绑定一个 CloudMail 实例。
5. 调用方可以不传域名、传一个指定域名，或者传一个域名候选范围。
6. 调用方不直接选择 CloudMail 实例，网关根据域名自动找到所属实例。
7. 完整邮箱地址由网关生成，调用方可以选择内置用户名规则并传入可选姓名基础值，但不能指定完整邮箱地址。
8. CloudMail 管理员邮箱、管理员密码、Token、邮箱密码和内部接口均不返回给调用方。
9. 系统只保留一个管理员账号和普通用户账号；管理员账号唯一，不开放新增第二个管理员，不引入复杂 RBAC。
10. 用户可以自行创建、长期查看完整值、重新生成和撤销自己的调用密钥；调用密钥通过 `X-API-Key` 使用，密钥归属用户而不是管理员或系统全局。
11. 每个用户拥有一个用户级 POP 授权码；该授权码按明文保存，用户可以在用户中心自动生成、重置、长期查看和复制，POP 登录时用于访问该用户自己的邮箱。
12. 创建邮箱后由网关返回短期、单邮箱范围的 `mailboxToken`，后续 HTTP 查询仍需同时满足用户归属和邮箱 Token 校验。
13. 用户拥有积分余额；创建一个邮箱按照管理端配置的扣费规则扣除积分，同一个幂等请求不得重复扣费，创建失败必须退回预扣积分。
14. 必须提供独立、受鉴权保护的管理端和用户中心；用户登录后只能管理自己的调用密钥、用户级 POP 授权码、积分余额和邮箱记录。
15. 唯一管理员可以管理全部用户、CloudMail 实例、域名、积分规则和积分流水；可以通过管理 API 查看全部邮箱记录和请求日志，并通过管理员全局 POP 授权码在 POP3 `110` 读取全部可查询邮箱内容。
16. 网关不提供 CloudMail Token 外发接口，调用方只能使用统一邮箱业务接口。
17. 本期只提供单一 POP3 `110` 只读代理，不实现完整邮件服务器能力；不开放 POP3S `995`。
18. 不新增独立的“创建用户邮箱”接口，继续使用 `POST /v1/mailboxes`；创建成功时返回邮箱地址、`mailboxToken` 和过期时间，不再为每个邮箱单独生成 POP 授权码。
19. POP 客户端通过固定的 POP 主机和 `110` 端口连接网关，不提交 POP 主机和端口 JSON 参数。
20. 网关收到 `USER`、`PASS` 后，根据邮箱归属用户校验该用户的 POP 授权码，再调用 CloudMail HTTP `emailList`，不暴露 CloudMail Token、管理员凭据或 Provider 内部密码。
21. 用户注册能力预留但默认关闭；未来开放注册时沿用同一用户、密钥、积分和权限模型。
22. 唯一管理员拥有独立的管理员 POP 授权码；管理员使用该授权码和任意邮箱地址登录 POP3 后，可以读取全部未物理删除且上游仍存在的邮箱，不受普通用户归属、用户 POP 开关、邮箱过期状态限制。
23. 管理员 POP 授权码与管理员登录密码、普通用户 `userAuthCode` 完全分离；两类 POP 授权码均按明文保存，但分别只通过管理员会话和对应普通用户会话回显。管理员强制清除普通用户授权码时只使旧值失效，由普通用户在用户中心点击按钮重新生成。

## 3. 建设目标

### 3.1 客户端目标

调用方只需要配置：

```json
{
  "type": "xiaoasi_gateway",
  "gateway_api_base": "https://cloudmail.xiaoasi.xyz",
  "pop_host": "pop-a.example.com",
  "pop_port": 110,
  "pop_tls": false
}
```

`110` 是为兼容现有调用方保留的普通 POP3 端口。首期只实现普通 `USER/PASS`，不开放 `995`，也不把 `STLS` 纳入首期验收。未来如开启 `STLS`，必须通过独立配置控制，不能把 `110` 误当作隐式 TLS 的 `995`。外部端口固定为 `110`，容器内部建议监听高端口 `8110`，通过 Docker 映射 `110:8110`，避免非 root 进程绑定特权端口。

调用方不再配置：

- CloudMail API 地址；
- CloudMail 管理员邮箱；
- CloudMail 管理员密码；
- CloudMail Token；
- CloudMail 邮箱内部密码；
- CloudMail `genToken`、`addUser`、`emailList` 等接口路径；
- CloudMail 业务响应码和刷新规则。

### 3.2 服务端目标

网关统一负责：

- 多 CloudMail 实例配置；
- 每实例独立 Token 缓存和刷新锁；
- 多域名维护和健康状态；
- 域名自动选择、指定选择和候选范围选择；
- 邮箱地址生成；
- 邮箱创建；
- 邮件轮询；
- 用户注册预留、用户登录和用户中心；
- 用户级调用密钥创建、撤销和归属校验；
- 用户级 POP 授权码设置和重置；
- 用户积分余额、扣费、退回和管理员调整；
- 单一 POP3 `110` 服务监听；
- POP3 邮箱授权、邮件列表和基础正文读取；
- CloudMail HTTP 邮件响应到简单 RFC822 邮件的转换；
- 历史邮件过滤；
- OpenAI、Grok 等验证码提取；
- 幂等请求；
- 短期邮箱访问凭证；
- 失败重试和域名冷却；
- 邮箱生命周期记录和后续清理；
- 运行日志、统计和管理端操作。

## 4. 非目标

第一阶段不包含：

- 地域或 `region` 路由；
- 调用方直接指定 CloudMail 实例；
- 调用方自行指定完整邮箱地址；
- 未经邮箱授权向调用方开放完整邮件正文；
- POP3S `995`、POP3 `STLS`、SMTP 发信、IMAP 服务和任意第三方邮箱协议代理；
- 邮件删除、附件下载和长期邮箱管理；
- 多容器副本和分布式锁；
- Redis、消息队列和多副本分布式协调；
- 多管理员角色、复杂 RBAC、组织和团队权限；
- 在线支付、充值、套餐、优惠券和自动续费；
- 将任意第三方邮箱 API 透传成通用代理接口。

## 5. 总体架构

```text
用户中心 / 管理端       HTTP 业务调用方       POP3 邮件客户端
       |                      |                    |
       | 用户登录             | X-API-Key         | POP 主机:110
       v                      v                    v
        Xiaoasi Mail Gateway（用户中心 + FastAPI + POP3 服务端）
          |       |       |       |             |
          |       |       |       +-- 积分、用户、调用密钥、权限 |
          |       |       +---------- 邮箱会话、POP 授权、归属校验 |
          |       +------------------ 管理端、运行日志和审计 |
          +-------------------------- Provider 适配层 <----------+
                                      |
                             CloudMail HTTP API
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
             CloudMail 实例 A            CloudMail 实例 B
               |      |                    |      |
             域名 A  域名 B              域名 C  域名 D
```

HTTP 业务客户端只认识 Xiaoasi Mail API 和用户自己的 `X-API-Key`；POP 客户端只认识 POP3 主机、`110` 端口、邮箱和用户级 POP 授权码。CloudMail 是网关内部的第一个 Provider 实现，未来新增其他邮箱服务时，不改变客户端主流程。

## 6. 核心数据关系

```text
User               1 ---- N UserApiKey
User               1 ---- N Mailbox
User               1 ---- N CreditTransaction
CloudMailInstance  1 ---- N MailDomain
CloudMailInstance  1 ---- N Mailbox
MailDomain         1 ---- N Mailbox
Mailbox            1 ---- N GatewayRequestLog
User               1 ---- N GatewayRequestLog
```

### 6.1 CloudMail 实例表 `cloudmail_instances`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | UUID/ULID | 实例唯一编号 |
| `name` | VARCHAR | 管理端显示名称，要求唯一 |
| `base_url` | VARCHAR | CloudMail API 地址，保存时去除末尾 `/` |
| `admin_email` | VARCHAR | CloudMail 管理员邮箱 |
| `admin_password_encrypted` | TEXT | 使用服务端数据密钥加密保存 |
| `proxy_url` | VARCHAR | 可选代理地址 |
| `verify_tls` | BOOLEAN | 是否验证 HTTPS 证书 |
| `request_timeout_seconds` | INTEGER | 上游请求超时 |
| `enabled` | BOOLEAN | 是否参与业务调用 |
| `health_status` | VARCHAR | `unknown`、`healthy`、`unhealthy`、`cooldown` |
| `consecutive_failures` | INTEGER | 连续失败次数 |
| `cooldown_until` | DATETIME | 实例冷却截止时间 |
| `last_checked_at` | DATETIME | 最近健康检测时间 |
| `last_success_at` | DATETIME | 最近成功请求时间 |
| `last_error_code` | VARCHAR | 脱敏错误码 |
| `last_error_message` | TEXT | 脱敏错误摘要 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 修改时间 |

管理员密码保存后不再返回前端。编辑时密码字段为空表示保持原密码，填写新值表示替换。

### 6.2 邮箱域名表 `mail_domains`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | UUID/ULID | 域名唯一编号 |
| `instance_id` | 外键 | 所属 CloudMail 实例 |
| `domain` | VARCHAR | 标准化后的邮箱域名，不包含 `@` |
| `enabled` | BOOLEAN | 是否允许创建邮箱 |
| `weight` | INTEGER | 自动选择权重，建议范围 1～100 |
| `health_status` | VARCHAR | `unknown`、`healthy`、`unhealthy`、`cooldown` |
| `consecutive_failures` | INTEGER | 连续失败次数 |
| `cooldown_until` | DATETIME | 域名冷却截止时间 |
| `success_count` | INTEGER | 创建成功累计数量 |
| `failure_count` | INTEGER | 创建失败累计数量 |
| `last_used_at` | DATETIME | 最近一次选中时间 |
| `last_success_at` | DATETIME | 最近一次成功创建时间 |
| `last_error_code` | VARCHAR | 最近脱敏错误码 |
| `remark` | VARCHAR | 管理备注 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 修改时间 |

约束：

- `domain` 标准化为小写并移除开头的 `@`；
- 同一域名不能同时绑定多个启用实例；
- 禁用实例时，其全部域名自动停止参与路由，但不强制修改域名自身的 `enabled`；
- 删除仍存在邮箱记录的实例或域名时采用软删除或拒绝删除，不能破坏历史关联。

### 6.3 邮箱记录表 `mailboxes`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | UUID/ULID | 对外 `mailboxId` |
| `owner_user_id` | 外键 | 邮箱所属用户，所有业务和 POP 访问必须校验归属 |
| `instance_id` | 外键 | 实际使用的 CloudMail 实例 |
| `domain_id` | 外键 | 实际使用的邮箱域名 |
| `address` | VARCHAR | 标准化后的完整邮箱地址，必须建立唯一约束 |
| `purpose` | VARCHAR | `openai`、`grok`、`generic` 等用途 |
| `source` | VARCHAR | 由已认证用户调用密钥自动写入的调用来源名称 |
| `created_at` | DATETIME | 邮箱创建时间，也是历史邮件过滤基线 |
| `expires_at` | DATETIME | 网关邮箱会话过期时间 |
| `status` | VARCHAR | `creating`、`active`、`failed`、`expired`、`released` |
| `verification_status` | VARCHAR | `pending`、`received`、`timeout`、`failed` |
| `verification_code` | VARCHAR | 已识别验证码；管理员可查看全部，普通用户只能查看自己邮箱的验证码；不写入请求日志 |
| `last_polled_at` | DATETIME | 最近查询邮件时间 |
| `provider_reference` | VARCHAR | 内部 Provider 引用，不向客户端返回 |
| `error_code` | VARCHAR | 最近脱敏错误码 |
| `error_message` | TEXT | 最近脱敏错误摘要 |
| `pop_enabled` | BOOLEAN | 是否允许该邮箱通过 POP3 登录 |
| `last_mail_query_at` | DATETIME | 最近一次完整邮件查询时间 |

POP 授权码不再按邮箱保存，而是优先校验邮箱所属用户的 `user_auth_code` 明文；升级前遗留的 `user_auth_code_hash` 仅用于兼容验证，用户重新生成后清空。同一用户的所有有效邮箱共用该用户级授权码；用户重置授权码后，旧授权码立即对该用户的全部邮箱失效。CloudMail 内部邮箱密码仍由网关生成，不返回调用方，也不写入普通日志。

邮箱地址必须在网关数据库中全局唯一；创建时即使 CloudMail 返回地址冲突，也不能把已有邮箱当作创建成功，必须重新生成地址并重试，直到成功或达到重试上限。

### 6.4 用户表 `users`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | UUID/ULID | 用户唯一编号 |
| `username` | VARCHAR | 登录名，要求唯一 |
| `email` | VARCHAR | 可选邮箱，启用注册时建议要求唯一 |
| `password_hash` | TEXT | 用户中心登录密码哈希 |
| `role` | VARCHAR | 仅 `admin`、`user` 两种角色；全库只允许一个 `admin` |
| `status` | VARCHAR | `active`、`disabled` |
| `user_auth_code` | TEXT | 用户级 POP 授权码明文，仅允许对应普通用户会话查询 |
| `user_auth_code_hash` | TEXT | 旧版兼容字段；用户重新生成明文后清空 |
| `user_auth_code_updated_at` | DATETIME | 最近一次设置或重置授权码时间 |
| `admin_pop_auth_code` | TEXT | 仅唯一 `admin` 用户使用的全局 POP 授权码明文；普通用户必须为空 |
| `admin_pop_auth_code_hash` | TEXT | 旧版兼容字段；管理员重新保存明文后清空 |
| `admin_pop_auth_code_updated_at` | DATETIME | 管理员全局 POP 授权码最近更新时间 |
| `pop_enabled` | BOOLEAN | 用户是否允许通过 POP3 读取自己的邮箱 |
| `pop_failed_attempts` | INTEGER | 用户级连续 POP 登录失败次数 |
| `pop_locked_until` | DATETIME | 用户级 POP 临时锁定截止时间 |
| `last_pop_login_at` | DATETIME | 最近一次 POP 登录时间 |
| `credit_balance` | BIGINT | 当前可用积分，只允许通过积分流水变更 |
| `created_at` | DATETIME | 用户创建时间 |
| `updated_at` | DATETIME | 用户更新时间 |

用户登录密码、普通用户 POP 授权码和管理员全局 POP 授权码是三套独立凭证。唯一管理员可以启用或停用普通用户的 POP 能力，也可以强制清除普通用户授权码，使其旧授权码立即失效；管理员用户列表不回显普通用户授权码，普通用户通过自己的会话长期查看和复制当前值。管理员自己的全局 POP 授权码按明文保存，可在管理端随时查看、复制和修改。普通用户不能把自己的角色修改为 `admin`，普通用户记录的 `admin_pop_auth_code` 必须为空。

### 6.5 用户调用密钥表 `user_api_keys`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | UUID/ULID | 调用密钥编号 |
| `user_id` | 外键 | 密钥所属用户 |
| `name` | VARCHAR | 用户自定义名称 |
| `key_prefix` | VARCHAR | 用于列表展示的前缀 |
| `key_hash` | TEXT | 调用密钥哈希，用于接口认证 |
| `api_key` | TEXT | 调用密钥明文，仅允许所属用户会话查询 |
| `enabled` | BOOLEAN | 是否可用 |
| `last_used_at` | DATETIME | 最近使用时间 |
| `created_at` | DATETIME | 创建时间 |
| `revoked_at` | DATETIME | 撤销时间 |

完整调用密钥在创建后按明文保存，所属用户可以长期查看、复制、重新生成或撤销，但不能查看其他用户密钥；旧版仅有哈希的密钥无法反推，重新生成后旧值立即失效并保存新明文。首版不设计密钥级复杂 scopes，所有用户密钥都只能访问该用户自己的业务资源。

### 6.6 用户会话表 `user_sessions`

用户中心和管理端统一使用 HttpOnly、Secure、SameSite Cookie 会话；数据库只保存会话哈希、用户 ID、角色、创建时间、过期时间和最近访问时间。退出登录或重置密码时可以撤销该用户全部会话。

### 6.7 积分规则表 `credit_rules`

第一版只配置一个全局邮箱创建扣费规则：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `operation` | VARCHAR | 固定为 `create_mailbox` |
| `cost_points` | BIGINT | 创建一个邮箱扣除的积分，必须大于等于 0 |
| `initial_user_points` | BIGINT | 新用户默认积分 |
| `updated_by` | 外键 | 最近修改规则的管理员 |
| `updated_at` | DATETIME | 修改时间 |

后续若需要按 `purpose` 或域名配置不同价格，再将规则扩展为多行，不在首版引入套餐和支付系统。

### 6.8 积分流水表 `credit_transactions`

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | UUID/ULID | 流水编号 |
| `user_id` | 外键 | 用户 |
| `type` | VARCHAR | `consume`、`refund`、`admin_adjust` |
| `status` | VARCHAR | `pending`、`completed`、`reversed` |
| `amount` | BIGINT | 正数增加、负数扣减 |
| `balance_after` | BIGINT | 变更后的余额 |
| `reference_type` | VARCHAR | `mailbox`、`idempotency`、`admin` |
| `reference_id` | VARCHAR | 关联邮箱、幂等键或管理员操作编号 |
| `remark` | VARCHAR | 脱敏说明 |
| `created_at` | DATETIME | 流水时间 |

创建邮箱时写入一笔 `type=consume,status=pending,amount=-cost_points` 的积分扣款记录，这一笔记录就是预扣。CloudMail 创建成功后将其更新为 `completed`；明确失败时将其更新为 `reversed`，并写入一笔关联的 `refund` 正向流水。仅发生网络超时而无法确认上游结果时，保留 `pending`，由重试任务或管理员人工确认，不能先退款再盲目重建，避免出现邮箱已创建但积分重复返还。管理员手工调整必须写明原因并进入审计日志。

### 6.9 幂等记录表 `idempotency_records`

| 字段 | 说明 |
| --- | --- |
| `idempotency_key` | 调用方提供的唯一请求标识 |
| `user_id` | 发起请求的用户；幂等键只在用户范围内生效 |
| `request_fingerprint` | 规范化请求参数摘要 |
| `mailbox_id` | 已创建的邮箱记录 |
| `status` | `processing`、`completed`、`failed` |
| `expires_at` | 幂等记录过期时间 |

数据库必须建立 `(user_id, idempotency_key)` 唯一约束，并以该组合键作为幂等查找条件；不能只依赖应用层查询后再插入。

同一个 `Idempotency-Key`：

- 参数相同且已成功：返回原邮箱；
- 参数不同：返回 `IDEMPOTENCY_CONFLICT`；
- 正在处理中：返回处理中状态或等待已有任务；
- 失败且符合重试条件：按明确规则允许重试，不重复创建未知邮箱。

### 6.10 请求日志表 `gateway_request_logs`

记录：

- 请求时间；
- 接口和方法；
- 来源 IP 的脱敏值；
- 来源提示；
- `user_id`；
- `mailbox_id`；
- 实例和域名；
- HTTP 状态；
- 业务错误码；
- 请求耗时；
- 是否发生上游重试。

严禁记录：

- CloudMail 管理员密码；
- CloudMail 完整 Token；
- `mailboxToken`；
- 邮箱内部密码；
- 完整邮件正文；
- 验证码明文。

### 6.11 管理员审计日志表 `admin_audit_logs`

管理员创建用户、调整积分、设置或重置授权码、实例和域名管理等 HTTP 管理操作必须写入审计日志。POP3 邮件读取通过独立 TCP 会话完成，当前不额外承诺 POP3 会话审计。至少记录：

- 操作管理员用户 ID；
- 操作类型；
- 目标用户 ID、邮箱 ID 或规则 ID；
- 来源 IP 和请求 ID；
- 操作前后关键状态摘要；
- 创建时间。

审计日志不得记录登录密码、用户授权码、管理员 POP 授权码、调用密钥、邮箱内部密码、完整邮件正文或 CloudMail Token。

### 6.12 POP3 运行配置

本期只运行一个 POP3 监听器，不新增 POP 节点数据表，也不做管理端节点 CRUD。当前实现实际读取的运行配置通过环境变量维护：

```dotenv
POP3_ENABLED=true
POP3_BIND_HOST=0.0.0.0
POP3_PORT=8110
POP3_MAX_CONNECTIONS=100
POP3_MAX_AUTH_FAILURES=3
POP3_MAX_MESSAGES=20
```

外部端口不由应用环境变量控制，而由 Docker/宿主机映射为 `110:8110`。`POP3_PUBLIC_PORT`、`POP3_STLS_ENABLED`、`POP3_TLS_CERT_FILE` 和 `POP3_TLS_KEY_FILE` 当前不是生效配置；本期不提供 STLS/POP3S `995`。

公网通过 Docker 或宿主机端口映射提供 `110 -> 8110`，客户端始终使用 `110`，应用进程监听 `8110`。邮箱创建时根据域名路由选择 CloudMail 实例，并将最终的 `instance_id` 持久写入邮箱记录；POP 登录和邮件查询只使用邮箱记录中的 `instance_id`，不根据客户端提交的主机、端口或后续变更的域名动态选择上游地址。

## 7. 域名路由规则

创建邮箱请求只允许以下三种域名模式。

### 7.1 指定单域名

```json
{
  "purpose": "openai",
  "domain": "mail-a.example.com",
  "addressPattern": "name_digits_4",
  "name": "kirox"
}
```

处理规则：

1. 查找域名记录及所属实例；
2. 校验域名和实例均启用；
3. 校验实例及域名未处于冷却；
4. 只使用该域名创建；
5. 创建失败时返回明确错误，不自动切换其他域名。

### 7.2 指定域名范围

```json
{
  "purpose": "openai",
  "domains": [
    "mail-a.example.com",
    "mail-c.example.com",
    "mail-e.example.com"
  ],
  "addressPattern": "name_digits_4",
  "name": "image2api"
}
```

候选域名可以属于不同 CloudMail 实例。处理规则：

1. 标准化并去重；
2. 验证域名均存在于网关允许列表；
3. 过滤禁用、异常和冷却中的实例及域名；
4. 对剩余域名按权重随机排序；
5. 失败时尝试下一个候选域名；
6. 达到最大尝试次数或候选耗尽后返回统一失败结果。

### 7.3 未指定域名

```json
{
  "purpose": "openai",
  "addressPattern": "name_digits_4",
  "name": "image2api"
}
```

网关从全部启用且健康的域名池中按权重随机选择。失败后可以切换其他域名和其他 CloudMail 实例。

### 7.4 参数冲突

`domain` 和 `domains` 不能同时提供，否则返回：

```json
{
  "code": "DOMAIN_SELECTOR_CONFLICT",
  "message": "domain 和 domains 只能选择一种"
}
```

### 7.5 加权随机与失败冷却

第一阶段按域名记录的 `weight` 进行加权随机。选择前必须过滤：

- 域名未启用；
- 所属实例未启用；
- 实例不健康或正在冷却；
- 域名不健康或正在冷却。

建议默认规则：

```text
连续创建失败 3 次
    → 域名进入 5 分钟冷却

实例连续上游失败 3 次
    → 实例进入 5 分钟冷却

冷却结束
    → 健康检测成功后恢复
```

业务失败和网络失败应区分统计。邮箱地址重复可以重新生成地址后在同一域名重试，不应立即判定整个实例故障。

## 8. 邮箱地址生成规则

### 8.1 默认行为

调用方不传完整地址，网关生成完整邮箱：

```text
<清洗后的姓名基础值><规则生成的随机后缀>@<选中域名>
```

示例：

```text
image2api4821@mail-a.example.com
```

### 8.2 用户名生成规则

调用方可以传 `addressPattern` 和 `name`。`addressPattern` 默认是 `name_digits_4`，即“姓名基础值 + 4 位数字”。没有提供 `name` 时，网关使用 Faker `en_US` 人名数据生成类似 `DanielCarter2153` 的邮箱用户名；内置姓名池只作为异常兜底。当前规则包括：

- `name_digits_4`；
- `name_digits_6`；
- `name_random_6`；
- `random_12`；
- `legacy_prefix_random`。

`prefix` 仅作为旧客户端兼容字段。网关必须：

- 转为小写；
- 只保留字母和数字；
- 限制最大长度；
- 拒绝或替换 `admin`、`root`、`support` 等保留名称；
- 除纯随机规则外始终追加随机部分，不能把姓名基础值直接作为完整本地部分；
- 地址已存在时重新生成，不能把已有邮箱当作本次创建成功。

### 8.3 不开放完整地址生成

第一阶段不接受调用方传入 `email` 或完整 `localPart`，避免：

- 地址冲突；
- 非法字符；
- 越权使用未授权域名；
- 枚举系统和管理员地址；
- 不同 Provider 规则泄漏到客户端；
- 网络重试产生不一致状态。

确有固定地址业务时，后续单独设计受权限控制的管理接口，不并入普通创建接口。

## 9. 对外业务 API

### 9.1 用户中心接口

用户中心使用独立的登录会话，不使用 `X-API-Key` 登录。首版只开放以下用户能力：

```http
POST /user-api/auth/login
GET  /user-api/auth/registration-config
POST /user-api/auth/register-code
POST /user-api/auth/register
POST /user-api/auth/logout
PUT  /user-api/auth/password
POST /user-api/auth/sessions/revoke-all
GET  /user-api/me
GET  /user-api/api-keys
POST /user-api/api-keys
DELETE /user-api/api-keys/{keyId}
PUT  /user-api/auth-code
GET  /user-api/credits
GET  /user-api/mailboxes
```

用户邮箱验证码注册已通过 `POST /user-api/auth/register-code` 和 `POST /user-api/auth/register` 落地，仅在 `USER_REGISTRATION_ENABLED=true` 且 SMTP 配置完整时开放；关闭时返回统一的 `USER_REGISTRATION_DISABLED`。验证码明文只进入邮件，不写入数据库或日志；数据库保存基于服务端密钥的 HMAC 哈希，默认 10 分钟有效、同邮箱 60 秒发送冷却、连续输错 5 次失效。任何注册请求都只能创建普通用户，并按积分规则初始化余额。

用户登录后只能：

- 创建、长期查看完整值、重新生成和撤销自己的调用密钥；
- 点击按钮自动生成或重置自己的用户级 POP 授权码；
- 查看自己的积分余额；
- 搜索和筛选自己创建的邮箱记录，并查看或复制已识别验证码。

用户不能查看或修改 CloudMail 实例、域名、其他用户、系统积分规则、请求日志和管理员配置。

用户级 POP 授权码由用户中心使用浏览器安全随机数自动生成，用户不手动输入或重复确认；完整值按明文保存，用户之后登录仍可查看和复制。用户中心同时从服务端自动读取 `POP3_PUBLIC_HOST`、固定端口 `110` 和当前用户可用邮箱地址，直接组成客户端连接参数。

### 9.2 创建邮箱

```http
POST /v1/mailboxes
Content-Type: application/json
Idempotency-Key: register-task-123-attempt-1
X-API-Key: <user-api-key>
```

请求：

```json
{
  "purpose": "openai",
  "domain": "",
  "domains": [],
  "addressPattern": "name_digits_4",
  "name": "image2api"
}
```

响应：

```json
{
  "code": 200,
  "data": {
    "mailboxId": "mbx_01k2example",
    "address": "image2api4821@mail-a.example.com",
    "domain": "mail-a.example.com",
    "mailboxToken": "短期单邮箱访问凭证",
    "createdAt": "2026-08-10T08:00:00Z",
    "expiresAt": "2026-08-10T08:30:00Z",
    "remainingCredits": 99
  }
}
```

响应不返回 CloudMail 实例名称或 Provider 类型，调用方无需感知内部路由。

创建请求通过用户自己的 `X-API-Key` 认证，网关自动将新邮箱写入该用户的 `owner_user_id`，调用方不能提交或修改邮箱归属。首期创建邮箱前必须已经设置用户级 POP 授权码；HTTP-only 用户不在首期支持范围内。

创建成功时按照 `credit_rules` 中 `operation='create_mailbox'` 的 `cost_points` 扣除积分。相同用户使用相同幂等键重试时返回原邮箱和原扣费结果，不重复创建、不重复扣费；不同用户使用相同幂等键时互不影响。

扣费流程采用“预扣—上游创建—确认/退款”：先在数据库事务中锁定用户余额并写入 `pending` 预扣，CloudMail `addUser` 成功后转为 `completed`，明确失败才写入退款流水；网络超时进入可重试的 `pending` 状态。余额不足返回 `INSUFFICIENT_CREDITS`，不调用 CloudMail。

### 9.3 最小 POP3 取信

客户端直接连接网关的固定 POP3 地址和 `110` 端口：

```text
服务器：pop.example.com
端口：110
安全性：普通 POP3；如启用 `STLS`，由客户端主动升级 TLS
用户名：创建邮箱后返回的 address
密码：该邮箱所属用户自动生成的 userAuthCode
```

首期普通 `110` 连接中的邮箱和授权码不经过 TLS 加密，部署时必须在防火墙、访问来源和网络边界上限制暴露范围；如果调用方环境要求加密，需等后续 `STLS` 或独立 TLS 入口完成后再启用。

网关只实现取信所需的最小命令：

| 命令 | 用途 |
| --- | --- |
| `CAPA` | 返回客户端兼容能力 |
| `USER` | 接收邮箱地址 |
| `PASS` | 校验邮箱授权码 |
| `STAT` | 获取邮件数量和总大小 |
| `LIST` | 获取邮件列表和大小 |
| `UIDL` | 返回会话邮件的稳定唯一标识 |
| `RETR` | 获取单封邮件 |
| `TOP` | 获取邮件头部和指定数量正文行 |
| `NOOP` | 保持连接 |
| `RSET` | 重置当前会话删除标记；首期无删除标记 |
| `STLS` | 后续扩展命令，首期不实现 |
| `QUIT` | 关闭连接 |

处理流程：

```text
POP3 客户端连接 110
    → USER 邮箱
    → PASS 授权码
    → 网关查询邮箱记录，校验 owner_user_id 和用户级授权码
    → 使用邮箱记录中固定的 instance_id 找到 CloudMail 实例
    → 调用 CloudMail /api/public/emailList
    → 将 content/text 转为简单 RFC822 邮件
    → 按生成后的 RFC822 字节数返回 STAT/LIST 大小
    → 对多行正文执行 CRLF 规范化和 dot-stuffing
    → 返回 STAT/LIST/UIDL/RETR/TOP 结果
```

第一版明确限制：

- 只支持 POP3 `110`，不提供 POP3S `995`；首期只实现普通 `USER`/`PASS`，`STLS` 留作后续扩展；
- 只读，不支持 `DELE`；
- 不处理附件；
- 每次连接最多读取 `POP3_MAX_MESSAGES` 封邮件；
- POP 会话中的邮件编号使用 `1..N`，网关内部再映射到 CloudMail 的 `emailId`；
- `UIDL` 返回稳定的 CloudMail `emailId`，不把上游 ID 直接当作 POP 邮件编号；
- 如果上游没有稳定的 `emailId`，必须使用邮件关键字段生成确定性 UIDL，不能每次查询随机生成；
- 邮件内容使用 CloudMail 的 `content` 或 `text` 合成简单 RFC822 内容，至少包含 `From`、`To`、`Subject`、`Date`、`Message-ID` 和 `Content-Type` 头；
- `TOP` 只返回合成邮件的头部和指定数量正文行；`CAPA`、`NOOP`、`RSET` 用于兼容常见客户端；
- `DELE` 明确返回只读错误，客户端必须配置为“保留服务器上的邮件”；
- 不把用户级 POP 授权码转发给 CloudMail；
- 用户重置授权码后，该用户的全部有效邮箱立即使用新授权码；
- 用户被停用或 `pop_enabled=false` 时，该用户的全部邮箱不能通过 POP 登录。

管理员全局 POP 访问规则：

- 唯一管理员在管理端设置 `admin_pop_auth_code`，数据库直接保存明文，管理端可随时读取、显示和复制；
- POP 客户端使用任意未物理删除的邮箱地址作为 `USER`，使用管理员 POP 授权码作为 `PASS`；
- 管理员授权码可以读取全部未物理删除且 CloudMail 上游仍存在的邮箱，包括普通用户已停用、用户 POP 已关闭、邮箱已过期或已释放的邮箱；
- 管理员授权码不受 `owner_user_id`、用户 `pop_enabled`、邮箱 `pop_enabled` 和邮箱会话过期时间限制，但邮箱记录被物理清理或上游账号已不存在时仍不能读取；
- 管理员 POP 登录、`STAT`、`LIST`、`UIDL`、`RETR` 都必须写入审计日志；日志只记录管理员用户、邮箱 ID、命令类型、耗时和结果，不记录授权码或完整邮件正文；
- 普通用户和管理员授权码使用各自独立的明文字段并按不同会话权限回显，两者不能混用；管理员不能使用登录密码代替 POP 授权码。

### 9.4 查询验证码

```http
POST /v1/mailboxes/{mailboxId}/verification-code
Authorization: Mailbox <mailboxToken>
X-API-Key: <user-api-key>
Content-Type: application/json
```

请求：

```json
{
  "purpose": "openai",
  "waitSeconds": 20
}
```

收到验证码：

```json
{
  "code": 200,
  "data": {
    "status": "received",
    "verificationCode": "123456"
  }
}
```

暂未收到：

```json
{
  "code": 200,
  "data": {
    "status": "pending",
    "verificationCode": ""
  }
}
```

建议单次等待最多 20～30 秒，避免宝塔、Nginx 或 CDN 长连接超时。调用方可以每 3～5 秒再次请求。

### 9.5 查询邮箱状态

```http
GET /v1/mailboxes/{mailboxId}
Authorization: Mailbox <mailboxToken>
X-API-Key: <user-api-key>
```

只返回邮箱地址、状态、创建时间、过期时间和验证码状态，不返回内部实例、管理员凭据或邮件正文。

### 9.6 释放邮箱

```http
DELETE /v1/mailboxes/{mailboxId}
Authorization: Mailbox <mailboxToken>
X-API-Key: <user-api-key>
```

第一阶段至少将网关记录标记为已释放。若 CloudMail 支持安全删除邮箱，再由 Provider 执行真实删除；不确定支持能力前不得假设存在删除 API。

## 10. 邮箱访问凭证

HTTP 业务调用方必须配置用户自己创建的 `X-API-Key`；创建邮箱后还必须使用该邮箱自己的 `mailboxToken`。网关从调用密钥解析 `user_id`，并同时校验邮箱的 `owner_user_id`，防止用户 A 的调用密钥访问用户 B 的邮箱。POP3 客户端不携带 `X-API-Key`，使用邮箱地址和该邮箱所属用户的 `userAuthCode` 登录 POP 服务。

`mailboxToken` 应满足：

- 只能访问一个 `mailboxId`；
- 带过期时间；
- 无法被调用方伪造；
- 不包含管理员密码、CloudMail Token 或邮箱内部密码；
- 日志不得打印完整值。

第一阶段可使用服务端签名的无状态凭证，配置：

```dotenv
MAILBOX_SESSION_SECRET=<高强度随机密钥>
MAILBOX_SESSION_TTL_SECONDS=1800
```

这两项只配置在网关服务器，不提供给图片站、Kirox 或 EXE。

### 10.1 凭证分工

各类凭证分工如下：

| 凭证 | 使用场景 | 生命周期 | 保存方式 |
| --- | --- | --- | --- |
| 用户登录会话 | 用户中心和管理端页面 | 短期 | 数据库保存会话哈希 |
| `X-API-Key` | 用户外部调用网关业务 API | 用户重新生成或撤销前有效 | 明文与认证哈希同时保存，仅向所属用户回显明文 |
| `mailboxToken` | 单个邮箱状态、验证码、释放接口 | 短期 | 网关签名，无状态校验 |
| `userAuthCode` | 该用户全部邮箱的 POP3 登录密码 | 用户重置前有效 | 明文保存，仅向对应用户会话回显 |
| `adminPopAuthCode` | 唯一管理员读取全部邮箱的 POP3 登录密码 | 管理员重置前有效 | 明文保存，仅向管理员会话回显 |
| CloudMail Token | 网关调用上游 HTTP | 网关内部缓存 | 仅内存缓存，不对外返回 |
| CloudMail 内部邮箱密码 | 网关创建上游邮箱 | 网关内部使用 | 不返回、不写普通日志 |

第一版规则：

- 用户登录密码、用户级 POP 授权码、调用密钥和 `mailboxToken` 不能互相替代；
- 用户级 POP 授权码由用户中心自动生成，并允许对应用户之后继续查看和复制；
- 管理员全局 POP 授权码由管理员设置或修改，并允许管理员随时查询当前明文；
- 日志、请求记录、异常消息和用户管理列表不得展示任何完整授权码或调用密钥；调用密钥和授权码只在所属用户或管理员的对应页面回显；
- 认证失败使用统一错误，不区分邮箱不存在、用户授权码错误或邮箱已释放；
- 按用户、邮箱和来源 IP 限制 POP 登录失败次数；
- 用户重置授权码后旧授权码立即失效，但不影响邮箱记录和积分余额；
- 管理员重置全局 POP 授权码后旧管理员授权码立即对全部邮箱失效；
- POP3 登录不把用户授权码转发给 CloudMail。

### 10.2 POP3 会话边界

每个 POP3 连接独立完成“授权 → 查询邮件 → 读取邮件 → 断开”。网关只在当前连接内保存邮箱和邮件列表，不创建额外的长期会话 Token。

## 11. Provider 适配层

统一接口建议：

```python
class MailProvider:
    async def test_connection(self) -> ProviderHealth: ...
    async def create_mailbox(self, request: CreateMailboxRequest) -> ProviderMailbox: ...
    async def list_messages(self, mailbox: ProviderMailbox, *, size: int = 20) -> list[MailMessage]: ...
    async def delete_mailbox(self, mailbox: ProviderMailbox) -> None: ...
```

第一期实现 `CloudMailProvider`：

```text
按 instance_id 获取实例配置
    → 获取该实例独立缓存 Token
    → POST /api/public/addUser
    → 保存邮箱创建时间
     → POST /api/public/emailList（`toEmail`、`type=0`、`isDel=0`、`num=1`、`size`）
     → 过滤创建时间之前的历史邮件
     → 统一转换 `emailId`、发件人、收件人、主题、正文和时间字段
     → 使用 `content` 或 `text` 生成简单邮件内容
     → 统一提取验证码
```

CloudMail Provider 只负责查询和字段转换，不实现附件、删除或完整原始 MIME。POP3 层根据 `MailMessage` 生成最小可读邮件。

每个 CloudMail 实例必须拥有独立的：

- Token 缓存；
- Token 版本；
- Token 过期时间；
- 刷新锁；
- 刷新次数；
- 401/403 单次刷新重试；
- 健康和错误状态。

不能使用一个全局 Token 覆盖所有实例。

## 12. 可视化管理端

### 12.1 路由划分

```text
/v1/*         对外邮箱业务 API
/admin-api/*  管理端后端 API
/admin/*      管理端前端页面
/user-api/*   用户中心后端 API
/user/*       用户中心前端页面
```

业务 API 必须携带用户自己的 `X-API-Key`；管理端和用户中心分别使用登录会话鉴权。

### 12.2 左侧菜单

```text
运行概览
用户管理
积分规则
CloudMail 实例
邮箱域名
邮箱记录
请求日志
系统设置
```

管理端按“实例 → 域名 → 邮箱 → 日志”分层，避免把多实例凭据、域名状态和业务记录堆在一个配置表单中。

用户中心只显示以下菜单：

```text
我的调用密钥
我的 POP 授权码
我的积分
我的邮箱
账号安全
```

用户中心不显示 CloudMail 实例配置、其他用户、请求日志和系统配置。用户邮箱列表展示地址、用途/来源、域名、状态、创建时间、过期时间和已识别验证码，支持按邮箱/域名/来源搜索，并按用途、邮箱状态、验证码状态筛选；用户授权码页面可以查看自己的完整授权码和自动加载的 POP3 连接参数，但不展示内部实例凭据、邮箱内部密码或完整邮件正文。

### 12.2.1 用户中心操作

- 调用密钥：创建、命名、长期查看和复制完整值、重新生成、撤销；
- POP 授权码：自动生成、重置、长期查看和复制当前值；管理员强制清除后，用户必须重新生成；
- 积分：查看当前余额和最近积分变更摘要，不允许用户自行增加积分；
- 邮箱：搜索和筛选自己的邮箱记录，查看状态、过期时间并复制已识别验证码；释放邮箱仍需经过邮箱 Token 或用户归属校验；
- 账号安全：修改登录密码、退出当前会话、撤销全部会话。

### 12.2.2 简单权限模型

| 角色 | 权限范围 |
| --- | --- |
| `admin` | 唯一管理员；管理用户、CloudMail 实例、域名、积分规则和积分调整；查看全部邮箱记录、请求日志，并通过全局 POP 授权码读取全部可查询邮箱 |
| `user` | 仅管理自己的调用密钥、用户级 POP 授权码、积分余额、邮箱记录和账号安全 |

普通用户资源查询必须在 SQL 条件中带上 `user_id`，不能只在前端隐藏菜单；管理员接口统一要求唯一账号且 `role=admin`。管理员查询全部邮箱时允许不加用户过滤；当前 HTTP 管理 API 只提供邮箱记录列表和请求日志查询，邮件正文通过 POP3 `110` + 管理员全局授权码读取。

管理员接口至少包含：

```http
GET   /admin-api/users
POST  /admin-api/users
PATCH /admin-api/users/{userId}
POST  /admin-api/users/{userId}/reset-auth-code
POST  /admin-api/users/{userId}/credits/adjust
GET   /admin-api/users/{userId}/credit-transactions
GET   /admin-api/credit-rules
PUT   /admin-api/credit-rules
PUT   /admin-api/pop-auth-code
GET   /admin-api/mailboxes
GET   /admin-api/request-logs
```

其中 `POST /admin-api/users/{userId}/reset-auth-code` 只清除旧授权码并使其立即失效，不返回新授权码明文；普通用户必须在用户中心重新生成授权码。

唯一管理员可以创建、停用和强制清除普通用户授权码，但不能创建第二个管理员，也不能查看用户登录密码、普通用户 POP 授权码或调用密钥明文；管理员自己的全局 POP 授权码可以手动输入并切换明文显隐，也可以将两个输入框留空后由前端安全随机生成，或先点击自动生成按钮预览再保存。授权码直接以明文保存，之后可以在管理端随时查看、复制和修改。积分调整必须记录调整前余额、调整后余额、变更数量和原因。管理员可以通过 HTTP 管理 API 查看全部邮箱记录、状态和脱敏错误，并通过全局 POP 授权码读取邮件内容。当前不提供管理员 HTTP 邮件内容、释放、禁用或重新查询子接口。

### 12.3 运行概览

顶部指标卡：

- 实例总数；
- 健康实例数；
- 可用域名数；
- 今日创建邮箱数；
- 今日验证码成功率；
- 最近一小时错误数。

主体区域：

- 各实例健康状态；
- 各域名使用比例；
- 最近创建趋势；
- 最近错误列表；
- 冷却中的实例和域名提醒。

必须覆盖的异常状态：

- 没有任何可用实例；
- 实例凭据失效；
- 实例连续请求失败；
- 域名全部禁用；
- 域名正在冷却；
- 创建成功但验证码查询失败。

### 12.4 CloudMail 实例页面

管理端列表采用紧凑行高和单行组合字段，减少常规桌面宽度下的横向滚动。列表字段：

- 名称；
- API 地址；
- 管理员邮箱；
- 域名数量；
- 启用状态；
- 健康状态；
- Token 是否已缓存；
- 最近检测时间；
- 最近脱敏错误；
- 操作。

操作：

- 新增；
- 编辑；
- 启用或停用；
- 测试连接；
- 强制刷新该实例 Token；
- 查看所属域名；
- 查看实例统计；
- 删除或归档。

测试连接只展示是否成功、业务状态和耗时，不返回完整 Token。

### 12.5 邮箱域名页面

列表字段：

- 域名；
- 所属实例；
- 启用状态；
- 健康状态；
- 权重；
- 成功次数；
- 失败次数；
- 最近使用时间；
- 冷却截止时间；
- 操作。

操作：

- 单个新增；
- 批量新增；
- 修改所属实例；
- 修改权重；
- 启用或停用；
- 批量操作；
- 清除连续失败计数；
- 解除冷却；
- 测试创建邮箱；
- 查看最近错误。

测试创建邮箱会真实创建账号，点击前必须明确提示影响，并将测试邮箱纳入邮箱记录。

### 12.6 邮箱记录页面

列表字段：

- 邮箱地址；
- 用途与来源提示，单行组合展示；
- 所属域名与所属实例，单行组合展示；
- 创建状态；
- 验证码明文或验证码状态；
- 创建时间；
- 过期时间。

操作：

- 查看邮箱记录和状态；
- 查看脱敏错误。

管理员邮箱列表可以查看和复制已识别验证码，但不展示邮箱密码、授权码、CloudMail Token 和完整邮件正文。

### 12.7 请求日志页面

当前支持按关键词和状态分组筛选：关键词可匹配接口、错误码、调用密钥名称、用户名或用户邮箱；状态分组包含成功、客户端错误和服务端错误。列表采用紧凑布局，时间保持单行展示：

- 请求时间；
- 方法和路径；
- 调用人邮箱和用户名；
- 调用密钥名称和用户 ID；
- 状态；
- 耗时；
- 脱敏错误。

### 12.8 系统设置页面

当前系统设置页面只展示真实运行约束，不提供无法持久化的假表单。邮箱会话有效期、创建和查询限流等部署级配置通过服务器环境变量维护；用户名生成规则由调用方在创建邮箱请求中选择。积分规则作为业务配置持久化在 `credit_rules`，由管理员在“积分规则”页面修改。

管理员可配置：

- 创建一个邮箱扣除的积分；
- 新用户默认积分；
- 是否允许新用户注册；
- 用户注册后的默认状态。

积分规则修改只影响后续创建请求，不追溯修改历史扣费流水。

敏感环境密钥不允许在普通设置页面查看或修改。未来需要在线修改部署参数时，应先增加独立持久化和审计能力，再开放相应表单。

## 13. 管理端鉴权和敏感配置

用户中心和管理端统一使用数据库用户模型，首版只保留 `admin` 与 `user` 两种角色。部署时通过环境变量引导创建第一个管理员账号：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=<安全密码哈希>
DATA_ENCRYPTION_KEY=<数据库敏感字段加密密钥>
MAILBOX_SESSION_SECRET=<邮箱会话签名密钥>
USER_REGISTRATION_ENABLED=true
USER_REGISTRATION_CODE_TTL_SECONDS=600
USER_REGISTRATION_CODE_COOLDOWN_SECONDS=60
USER_REGISTRATION_RATE_LIMIT_PER_MINUTE=10
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USERNAME=<发件邮箱>
SMTP_PASSWORD=<SMTP 授权码>
SMTP_FROM=<发件邮箱>
SMTP_TLS=true
POP3_PORT=8110
POP3_MAX_CONNECTIONS=100
POP3_MAX_AUTH_FAILURES=3
POP3_MAX_MESSAGES=20
```

`ADMIN_PASSWORD_HASH` 与旧部署兼容的 `ADMIN_PASSWORD` 二选一，生产优先使用密码哈希；初始化完成后不得在生产环境继续保留管理员明文密码配置。

规则：

- 用户登录密码只保存哈希；
- 用户级 POP 授权码按明文保存，仅允许对应用户会话查看；管理员用户列表不回显；
- 用户调用密钥同时保存明文和认证哈希，明文仅允许所属用户会话查询；
- 管理员全局 POP 授权码按产品要求直接保存明文，并只通过管理员鉴权接口回显；
- CloudMail 管理员密码使用 `DATA_ENCRYPTION_KEY` 加密入库；
- 管理端和用户中心 Session 使用 HttpOnly、Secure、SameSite Cookie；
- 管理 API 必须验证登录态和 `admin` 角色；
- 用户中心 API 必须验证登录态和当前用户 ID；
- 生产环境只能通过 HTTPS 访问；
- 可在宝塔或反向代理层额外限制管理端访问来源；
- 所有管理修改写入审计日志。

管理员全局 POP 授权码不使用环境变量注入，直接写入唯一 `admin` 用户记录的 `admin_pop_auth_code`；只有管理端登录后可以查询、设置或修改，POP 服务运行时使用恒定时间比较校验。旧版 `admin_pop_auth_code_hash` 仅用于管理员尚未重新保存时的过渡兼容。

用户注册由环境变量控制。开启后，用户先通过 SMTP 获取邮箱验证码，再提交账号、邮箱、密码和验证码；注册只能创建 `role=user`、`status=active` 的普通用户，并按 `credit_rules.initial_user_points` 初始化积分，不能创建或申请 `admin` 角色。当前已实现邮箱发送冷却、来源分钟限流、验证码有效期和输错失效；Turnstile、人机验证和人工审核可后续增加，不改变用户资源归属模型。

## 14. 数据库和部署

生产数据统一使用服务器现有 PostgreSQL，Docker Compose 不创建数据库容器：

```text
DATABASE_URL=postgresql://数据库用户:数据库密码@host.docker.internal:5432/数据库名
```

Compose 仅增加宿主机地址映射：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
ports:
  - "110:8110"  # 对外 POP3 110，容器内部监听 8110
```

生产环境还需要通过环境变量或 Docker Secret 提供：

```dotenv
POP3_ENABLED=true
POP3_BIND_HOST=0.0.0.0
POP3_PORT=8110
POP3_MAX_CONNECTIONS=100
POP3_MAX_AUTH_FAILURES=3
POP3_MAX_MESSAGES=20
```

`POP3_PORT=8110` 是容器内监听端口，公网 `110` 由 Compose 的 `110:8110` 映射提供。`POP3_PUBLIC_PORT`、`POP3_STLS_ENABLED`、`POP3_TLS_CERT_FILE` 和 `POP3_TLS_KEY_FILE` 当前不是生效配置；本期不提供 STLS/POP3S `995`。

当前容器继续使用 `read_only: true`，业务数据不写入容器文件系统。数据库结构在启动时自动初始化，且必须保证重复执行安全。

PostgreSQL 负责以下共享持久化数据：

- 用户账号、角色和用户会话；
- 用户调用密钥；
- 用户积分余额和积分流水；
- 积分扣费规则；
- CloudMail 实例配置；
- 域名配置；
- 邮箱记录；
- 幂等记录；
- 请求日志；
- 管理端操作。

### 14.1 一次性历史数据清理和新模型初始化

本次改版不要求兼容历史调用密钥、历史邮箱记录和历史请求日志，可以执行一次显式的数据清理和表结构重建。迁移不是每次启动自动执行，必须先停止业务容器、完成数据库备份，再通过独立迁移命令并带 `--apply` 参数确认。

清理范围：

- 清空旧的 `gateway_client_keys`；
- 清空 `mailboxes`、`idempotency_records` 和 `gateway_request_logs`；
- 清空旧的管理会话和旧审计记录，重新建立用户会话和审计链路；
- 删除或重建旧的 `mailboxes`、`idempotency_records`、`gateway_request_logs`、`admin_sessions`、`admin_audit_logs` 和 `gateway_client_keys` 表，不能只删除数据行；
- 创建全新的 `users`、`user_api_keys`、`user_sessions`、`credit_rules`、`credit_transactions` 和新审计表；
- 为 `mailboxes` 增加 `owner_user_id`、`pop_enabled` 等新字段，并建立用户、邮箱、幂等键和积分流水索引；
- 为 `users.role='admin'` 建立唯一约束，确保数据库中最多一个管理员；
- 按环境变量创建唯一的初始 `admin` 用户；如果数据库中已经存在管理员，启动时拒绝再次创建管理员；
- 初始化 `credit_rules`，写入创建邮箱扣费和新用户默认积分；
- 保留 `cloudmail_instances` 和 `mail_domains`，避免重复录入 CloudMail 配置；如需完全重置，可由管理员单独清理实例和域名。

本地清空邮箱记录不等于删除 CloudMail 上游邮箱。若 CloudMail 提供删除用户接口，应在清理前按实例执行上游清理；若不提供，则必须在迁移结果中明确旧上游邮箱仍然存在，并继续依靠地址冲突重试和后续人工清理，不能误报为已删除。

迁移完成后，旧的 `X-API-Key`、旧 `mailboxToken`、旧邮箱记录和旧幂等键全部失效；新用户必须重新创建调用密钥、设置用户级 POP 授权码；管理员还必须设置新的全局 POP 授权码。迁移命令必须输出删除表、保留表、初始化用户、积分规则和失败回滚提示。

数据库已具备并发访问能力。未来需要运行多个网关副本时，还需要将 Token 缓存锁和限流迁移到 Redis 或 PostgreSQL 协调层；当前仍明确只运行一个容器副本。

## 15. 管理端技术方案

推荐：

- 后端：现有 FastAPI；
- POP3 服务：独立的 asyncio TCP 监听器，与 FastAPI HTTP 监听端口分离；如启用 `STLS`，再配置 TLS 证书；
- 管理端：React + TypeScript + Ant Design；
- 构建：Docker 多阶段构建前端静态资源；
- 部署：FastAPI 同域提供 `/admin/`、`/user/` 静态页面和 `/admin-api`；
- 数据：服务器 PostgreSQL + SQLAlchemy 连接池；
- 样式：信息密度适中的桌面管理台，优先表格、状态标签、抽屉表单和明确反馈。

同域部署可以避免单独处理跨域、第二个容器和两套发布流程。POP3 监听器可以与 FastAPI 在同一容器内运行，但必须使用独立 TCP 端口和独立连接生命周期；不能让 Uvicorn HTTP 路由冒充 POP3 服务。管理端不增加 POP 节点页面，POP3 只通过服务器配置启动。

单容器首版采用单 Uvicorn worker：应用 lifespan 启动时创建 asyncio POP3 server，监听容器内 `8110`；应用停止或重载时先停止接收新连接，再等待现有连接释放。Dockerfile 必须声明 `EXPOSE 8110`，Compose 必须映射 `110:8110`。当前 Compose 健康检查同时验证 HTTP `/healthz` 的 `pop3Listening` 状态和容器内 `8110` TCP 连接；不得通过普通 HTTP 反向代理转发 POP3，也不得启动多个会争抢 `8110` 的 worker。

## 16. 调用方接入与边界

### 16.1 新项目边界

Xiaoasi Mail Gateway 是独立新项目，只提供统一邮箱业务接口和管理接口，不提供 CloudMail Token 外发能力。CloudMail Token、管理员账号、管理员密码和上游接口路径只存在于网关内部。

### 16.2 图片站迁移

新增 Provider：

```text
xiaoasi_gateway
```

配置只保留：

- 网关地址；
- 可选指定域名或域名候选列表；
- 可选用户名生成规则和姓名基础值；
- 创建超时；
- 验证码轮询参数。

POP3 调用方额外使用：

- 已创建邮箱的 `address`；
- 该邮箱所属用户自动生成的 `userAuthCode`；
- 固定的 POP3 主机、110 端口；
- 标准邮件客户端的 POP3 连接能力，不直接调用 CloudMail `emailList`。

删除 CloudMail 管理员邮箱、管理员密码、Token 获取和直接 `addUser`、`emailList` 调用。

### 16.3 Kirox 接入

增加对应网关 Provider，调用统一创建邮箱和查询验证码接口，删除直接获取 CloudMail Token 以及直接调用 CloudMail 的实现。

### 16.4 其他调用方

Windows EXE 和其他项目只保存网关地址、域名选择参数、`mailboxId` 与短期 `mailboxToken`，不得保存 CloudMail 管理凭据或请求 CloudMail Token。

### 16.5 POP3 调用方

POP3 调用方不调用网关 HTTP 邮件查询接口，而是按标准邮件客户端方式连接固定的 POP3 主机和 110 端口：

1. 使用用户自己的 `X-API-Key` 调用 `POST /v1/mailboxes` 创建邮箱；
2. 在用户中心自动生成并安全保存用户级 `userAuthCode`；
3. 保存响应中的 `address` 和 `mailboxToken`；
4. 在邮件客户端中配置固定的 POP3 主机、110 端口、邮箱和用户级授权码；
5. 通过 `CAPA`、`USER`、`PASS`、`STAT`、`LIST`、`UIDL`、`RETR`、`TOP`、`NOOP`、`RSET`、`QUIT` 读取邮件；
6. 不感知 CloudMail `emailList` 字段、Token 刷新规则和实例路由。

## 17. 错误码建议

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| `DOMAIN_SELECTOR_CONFLICT` | 400 | 同时传入 `domain` 和 `domains` |
| `DOMAIN_NOT_ALLOWED` | 400 | 指定域名不存在于允许列表 |
| `DOMAIN_UNAVAILABLE` | 503 | 指定域名禁用、异常或冷却 |
| `NO_AVAILABLE_DOMAIN` | 503 | 自动模式没有可用域名 |
| `INSTANCE_UNAVAILABLE` | 503 | 域名所属 CloudMail 实例不可用 |
| `MAILBOX_CREATE_FAILED` | 502 | 上游创建邮箱失败 |
| `MAILBOX_NOT_FOUND` | 404 | 邮箱记录不存在 |
| `MAILBOX_TOKEN_INVALID` | 401 | 邮箱访问凭证无效 |
| `MAILBOX_SESSION_EXPIRED` | 401 | 邮箱访问凭证过期 |
| `API_KEY_INVALID` | 401 | 用户调用密钥无效或已撤销 |
| `USER_FORBIDDEN` | 403 | 当前用户无权访问该资源 |
| `USER_AUTH_CODE_REQUIRED` | 409 | 创建邮箱或 POP 登录前尚未设置用户级授权码 |
| `USER_AUTH_CODE_INVALID` | 401 / POP `-ERR` | 用户级 POP 授权码无效 |
| `INSUFFICIENT_CREDITS` | 402 | 用户积分余额不足 |
| `POP_SERVER_UNAVAILABLE` | POP `-ERR` | POP3 服务或 CloudMail 实例不可用 |
| `POP_QUERY_FAILED` | POP `-ERR` | CloudMail 邮件查询失败 |
| `POP_CONNECTION_LIMITED` | POP `-ERR` | 超过 POP3 连接或登录失败限制 |
| `IDEMPOTENCY_CONFLICT` | 409 | 相同幂等键对应不同请求参数 |
| `VERIFICATION_PENDING` | 200 | 尚未收到验证码，使用响应状态表达 |
| `VERIFICATION_TIMEOUT` | 200/408 | 等待窗口内未收到验证码 |
| `RATE_LIMITED` | 429 | 超过接口限流 |
| `ADMIN_UNAUTHORIZED` | 401 | 管理端未登录或登录态无效 |

HTTP 上游错误必须转换成网关错误；POP3 上游错误必须转换成脱敏的 `-ERR` 响应，不直接回显 CloudMail 原始响应、管理员信息或 Token。

## 18. 日志、统计和清理

### 18.1 日志

结构化日志至少包含：

- `request_id`；
- `mailbox_id`；
- `user_id`；
- `instance_id`；
- `domain_id`；
- `operation`；
- `status`；
- `duration_ms`；
- `retry_count`；
- `error_code`。

POP3 连接可额外记录：

- 连接建立、认证成功或失败；
- 脱敏后的邮箱地址和来源 IP；
- POP 命令类型和耗时，不记录命令参数中的授权码；
- 当前会话读取的邮件数量和邮件 ID；
- 上游查询和 `RETR` 失败原因。

上述记录不得包含邮箱授权码、完整邮件正文、HTML、附件、CloudMail Token 或 Provider 原始响应。

### 18.2 统计

管理端统计应基于持久化记录，至少支持：

- 按实例统计成功率和耗时；
- 按域名统计创建量和失败率；
- 按用途统计验证码成功率；
- 按来源统计请求量；
- 按时间查看趋势。

### 18.3 清理

必须提供定时清理脚本或内部任务：

- 清理过期幂等记录；
- 清理超过保留期的请求日志；
- 将过期邮箱会话标记为 `expired`；
- 按配置删除或归档历史邮箱记录；
- 若 CloudMail 支持删除邮箱，则执行上游清理；
- 若 CloudMail 不支持删除邮箱，文档中明确需要在 CloudMail 侧处理账号保留策略。

清理必须先支持 dry-run，再允许正式 apply，并输出可供宝塔定时任务查看的中文摘要。

## 19. 开发阶段

### 阶段一：用户模型、积分和一次性数据清理

- 执行一次显式历史数据清理，清空旧调用密钥、邮箱记录、幂等记录和请求日志；
- 新建 `users`、`user_api_keys`、`user_sessions`、`credit_rules` 和 `credit_transactions`；
- 引导创建初始 `admin` 用户；
- 实现 `admin`/`user` 两角色和资源归属校验；
- 实现用户登录、退出、密码修改和会话撤销；
- 实现用户级 POP 授权码设置、重置和失败锁定；
- 实现用户级调用密钥创建、明文展示、重新生成和撤销；
- 实现积分余额、积分流水和管理员调整；
- 引入服务器 PostgreSQL、SQLAlchemy 连接池和自动建表；
- 实现实例和域名数据模型；
- 实现管理员敏感字段加密；
- 实现按 CloudMail 实例隔离的 Token 缓存和并发刷新锁；
- 实现实例连接测试和健康状态；

### 阶段二：用户归属的邮箱网关业务 API

- 实现域名路由；
- 实现邮箱地址生成；
- 实现幂等创建；
- 所有业务 API 从 `X-API-Key` 解析用户，并写入 `owner_user_id`；
- 创建邮箱前校验积分余额和用户级 POP 授权码；
- 实现预扣积分、成功确认、失败退款和幂等不重复扣费；
- 实现 `CloudMailProvider.addUser`；
- 实现邮箱记录；
- 实现 `mailboxToken`；
- 实现邮件查询、历史过滤和验证码提取；
- 实现单一 POP3 `110` 监听服务；
- 实现 `CAPA`、`USER`、`PASS`、`STAT`、`LIST`、`UIDL`、`RETR`、`TOP`、`NOOP`、`RSET`、`QUIT`；`STLS` 不纳入首期开发；
- POP 登录支持普通用户授权码和管理员全局授权码两条校验路径；
- 普通用户按 `owner_user_id` 和用户级授权码校验，管理员按唯一管理员全局授权码校验并允许全量访问；
- 按邮箱记录中的 `instance_id` 访问上游；
- 调用 CloudMail `emailList` 并生成简单邮件内容；
- 实现基础连接数和登录失败限制；
- 实现业务限流和统一错误码。

### 阶段三：管理端和用户中心

- 实现管理员登录；
- 实现管理员全局 POP 授权码明文查询、设置、修改和 POP 校验；
- 实现用户登录和用户中心；
- 实现用户调用密钥管理；
- 实现用户级 POP 授权码管理；
- 实现用户积分和邮箱记录页面；
- 实现运行概览；
- 实现实例 CRUD、启停和测试连接；
- 实现域名 CRUD、权重、批量操作和冷却管理；
- 实现用户 CRUD、启停和授权码重置；
- 实现积分规则配置和用户积分手工调整；
- 实现邮箱记录和请求日志只读页面；
- 实现管理员全量邮箱记录查询；管理员邮件内容通过 POP3 `110` + 全局授权码读取；释放、禁用、重新查询等 HTTP 管理操作留作后续扩展；
- 实现系统设置和审计日志。

### 阶段四：客户端迁移

- 图片站新增 `xiaoasi_gateway`；
- Kirox 新增网关 Provider；
- EXE 和其他项目接入；
- 灰度切换并保留调用方回滚方案；
- 验证所有调用方均不保存 CloudMail 管理凭据或 Token。

### 阶段五：运维和清理

- 增加数据库备份说明；
- 增加 dry-run/apply 清理任务；
- 增加宝塔定时任务配置；
- 增加健康检查和告警；
- 完成正式部署、接口和运维文档。

## 20. 测试范围

### 20.1 单元测试

- 实例配置校验和密码加密；
- 域名标准化、唯一约束和权重；
- 指定域名路由；
- 指定域名列表路由；
- 自动域名路由；
- 禁用、异常和冷却过滤；
- 用户名规则、姓名基础值清洗和随机生成；
- 短数字用户名碰撞后自动重新生成；
- 幂等创建；
- 每实例 Token 缓存隔离；
- 单实例并发刷新锁；
- 401/403 单次刷新；
- 用户登录、会话过期和角色校验；
- 用户只能读取和修改自己的邮箱、调用密钥、授权码和积分信息；
- 用户不能读取其他用户邮箱、密钥、积分和管理配置；
- 调用密钥创建、撤销和哈希校验；
- 用户授权码设置、强制清除、重新设置和旧授权码失效；管理员强制清除后不能获得普通用户新授权码明文；
- 管理员全局 POP 授权码设置、重置、全量邮箱访问和审计记录；
- 积分扣费、余额不足、创建失败退款和管理员调整；
- `addUser` 成功、重复和失败；
- `emailList` 解析和历史邮件过滤；
- POP3 `110` 监听和连接握手；
- POP 邮箱域名到 CloudMail 实例的路由；
- 用户级 POP 授权码明文校验、旧哈希兼容和失败计数；
- POP3 命令状态机和未授权命令阻断；
- `STAT`、`LIST`、`RETR` 和简单邮件内容转换；
- `CAPA`、`NOOP`、`RSET`、`TOP` 等常见客户端兼容命令；
- 上游邮件查询失败、超时和 401/403 刷新；
- OpenAI、Grok 验证码提取；
- `mailboxToken` 校验、越权和过期；
- 日志脱敏。

### 20.2 API 测试

- 自动创建邮箱闭环；
- 指定域名创建；
- 跨实例候选域名失败切换；
- 相同幂等键不重复建箱；
- 相同用户的重复幂等请求不重复建箱、不重复扣费；
- 不同用户使用相同幂等键互不影响；
- 用户积分不足时不会调用 CloudMail；
- CloudMail 创建失败后积分可以退款；
- 网络超时保持积分扣款 `pending`，重试或人工确认不会重复建箱、重复扣费；
- 标准 POP3 客户端可以通过固定主机和 110 端口连接；
- 正确邮箱和授权码可以完成 `USER`、`PASS` 登录；
- 错误邮箱、错误授权码和已释放邮箱不能登录；
- 未授权状态不能执行 `STAT`、`LIST`、`RETR`；
- POP 会话只能访问邮箱所属 CloudMail 实例；
- `STAT`、`LIST` 和 `RETR` 可以读取 CloudMail 邮件；
- 管理员使用管理员 POP 授权码可以读取其他用户邮箱和过期邮箱；
- 普通用户授权码不能读取其他用户邮箱；
- 过量连接和登录失败会被限制；
- 用户 A 的调用密钥和邮箱 Token 无法读取用户 B 的邮箱；
- 管理端未登录无法读取实例配置；
- 用户中心未登录无法读取用户数据；
- 用户角色无法调用管理员接口；
- 管理 API 不返回管理员密码和 CloudMail Token；
- 业务 API 不暴露实际 Provider。

### 20.3 管理端验收

- 可以新增两个 CloudMail 实例；
- 每个实例可以维护多个域名；
- 可以测试连接并看到清晰结果；
- 可以批量启停域名；
- 可以修改域名权重；
- 可以看到实例和域名健康状态；
- 可以查看邮箱记录和脱敏错误；
- 可以在服务器配置 POP3 主机、110 端口；STLS 证书配置仅作为后续扩展预留；
- 可以看到 POP3 认证成功率、邮件读取次数和上游失败情况；
- 可以管理用户、用户状态和用户级授权码重置；
- 可以设置、重置管理员全局 POP 授权码，并通过管理员账号查看全部邮箱邮件内容；
- 可以配置创建邮箱扣除积分和新用户默认积分；
- 可以为用户增加或扣减积分并查看积分流水；
- 所有保存操作都有加载、成功和失败反馈；
- 密码字段不会重新回显；
- 关键删除和真实测试创建操作有二次确认。

### 20.4 用户中心验收

- 用户可以登录、退出和修改自己的登录密码；
- 用户可以创建、长期查看、复制、重新生成和撤销自己的调用密钥；
- 用户可以自动生成、重置、长期查看和复制自己的用户级 POP 授权码及完整 POP3 连接参数；
- 管理员可以查看、复制、设置或修改全局 POP 授权码明文；
- 用户可以查看积分余额和积分变更摘要；
- 用户可以搜索和筛选自己的邮箱记录、查看并复制自己的验证码，但不能查看其他用户邮箱；
- 用户不能进入管理员页面、读取 CloudMail 配置、修改积分规则或调整积分；
- 用户注册开关关闭时，公开注册接口不可用；开启后新用户按默认积分规则创建。

## 21. 最终验收标准

1. 至少配置两个独立 CloudMail 实例，每个实例配置两个以上域名。
2. 不传域名时，可以从全部健康域名中自动选择并创建邮箱。
3. 指定单域名时，只在该域名及所属实例创建。
4. 传域名候选范围时，可以跨实例随机选择，并在失败时切换候选。
5. 图片站和 Kirox 不保存 CloudMail 管理员凭据及 Token。
6. 调用方无法获知实际使用的 CloudMail 实例。
7. 普通用户邮箱 A 的访问凭证不能查询邮箱 B；管理员全局授权码是明确记录的管理员例外。
8. 同一幂等键重复请求不会创建多个邮箱。
9. 一个实例 Token 刷新不会覆盖另一个实例 Token。
10. 管理端可以可视化管理实例、域名、邮箱和日志，邮箱与日志列表在常规桌面宽度下保持紧凑可读。
11. 请求日志不泄露密码、Token、邮箱访问凭证、验证码和邮件正文；邮箱列表只按管理员或邮箱所属用户权限展示已识别验证码。
12. 全部客户端迁移完成后，CloudMail Token 不再通过公开接口外发。
13. 系统始终只有一个 `admin` 账号，不能通过注册、用户接口或管理端创建第二个管理员。
14. 唯一管理员可以访问全部用户、全部邮箱、全部请求日志和全部积分流水。
15. 用户可以登录用户中心，并且只能访问自己的调用密钥、授权码、积分和邮箱记录。
16. 用户可以创建和撤销自己的 `X-API-Key`，调用密钥不能访问其他用户资源。
17. 用户可以自动生成或重置用户级 POP 授权码，旧授权码立即失效。
18. 唯一管理员可以查看、复制、设置或修改全局 POP 授权码；保存新值后旧授权码立即失效。
19. 管理端可以配置创建邮箱扣除积分和新用户默认积分。
20. 创建邮箱会正确扣费，余额不足不会调用 CloudMail，CloudMail 创建失败会退款。
21. 上游超时会保留积分扣款 `pending`，重试和人工确认不会重复建箱或重复扣费。
22. 相同用户的相同幂等请求不重复建箱、不重复扣费，不同用户相同幂等键互不影响。
23. 不新增独立创建用户邮箱接口，用户通过 `POST /v1/mailboxes` 完成建箱并获得邮箱地址和 `mailboxToken`。
24. 标准 POP3 客户端可以使用固定的 POP 主机和 110 端口连接网关。
25. 正确邮箱和普通用户授权码可以完成 POP3 登录并读取所属邮箱。
26. 正确邮箱和管理员全局授权码可以读取全部未物理删除且上游仍存在的邮箱，包括其他用户、过期和已释放邮箱。
27. 错误授权码、普通用户跨用户邮箱、跨实例邮箱均不能登录或读取邮件。
28. POP3 未授权状态不能执行邮件读取命令。
29. POP3 服务只调用邮箱记录绑定的 CloudMail 实例。
30. `STAT`、`LIST`、`UIDL`、`RETR` 返回可被标准客户端解析的结果。
31. POP3 服务不返回 CloudMail Token、管理员信息、邮箱内部密码或上游原始响应。
32. 历史调用密钥、邮箱记录和请求日志清理后全部失效，新的用户和积分模型可以正常初始化。
33. 对外文档明确 POP3 主机、110 端口、用户名、普通用户授权码和管理员全局授权码使用方式。

## 22. 最终形态

```text
用户使用 X-API-Key 调用 POST /v1/mailboxes 创建邮箱
                ↓
网关校验用户状态、用户级授权码配置和积分余额
                ↓
网关预扣积分，选择域名和所属 CloudMail 实例
                ↓
网关调用 CloudMail addUser 创建邮箱并写入 owner_user_id
                ↓
创建成功确认扣费，失败则写入退款流水
                ↓
用户在邮件客户端配置 POP 主机、110 端口、邮箱和 userAuthCode
                ↓
客户端通过 POP3 TCP 连接网关 110 端口
                ↓
网关处理 USER/PASS：普通用户校验用户归属和用户授权码，管理员校验全局授权码并允许全量访问
                ↓
网关调用对应 CloudMail HTTP emailList
                ↓
网关转换为 STAT/LIST/UIDL/RETR；HTTP 调用方仍可使用 mailboxToken 查询验证码
```

CloudMail 将成为网关内部可替换的 Provider。普通邮件客户端只依赖 POP3 主机、110 端口、邮箱和用户级授权码；管理员邮件客户端使用相同 POP3 主机、110 端口、任意邮箱地址和管理员全局授权码。所有客户端均不感知 CloudMail HTTP、Token、管理员凭据和实例路由；用户注册、调用密钥、积分和管理员全量访问均由网关统一管理。
