import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiOutlined,
  CheckCircleOutlined,
  CopyOutlined,
  DashboardOutlined,
  DeleteOutlined,
  InboxOutlined,
  KeyOutlined,
  LockOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
  WalletOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App as AntApp,
  Badge,
  Button,
  Card,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  Layout,
  Menu,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { UserApiError, userApi } from "./userApi";
import type { CreditTransaction, UserApiKey, UserMailbox, UserProfile } from "./userTypes";

const { Header, Sider, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

type UserPageKey = "overview" | "apiKeys" | "authCode" | "credits" | "mailboxes" | "security";

const userNavItems = [
  { key: "overview", icon: <DashboardOutlined />, label: "账户概览" },
  { key: "apiKeys", icon: <KeyOutlined />, label: "我的调用密钥" },
  { key: "authCode", icon: <SafetyCertificateOutlined />, label: "我的 POP 授权码" },
  { key: "credits", icon: <WalletOutlined />, label: "我的积分" },
  { key: "mailboxes", icon: <InboxOutlined />, label: "我的邮箱" },
  { key: "security", icon: <LockOutlined />, label: "账号安全" },
];

const userPageMeta: Record<UserPageKey, { title: string; description: string }> = {
  overview: { title: "账户概览", description: "查看当前账户状态、积分和邮箱接入准备情况" },
  apiKeys: { title: "我的调用密钥", description: "管理用于调用网关业务 API 的用户级 X-API-Key" },
  authCode: { title: "我的 POP 授权码", description: "设置连接 POP3 110 时使用的用户级授权码" },
  credits: { title: "我的积分", description: "查看余额和最近的积分变更摘要" },
  mailboxes: { title: "我的邮箱", description: "查看当前账户创建的邮箱及其生命周期状态" },
  security: { title: "账号安全", description: "修改登录密码、撤销会话并安全退出用户中心" },
};

function formatTime(value?: string | null) {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "—";
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "请求失败，请稍后重试";
}

function statusTag(status?: string) {
  const normalized = (status || "unknown").toLowerCase();
  const config: Record<string, { color: string; text: string }> = {
    active: { color: "success", text: "使用中" },
    enabled: { color: "success", text: "启用" },
    pending: { color: "processing", text: "处理中" },
    received: { color: "success", text: "已收到" },
    expired: { color: "warning", text: "已过期" },
    released: { color: "default", text: "已释放" },
    disabled: { color: "default", text: "已停用" },
    failed: { color: "error", text: "失败" },
    timeout: { color: "warning", text: "已超时" },
    unknown: { color: "default", text: "未知" },
  };
  const item = config[normalized] || { color: "default", text: status || "未知" };
  return <Tag color={item.color}>{item.text}</Tag>;
}

function displayName(user: UserProfile) {
  return user.display_name || user.displayName || user.username || user.email || "用户";
}

function authCodeConfigured(user: UserProfile) {
  return Boolean(user.auth_code_configured ?? user.authCodeConfigured ?? user.has_user_auth_code ?? user.hasUserAuthCode);
}

function creditBalance(user: UserProfile) {
  return Number(user.credits ?? user.credit_balance ?? user.creditBalance ?? 0);
}

function UserLogin({ onSuccess }: { onSuccess: () => Promise<void> | void }) {
  const { message } = AntApp.useApp();
  const [loading, setLoading] = useState(false);

  const submit = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await userApi.login(values.username, values.password);
      await onSuccess();
      message.success("登录成功");
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="user-login-shell">
      <section className="user-login-aside">
        <div className="user-aside-top">
          <div className="brand-mark large"><UserOutlined /></div>
          <Text className="eyebrow">XIAOASI USER CENTER</Text>
        </div>
        <div className="user-login-intro">
          <Title>你的邮箱<br />接入控制台</Title>
          <Paragraph>集中管理调用密钥、POP 授权码、积分和已创建邮箱。连接方式清晰，敏感凭据只在必要时出现。</Paragraph>
        </div>
        <div className="user-aside-foot"><span>USER ACCESS / 01</span><span>POP3 : 110</span></div>
      </section>
      <section className="user-login-panel">
        <div className="user-login-form-wrap">
          <Text className="section-index">ACCOUNT / SIGN IN</Text>
          <Title level={2}>用户登录</Title>
          <Paragraph type="secondary">使用管理员创建的普通用户账号进入用户中心。</Paragraph>
          <Form layout="vertical" onFinish={submit} requiredMark={false} size="large">
            <Form.Item label="用户账号 / 邮箱" name="username" rules={[{ required: true, message: "请输入用户账号或邮箱" }]}>
              <Input autoComplete="username" placeholder="输入账号或邮箱" prefix={<UserOutlined />} />
            </Form.Item>
            <Form.Item label="登录密码" name="password" rules={[{ required: true, message: "请输入登录密码" }]}>
              <Input.Password autoComplete="current-password" placeholder="输入登录密码" prefix={<LockOutlined />} />
            </Form.Item>
            <Button block type="primary" htmlType="submit" loading={loading}>进入用户中心</Button>
          </Form>
          <div className="secure-note"><SafetyCertificateOutlined /> 使用 HttpOnly Cookie 会话，不在浏览器保存登录凭证</div>
        </div>
      </section>
    </main>
  );
}

