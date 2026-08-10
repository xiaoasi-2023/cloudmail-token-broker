# Xiaoasi Mail Gateway 多实例邮箱网关开发方案

## 1. 文档状态

- 状态：核心网关和管理端已开发，待真实 CloudMail 环境验收及调用方迁移
- 制定日期：2026-08-10
- 当前仓库：`cloudmail-token-broker`
- 当前镜像：`registry.cn-hangzhou.aliyuncs.com/jiangshitong/cloudmail-token-broker`
- 目标产品名称：`Xiaoasi Mail Gateway`
- 客户端 Provider 建议标识：`xiaoasi_gateway`

本方案建设一个独立的完整邮箱网关。图片站、Kirox、Windows EXE 及其他调用方只对接 Xiaoasi Mail Gateway，不了解 CloudMail 的管理员凭据、Token、接口路径和响应结构。

截至 2026-08-10 已完成：服务器 PostgreSQL 持久化、多实例独立 Token、域名路由、幂等建箱、邮箱会话凭证、验证码查询、管理端登录、实例和域名管理、邮箱记录、请求日志、Docker 多阶段构建及数据保留清理脚本。尚待完成的外部工作是图片站/Kirox Provider 迁移以及生产宝塔点验。

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
9. 每个业务调用方由管理端创建独立明文调用密钥，所有业务接口必须携带 `X-API-Key`。
10. 创建邮箱后由网关返回短期、单邮箱范围的 `mailboxToken`，后续查询只能访问该邮箱。
11. 必须提供独立、受鉴权保护的可视化管理端。
12. 管理端能够维护 CloudMail 实例、域名、运行状态、邮箱记录和请求日志。
13. 网关不提供 CloudMail Token 外发接口，调用方只能使用统一邮箱业务接口。

## 3. 建设目标

### 3.1 客户端目标

调用方只需要配置：

```json
{
  "type": "xiaoasi_gateway",
  "api_base": "https://cloudmail.xiaoasi.xyz"
}
```

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
- 向普通调用方开放完整邮件正文；
- 多容器副本和分布式锁；
- Redis、消息队列和多副本分布式协调；
- 多管理员角色和复杂 RBAC；
- 将任意第三方邮箱 API 透传成通用代理接口。

## 5. 总体架构

```text
图片站 / Kirox / EXE / 其他调用方
                  |
                  | Xiaoasi Mail API
                  v
        Xiaoasi Mail Gateway
          |       |       |
          |       |       +-- 管理端与运行日志
          |       +---------- 邮箱会话、幂等和域名路由
          +------------------ Provider 适配层
                  |
          +-------+-------+
          |               |
          v               v
    CloudMail 实例 A  CloudMail 实例 B
      |      |          |      |
    域名 A  域名 B    域名 C  域名 D
```

业务客户端只认识网关协议。CloudMail 是网关内部的第一个 Provider 实现，未来新增其他邮箱服务时，不改变客户端主流程。

## 6. 核心数据关系

