import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  MailOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
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
  InputNumber,
  Layout,
  Menu,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { InputRef } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { UserApiError, userApi } from "./userApi";
import type { BatchCreateMailboxesResult, CreditTransaction, UserApiKey, UserAuthCodeInfo, UserMailbox, UserProfile } from "./userTypes";

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
  authCode: { title: "我的 POP 授权码", description: "查看和管理 POP3 的完整连接参数" },
  credits: { title: "我的积分", description: "查看余额和最近的积分变更摘要" },
  mailboxes: { title: "我的邮箱", description: "查看当前账户创建的邮箱及其生命周期状态" },
  security: { title: "账号安全", description: "修改登录密码、撤销会话并安全退出用户中心" },
};

const userTablePagination = {
  defaultPageSize: 20,
  showSizeChanger: true,
  pageSizeOptions: [20, 50, 100],
  showTotal: (total: number) => `共 ${total} 条`,
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
    expired: { color: "warning", text: "POP 可用" },
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

function generateUserAuthCode(length = 32) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  const randomValues = new Uint8Array(length);
  window.crypto.getRandomValues(randomValues);
  return Array.from(randomValues, (value) => alphabet[value & 63]).join("");
}

function UserLogin({ onSuccess }: { onSuccess: () => Promise<void> | void }) {
  const { message } = AntApp.useApp();
  const [loading, setLoading] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const [registerForm] = Form.useForm<{ username: string; email: string; code: string; password: string; confirm: string }>();
  const registerEmailInputRef = useRef<InputRef>(null);

  useEffect(() => {
    void userApi.registrationConfig()
      .then((config) => setRegistrationEnabled(Boolean(config.enabled)))
      .catch(() => setRegistrationEnabled(false));
  }, []);

  useEffect(() => {
    if (countdown <= 0) return undefined;
    const timer = window.setInterval(() => setCountdown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [countdown]);

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

  const sendRegisterCode = async () => {
    try {
      // 浏览器或密码管理器自动填充时，DOM 已有值但 Ant Design 表单状态可能仍为空。
      const email = String(registerEmailInputRef.current?.input?.value || registerForm.getFieldValue("email") || "").trim();
      registerForm.setFieldValue("email", email);
      await registerForm.validateFields(["email"]);
      setSendingCode(true);
      const result = await userApi.sendRegisterCode(email);
      setCountdown(Number(result.cooldown_seconds || 60));
      message.success("验证码已发送，请检查邮箱");
    } catch (error) {
      if (error instanceof Error) message.error(getErrorMessage(error));
    } finally {
      setSendingCode(false);
    }
  };

  const register = async (values: { username: string; email: string; code: string; password: string }) => {
    setLoading(true);
    try {
      await userApi.register(values.username, values.email, values.password, values.code);
      await userApi.login(values.username, values.password);
      await onSuccess();
      message.success("注册成功，已进入用户中心");
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className={`user-login-shell ${mode === "register" ? "is-register" : "is-login"}`}>
      <section className="user-login-aside">
        <div className="user-aside-top">
          <div className="brand-mark large"><UserOutlined /></div>
          <Text className="eyebrow">XIAOASI USER CENTER</Text>
        </div>
        <div className="user-login-intro">
          <Text className="user-intro-index">{mode === "login" ? "ACCESS / SIGN IN" : "NEW ACCOUNT / VERIFY"}</Text>
          <Title>{mode === "login" ? <><span>你的邮箱</span><br />接入控制台</> : <><span>创建账号</span><br />开始收取邮件</>}</Title>
          <Paragraph>{mode === "login" ? "集中管理调用密钥、POP 授权码、积分和已创建邮箱。" : "验证常用邮箱后创建用户账号，随后即可配置 POP 授权码和调用密钥。"}</Paragraph>
          <div className="user-intro-points">
            <span><b>01</b> 邮箱验证码注册</span>
            <span><b>02</b> 用户数据独立隔离</span>
          </div>
        </div>
        <div className="user-aside-foot"><span>USER ACCESS / 01</span></div>
      </section>
      <section className="user-login-panel">
        <div className={`user-login-form-wrap ${mode === "register" ? "register-mode" : "login-mode"}`}>
          <Text className="section-index">ACCOUNT / {mode === "login" ? "SIGN IN" : "REGISTER"}</Text>
          <Title level={2}>{mode === "login" ? "用户登录" : "注册用户账号"}</Title>
          <Paragraph type="secondary">{mode === "login" ? (registrationEnabled ? "使用账号或邮箱登录，也可以注册新的普通用户。" : "使用管理员创建的普通用户账号进入用户中心。") : "使用邮箱验证码创建普通用户，初始积分按管理端规则发放。"}</Paragraph>
          {mode === "login" ? <Form className="user-auth-form user-signin-form" layout="vertical" onFinish={submit} requiredMark={false} size="large">
            <Form.Item label="用户账号 / 邮箱" name="username" rules={[{ required: true, message: "请输入用户账号或邮箱" }]}>
              <Input autoComplete="username" placeholder="输入账号或邮箱" prefix={<UserOutlined />} />
            </Form.Item>
            <Form.Item label="登录密码" name="password" rules={[{ required: true, message: "请输入登录密码" }]}>
              <Input.Password autoComplete="current-password" placeholder="输入登录密码" prefix={<LockOutlined />} />
            </Form.Item>
            <Button block type="primary" htmlType="submit" loading={loading}>进入用户中心</Button>
          </Form> : <Form className="user-auth-form user-register-form" form={registerForm} layout="vertical" onFinish={register} requiredMark={false} size="middle">
            <div className="register-form-grid">
              <Form.Item label="用户账号" name="username" rules={[{ required: true, message: "请输入用户账号" }, { min: 3, message: "用户账号至少 3 位" }, { pattern: /^[a-zA-Z0-9_.-]+$/, message: "账号只能包含字母、数字、点、下划线和短横线" }]}>
                <Input autoComplete="username" placeholder="例如 xiaoasi" prefix={<UserOutlined />} />
              </Form.Item>
              <Form.Item label="注册邮箱" name="email" rules={[{ required: true, message: "请输入注册邮箱" }, { type: "email", message: "请输入有效的邮箱地址" }]}>
                <Input ref={registerEmailInputRef} autoComplete="email" placeholder="用于接收验证码" prefix={<MailOutlined />} />
              </Form.Item>
              <Form.Item className="register-code-field" label="邮箱验证码" required>
                <Space.Compact block>
                  <Form.Item name="code" noStyle rules={[{ required: true, message: "请输入邮箱验证码" }, { pattern: /^\d{6}$/, message: "请输入 6 位数字验证码" }]}>
                    <Input inputMode="numeric" maxLength={6} placeholder="输入 6 位验证码" prefix={<SafetyCertificateOutlined />} />
                  </Form.Item>
                  <Button className="register-code-button" loading={sendingCode} disabled={countdown > 0} onClick={() => void sendRegisterCode()}>{countdown > 0 ? `${countdown}s 后重试` : "获取验证码"}</Button>
                </Space.Compact>
              </Form.Item>
              <Form.Item label="登录密码" name="password" rules={[{ required: true, message: "请输入登录密码" }, { min: 10, message: "登录密码至少 10 位" }]}>
                <Input.Password autoComplete="new-password" placeholder="至少 10 位" prefix={<LockOutlined />} />
              </Form.Item>
              <Form.Item label="确认密码" name="confirm" dependencies={["password"]} rules={[{ required: true, message: "请再次输入登录密码" }, ({ getFieldValue }) => ({ validator(_, value) { return !value || getFieldValue("password") === value ? Promise.resolve() : Promise.reject(new Error("两次输入的密码不一致")); } })]}>
                <Input.Password autoComplete="new-password" placeholder="再次输入登录密码" prefix={<LockOutlined />} />
              </Form.Item>
            </div>
            <Button block type="primary" htmlType="submit" loading={loading}>验证邮箱并创建账号</Button>
          </Form>}
          {registrationEnabled && <div className="auth-mode-text">
            <span>{mode === "login" ? "还没有账号？" : "已经有账号？"}</span>
            <button type="button" onClick={() => setMode((value) => value === "login" ? "register" : "login")}>{mode === "login" ? "立即注册" : "返回登录"}</button>
          </div>}
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
        <div className={`preflight-item ${configured ? "done" : ""}`}><span>01</span><CheckCircleOutlined /><div><b>生成用户级 POP 授权码</b><small>{configured ? "已配置，可查看完整 POP3 连接参数" : "邮件客户端连接 POP3 时需要"}</small></div><Button type="link" onClick={() => onNavigate("authCode")}>{configured ? "查看" : "去生成"}</Button></div>
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
  const [regeneratingId, setRegeneratingId] = useState<string | number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

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
      await userApi.createApiKey(values.name.trim());
      message.success("调用密钥已创建，可随时查看和复制");
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

  const regenerate = async (item: UserApiKey) => {
    setRegeneratingId(item.id);
    try {
      await userApi.regenerateApiKey(item.id);
      message.success("调用密钥已重新生成，旧值立即失效");
      await load();
    } catch (error) { message.error(getErrorMessage(error)); }
    finally { setRegeneratingId(null); }
  };

  const columns: ColumnsType<UserApiKey> = [
    { title: "名称", dataIndex: "name", render: (value) => <Text strong>{value}</Text> },
    { title: "调用密钥", key: "key", render: (_, item) => { const fullKey = item.api_key || item.apiKey || ""; return fullKey ? <div className="api-key-display"><Text code copyable={{ text: fullKey }}>{fullKey}</Text><span>完整密钥可随时查看和复制</span></div> : <div className="primary-cell"><b>{item.key_masked || item.keyMasked || item.masked_key || item.maskedKey || item.key_prefix || item.keyPrefix || "旧密钥"}</b><span>旧密钥无法反推，点击重新生成后即可完整显示</span></div>; } },
    { title: "状态", key: "enabled", width: 100, render: (_, item) => item.enabled === false ? <Tag>已停用</Tag> : <Tag color="success">有效</Tag> },
    { title: "创建时间", key: "created_at", width: 180, render: (_, item) => formatTime(item.created_at || item.createdAt) },
    { title: "操作", key: "actions", width: 205, render: (_, item) => <Space size={6}><Popconfirm title="重新生成后旧密钥立即失效，确认继续？" onConfirm={() => void regenerate(item)}><Button size="small" loading={regeneratingId === item.id} icon={<ReloadOutlined />}>重新生成</Button></Popconfirm><Popconfirm title="撤销后该密钥立即失效，确认继续？" onConfirm={() => void revoke(item)}><Button size="small" danger icon={<DeleteOutlined />}>撤销</Button></Popconfirm></Space> },
  ];

  return <>
    <div className="toolbar"><div className="toolbar-copy"><Text type="secondary">业务接口请求头：X-API-Key</Text><Text type="secondary">完整密钥会长期显示，可直接复制使用。</Text></div><Space><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button type="primary" icon={<KeyOutlined />} onClick={() => setModalOpen(true)}>创建调用密钥</Button></Space></div>
    <Table rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={userTablePagination} locale={{ emptyText: <Empty description="还没有调用密钥" /> }} scroll={{ x: 900 }} />
    <Modal title="创建用户调用密钥" open={modalOpen} confirmLoading={saving} okText="创建密钥" cancelText="取消" onOk={() => void create()} onCancel={() => { setModalOpen(false); form.resetFields(); }} destroyOnClose>
      <Alert className="form-alert" type="info" showIcon message="请为密钥命名" description="创建成功后完整 API Key 会保存在用户中心，可随时查看和复制。" />
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item label="密钥名称" name="name" rules={[{ required: true, message: "请输入密钥名称" }, { max: 100, message: "名称不能超过 100 个字符" }]}><Input placeholder="例如：图片站生产环境" autoFocus /></Form.Item>
      </Form>
    </Modal>
  </>;
}

function AuthCodePage({ user, onConfigured }: { user: UserProfile; onConfigured: () => void }) {
  const { message } = AntApp.useApp();
  const [info, setInfo] = useState<UserAuthCodeInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedMailbox, setSelectedMailbox] = useState("");

  const applyInfo = useCallback((result: UserAuthCodeInfo) => {
    const mailboxes = result.mailboxes || [];
    setInfo(result);
    setSelectedMailbox((current) => current && mailboxes.includes(current) ? current : (mailboxes[0] || ""));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try { applyInfo(await userApi.authCode()); }
    catch (error) { message.error(getErrorMessage(error)); }
    finally { setLoading(false); }
  }, [applyInfo, message]);

  useEffect(() => { void load(); }, [load]);

  const configured = info?.configured ?? authCodeConfigured(user);
  const currentCode = info?.user_auth_code || info?.userAuthCode || "";
  const legacyHashOnly = Boolean(info?.legacy_hash_only ?? info?.legacyHashOnly);
  const popHost = info?.pop_host || info?.popHost || "pop.cloudmail.xiaoasi.xyz";
  const popPort = info?.pop_port || info?.popPort || 18110;
  const mailboxes = info?.mailboxes || [];

  const generate = async () => {
    setSaving(true);
    try {
      const generatedCode = generateUserAuthCode();
      const result = await userApi.setAuthCode(generatedCode);
      applyInfo(result);
      onConfigured();
      message.success(configured ? "POP 授权码已自动重置，旧值立即失效" : "POP 授权码已自动生成");
    } catch (error) { message.error(getErrorMessage(error)); }
    finally { setSaving(false); }
  };

  const copyConnectionValue = async (label: string, value: string) => {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard API unavailable");
      await navigator.clipboard.writeText(value);
      message.success(`${label}已复制`);
    } catch {
      message.error("复制失败，请手动复制");
    }
  };

  return <>
    <div className="user-auth-grid">
      <Card className="user-secret-card" title={<span><SafetyCertificateOutlined /> POP3 连接信息</span>}>
        <div className={`auth-status ${configured ? "ready" : "not-ready"}`}><span className="auth-status-dot" /><div><b>{configured ? "授权码已配置" : "尚未配置授权码"}</b><small>{legacyHashOnly ? "当前是旧版哈希授权码，重置一次后即可长期查看明文。" : configured ? "以下连接参数已自动读取，可直接复制到 POP3 客户端。" : "生成授权码并创建邮箱后即可连接 POP3。"}</small></div></div>
        <div className="auth-connection-info">
          <div className="auth-connection-row">
            <span className="connection-label">POP 主机</span>
            <div className="connection-value">{loading ? <Spin size="small" /> : <code title={popHost}>{popHost}</code>}</div>
            <Button className="connection-copy-button" type="text" size="small" icon={<CopyOutlined />} disabled={loading} onClick={() => void copyConnectionValue("POP 主机", popHost)}>复制</Button>
          </div>
          <div className="auth-connection-row">
            <span className="connection-label">端口</span>
            <div className="connection-value"><code>{popPort}</code></div>
            <Button className="connection-copy-button" type="text" size="small" icon={<CopyOutlined />} onClick={() => void copyConnectionValue("端口", String(popPort))}>复制</Button>
          </div>
          <div className="auth-connection-row">
            <span className="connection-label">用户名</span>
            <div className="connection-value connection-select-value">{mailboxes.length ? <Select className="connection-mailbox-select" value={selectedMailbox} onChange={setSelectedMailbox} options={mailboxes.map((address) => ({ value: address, label: address }))} /> : <span className="connection-placeholder">暂无可用邮箱，请先创建邮箱</span>}</div>
            <Button className="connection-copy-button" type="text" size="small" icon={<CopyOutlined />} disabled={!selectedMailbox} onClick={() => void copyConnectionValue("用户名", selectedMailbox)}>复制</Button>
          </div>
          <div className="auth-connection-row">
            <span className="connection-label">密码</span>
            <div className="connection-value">{currentCode ? <code title={currentCode}>{currentCode}</code> : <span className="connection-placeholder">{legacyHashOnly ? "旧授权码无法反推，请点击右侧重置" : "尚未生成授权码"}</span>}</div>
            <Button className="connection-copy-button" type="text" size="small" icon={<CopyOutlined />} disabled={!currentCode} onClick={() => void copyConnectionValue("密码", currentCode)}>复制</Button>
          </div>
        </div>
      </Card>
      <Card className="user-auth-action-card" title={configured ? "重置 userAuthCode" : "生成 userAuthCode"}>
        <Alert className="form-alert" type={configured ? "warning" : "info"} showIcon message={configured ? "重置后旧授权码立即失效" : "授权码用于该用户全部邮箱的 POP3 登录"} description={legacyHashOnly ? "旧授权码只有哈希值，无法回显；重置后新值会长期保存在本页。" : "授权码会保存并长期显示，之后登录仍可查看和复制。"} />
        <div className="auth-code-auto-panel"><KeyOutlined /><div><b>{configured ? "生成新的随机授权码" : "自动创建随机授权码"}</b><small>{configured ? "点击按钮后立即替换当前授权码，新的完整值会直接显示在左侧。" : "生成后会自动写入连接信息，无需手动输入或重复确认。"}</small></div></div>
        <Button type="primary" icon={<ReloadOutlined />} loading={saving} onClick={() => void generate()}>{configured ? "重置并自动生成" : "自动生成授权码"}</Button>
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
    <div className="toolbar"><Space size={18}><Text strong>当前余额：<Text className="success-text">{loading ? "—" : balance} 分</Text></Text><Text type="secondary">最近积分变更摘要</Text></Space><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button></div>
    <Table rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={userTablePagination} locale={{ emptyText: <Empty description="暂无积分变更记录" /> }} scroll={{ x: 700 }} />
  </>;
}

function MailboxesPage() {
  const { message } = AntApp.useApp();
  const [items, setItems] = useState<UserMailbox[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");
  const [purpose, setPurpose] = useState("");
  const [mailboxStatus, setMailboxStatus] = useState("");
  const [verificationStatus, setVerificationStatus] = useState("");
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchForm] = Form.useForm<{ count: number; purpose: string; domain?: string }>();
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setItems(await userApi.mailboxes(appliedKeyword, purpose, mailboxStatus, verificationStatus)); }
    catch (err) { const value = getErrorMessage(err); setError(value); message.error(value); }
    finally { setLoading(false); }
  }, [appliedKeyword, mailboxStatus, message, purpose, verificationStatus]);
  useEffect(() => { void load(); }, [load]);

  const createBatch = async () => {
    const values = await batchForm.validateFields();
    setBatchLoading(true);
    try {
      const result = await userApi.createMailboxesBatch(values) as BatchCreateMailboxesResult;
      if (result.failed) {
        message.warning(`已创建 ${result.succeeded} 个，${result.failed} 个失败，请查看积分和邮箱列表`);
      } else {
        message.success(`已批量创建 ${result.succeeded} 个邮箱`);
      }
      setBatchOpen(false);
      batchForm.resetFields();
      await load();
    } catch (error) { message.error(getErrorMessage(error)); }
    finally { setBatchLoading(false); }
  };

  const columns: ColumnsType<UserMailbox> = [
    { title: "邮箱地址", dataIndex: "address", width: 245, render: (value) => <Text copyable>{value}</Text> },
    { title: "用途 / 来源", key: "purpose", width: 180, responsive: ["md"], render: (_, item) => <div className="mailbox-context"><b>{item.purpose || "未标记"}</b><span>（{item.source || "业务调用"}）</span></div> },
    { title: "域名", dataIndex: "domain", width: 170, responsive: ["lg"], render: (value) => value || "—" },
    { title: "状态", dataIndex: "status", width: 90, render: statusTag },
    {
      title: "验证码",
      key: "verification",
      width: 135,
      render: (_, item) => {
        const code = item.verification_code || item.verificationCode || "";
        const status = item.verification_status || item.verificationStatus;
        return code
          ? <Text code copyable={{ text: code }}>{code}</Text>
          : status === "received"
            ? <Tag>旧记录未保存</Tag>
            : statusTag(status);
      },
    },
    { title: "创建时间", key: "created_at", width: 170, render: (_, item) => <span className="mailbox-created-at">{formatTime(item.created_at || item.createdAt)}</span> },
    { title: "过期时间", key: "expires_at", width: 170, responsive: ["xl"], render: (_, item) => <span className="mailbox-created-at">{formatTime(item.expires_at || item.expiresAt)}</span> },
  ];

  return <>
    <div className="toolbar mailbox-toolbar"><div className="mailbox-filters"><Input.Search allowClear value={keyword} onChange={(event) => { const value = event.target.value; setKeyword(value); if (!value) setAppliedKeyword(""); }} onSearch={(value) => setAppliedKeyword(value.trim())} placeholder="搜索邮箱、域名或来源" style={{ width: 270 }} /><Select allowClear value={purpose || undefined} onChange={(value) => setPurpose(value || "")} placeholder="全部用途" style={{ width: 130 }} options={[{ value: "openai", label: "OpenAI" }, { value: "kiro", label: "Kiro" }, { value: "cursor", label: "Cursor" }, { value: "grok", label: "Grok" }]} /><Select allowClear value={mailboxStatus || undefined} onChange={(value) => setMailboxStatus(value || "")} placeholder="全部状态" style={{ width: 125 }} options={[{ value: "active", label: "使用中" }, { value: "expired", label: "已过期" }, { value: "released", label: "已释放" }]} /><Select allowClear value={verificationStatus || undefined} onChange={(value) => setVerificationStatus(value || "")} placeholder="验证码状态" style={{ width: 140 }} options={[{ value: "pending", label: "处理中" }, { value: "received", label: "已收到" }, { value: "timeout", label: "已超时" }, { value: "failed", label: "失败" }]} /></div><Space><Text type="secondary">{items.length} 条</Text><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setBatchOpen(true)}>批量创建</Button></Space></div>
    {error ? <ErrorState error={error} retry={() => void load()} /> : <Table className="dense-table" size="small" rowKey={(item) => item.id || item.mailbox_id || item.mailboxId || item.address} loading={loading} columns={columns} dataSource={items} pagination={userTablePagination} locale={{ emptyText: <Empty description="没有符合条件的邮箱记录" /> }} scroll={{ x: 980 }} />}
    <Modal title="批量创建 POP 邮箱" open={batchOpen} confirmLoading={batchLoading} okText="开始创建" cancelText="取消" onOk={() => void createBatch()} onCancel={() => { setBatchOpen(false); batchForm.resetFields(); }} destroyOnClose>
      <Alert className="form-alert" type="info" showIcon message="按当前积分规则逐个扣费" description="每个成功创建的邮箱都会保留在“我的邮箱”中，并可使用同一个用户级 POP 授权码读取。" />
      <Form form={batchForm} layout="vertical" requiredMark={false} initialValues={{ count: 5, purpose: "openai" }}>
        <Form.Item label="创建数量" name="count" rules={[{ required: true, message: "请输入创建数量" }]}><InputNumber min={1} max={50} precision={0} style={{ width: "100%" }} /></Form.Item>
        <Form.Item label="用途" name="purpose" rules={[{ required: true, message: "请选择用途" }]}><Select options={[{ value: "openai", label: "OpenAI" }, { value: "kiro", label: "Kiro" }, { value: "cursor", label: "Cursor" }, { value: "grok", label: "Grok" }]} /></Form.Item>
        <Form.Item label="指定域名（可选）" name="domain" rules={[{ max: 253, message: "域名长度不能超过 253 个字符" }]}><Input placeholder="留空则自动选择健康域名" /></Form.Item>
      </Form>
    </Modal>
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
  const sidebar = <><div className="console-brand user-console-brand"><div className="brand-mark"><UserOutlined /></div>{!collapsed && <div><b>Xiaoasi Mail</b><span>User Center</span></div>}</div><Menu theme="dark" mode="inline" selectedKeys={[page]} items={userNavItems} onClick={({ key }) => navigate(key)} /><div className="sider-footer"><div>{!collapsed && <span>USER CENTER<br />POP3 / 18110</span>}</div><TooltipLogout onLogout={logout} loading={loggingOut} /></div></>;

  return <Layout className="console-layout user-console-layout">
    <Sider className="desktop-sider user-sider" width={244} collapsedWidth={78} collapsed={collapsed} trigger={null}>{sidebar}</Sider>
    <Drawer className="mobile-drawer user-mobile-drawer" width={260} placement="left" open={mobileOpen} onClose={() => setMobileOpen(false)} closable={false}>{sidebar}</Drawer>
    <Layout>
      <Header className="console-header user-console-header"><Button className="desktop-collapse" type="text" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)} /><Button className="mobile-menu" type="text" icon={<MenuUnfoldOutlined />} onClick={() => setMobileOpen(true)} /><Text className="section-index header-console-name">USER WORKSPACE</Text><Badge status="success" text={`${displayName(currentUser)} · 用户会话已连接`} /></Header>
      <Content className="console-content"><div className="page-heading"><div><Title level={2}>{meta.title}</Title><Text>{meta.description}</Text></div></div><div className="page-body">{content}</div></Content>
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