function BootState() {
  return <div className="boot-screen"><div className="brand-mark large"><UserOutlined /></div><Spin /><Text>正在连接用户中心…</Text></div>;
}

function ErrorState({ error, retry }: { error: string; retry: () => void }) {
  return <Alert showIcon type="error" message="数据加载失败" description={error} action={<Button onClick={retry}>重新加载</Button>} />;
}

function OneTimeSecret({ title, secret, description, onClose }: { title: string; secret: string; description: string; onClose: () => void }) {
  return (
    <Modal open title={title} onCancel={onClose} onOk={onClose} okText="我已安全保存" cancelButtonProps={{ style: { display: "none" } }} destroyOnClose>
      <Alert type="warning" showIcon message="完整值只显示这一次" description={description} />
      <div className="one-time-secret"><Text code copyable={{ text: secret }}><span>{secret}</span></Text><Button type="text" icon={<CopyOutlined />} onClick={() => void navigator.clipboard?.writeText(secret)}>复制</Button></div>
    </Modal>
  );
}

function OverviewPage({ user, onNavigate }: { user: UserProfile; onNavigate: (page: UserPageKey) => void }) {
  const { message } = AntApp.useApp();
  const [credits, setCredits] = useState(creditBalance(user));
  const [mailboxCount, setMailboxCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [creditData, mailboxes] = await Promise.all([userApi.credits(), userApi.mailboxes()]);
      setCredits(creditData.balance);
      setMailboxCount(mailboxes.length);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { void load(); }, [load]);

  const configured = authCodeConfigured(user);
  return (
    <div className="user-overview-grid">
      <Card className="user-welcome-card">
        <div>
          <Text className="section-index">PERSONAL WORKSPACE</Text>
          <Title level={2}>你好，{displayName(user)}</Title>
          <Paragraph>在这里准备好业务调用所需的凭据，然后使用自己的 API Key 创建邮箱。</Paragraph>
          <Space wrap>
            <Button type="primary" onClick={() => onNavigate("apiKeys")}>管理调用密钥</Button>
            <Button onClick={() => onNavigate("authCode")}>设置 POP 授权码</Button>
          </Space>
        </div>
        <div className="user-welcome-badge"><UserOutlined /><span>普通用户</span><b>{user.status || "active"}</b></div>
      </Card>
      <div className="user-stat-grid">
        <Card><Statistic title="积分余额" value={loading ? "—" : credits} suffix="分" prefix={<WalletOutlined />} /></Card>
        <Card><Statistic title="我的邮箱" value={loading ? "—" : (mailboxCount ?? 0)} suffix="个" prefix={<InboxOutlined />} /></Card>
        <Card><Statistic title="POP 授权码" value={configured ? "已配置" : "未配置"} prefix={<SafetyCertificateOutlined />} /></Card>
      </div>
      <Card className="user-preflight-card" title="开始使用前的三项准备">
        <div className={`preflight-item ${configured ? "done" : ""}`}><span>01</span><CheckCircleOutlined /><div><b>设置用户级 POP 授权码</b><small>{configured ? "已配置，可用于该用户全部邮箱的 POP3 登录" : "邮件客户端连接 POP3 110 时需要"}</small></div><Button type="link" onClick={() => onNavigate("authCode")}>{configured ? "重置" : "去设置"}</Button></div>
        <div className="preflight-item"><span>02</span><KeyOutlined /><div><b>创建自己的 X-API-Key</b><small>调用 POST /v1/mailboxes 创建邮箱</small></div><Button type="link" onClick={() => onNavigate("apiKeys")}>去管理</Button></div>
        <div className="preflight-item"><span>03</span><WalletOutlined /><div><b>确认积分余额</b><small>创建邮箱会按管理端配置扣除积分</small></div><Button type="link" onClick={() => onNavigate("credits")}>查看积分</Button></div>
      </Card>
    </div>
  );
}