```text
CloudMailInstance 1 ---- N MailDomain
CloudMailInstance 1 ---- N Mailbox
MailDomain         1 ---- N Mailbox
Mailbox            1 ---- N GatewayRequestLog
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
| `instance_id` | 外键 | 实际使用的 CloudMail 实例 |
| `domain_id` | 外键 | 实际使用的邮箱域名 |
| `address` | VARCHAR | 完整邮箱地址 |
| `purpose` | VARCHAR | `openai`、`grok`、`generic` 等用途 |
| `source` | VARCHAR | 由已认证调用密钥自动写入的可信调用方名称 |
| `created_at` | DATETIME | 邮箱创建时间，也是历史邮件过滤基线 |
| `expires_at` | DATETIME | 网关邮箱会话过期时间 |
| `status` | VARCHAR | `creating`、`active`、`failed`、`expired`、`deleted` |
| `verification_status` | VARCHAR | `pending`、`received`、`timeout`、`failed` |
| `verification_code` | VARCHAR | 已识别验证码；仅管理端鉴权后展示，不写入请求日志 |
| `last_polled_at` | DATETIME | 最近查询邮件时间 |
| `provider_reference` | VARCHAR | 内部 Provider 引用，不向客户端返回 |
| `error_code` | VARCHAR | 最近脱敏错误码 |
| `error_message` | TEXT | 最近脱敏错误摘要 |

邮箱密码由网关内部生成或使用实例级策略，不返回调用方，也不写入普通日志。若 CloudMail 后续删除邮箱需要密码，应加密保存或保存可重新推导的内部凭据。

### 6.4 幂等记录表 `idempotency_records`

| 字段 | 说明 |
| --- | --- |
| `idempotency_key` | 调用方提供的唯一请求标识 |
| `request_fingerprint` | 规范化请求参数摘要 |
| `mailbox_id` | 已创建的邮箱记录 |
| `status` | `processing`、`completed`、`failed` |
| `expires_at` | 幂等记录过期时间 |

同一个 `Idempotency-Key`：

- 参数相同且已成功：返回原邮箱；
- 参数不同：返回 `IDEMPOTENCY_CONFLICT`；
- 正在处理中：返回处理中状态或等待已有任务；
- 失败且符合重试条件：按明确规则允许重试，不重复创建未知邮箱。

### 6.5 请求日志表 `gateway_request_logs`

记录：

- 请求时间；
- 接口和方法；
- 来源 IP 的脱敏值；
- 来源提示；
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

调用方可以传 `addressPattern` 和 `name`。`addressPattern` 默认是 `name_digits_4`，即“姓名基础值 + 4 位数字”。没有提供 `name` 时，网关随机选择内置英文名。当前内置规则包括：

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

### 9.1 创建邮箱

```http
POST /v1/mailboxes
Content-Type: application/json
Idempotency-Key: register-task-123-attempt-1
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
    "expiresAt": "2026-08-10T08:30:00Z"
  }
}
```

响应不返回 CloudMail 实例名称或 Provider 类型，调用方无需感知内部路由。

### 9.2 查询验证码

```http
POST /v1/mailboxes/{mailboxId}/verification-code
Authorization: Mailbox <mailboxToken>
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

### 9.3 查询邮箱状态

```http
GET /v1/mailboxes/{mailboxId}
Authorization: Mailbox <mailboxToken>
```

只返回邮箱地址、状态、创建时间、过期时间和验证码状态，不返回内部实例、管理员凭据或邮件正文。

### 9.4 释放邮箱

```http
DELETE /v1/mailboxes/{mailboxId}
Authorization: Mailbox <mailboxToken>
```

第一阶段至少将网关记录标记为已释放。若 CloudMail 支持安全删除邮箱，再由 Provider 执行真实删除；不确定支持能力前不得假设存在删除 API。

## 10. 邮箱访问凭证

调用方必须配置管理端签发的长期 `X-API-Key`；创建邮箱后还必须使用该邮箱自己的 `mailboxToken`。网关校验邮箱所属调用方，其他有效密钥不能访问该邮箱。

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

## 11. Provider 适配层

统一接口建议：

```python
class MailProvider:
    async def test_connection(self) -> ProviderHealth: ...
    async def create_mailbox(self, request: CreateMailboxRequest) -> ProviderMailbox: ...
    async def list_messages(self, mailbox: ProviderMailbox) -> list[MailMessage]: ...
    async def delete_mailbox(self, mailbox: ProviderMailbox) -> None: ...
```

第一期实现 `CloudMailProvider`：

