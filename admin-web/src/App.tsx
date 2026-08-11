import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  GlobalOutlined,
  InboxOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ThunderboltOutlined,
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
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { api, ApiError } from "./api";
import { UserPortal } from "./UserApp";
import type {
  AdminUser,
  CloudMailInstance,
  CreditRule,
  DomainPayload,
  InstancePayload,
  MailboxRecord,
  MailDomain,
  Overview,
  RequestLog,
} from "./types";

const { Header, Sider, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

type PageKey = "overview" | "instances" | "domains" | "users" | "creditSettings" | "mailboxes" | "logs" | "settings";

const navItems = [
  { key: "overview", icon: <DashboardOutlined />, label: "运行概览" },
  { key: "instances", icon: <CloudServerOutlined />, label: "CloudMail 实例" },
  { key: "domains", icon: <GlobalOutlined />, label: "邮箱域名" },
  { key: "users", icon: <UserOutlined />, label: "用户管理" },
  { key: "creditSettings", icon: <WalletOutlined />, label: "积分/POP 设置" },
  { key: "mailboxes", icon: <InboxOutlined />, label: "邮箱记录" },
  { key: "logs", icon: <DatabaseOutlined />, label: "请求日志" },
  { key: "settings", icon: <SettingOutlined />, label: "系统设置" },
];

const pageMeta: Record<PageKey, { title: string; description: string }> = {
  overview: { title: "运行概览", description: "实例、域名与邮箱链路的实时运行摘要" },
  instances: { title: "CloudMail 实例", description: "管理上游服务连接、凭据和可用状态" },
  domains: { title: "邮箱域名", description: "维护域名归属、选择权重与冷却状态" },
  users: { title: "用户管理", description: "查看用户状态、积分余额与 POP 授权配置" },
  creditSettings: { title: "积分/POP 设置", description: "配置邮箱积分规则与管理员全局 POP 授权码" },
  mailboxes: { title: "邮箱记录", description: "查看网关创建的邮箱及验证码处理状态" },
  logs: { title: "请求日志", description: "追踪业务请求、响应耗时与脱敏错误信息" },
  settings: { title: "系统设置", description: "查看部署模式、安全边界和运行参数入口" },
};

function formatTime(value?: string | null) {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "—";
}

function generatePopAuthCode(length = 32) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  const randomValues = new Uint8Array(length);
  window.crypto.getRandomValues(randomValues);
  return Array.from(randomValues, (value) => alphabet[value & 63]).join("");
}

function statusTag(status?: string) {
  const normalized = (status || "unknown").toLowerCase();
  const config: Record<string, { color: string; text: string }> = {
    healthy: { color: "success", text: "健康" },
    enabled: { color: "success", text: "启用" },
    active: { color: "processing", text: "活跃" },
    success: { color: "success", text: "成功" },
    received: { color: "success", text: "已收到" },
    unhealthy: { color: "error", text: "异常" },
    failed: { color: "error", text: "失败" },
    disabled: { color: "default", text: "停用" },
    cooldown: { color: "warning", text: "冷却中" },
    pending: { color: "processing", text: "等待中" },
    timeout: { color: "warning", text: "已超时" },
    released: { color: "default", text: "已释放" },
    unknown: { color: "default", text: "未检测" },
  };
  const item = config[normalized] || { color: "default", text: status || "未知" };
  return <Tag color={item.color}>{item.text}</Tag>;
}

function domainStatusTag(domain: MailDomain) {
  const normalized = (domain.status || "unknown").toLowerCase();
  const hasRuntimeResult = domain.success_count > 0 || domain.failure_total > 0;
  const config: Record<string, { color: string; text: string }> = {
    healthy: { color: "success", text: "运行正常" },
    unhealthy: { color: "error", text: "运行异常" },
    disabled: { color: "default", text: "已停用" },
    cooldown: { color: "warning", text: "冷却中" },
    unknown: { color: hasRuntimeResult ? "warning" : "default", text: hasRuntimeResult ? "观察中" : "待首次调用" },
  };
  const item = config[normalized] || { color: "default", text: domain.status || "状态未知" };
  const explanation = normalized === "unknown"
    ? hasRuntimeResult
      ? "该域名最近出现过失败，但尚未达到冷却阈值，后续调用结果会继续更新状态。"
      : "该域名尚未经历真实的创建邮箱调用，首次调用后会根据结果自动更新状态。"
    : "该状态由真实的创建邮箱调用结果自动更新。";
  return <Tooltip title={explanation}><Tag color={item.color}>{item.text}</Tag></Tooltip>;
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "请求失败，请稍后重试";
}

function LoadingState() {
  return <div className="state-panel"><Spin size="large" /><Text type="secondary">正在读取网关数据…</Text></div>;
}

function ErrorState({ error, retry }: { error: string; retry: () => void }) {
  return <Alert showIcon type="error" message="数据加载失败" description={error} action={<Button onClick={retry}>重新加载</Button>} />;
}

function Login({ onSuccess }: { onSuccess: () => void }) {
  const { message } = AntApp.useApp();
  const [loading, setLoading] = useState(false);

  const submit = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await api.login(values.username, values.password);
      message.success("登录成功");
      onSuccess();
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-brand">
        <div className="brand-mark large"><ApiOutlined /></div>
        <div>
          <Text className="eyebrow">XIAOASI INFRASTRUCTURE</Text>
          <Title>邮箱基础设施<br />控制平面</Title>
          <Paragraph>统一调度多个 CloudMail 实例与域名池，业务调用者无需感知内部实现。</Paragraph>
        </div>
        <div className="signal-grid" aria-hidden="true">
          {Array.from({ length: 18 }).map((_, index) => <i key={index} />)}
        </div>
      </section>
      <section className="login-panel">
        <div className="login-form-wrap">
          <Text className="section-index">CONTROL / 01</Text>
          <Title level={2}>管理员登录</Title>
          <Paragraph type="secondary">使用部署时配置的管理端账号进入控制台。</Paragraph>
          <Form layout="vertical" onFinish={submit} requiredMark={false} size="large">
            <Form.Item label="管理员账号" name="username" rules={[{ required: true, message: "请输入管理员账号" }]}>
              <Input autoComplete="username" placeholder="admin" />
            </Form.Item>
            <Form.Item label="管理员密码" name="password" rules={[{ required: true, message: "请输入管理员密码" }]}>
              <Input.Password autoComplete="current-password" placeholder="输入管理端密码" />
            </Form.Item>
            <Button block type="primary" htmlType="submit" loading={loading}>进入控制台</Button>
          </Form>
          <div className="secure-note"><SafetyCertificateOutlined /> 会话使用 HttpOnly Cookie，不在浏览器存储管理密钥</div>
        </div>
      </section>
    </main>
  );
}