function ApiKeysPage() {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<{ name: string }>();
  const [items, setItems] = useState<UserApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [oneTimeKey, setOneTimeKey] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try { setItems(await userApi.apiKeys()); }
    catch (error) { message.error(getErrorMessage(error)); }
    finally { setLoading(false); }
  }, [message]);

  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const created = await userApi.createApiKey(values.name.trim());
      const fullKey = created.api_key || created.apiKey || "";
      setOneTimeKey(fullKey);
      message.success(fullKey ? "调用密钥已创建，请立即安全保存" : "调用密钥已创建");
      setModalOpen(false);
      form.resetFields();
      await load();
    } catch (error) { message.error(getErrorMessage(error)); }
    finally { setSaving(false); }
  };

  const revoke = async (item: UserApiKey) => {
    try { await userApi.revokeApiKey(item.id); message.success("调用密钥已撤销"); await load(); }
    catch (error) { message.error(getErrorMessage(error)); }
  };

  const columns: ColumnsType<UserApiKey> = [
    { title: "名称", dataIndex: "name", render: (value) => <Text strong>{value}</Text> },
    { title: "密钥状态", key: "key", render: (_, item) => <div className="primary-cell"><b>{item.key_masked || item.keyMasked || item.masked_key || item.maskedKey || item.key_prefix || item.keyPrefix || "已创建，明文不可回显"}</b><span>完整密钥仅在创建成功时展示一次</span></div> },
    { title: "状态", key: "enabled", width: 100, render: (_, item) => item.enabled === false ? <Tag>已停用</Tag> : <Tag color="success">有效</Tag> },
    { title: "创建时间", key: "created_at", width: 180, render: (_, item) => formatTime(item.created_at || item.createdAt) },
    { title: "操作", key: "actions", width: 110, render: (_, item) => <Popconfirm title="撤销后该密钥立即失效，确认继续？" onConfirm={() => void revoke(item)}><Button size="small" danger icon={<DeleteOutlined />}>撤销</Button></Popconfirm> },
  ];

  return <>
    {oneTimeKey && <OneTimeSecret title="保存新的 X-API-Key" secret={oneTimeKey} description="关闭此窗口后，用户中心不会再次显示完整密钥。请将它保存到安全的密钥管理位置。" onClose={() => setOneTimeKey("")} />}
    <div className="toolbar"><div className="toolbar-copy"><Text type="secondary">业务接口请求头：X-API-Key</Text><Text type="secondary">历史密钥只显示前缀或掩码，不能回显明文。</Text></div><Space><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button type="primary" icon={<KeyOutlined />} onClick={() => setModalOpen(true)}>创建调用密钥</Button></Space></div>
    <Table rowKey="id" loading={loading} columns={columns} dataSource={items} locale={{ emptyText: <Empty description="还没有调用密钥" /> }} scroll={{ x: 760 }} />
    <Modal title="创建用户调用密钥" open={modalOpen} confirmLoading={saving} okText="创建并显示一次" cancelText="取消" onOk={() => void create()} onCancel={() => { setModalOpen(false); form.resetFields(); }} destroyOnClose>
      <Alert className="form-alert" type="info" showIcon message="请为密钥命名" description="创建成功后完整 API Key 只显示一次，之后只能看到掩码。" />
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item label="密钥名称" name="name" rules={[{ required: true, message: "请输入密钥名称" }, { max: 100, message: "名称不能超过 100 个字符" }]}><Input placeholder="例如：图片站生产环境" autoFocus /></Form.Item>
      </Form>
    </Modal>
  </>;
}