```text
按 instance_id 获取实例配置
    → 获取该实例独立缓存 Token
    → POST /api/public/addUser
    → 保存邮箱创建时间
    → POST /api/public/emailList
    → 过滤创建时间之前的历史邮件
    → 统一提取验证码
```

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
```

业务 API 可以按当前决策公开创建，但管理端必须独立鉴权。

### 12.2 左侧菜单

```text
运行概览
CloudMail 实例
邮箱域名
邮箱记录
请求日志
系统设置
```

管理端按“实例 → 域名 → 邮箱 → 日志”分层，避免把多实例凭据、域名状态和业务记录堆在一个配置表单中。

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

列表字段：

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
- 用途；
- 来源提示；
- 所属域名；
- 所属实例；
- 创建状态；
- 验证码状态；
- 创建时间；
- 过期时间。

操作：

- 查看处理链路；
- 立即重新查询；
- 标记失效；
- 释放或删除；
- 查看脱敏错误。

默认不展示验证码明文、邮箱密码和完整邮件正文。

### 12.7 请求日志页面

支持按时间、接口、来源、实例、域名、结果和错误码筛选。列表展示：

- 请求时间；
- 方法和路径；
- 来源；
- 邮箱；
- 实例；
- 域名；
- 状态；
- 耗时；
- 重试次数；
- 脱敏错误。

### 12.8 系统设置页面

当前系统设置页面只展示真实运行约束，不提供无法持久化的假表单。邮箱会话有效期、创建和查询限流等部署级配置通过服务器环境变量维护；用户名生成规则由调用方在创建邮箱请求中选择。

敏感环境密钥不允许在普通设置页面查看或修改。未来需要在线修改部署参数时，应先增加独立持久化和审计能力，再开放相应表单。

## 13. 管理端鉴权和敏感配置

建议第一阶段使用单管理员登录：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=<安全密码哈希>
ADMIN_SESSION_SECRET=<高强度随机密钥>
DATA_ENCRYPTION_KEY=<数据库敏感字段加密密钥>
MAILBOX_SESSION_SECRET=<邮箱会话签名密钥>
```

规则：

- 管理密码只保存哈希；
- CloudMail 管理员密码使用 `DATA_ENCRYPTION_KEY` 加密入库；
- 管理 Session 使用 HttpOnly、Secure、SameSite Cookie；
- 管理 API 必须验证登录态；
- 生产环境只能通过 HTTPS 访问；
- 可在宝塔或反向代理层额外限制管理端访问来源；
- 所有管理修改写入审计日志。

## 14. 数据库和部署

生产数据统一使用服务器现有 PostgreSQL，Docker Compose 不创建数据库容器：

```text
DATABASE_URL=postgresql://数据库用户:数据库密码@host.docker.internal:5432/数据库名
```

Compose 仅增加宿主机地址映射：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

当前容器继续使用 `read_only: true`，业务数据不写入容器文件系统。数据库结构在启动时自动初始化，且必须保证重复执行安全。

PostgreSQL 负责以下共享持久化数据：

- CloudMail 实例配置；
- 域名配置；
- 邮箱记录；
- 幂等记录；
- 请求日志；
- 管理端操作。

数据库已具备并发访问能力。未来需要运行多个网关副本时，还需要将 Token 缓存锁和限流迁移到 Redis 或 PostgreSQL 协调层；当前仍明确只运行一个容器副本。

## 15. 管理端技术方案

推荐：

- 后端：现有 FastAPI；
- 管理端：React + TypeScript + Ant Design；
- 构建：Docker 多阶段构建前端静态资源；
- 部署：FastAPI 同域提供 `/admin` 静态页面和 `/admin-api`；
- 数据：服务器 PostgreSQL + SQLAlchemy 连接池；
- 样式：信息密度适中的桌面管理台，优先表格、状态标签、抽屉表单和明确反馈。

同域部署可以避免单独处理跨域、第二个容器和两套发布流程。管理端所有保存、启停、测试连接和删除操作必须展示加载状态和成功或失败反馈。

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

删除 CloudMail 管理员邮箱、管理员密码、Token 获取和直接 `addUser`、`emailList` 调用。

### 16.3 Kirox 接入

增加对应网关 Provider，调用统一创建邮箱和查询验证码接口，删除直接获取 CloudMail Token 以及直接调用 CloudMail 的实现。

### 16.4 其他调用方