function OverviewPage() {
  const [data, setData] = useState<Overview>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setData(await api.overview()); } catch (e) { setError(getErrorMessage(e)); } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} retry={load} />;
  if (!data) return <Empty description="暂无概览数据" />;

  const healthRate = data.instance_total ? Math.round((data.instance_healthy / data.instance_total) * 100) : 0;
  return (
    <div className="overview-grid">
      <Card className="hero-card">
        <div>
          <Text className="section-index">GATEWAY STATUS</Text>
          <Title level={2}>{data.error_total ? "链路存在待处理异常" : "邮箱网关运行平稳"}</Title>
          <Paragraph>当前已连接 {data.instance_total} 个上游实例，启用 {data.domain_enabled} 个可选域名。</Paragraph>
        </div>
        <div className={`health-dial ${data.error_total ? "warn" : ""}`}>
          <strong>{healthRate}%</strong><span>实例健康率</span>
        </div>
      </Card>
      <div className="metric-row">
        <Card><Statistic title="实例总数" value={data.instance_total} suffix={<small>/ {data.instance_enabled} 启用</small>} prefix={<CloudServerOutlined />} /></Card>
        <Card><Statistic title="可用域名" value={data.domain_enabled} suffix={<small>/ {data.domain_total} 总计</small>} prefix={<GlobalOutlined />} /></Card>
        <Card><Statistic title="累计邮箱" value={data.mailbox_total} prefix={<InboxOutlined />} /></Card>
        <Card className={data.error_total ? "metric-danger" : ""}><Statistic title="错误记录" value={data.error_total} prefix={<ThunderboltOutlined />} /></Card>
      </div>
      <Card title="调度链路" className="flow-card">
        <div className="flow-line">
          <div><ApiOutlined /><b>业务调用方</b><span>统一 Xiaoasi Mail API</span></div><i />
          <div><ThunderboltOutlined /><b>网关调度</b><span>过滤、权重与失败切换</span></div><i />
          <div><CloudServerOutlined /><b>CloudMail</b><span>{data.instance_healthy} 个健康实例</span></div><i />
          <div><InboxOutlined /><b>邮箱结果</b><span>标准化验证码响应</span></div>
        </div>
      </Card>
      {data.instance_total === 0 && <Alert showIcon type="info" message="尚未配置 CloudMail 实例" description="请先新增实例，再为实例配置可用邮箱域名。" />}
    </div>
  );
}

type InstanceDomainForm = Omit<DomainPayload, "instance_id">;

function InstanceDomainsPanel({ instanceId, onChanged }: { instanceId: number; onChanged: () => Promise<void> }) {
  const { message } = AntApp.useApp();
  const [items, setItems] = useState<MailDomain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MailDomain>();
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<InstanceDomainForm>();

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setItems(await api.domains(instanceId)); }
    catch (e) { setError(getErrorMessage(e)); }
    finally { setLoading(false); }
  }, [instanceId]);
  useEffect(() => { void load(); }, [load]);

  const openCreate = () => {
    setEditing(undefined);
    form.resetFields();
    form.setFieldsValue({ enabled: true, weight: 100, remark: "" });
    setModalOpen(true);
  };
  const openEdit = (record: MailDomain) => {
    setEditing(record);
    form.setFieldsValue({ domain: record.domain, enabled: record.enabled, weight: record.weight, remark: record.remark });
    setModalOpen(true);
  };
  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) await api.updateDomain(editing.id, values);
      else await api.createDomain({ ...values, instance_id: instanceId });
      message.success(editing ? "邮箱域名已更新" : "邮箱域名已添加到当前实例");
      setModalOpen(false);
      await Promise.all([load(), onChanged()]);
    } catch (e) { message.error(getErrorMessage(e)); }
    finally { setSaving(false); }
  };
  const remove = async (id: number) => {
    try {
      await api.deleteDomain(id);
      message.success("邮箱域名已删除");
      await Promise.all([load(), onChanged()]);
    } catch (e) { message.error(getErrorMessage(e)); }
  };

  const columns: ColumnsType<MailDomain> = [
    { title: "邮箱域名", key: "domain", render: (_, r) => <div className="primary-cell"><b>{r.domain}</b><span>{r.remark || "无备注"}</span></div> },
    { title: "权重", dataIndex: "weight", width: 70 },
    { title: "调度", dataIndex: "enabled", width: 82, render: (enabled: boolean) => <Badge status={enabled ? "success" : "default"} text={enabled ? "启用" : "停用"} /> },
    { title: "操作", key: "actions", width: 126, render: (_, r) => <Space size={4}><Button type="link" size="small" onClick={() => openEdit(r)}>编辑</Button><Popconfirm title="确认删除该域名？" onConfirm={() => void remove(r.id)}><Button type="link" size="small" danger>删除</Button></Popconfirm></Space> },
  ];

  return <Card className="instance-domains-card" title={<span><GlobalOutlined /> 当前实例的邮箱域名</span>} extra={<Button type="primary" ghost size="small" icon={<PlusOutlined />} onClick={openCreate}>添加域名</Button>}>
    <Text type="secondary">调用方指定域名或自动分配邮箱时，网关会通过这里的归属关系选择当前 CloudMail 实例。</Text>
    {error && <Alert className="embedded-alert" type="error" showIcon message="域名列表加载失败" description={error} action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
    <Table className="embedded-table" rowKey="id" size="small" loading={loading} columns={columns} dataSource={items} pagination={false} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前实例还没有邮箱域名" /> }} scroll={{ x: 500 }} />
    <Modal title={editing ? "编辑当前实例的邮箱域名" : "为当前实例添加邮箱域名"} open={modalOpen} confirmLoading={saving} onOk={() => void submit()} onCancel={() => setModalOpen(false)} okText="保存" cancelText="取消" destroyOnClose>
      <Alert className="form-alert" type="info" showIcon message="域名将自动绑定到当前 CloudMail 实例，无需再次选择实例。" />
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item label="邮箱域名" name="domain" rules={[{ required: true, message: "请输入邮箱域名" }, { pattern: /^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/, message: "请输入有效域名" }]}><Input placeholder="例如：mail.example.com" /></Form.Item>
        <Form.Item label="调度权重" name="weight" tooltip="权重越大，自动选择时被选中的概率越高" rules={[{ required: true }]}><InputNumber min={1} max={10000} style={{ width: "100%" }} /></Form.Item>
        <Form.Item label="管理备注" name="remark"><Input.TextArea rows={3} maxLength={500} showCount /></Form.Item>
        <Form.Item label="参与邮箱调度" name="enabled" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
  </Card>;
}