function AuthCodePage({ user, onConfigured }: { user: UserProfile; onConfigured: () => void }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<{ userAuthCode: string; confirm: string }>();
  const [saving, setSaving] = useState(false);
  const [oneTimeCode, setOneTimeCode] = useState("");
  const configured = authCodeConfigured(user);

  const submit = async (values: { userAuthCode: string; confirm: string }) => {
    setSaving(true);
    try {
      const result = await userApi.setAuthCode(values.userAuthCode);
      const returnedCode = result.userAuthCode || result.user_auth_code || result.authCode || "";
      setOneTimeCode(returnedCode);
      form.resetFields();
      onConfigured();
      message.success(configured ? "POP 授权码已重置，旧值立即失效" : "POP 授权码已设置");
    } catch (error) { message.error(getErrorMessage(error)); }
    finally { setSaving(false); }
  };

  return <>
    {oneTimeCode && <OneTimeSecret title="保存新的 userAuthCode" secret={oneTimeCode} description="这是接口返回的完整授权码，关闭此窗口后不会再次回显。普通 POP3 客户端使用它连接 110 端口。" onClose={() => setOneTimeCode("")} />}
    <div className="user-auth-grid">
      <Card className="user-secret-card" title={<span><SafetyCertificateOutlined /> POP3 访问状态</span>}>
        <div className={`auth-status ${configured ? "ready" : "not-ready"}`}><span className="auth-status-dot" /><div><b>{configured ? "授权码已配置" : "尚未配置授权码"}</b><small>{configured ? "可以使用该用户的邮箱地址 + userAuthCode 读取 POP3 邮件" : "创建邮箱前需要先设置用户级授权码"}</small></div></div>
        <Descriptions column={1} size="small" className="auth-connection-info"><Descriptions.Item label="POP 主机">由部署环境提供</Descriptions.Item><Descriptions.Item label="端口">110</Descriptions.Item><Descriptions.Item label="用户名">你的邮箱完整地址</Descriptions.Item><Descriptions.Item label="密码">当前用户 userAuthCode</Descriptions.Item></Descriptions>
      </Card>
      <Card title={configured ? "重置 userAuthCode" : "设置 userAuthCode"}>
        <Alert className="form-alert" type={configured ? "warning" : "info"} showIcon message={configured ? "重置后旧授权码立即失效" : "授权码用于该用户全部邮箱的 POP3 登录"} description="用户中心不会读取或显示历史授权码明文。" />
        <Form form={form} layout="vertical" requiredMark={false} onFinish={submit}>
          <Form.Item label="新的 userAuthCode" name="userAuthCode" rules={[{ required: true, message: "请输入新的 userAuthCode" }, { min: 10, message: "授权码至少 10 位" }]}><Input.Password autoComplete="new-password" placeholder="输入新的授权码" /></Form.Item>
          <Form.Item label="确认 userAuthCode" name="confirm" dependencies={["userAuthCode"]} rules={[{ required: true, message: "请再次输入授权码" }, ({ getFieldValue }) => ({ validator(_, value) { return !value || getFieldValue("userAuthCode") === value ? Promise.resolve() : Promise.reject(new Error("两次输入的授权码不一致")); } })]}><Input.Password autoComplete="new-password" placeholder="再次输入新的授权码" /></Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>{configured ? "重置授权码" : "保存授权码"}</Button>
        </Form>
      </Card>
    </div>
  </>;
}

function CreditsPage({ user }: { user: UserProfile }) {
  const { message } = AntApp.useApp();
  const [balance, setBalance] = useState(creditBalance(user));
  const [items, setItems] = useState<CreditTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try { const result = await userApi.credits(); setBalance(result.balance); setItems(result.transactions); }
    catch (error) { message.error(getErrorMessage(error)); }
    finally { setLoading(false); }
  }, [message]);
  useEffect(() => { void load(); }, [load]);

  const columns: ColumnsType<CreditTransaction> = [
    { title: "时间", key: "created_at", width: 180, render: (_, item) => formatTime(item.created_at || item.createdAt) },
    { title: "变更", dataIndex: "amount", width: 100, render: (value: number) => <Text className={value >= 0 ? "success-text" : "error-text"}>{value >= 0 ? `+${value}` : value}</Text> },
    { title: "变更后余额", key: "balance", width: 120, render: (_, item) => item.balance_after ?? item.balance ?? "—" },
    { title: "类型", dataIndex: "type", width: 120, render: (value) => value || "—" },
    { title: "说明", key: "reason", render: (_, item) => item.reason || item.description || "—" },
  ];

  return <>
    <div className="user-credit-hero"><div><Text className="section-index">CREDIT BALANCE</Text><Title level={2}>可用积分</Title><Paragraph>创建邮箱时会按照管理员配置的单次费用扣除积分，失败或超时按服务端规则处理。</Paragraph></div><Statistic value={loading ? "—" : balance} suffix="分" /></div>
    <div className="toolbar"><Text type="secondary">最近积分变更摘要</Text><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button></div>
    <Table rowKey="id" loading={loading} columns={columns} dataSource={items} locale={{ emptyText: <Empty description="暂无积分变更记录" /> }} scroll={{ x: 700 }} />
  </>;
}