Windows EXE 和其他项目只保存网关地址、域名选择参数、`mailboxId` 与短期 `mailboxToken`，不得保存 CloudMail 管理凭据或请求 CloudMail Token。

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
| `IDEMPOTENCY_CONFLICT` | 409 | 相同幂等键对应不同请求参数 |
| `VERIFICATION_PENDING` | 200 | 尚未收到验证码，使用响应状态表达 |
| `VERIFICATION_TIMEOUT` | 200/408 | 等待窗口内未收到验证码 |
| `RATE_LIMITED` | 429 | 超过接口限流 |
| `ADMIN_UNAUTHORIZED` | 401 | 管理端未登录或登录态无效 |

上游错误必须转换成网关错误，不直接向调用方回显 CloudMail 原始响应、管理员信息或 Token。

## 18. 日志、统计和清理

### 18.1 日志

结构化日志至少包含：

- `request_id`；
- `mailbox_id`；
- `instance_id`；
- `domain_id`；
- `operation`；
- `status`；
- `duration_ms`；
- `retry_count`；
- `error_code`。

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

### 阶段一：基础数据与多实例

- 引入服务器 PostgreSQL、SQLAlchemy 连接池和自动建表；
- 实现实例和域名数据模型；
- 实现管理员敏感字段加密；
- 实现按 CloudMail 实例隔离的 Token 缓存和并发刷新锁；
- 实现实例连接测试和健康状态；

### 阶段二：邮箱网关业务 API

- 实现域名路由；
- 实现邮箱地址生成；
- 实现幂等创建；
- 实现 `CloudMailProvider.addUser`；
- 实现邮箱记录；
- 实现 `mailboxToken`；
- 实现邮件查询、历史过滤和验证码提取；
- 实现业务限流和统一错误码。

### 阶段三：管理端

- 实现管理员登录；
- 实现运行概览；
- 实现实例 CRUD、启停和测试连接；
- 实现域名 CRUD、权重、批量操作和冷却管理；
- 实现邮箱记录和请求日志；
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
- `addUser` 成功、重复和失败；
- `emailList` 解析和历史邮件过滤；
- OpenAI、Grok 验证码提取；
- `mailboxToken` 校验、越权和过期；
- 日志脱敏。

### 20.2 API 测试

- 自动创建邮箱闭环；
- 指定域名创建；
- 跨实例候选域名失败切换；
- 相同幂等键不重复建箱；
- 邮箱 A 的 Token 无法读取邮箱 B；
- 管理端未登录无法读取实例配置；
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
- 所有保存操作都有加载、成功和失败反馈；
- 密码字段不会重新回显；
- 关键删除和真实测试创建操作有二次确认。

## 21. 最终验收标准

1. 至少配置两个独立 CloudMail 实例，每个实例配置两个以上域名。
2. 不传域名时，可以从全部健康域名中自动选择并创建邮箱。
3. 指定单域名时，只在该域名及所属实例创建。
4. 传域名候选范围时，可以跨实例随机选择，并在失败时切换候选。
5. 图片站和 Kirox 不保存 CloudMail 管理员凭据及 Token。
6. 调用方无法获知实际使用的 CloudMail 实例。
7. 邮箱 A 的访问凭证不能查询邮箱 B。
8. 同一幂等键重复请求不会创建多个邮箱。
9. 一个实例 Token 刷新不会覆盖另一个实例 Token。
10. 管理端可以可视化管理实例、域名、邮箱和日志。
11. 管理端和日志不泄露密码、Token、邮箱访问凭证、验证码和邮件正文。
12. 全部客户端迁移完成后，CloudMail Token 不再通过公开接口外发。

## 22. 最终形态

```text
调用方只提交邮箱需求和可选域名范围
                ↓
Xiaoasi Mail Gateway 选择域名和所属实例
                ↓
网关生成邮箱并调用对应 CloudMail
                ↓
调用方使用短期 mailboxToken 查询验证码
```

CloudMail 将成为网关内部可替换的 Provider。调用方只依赖 Xiaoasi Mail API，从而真正解决 Token 抢占、管理员凭据分散、多个项目重复实现、域名不可视和未来更换邮箱服务成本过高的问题。