function InstancesPage() {
  const { message } = AntApp.useApp();
  const [items, setItems] = useState<CloudMailInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<CloudMailInstance>();
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<number>();
  const [form] = Form.useForm<InstancePayload>();

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setItems(await api.instances()); } catch (e) { setError(getErrorMessage(e)); } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const openCreate = () => { setEditing(undefined); form.resetFields(); form.setFieldsValue({ verify_tls: true, enabled: true, proxy_url: "" }); setDrawerOpen(true); };
  const openEdit = (record: CloudMailInstance) => {
    setEditing(record);
    form.setFieldsValue({ name: record.name, base_url: record.base_url, admin_email: record.admin_email, admin_password: "", proxy_url: record.proxy_url || "", verify_tls: record.verify_tls, enabled: record.enabled });
    setDrawerOpen(true);
  };
  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        const payload = { ...values };
        if (!payload.admin_password) delete payload.admin_password;
        await api.updateInstance(editing.id, payload);
        message.success("实例已更新"); setDrawerOpen(false); await load();
      } else {
        const created = await api.createInstance(values);
        setEditing(created.data);
        form.setFieldsValue({ ...values, admin_password: "" });
        message.success("实例已创建，请继续为该实例添加邮箱域名");
        await load();
      }
    } catch (e) { message.error(getErrorMessage(e)); } finally { setSaving(false); }
  };
  const test = async (id: number) => {
    setTestingId(id);
    try { const result = await api.testInstance(id); message.success(result.data.message || `连接成功${result.data.latency_ms ? `，耗时 ${result.data.latency_ms}ms` : ""}`); await load(); }
    catch (e) { message.error(getErrorMessage(e)); } finally { setTestingId(undefined); }
  };
  const remove = async (id: number) => { try { await api.deleteInstance(id); message.success("实例已删除"); await load(); } catch (e) { message.error(getErrorMessage(e)); } };

  const columns: ColumnsType<CloudMailInstance> = [
    { title: "实例", key: "name", render: (_, r) => <div className="primary-cell"><b>{r.name}</b><span>{r.base_url}</span></div> },
    { title: "管理员邮箱", dataIndex: "admin_email", responsive: ["lg"] },
    { title: "域名", dataIndex: "domain_count", width: 90, render: (v) => `${v || 0} 个` },
    { title: "状态", key: "status", width: 110, render: (_, r) => <Space direction="vertical" size={2}>{statusTag(r.health_status)}<Badge status={r.enabled ? "success" : "default"} text={r.enabled ? "已启用" : "已停用"} /></Space> },
    { title: "最近检测", dataIndex: "last_checked_at", width: 170, responsive: ["xl"], render: formatTime },
    { title: "操作", key: "actions", width: 250, render: (_, r) => <Space wrap>
      <Button size="small" icon={<ThunderboltOutlined />} loading={testingId === r.id} onClick={() => void test(r.id)}>测试</Button>
      <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
      <Popconfirm title="确认删除该实例？" description="实例下存在域名时也会一并删除，请谨慎操作。" onConfirm={() => void remove(r.id)}><Button size="small" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm>
    </Space> },
  ];

  return <>
    <div className="toolbar"><Text type="secondary">共 {items.length} 个实例</Text><Space><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增实例</Button></Space></div>
    {error ? <ErrorState error={error} retry={load} /> : <Table rowKey="id" loading={loading} columns={columns} dataSource={items} locale={{ emptyText: <Empty description="暂无 CloudMail 实例" /> }} scroll={{ x: 920 }} />}
    <Drawer title={editing ? "编辑 CloudMail 实例" : "新增 CloudMail 实例"} width={620} open={drawerOpen} onClose={() => setDrawerOpen(false)} extra={<Space><Button onClick={() => setDrawerOpen(false)}>{editing ? "关闭" : "取消"}</Button><Button type="primary" loading={saving} onClick={() => void submit()}>{editing ? "保存实例" : "创建并配置域名"}</Button></Space>}>
      <Alert className="form-alert" type="info" showIcon message="管理员密码加密保存，保存后不会返回前端。编辑时留空表示不修改。" />
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item label="实例名称" name="name" rules={[{ required: true, message: "请输入实例名称" }]}><Input placeholder="例如：CloudMail 主实例" /></Form.Item>
        <Form.Item label="API 地址" name="base_url" rules={[{ required: true }, { type: "url", message: "请输入完整的 HTTP(S) 地址" }]}><Input placeholder="https://mail.example.com" /></Form.Item>
        <Form.Item label="管理员邮箱" name="admin_email" rules={[{ required: true }, { type: "email" }]}><Input /></Form.Item>
        <Form.Item label="管理员密码" name="admin_password" rules={editing ? [] : [{ required: true, message: "请输入管理员密码" }]}><Input.Password autoComplete="new-password" placeholder={editing ? "留空表示不修改" : "用于网关调用上游接口"} /></Form.Item>
        <Form.Item label="代理地址（可选）" name="proxy_url"><Input placeholder="http://mihomo:11004" /></Form.Item>
        <div className="switch-row"><Form.Item label="校验 TLS 证书" name="verify_tls" valuePropName="checked"><Switch /></Form.Item><Form.Item label="参与邮箱调度" name="enabled" valuePropName="checked"><Switch /></Form.Item></div>
      </Form>
      {editing && <InstanceDomainsPanel instanceId={editing.id} onChanged={load} />}
    </Drawer>
  </>;
}