function MailboxesPage() {
  const { message } = AntApp.useApp();
  const [items, setItems] = useState<UserMailbox[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setItems(await userApi.mailboxes()); }
    catch (err) { const value = getErrorMessage(err); setError(value); message.error(value); }
    finally { setLoading(false); }
  }, [message]);
  useEffect(() => { void load(); }, [load]);

  const columns: ColumnsType<UserMailbox> = [
    { title: "邮箱地址", dataIndex: "address", render: (value) => <Text copyable>{value}</Text> },
    { title: "用途 / 来源", key: "purpose", responsive: ["md"], render: (_, item) => <div className="primary-cell"><b>{item.purpose || "未标记"}</b><span>{item.source || "业务调用"}</span></div> },
    { title: "状态", dataIndex: "status", width: 100, render: statusTag },
    { title: "验证码状态", key: "verification", width: 120, render: (_, item) => statusTag(item.verification_status || item.verificationStatus) },
    { title: "创建时间", key: "created_at", width: 180, render: (_, item) => formatTime(item.created_at || item.createdAt) },
    { title: "过期时间", key: "expires_at", width: 180, render: (_, item) => formatTime(item.expires_at || item.expiresAt) },
  ];

  return <>
    <Alert className="page-alert" type="info" showIcon message="邮箱记录只展示当前用户自己的资源" description="邮箱内部密码、CloudMail Token、完整邮件正文和其他用户记录不会在用户中心显示。" />
    <div className="toolbar"><Text type="secondary">共 {items.length} 个邮箱记录</Text><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button></div>
    {error ? <ErrorState error={error} retry={() => void load()} /> : <Table rowKey={(item) => item.id || item.mailbox_id || item.mailboxId || item.address} loading={loading} columns={columns} dataSource={items} locale={{ emptyText: <Empty description="暂无邮箱记录" /> }} scroll={{ x: 930 }} />}
  </>;
}

function SecurityPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<{ currentPassword: string; newPassword: string; confirm: string }>();
  const [saving, setSaving] = useState(false);
  const [revoking, setRevoking] = useState(false);

  const changePassword = async (values: { currentPassword: string; newPassword: string }) => {
    setSaving(true);
    try { await userApi.changePassword(values.currentPassword, values.newPassword); form.resetFields(); message.success("登录密码已修改"); }
    catch (error) { message.error(getErrorMessage(error)); }
    finally { setSaving(false); }
  };

  const revokeAll = async () => {
    setRevoking(true);
    try { await userApi.revokeAllSessions(); message.success("全部会话已撤销，请重新登录"); onUnauthorized(); }
    catch (error) { message.error(getErrorMessage(error)); }
    finally { setRevoking(false); }
  };

  return <div className="user-security-grid">
    <Card title={<span><LockOutlined /> 修改登录密码</span>}>
      <Form form={form} layout="vertical" requiredMark={false} onFinish={(values) => void changePassword(values)}>
        <Form.Item label="当前密码" name="currentPassword" rules={[{ required: true, message: "请输入当前密码" }]}><Input.Password autoComplete="current-password" /></Form.Item>
        <Form.Item label="新密码" name="newPassword" rules={[{ required: true, message: "请输入新密码" }, { min: 10, message: "新密码至少 10 位" }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item label="确认新密码" name="confirm" dependencies={["newPassword"]} rules={[{ required: true, message: "请再次输入新密码" }, ({ getFieldValue }) => ({ validator(_, value) { return !value || getFieldValue("newPassword") === value ? Promise.resolve() : Promise.reject(new Error("两次输入的密码不一致")); } })]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>保存新密码</Button>
      </Form>
    </Card>
    <Card title={<span><SafetyCertificateOutlined /> 会话安全</span>}>
      <Descriptions column={1} size="small"><Descriptions.Item label="登录状态">当前用户会话有效</Descriptions.Item><Descriptions.Item label="凭证保存">HttpOnly Cookie</Descriptions.Item><Descriptions.Item label="管理员数据">用户中心不会访问管理员配置</Descriptions.Item></Descriptions>
      <Divider />
      <Popconfirm title="撤销全部用户中心会话？" description="当前页面也会退出，需要重新登录。" onConfirm={() => void revokeAll()} okText="确认撤销" cancelText="取消"><Button danger loading={revoking}>撤销全部会话</Button></Popconfirm>
    </Card>
  </div>;
}

function UserConsole({ user, onUnauthorized }: { user: UserProfile; onUnauthorized: () => void }) {
  const { message } = AntApp.useApp();
  const [page, setPage] = useState<UserPageKey>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [currentUser, setCurrentUser] = useState(user);
  const meta = userPageMeta[page];

  const refreshUser = useCallback(async () => {
    try { setCurrentUser(await userApi.me()); }
    catch (error) { if (error instanceof UserApiError && error.status === 401) onUnauthorized(); }
  }, [onUnauthorized]);

  const content = useMemo(() => ({
    overview: <OverviewPage user={currentUser} onNavigate={setPage} />,
    apiKeys: <ApiKeysPage />,
    authCode: <AuthCodePage user={currentUser} onConfigured={() => void refreshUser()} />,
    credits: <CreditsPage user={currentUser} />,
    mailboxes: <MailboxesPage />,
    security: <SecurityPage onUnauthorized={onUnauthorized} />,
  })[page], [currentUser, onUnauthorized, page, refreshUser]);

  useEffect(() => {
    const handleUnauthorized = () => onUnauthorized();
    window.addEventListener("user-unauthorized", handleUnauthorized);
    return () => window.removeEventListener("user-unauthorized", handleUnauthorized);
  }, [onUnauthorized]);

  const logout = async () => {
    setLoggingOut(true);
    try { await userApi.logout(); onUnauthorized(); }
    catch (error) { message.error(getErrorMessage(error)); }
    finally { setLoggingOut(false); }
  };

  const navigate = (key: string) => { setPage(key as UserPageKey); setMobileOpen(false); };
  const sidebar = <><div className="console-brand user-console-brand"><div className="brand-mark"><UserOutlined /></div>{!collapsed && <div><b>Xiaoasi Mail</b><span>User Center</span></div>}</div><Menu theme="dark" mode="inline" selectedKeys={[page]} items={userNavItems} onClick={({ key }) => navigate(key)} /><div className="sider-footer"><div>{!collapsed && <span>USER CENTER<br />POP3 / 110</span>}</div><TooltipLogout onLogout={logout} loading={loggingOut} /></div></>;

  return <Layout className="console-layout user-console-layout">
    <Sider className="desktop-sider user-sider" width={244} collapsedWidth={78} collapsed={collapsed} trigger={null}>{sidebar}</Sider>
    <Drawer className="mobile-drawer user-mobile-drawer" width={260} placement="left" open={mobileOpen} onClose={() => setMobileOpen(false)} closable={false}>{sidebar}</Drawer>
    <Layout>
      <Header className="console-header user-console-header"><Button className="desktop-collapse" type="text" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)} /><Button className="mobile-menu" type="text" icon={<MenuUnfoldOutlined />} onClick={() => setMobileOpen(true)} /><Text className="section-index header-console-name">USER WORKSPACE</Text><Badge status="success" text={`${displayName(currentUser)} · 用户会话已连接`} /></Header>
      <Content className="console-content"><div className="page-heading"><div><Title level={2}>{meta.title}</Title><Text>{meta.description}</Text></div><span className="page-code">USER / {String(userNavItems.findIndex((item) => item.key === page) + 1).padStart(2, "0")}</span></div><div className="page-body">{content}</div></Content>
    </Layout>
  </Layout>;
}

function TooltipLogout({ onLogout, loading }: { onLogout: () => Promise<void>; loading: boolean }) {
  return <Button type="text" icon={<LogoutOutlined />} loading={loading} onClick={() => void onLogout()} aria-label="退出登录" />;
}

export function UserPortal() {
  const [user, setUser] = useState<UserProfile | null | undefined>(undefined);

  const loadUser = useCallback(async () => {
    try { setUser(await userApi.me()); }
    catch { setUser(null); }
  }, []);

  useEffect(() => { void loadUser(); }, [loadUser]);

  if (user === undefined) return <BootState />;
  if (!user) return <UserLogin onSuccess={loadUser} />;
  return <UserConsole user={user} onUnauthorized={() => setUser(null)} />;
}