function DomainsPage() {
  const { message } = AntApp.useApp();
  const [items, setItems] = useState<MailDomain[]>([]);
  const [instances, setInstances] = useState<CloudMailInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [domainError, setDomainError] = useState("");
  const [instanceError, setInstanceError] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<MailDomain>();
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<DomainPayload>();

  const load = useCallback(async () => {
    setLoading(true); setDomainError(""); setInstanceError("");
    const [domainsResult, instancesResult] = await Promise.allSettled([api.domains(), api.instances()]);
    if (domainsResult.status === "fulfilled") setItems(domainsResult.value);
    else setDomainError(getErrorMessage(domainsResult.reason));
    if (instancesResult.status === "fulfilled") setInstances(instancesResult.value);
    else setInstanceError(getErrorMessage(instancesResult.reason));
    setLoading(false);
  }, []);
  useEffect(() => { void load(); }, [load]);
  const openCreate = () => { setEditing(undefined); form.resetFields(); form.setFieldsValue({ enabled: true, weight: 100, remark: "" }); setDrawerOpen(true); };
  const openEdit = (record: MailDomain) => { setEditing(record); form.setFieldsValue(record); setDrawerOpen(true); };
  const submit = async () => {
    const values = await form.validateFields(); setSaving(true);
    try { editing ? await api.updateDomain(editing.id, values) : await api.createDomain(values); message.success(editing ? "域名已更新" : "域名已创建"); setDrawerOpen(false); await load(); }
    catch (e) { message.error(getErrorMessage(e)); } finally { setSaving(false); }
  };
  const remove = async (id: number) => { try { await api.deleteDomain(id); message.success("域名已删除"); await load(); } catch (e) { message.error(getErrorMessage(e)); } };
  const clearCooldown = async (id: number) => { try { await api.clearDomainCooldown(id); message.success("冷却状态已清除"); await load(); } catch (e) { message.error(getErrorMessage(e)); } };
  const columns: ColumnsType<MailDomain> = [
    { title: "邮箱域名", key: "domain", render: (_, r) => <div className="primary-cell"><b>{r.domain}</b><span>{r.remark || "无备注"}</span></div> },
    { title: "所属实例", dataIndex: "instance_name", responsive: ["md"] },
    { title: "权重", dataIndex: "weight", width: 90 },
    { title: <Tooltip title="域名状态来自真实的创建邮箱调用，不会额外创建测试邮箱。">运行状态</Tooltip>, key: "status", width: 130, render: (_, r) => <Space direction="vertical" size={2}>{domainStatusTag(r)}<Badge status={r.enabled ? "success" : "default"} text={r.enabled ? "参与调度" : "已停用"} /></Space> },
    { title: "成功 / 失败", key: "stats", width: 130, responsive: ["lg"], render: (_, r) => <Text><span className="success-text">{r.success_count}</span> / <span className="error-text">{r.failure_total}</span></Text> },
    { title: "冷却截止", dataIndex: "cooldown_until", width: 170, responsive: ["xl"], render: formatTime },
    { title: "操作", key: "actions", width: 230, render: (_, r) => <Space wrap><Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>{r.cooldown_until && <Button size="small" onClick={() => void clearCooldown(r.id)}>解除冷却</Button>}<Popconfirm title="确认删除该域名？" onConfirm={() => void remove(r.id)}><Button size="small" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space> },
  ];
  return <>
    <div className="toolbar"><div className="toolbar-copy"><Text type="secondary">共 {items.length} 个域名，自动模式按启用状态与权重选择</Text><Text type="secondary">“待首次调用”表示尚未通过该域名创建邮箱，首次真实调用后会自动更新运行状态。</Text></div><Space><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button type="primary" icon={<PlusOutlined />} disabled={!instances.length} onClick={openCreate}>新增域名</Button></Space></div>
    {domainError && <Alert className="page-alert" type="error" showIcon message="邮箱域名加载失败" description={domainError} action={<Button size="small" onClick={() => void load()}>重新加载</Button>} />}
    {instanceError && <Alert className="page-alert" type="error" showIcon message="CloudMail 实例加载失败" description={`${instanceError}，暂时不能新增或调整域名归属。`} action={<Button size="small" onClick={() => void load()}>重新加载</Button>} />}
    {!instances.length && !loading && !instanceError && <Alert className="page-alert" type="warning" showIcon message="请先创建 CloudMail 实例，再添加邮箱域名。" />}
    <Table rowKey="id" loading={loading} columns={columns} dataSource={items} locale={{ emptyText: <Empty description={domainError ? "域名数据暂不可用" : "暂无邮箱域名"} /> }} scroll={{ x: 920 }} />
    <Drawer title={editing ? "编辑邮箱域名" : "新增邮箱域名"} width={480} open={drawerOpen} onClose={() => setDrawerOpen(false)} extra={<Space><Button onClick={() => setDrawerOpen(false)}>取消</Button><Button type="primary" loading={saving} onClick={() => void submit()}>保存</Button></Space>}>
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item label="所属实例" name="instance_id" rules={[{ required: true, message: "请选择 CloudMail 实例" }]}><Select options={instances.map((item) => ({ value: item.id, label: item.name, disabled: !item.enabled }))} placeholder="选择负责该域名的实例" /></Form.Item>
        <Form.Item label="邮箱域名" name="domain" rules={[{ required: true, message: "请输入邮箱域名" }, { pattern: /^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/, message: "请输入有效域名" }]}><Input placeholder="mail.example.com" /></Form.Item>
        <Form.Item label="调度权重" name="weight" tooltip="权重越大，在自动选择时被选中的概率越高" rules={[{ required: true }]}><InputNumber min={1} max={10000} style={{ width: "100%" }} /></Form.Item>
        <Form.Item label="管理备注" name="remark"><Input.TextArea rows={3} maxLength={500} showCount /></Form.Item>
        <Form.Item label="参与邮箱调度" name="enabled" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Drawer>
  </>;
}

function UsersPage() {
  const { message } = AntApp.useApp();
  const [items, setItems] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [adjustingUser, setAdjustingUser] = useState<AdminUser>();
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<{ amount: number; reason: string }>();

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setItems(await api.users()); }
    catch (e) { setError(getErrorMessage(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const updateStatus = async (user: AdminUser, enabled: boolean) => {
    try { await api.updateUser(user.id, enabled); message.success(enabled ? "用户已启用" : "用户已停用"); await load(); }
    catch (e) { message.error(getErrorMessage(e)); }
  };
  const clearAuthCode = async (user: AdminUser) => {
    try { await api.resetUserAuthCode(user.id); message.success("用户 POP 授权码已清除"); await load(); }
    catch (e) { message.error(getErrorMessage(e)); }
  };
  const adjustCredits = async () => {
    const values = await form.validateFields();
    if (!values.amount) { message.error("积分调整数量不能为 0"); return; }
    setSaving(true);
    try {
      await api.adjustUserCredits(adjustingUser!.id, values.amount, values.reason.trim());
      message.success("用户积分已调整");
      setAdjustingUser(undefined);
      form.resetFields();
      await load();
    } catch (e) { message.error(getErrorMessage(e)); }
    finally { setSaving(false); }
  };

  const columns: ColumnsType<AdminUser> = [
    { title: "用户", key: "user", width: 280, render: (_, user) => <div className="user-identity-cell"><span className={`user-avatar ${user.role === "admin" ? "admin" : ""}`}>{(user.username || "U").slice(0, 1).toUpperCase()}</span><div><div className="user-name-line"><b>{user.username}</b><span className={`role-pill ${user.role === "admin" ? "admin" : "user"}`}>{user.role === "admin" ? "管理员" : "普通用户"}</span></div><small>{user.email || "未绑定邮箱"}<i>·</i>ID #{user.id}</small></div></div> },
    { title: "状态", key: "status", width: 105, render: (_, user) => user.role === "admin" ? statusTag(user.status) : <Switch size="small" checked={user.status === "active"} onChange={(enabled) => void updateStatus(user, enabled)} checkedChildren="启用" unCheckedChildren="停用" /> },
    { title: "积分", dataIndex: "credit_balance", width: 95, render: (value: number) => <Text className={value > 0 ? "success-text" : value < 0 ? "error-text" : ""} strong>{value} 分</Text> },
    { title: "POP 授权码", key: "pop", width: 120, render: (_, user) => user.role === "admin" ? <Tag color={user.has_admin_pop_auth_code ? "success" : "default"}>{user.has_admin_pop_auth_code ? "已配置" : "未配置"}</Tag> : <Tag color={user.has_user_auth_code ? "success" : "default"}>{user.has_user_auth_code ? "已配置" : "未配置"}</Tag> },
    { title: "调用密钥", key: "api_key_count", width: 90, render: (_, user) => `${user.api_key_count || 0} 个` },
    { title: "创建时间", dataIndex: "created_at", width: 170, render: (value) => <span className="mailbox-created-at">{formatTime(value)}</span> },
    { title: "操作", key: "actions", width: 225, render: (_, user) => user.role === "admin" ? <Tag>系统账号</Tag> : <Space size={6} wrap><Button size="small" icon={<WalletOutlined />} onClick={() => { setAdjustingUser(user); form.setFieldsValue({ amount: 0, reason: "" }); }}>调整积分</Button>{user.has_user_auth_code && <Popconfirm title="清除后该用户的 POP 授权码立即失效，确认继续？" onConfirm={() => void clearAuthCode(user)}><Button size="small" danger icon={<SafetyCertificateOutlined />}>清除授权码</Button></Popconfirm>}</Space> },
  ];

  return <>
    <div className="toolbar"><Text type="secondary">共 {items.length} 个账号，可停用用户、调整积分或清除 POP 授权码</Text><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button></div>
    {error ? <ErrorState error={error} retry={load} /> : <Table className="dense-table user-management-table" size="small" rowKey="id" loading={loading} columns={columns} dataSource={items} locale={{ emptyText: <Empty description="暂无用户数据" /> }} scroll={{ x: 1085 }} />}
    <Modal title={`调整 ${adjustingUser?.username || "用户"} 的积分`} open={Boolean(adjustingUser)} confirmLoading={saving} okText="提交调整" cancelText="取消" onOk={() => void adjustCredits()} onCancel={() => { setAdjustingUser(undefined); form.resetFields(); }} destroyOnClose>
      <Alert className="form-alert" type="info" showIcon message="可增加或扣减积分" description="输入正数增加积分，输入负数扣减积分；余额不能低于 0。" />
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item label="调整数量" name="amount" rules={[{ required: true, message: "请输入积分数量" }]}><InputNumber style={{ width: "100%" }} precision={0} placeholder="例如：100 或 -50" /></Form.Item>
        <Form.Item label="调整原因" name="reason" rules={[{ required: true, message: "请输入调整原因" }, { max: 500, message: "原因不能超过 500 个字符" }]}><Input.TextArea rows={4} maxLength={500} showCount placeholder="例如：活动补发积分" /></Form.Item>
      </Form>
    </Modal>
  </>;
}

function CreditSettingsPage() {
  const { message } = AntApp.useApp();
  const [rule, setRule] = useState<CreditRule>();
  const [adminPopConfigured, setAdminPopConfigured] = useState(false);
  const [adminPopCode, setAdminPopCode] = useState("");
  const [legacyHashOnly, setLegacyHashOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savingRule, setSavingRule] = useState(false);
  const [savingPop, setSavingPop] = useState(false);
  const [popCodeVisible, setPopCodeVisible] = useState(false);
  const [ruleForm] = Form.useForm<Pick<CreditRule, "cost_points" | "initial_user_points">>();
  const [popForm] = Form.useForm<{ auth_code?: string; confirm?: string }>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextRule, popConfig] = await Promise.all([api.creditRules(), api.adminPopAuthCode()]);
      setRule(nextRule);
      ruleForm.setFieldsValue({ cost_points: nextRule.cost_points, initial_user_points: nextRule.initial_user_points });
      setAdminPopConfigured(Boolean(popConfig.configured));
      setAdminPopCode(popConfig.admin_pop_auth_code || "");
      setLegacyHashOnly(Boolean(popConfig.legacy_hash_only));
      if (popConfig.admin_pop_auth_code) {
        popForm.setFieldsValue({ auth_code: popConfig.admin_pop_auth_code, confirm: popConfig.admin_pop_auth_code });
      } else {
        popForm.resetFields();
      }
    } catch (e) { message.error(getErrorMessage(e)); }
    finally { setLoading(false); }
  }, [message, popForm, ruleForm]);
  useEffect(() => { void load(); }, [load]);

  const saveRule = async () => {
    const values = await ruleForm.validateFields();
    setSavingRule(true);
    try { const saved = await api.updateCreditRules(values); setRule(saved); message.success("积分规则已保存"); }
    catch (e) { message.error(getErrorMessage(e)); }
    finally { setSavingRule(false); }
  };
  const fillGeneratedPopCode = () => {
    const generated = generatePopAuthCode();
    popForm.setFields([
      { name: "auth_code", value: generated, errors: [] },
      { name: "confirm", value: generated, errors: [] },
    ]);
    setPopCodeVisible(true);
    message.success("已生成高强度授权码，可查看确认后再保存");
  };
  const savePopCode = async (values: { auth_code?: string; confirm?: string }) => {
    let authCode = values.auth_code?.trim() || "";
    const confirm = values.confirm?.trim() || "";
    popForm.setFields([{ name: "auth_code", errors: [] }, { name: "confirm", errors: [] }]);

    if (!authCode && !confirm) {
      authCode = generatePopAuthCode();
    } else if (!authCode || !confirm) {
      popForm.setFields([
        { name: "auth_code", errors: authCode ? [] : ["请输入授权码，或清空两个输入框自动生成"] },
        { name: "confirm", errors: confirm ? [] : ["请确认授权码，或清空两个输入框自动生成"] },
      ]);
      return;
    } else if (authCode.length < 10) {
      popForm.setFields([{ name: "auth_code", errors: ["授权码至少 10 位"] }]);
      return;
    } else if (authCode !== confirm) {
      popForm.setFields([{ name: "confirm", errors: ["两次输入的授权码不一致"] }]);
      return;
    }

    setSavingPop(true);
    try {
      const result = await api.setAdminPopAuthCode(authCode);
      const savedCode = result.data.admin_pop_auth_code || authCode;
      setAdminPopCode(savedCode);
      setAdminPopConfigured(true);
      setLegacyHashOnly(false);
      popForm.setFieldsValue({ auth_code: savedCode, confirm: savedCode });
      setPopCodeVisible(true);
      message.success(adminPopConfigured ? "全局 POP 授权码已更新，可随时查看" : "全局 POP 授权码已设置，可随时查看");
      await load();
    } catch (e) { message.error(getErrorMessage(e)); }
    finally { setSavingPop(false); }
  };

  return <>
    <div className="admin-settings-grid">
      <Card className="admin-setting-card" title={<span><WalletOutlined /> 邮箱积分规则</span>} loading={loading} extra={rule && <Text type="secondary">更新于 {formatTime(rule.updated_at)}</Text>}>
        <Alert className="form-alert" type="info" showIcon message="规则作用于新建邮箱" description="每次创建邮箱会按单次费用扣除积分；新用户初始积分也从这里读取。" />
        <Form form={ruleForm} layout="vertical" requiredMark={false}>
          <Form.Item label="创建邮箱扣除积分" name="cost_points" rules={[{ required: true, message: "请输入扣除积分" }]}><InputNumber min={0} precision={0} style={{ width: "100%" }} addonAfter="分 / 次" /></Form.Item>
          <Form.Item label="新用户初始积分" name="initial_user_points" rules={[{ required: true, message: "请输入初始积分" }]}><InputNumber min={0} precision={0} style={{ width: "100%" }} addonAfter="分" /></Form.Item>
          <Button type="primary" loading={savingRule} onClick={() => void saveRule()}>保存积分规则</Button>
        </Form>
      </Card>
      <Card className="admin-setting-card admin-pop-card" title={<span><SafetyCertificateOutlined /> 管理员全局 POP 授权码</span>} loading={loading}>
        <div className={`admin-pop-status ${adminPopConfigured ? "ready" : "not-ready"}`}><span className="auth-status-dot" /><div><b>{adminPopConfigured ? "已配置全局授权码" : "尚未配置全局授权码"}</b><small>管理员使用该授权码登录 POP3 时，可读取系统中全部可查询邮箱。</small></div></div>
        {legacyHashOnly && <Alert className="admin-pop-legacy-alert" type="warning" showIcon message="当前是旧版哈希数据，无法还原明文" description="请重新输入或自动生成一次。保存后会改为明文存储，之后可在本页随时查看和复制。" />}
        {adminPopCode && <div className="admin-pop-current"><div><Text>当前明文授权码</Text><small>该值直接保存在数据库中</small></div><Text code copyable={{ text: adminPopCode }}>{popCodeVisible ? adminPopCode : "••••••••••••••••"}</Text><Button type="link" onClick={() => setPopCodeVisible((visible) => !visible)}>{popCodeVisible ? "隐藏" : "显示"}</Button></div>}
        <Form form={popForm} layout="vertical" requiredMark={false} onFinish={savePopCode} className="admin-pop-form">
          <div className="admin-pop-helper"><Text>授权码按明文保存，可随时查看和复制；两个输入框都留空时，点击保存会自动生成。</Text><Button type="link" onClick={() => setPopCodeVisible((visible) => !visible)}>{popCodeVisible ? "隐藏输入内容" : "显示输入内容"}</Button></div>
          <Form.Item label={adminPopConfigured ? "修改全局 POP 授权码" : "全局 POP 授权码"} name="auth_code"><Input.Password autoComplete="new-password" visibilityToggle={{ visible: popCodeVisible, onVisibleChange: setPopCodeVisible }} placeholder="手动输入，或留空自动生成" /></Form.Item>
          <Form.Item label="确认授权码" name="confirm"><Input.Password autoComplete="new-password" visibilityToggle={{ visible: popCodeVisible, onVisibleChange: setPopCodeVisible }} placeholder="再次输入；自动生成时可留空" /></Form.Item>
          <Space className="admin-pop-actions" wrap>
            <Button type="primary" htmlType="submit" loading={savingPop}>{adminPopConfigured ? "保存当前授权码" : "保存或自动生成授权码"}</Button>
            <Button icon={<ThunderboltOutlined />} onClick={fillGeneratedPopCode} disabled={savingPop}>自动生成并填入</Button>
          </Space>
        </Form>
      </Card>
    </div>
  </>;
}

function MailboxesPage() {
  const [items, setItems] = useState<MailboxRecord[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [keyword, setKeyword] = useState(""); const [appliedKeyword, setAppliedKeyword] = useState(""); const [purpose, setPurpose] = useState("");
  const load = useCallback(async () => { setLoading(true); setError(""); try { setItems(await api.mailboxes(100, 0, appliedKeyword, purpose)); } catch (e) { setError(getErrorMessage(e)); } finally { setLoading(false); } }, [appliedKeyword, purpose]);
  useEffect(() => { void load(); }, [load]);
  const columns: ColumnsType<MailboxRecord> = [
    { title: "邮箱地址", dataIndex: "address", width: 225, render: (v) => <Text copyable>{v}</Text> },
    { title: "用途 / 调用方", key: "source", width: 165, responsive: ["md"], render: (_, r) => <div className="mailbox-context"><b>{r.purpose || "未标记"}</b><span>（{r.source || "未知调用方"}）</span></div> },
    { title: "域名 / 实例", key: "route", width: 210, responsive: ["lg"], render: (_, r) => <div className="mailbox-context route"><b>{r.domain || "—"}</b><span>（{r.instance_name || "未绑定实例"}）</span></div> },
    { title: "状态", dataIndex: "status", width: 85, render: statusTag },
    {
      title: "验证码",
      key: "verification_code",
      width: 125,
      render: (_, record) => record.verification_code
        ? <Text code copyable={{ text: record.verification_code }}>{record.verification_code}</Text>
        : record.verification_status === "received"
          ? <Tag>旧记录未保存</Tag>
          : statusTag(record.verification_status),
    },
    { title: "创建时间", dataIndex: "created_at", width: 165, render: (value) => <span className="mailbox-created-at">{formatTime(value)}</span> },
  ];
  return <><div className="toolbar"><div className="mailbox-filters"><Input.Search allowClear value={keyword} onChange={(event) => { const value = event.target.value; setKeyword(value); if (!value) setAppliedKeyword(""); }} onSearch={(value) => setAppliedKeyword(value.trim())} placeholder="搜索邮箱、域名或调用方" style={{ width: 280 }} /><Select allowClear value={purpose || undefined} onChange={(value) => setPurpose(value || "")} placeholder="全部类型" style={{ width: 140 }} options={[{ value: "openai", label: "OpenAI" }, { value: "kiro", label: "Kiro" }, { value: "cursor", label: "Cursor" }, { value: "grok", label: "Grok" }]} /></div><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button></div>{error ? <ErrorState error={error} retry={load} /> : <Table className="dense-table" size="small" rowKey="id" loading={loading} columns={columns} dataSource={items} locale={{ emptyText: <Empty description="没有符合条件的邮箱记录" /> }} scroll={{ x: 975 }} />}</>;
}

function LogsPage() {
  const [items, setItems] = useState<RequestLog[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [keyword, setKeyword] = useState(""); const [appliedKeyword, setAppliedKeyword] = useState(""); const [statusGroup, setStatusGroup] = useState("");
  const load = useCallback(async () => { setLoading(true); setError(""); try { setItems(await api.requestLogs(100, 0, appliedKeyword, statusGroup)); } catch (e) { setError(getErrorMessage(e)); } finally { setLoading(false); } }, [appliedKeyword, statusGroup]);
  useEffect(() => { void load(); }, [load]);
  const columns: ColumnsType<RequestLog> = [
    { title: "时间", dataIndex: "created_at", width: 180, render: (value) => <span className="request-log-time">{formatTime(value)}</span> },
    { title: "请求", key: "request", width: 295, render: (_, r) => <div className="request-cell"><b><Tag>{r.method || "—"}</Tag>{r.path || "—"}</b><span>{r.request_id || "无请求 ID"}</span></div> },
    { title: "调用人", key: "caller", width: 255, responsive: ["md"], render: (_, r) => <div className="request-caller"><b>{r.user_email || r.user_username || r.source || "未知调用方"}</b><span>{[r.user_username && r.user_username !== r.user_email ? r.user_username : "", r.source ? `密钥：${r.source}` : "", r.user_id ? `用户 ID ${r.user_id}` : ""].filter(Boolean).join(" · ") || "未关联用户"}</span></div> },
    { title: "状态", dataIndex: "status_code", width: 78, render: (v: number) => <Tag color={v >= 500 ? "error" : v >= 400 ? "warning" : "success"}>{v}</Tag> },
    { title: "耗时", dataIndex: "duration_ms", width: 82, render: (v) => v == null ? "—" : `${v} ms` },
    { title: "错误码", dataIndex: "error_code", width: 125, responsive: ["lg"], render: (v) => v || "—" },
  ];
  return <><div className="toolbar"><div className="mailbox-filters"><Input.Search allowClear value={keyword} onChange={(event) => { const value = event.target.value; setKeyword(value); if (!value) setAppliedKeyword(""); }} onSearch={(value) => setAppliedKeyword(value.trim())} placeholder="搜索接口、用户邮箱、用户名或密钥" style={{ width: 330 }} /><Select allowClear value={statusGroup || undefined} onChange={(value) => setStatusGroup(value || "")} placeholder="全部请求状态" style={{ width: 155 }} options={[{ value: "success", label: "成功（2xx/3xx）" }, { value: "client_error", label: "客户端错误（4xx）" }, { value: "server_error", label: "服务端错误（5xx）" }]} /></div><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button></div>{error ? <ErrorState error={error} retry={load} /> : <Table className="dense-table request-log-table" size="small" rowKey={(r) => r.id || r.request_id || r.created_at} loading={loading} columns={columns} dataSource={items} locale={{ emptyText: <Empty description="没有符合条件的请求日志" /> }} scroll={{ x: 1015 }} />}</>;
}

function SettingsPage() {
  return <div className="settings-grid">
    <Card title="运行方式"><Descriptions column={1} size="small"><Descriptions.Item label="管理接口">同域 /admin-api</Descriptions.Item><Descriptions.Item label="管理会话">HttpOnly Cookie</Descriptions.Item><Descriptions.Item label="数据存储">服务器 PostgreSQL 连接池</Descriptions.Item><Descriptions.Item label="敏感配置">服务端主密钥加密保存</Descriptions.Item></Descriptions></Card>
    <Card title="安全边界"><div className="policy-list"><div><SafetyCertificateOutlined /><span><b>管理端必须鉴权</b><small>管理账号与业务公开接口相互隔离</small></span></div><div><ApiOutlined /><span><b>上游凭据不外发</b><small>调用方不会获得 CloudMail Token 和管理员密码</small></span></div><div><DatabaseOutlined /><span><b>日志默认脱敏</b><small>不记录验证码、邮件正文和会话凭证</small></span></div></div></Card>
    <Alert className="settings-notice" type="info" showIcon message="部署级设置通过服务器环境变量管理" description="当前后端尚未提供在线修改系统密钥、会话有效期和数据库位置的接口。为避免界面产生无法持久化的假配置，本页只展示真实运行约束；修改后请在宝塔容器编排中重建服务。" />
  </div>;
}

function Console({ onUnauthorized }: { onUnauthorized: () => void }) {
  const { message } = AntApp.useApp();
  const [page, setPage] = useState<PageKey>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const meta = pageMeta[page];
  const content = useMemo(() => ({ overview: <OverviewPage />, instances: <InstancesPage />, domains: <DomainsPage />, users: <UsersPage />, creditSettings: <CreditSettingsPage />, mailboxes: <MailboxesPage />, logs: <LogsPage />, settings: <SettingsPage /> })[page], [page]);
  useEffect(() => {
    window.addEventListener("admin-unauthorized", onUnauthorized);
    return () => window.removeEventListener("admin-unauthorized", onUnauthorized);
  }, [onUnauthorized]);
  const logout = async () => { setLoggingOut(true); try { await api.logout(); onUnauthorized(); } catch (e) { message.error(getErrorMessage(e)); } finally { setLoggingOut(false); } };
  const navigate = (key: string) => { setPage(key as PageKey); setMobileOpen(false); };
  const sidebar = <><div className="console-brand"><div className="brand-mark"><ApiOutlined /></div>{!collapsed && <div><b>Xiaoasi Mail</b><span>Gateway Control</span></div>}</div><Menu theme="dark" mode="inline" selectedKeys={[page]} items={navItems} onClick={({ key }) => navigate(key)} /><div className="sider-footer">{!collapsed && <span>CONTROL PLANE<br />VERSION 0.3</span>}<Tooltip title="退出登录"><Button type="text" icon={<LogoutOutlined />} loading={loggingOut} onClick={() => void logout()} /></Tooltip></div></>;
  return <Layout className="console-layout">
    <Sider className="desktop-sider" width={244} collapsedWidth={78} collapsed={collapsed} trigger={null}>{sidebar}</Sider>
    <Drawer className="mobile-drawer" width={260} placement="left" open={mobileOpen} onClose={() => setMobileOpen(false)} closable={false}>{sidebar}</Drawer>
    <Layout>
      <Header className="console-header"><Button className="desktop-collapse" type="text" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)} /><Button className="mobile-menu" type="text" icon={<MenuUnfoldOutlined />} onClick={() => setMobileOpen(true)} /><Text className="section-index header-console-name">MAIL OPERATIONS</Text><Badge status="success" text="管理会话已连接" /></Header>
      <Content className="console-content"><div className="page-heading"><div><Title level={2}>{meta.title}</Title><Text>{meta.description}</Text></div><span className="page-code">XM / {String(navItems.findIndex((i) => i.key === page) + 1).padStart(2, "0")}</span></div><div className="page-body">{content}</div></Content>
    </Layout>
  </Layout>;
}

function RootApp() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  useEffect(() => {
    api.session()
      .then((session) => setAuthenticated(session.authenticated))
      .catch(() => setAuthenticated(false));
  }, []);
  if (authenticated === null) return <div className="boot-screen"><div className="brand-mark large"><ApiOutlined /></div><Spin /><Text>正在连接管理控制面…</Text></div>;
  return authenticated ? <Console onUnauthorized={() => setAuthenticated(false)} /> : <Login onSuccess={() => setAuthenticated(true)} />;
}

export default function App() {
  const isUserCenter = window.location.pathname === "/user" || window.location.pathname.startsWith("/user/");
  return <AntApp>{isUserCenter ? <UserPortal /> : <RootApp />}</AntApp>;
}
