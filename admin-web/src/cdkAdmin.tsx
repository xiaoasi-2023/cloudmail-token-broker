import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CopyOutlined,
  EditOutlined,
  GiftOutlined,
  KeyOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App as AntApp,
  Badge,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { api } from "./api";
import type { CreditCdk, CreditCdkPackage } from "./types";

const { Text, Paragraph } = Typography;

type PackageFormValues = Pick<CreditCdkPackage, "name" | "points" | "purchase_url" | "enabled">;

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "请求失败，请稍后重试";
}

function formatTime(value?: string | null) {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "—";
}

function cdkStatusTag(status: string) {
  const config: Record<string, { color: string; label: string }> = {
    unused: { color: "success", label: "未使用" },
    redeemed: { color: "processing", label: "已兑换" },
    disabled: { color: "default", label: "已停用" },
  };
  const item = config[status] || { color: "default", label: status || "未知" };
  return <Tag color={item.color}>{item.label}</Tag>;
}

async function copyText(text: string, onSuccess: () => void, onError: () => void) {
  try {
    await navigator.clipboard.writeText(text);
    onSuccess();
  } catch {
    onError();
  }
}

export function CdkAdminPage() {
  const { message } = AntApp.useApp();
  const [packages, setPackages] = useState<CreditCdkPackage[]>([]);
  const [cdks, setCdks] = useState<CreditCdk[]>([]);
  const [packageLoading, setPackageLoading] = useState(true);
  const [cdkLoading, setCdkLoading] = useState(true);
  const [error, setError] = useState("");
  const [packageModalOpen, setPackageModalOpen] = useState(false);
  const [editingPackage, setEditingPackage] = useState<CreditCdkPackage>();
  const [savingPackage, setSavingPackage] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [disablingId, setDisablingId] = useState<number>();
  const [generatorPackageId, setGeneratorPackageId] = useState<number>();
  const [quantity, setQuantity] = useState(10);
  const [generatedItems, setGeneratedItems] = useState<CreditCdk[]>([]);
  const [keyword, setKeyword] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [packageFilter, setPackageFilter] = useState<number>();
  const [form] = Form.useForm<PackageFormValues>();

  const enabledPackages = useMemo(() => packages.filter((item) => item.enabled), [packages]);
  const defaultPackage = enabledPackages[0];

  const loadPackages = useCallback(async () => {
    setPackageLoading(true);
    try {
      const nextPackages = await api.cdkPackages();
      setPackages(nextPackages);
      setGeneratorPackageId((current) => {
        if (current && nextPackages.some((item) => item.id === current && item.enabled)) return current;
        return nextPackages.find((item) => item.enabled)?.id;
      });
    } catch (currentError) {
      setError(getErrorMessage(currentError));
    } finally {
      setPackageLoading(false);
    }
  }, []);

  const loadCdks = useCallback(async () => {
    setCdkLoading(true);
    try {
      setCdks(await api.cdks({ limit: 100, keyword: appliedKeyword, packageId: packageFilter, status }));
    } catch (currentError) {
      setError(getErrorMessage(currentError));
    } finally {
      setCdkLoading(false);
    }
  }, [appliedKeyword, packageFilter, status]);

  useEffect(() => {
    void Promise.all([loadPackages(), loadCdks()]);
  }, [loadPackages, loadCdks]);

  useEffect(() => {
    if (defaultPackage && !generatorPackageId) setGeneratorPackageId(defaultPackage.id);
  }, [defaultPackage, generatorPackageId]);

  const openCreatePackage = () => {
    setEditingPackage(undefined);
    form.resetFields();
    form.setFieldsValue({ name: "", points: 100, purchase_url: "", enabled: true });
    setPackageModalOpen(true);
  };

  const openEditPackage = (record: CreditCdkPackage) => {
    setEditingPackage(record);
    form.setFieldsValue({
      name: record.name,
      points: record.points,
      purchase_url: record.purchase_url || "",
      enabled: record.enabled,
    });
    setPackageModalOpen(true);
  };

  const savePackage = async () => {
    const values = await form.validateFields();
    setSavingPackage(true);
    try {
      const payload = { ...values, name: values.name.trim(), purchase_url: values.purchase_url.trim() };
      if (editingPackage) {
        await api.updateCdkPackage(editingPackage.id, payload);
        message.success("套餐已更新");
      } else {
        await api.createCdkPackage(payload);
        message.success("套餐已创建");
      }
      setPackageModalOpen(false);
      await loadPackages();
    } catch (currentError) {
      message.error(getErrorMessage(currentError));
    } finally {
      setSavingPackage(false);
    }
  };

  const togglePackage = async (record: CreditCdkPackage, enabled: boolean) => {
    try {
      await api.updateCdkPackage(record.id, { enabled });
      message.success(enabled ? "套餐已启用" : "套餐已停用");
      await loadPackages();
    } catch (currentError) {
      message.error(getErrorMessage(currentError));
    }
  };

  const generate = async () => {
    if (!generatorPackageId) {
      message.warning("请先创建并选择一个套餐");
      return;
    }
    setGenerating(true);
    try {
      const result = await api.generateCdks(generatorPackageId, quantity);
      setGeneratedItems(result.data.items);
      message.success(`已生成 ${result.data.items.length} 个 CDK`);
      await loadCdks();
    } catch (currentError) {
      message.error(getErrorMessage(currentError));
    } finally {
      setGenerating(false);
    }
  };

  const disableCdk = async (record: CreditCdk) => {
    setDisablingId(record.id);
    try {
      await api.disableCdk(record.id);
      message.success("CDK 已停用");
      await loadCdks();
    } catch (currentError) {
      message.error(getErrorMessage(currentError));
    } finally {
      setDisablingId(undefined);
    }
  };

  const copyGenerated = () => {
    void copyText(
      generatedItems.map((item) => item.code).join("\n"),
      () => message.success("已复制全部 CDK"),
      () => message.error("复制失败，请检查浏览器剪贴板权限"),
    );
  };

  const packageColumns: ColumnsType<CreditCdkPackage> = [
    {
      title: "套餐",
      key: "package",
      render: (_, record) => (
        <div className="primary-cell">
          <b>{record.name}</b>
          <span>{record.purchase_url || "未配置购买链接"}</span>
        </div>
      ),
    },
    { title: "额度", dataIndex: "points", width: 100, render: (value: number) => <Text strong>{value} 分</Text> },
    {
      title: "状态",
      dataIndex: "enabled",
      width: 108,
      render: (enabled: boolean, record) => (
        <Switch
          size="small"
          checked={enabled}
          onChange={(next) => void togglePackage(record, next)}
          checkedChildren="启用"
          unCheckedChildren="停用"
        />
      ),
    },
    { title: "更新时间", dataIndex: "updated_at", width: 170, responsive: ["lg"], render: formatTime },
    {
      title: "操作",
      key: "actions",
      width: 86,
      render: (_, record) => <Button size="small" icon={<EditOutlined />} onClick={() => openEditPackage(record)}>编辑</Button>,
    },
  ];

  const cdkColumns: ColumnsType<CreditCdk> = [
    {
      title: "CDK",
      dataIndex: "code",
      width: 285,
      render: (value: string) => <Text code copyable={{ text: value, tooltips: ["复制", "已复制"] }}>{value}</Text>,
    },
    {
      title: "套餐",
      key: "package",
      width: 180,
      render: (_, record) => <div className="primary-cell"><b>{record.package_name || "未命名套餐"}</b><span>{record.points == null ? "—" : `${record.points} 分`}</span></div>,
    },
    { title: "状态", dataIndex: "status", width: 100, render: cdkStatusTag },
    { title: "兑换用户", dataIndex: "redeemed_username", width: 150, responsive: ["lg"], render: (value) => value || "—" },
    { title: "生成时间", dataIndex: "created_at", width: 170, responsive: ["xl"], render: formatTime },
    {
      title: "操作",
      key: "actions",
      width: 90,
      render: (_, record) => record.status === "unused" ? <Button size="small" danger loading={disablingId === record.id} onClick={() => void disableCdk(record)}>停用</Button> : <Text type="secondary">—</Text>,
    },
  ];

  return (
    <>
      {error && <Alert className="page-alert" type="error" showIcon message="CDK 数据加载失败" description={error} action={<Button size="small" onClick={() => { setError(""); void Promise.all([loadPackages(), loadCdks()]); }}>重试</Button>} />}
      <div className="admin-settings-grid" style={{ marginBottom: 20 }}>
        <Card className="admin-setting-card" title={<span><GiftOutlined /> 默认套餐</span>} extra={<Tag color={defaultPackage?.enabled ? "success" : "default"}>{defaultPackage ? "生成器预选" : "待配置"}</Tag>}>
          {packageLoading ? <Spin /> : defaultPackage ? <>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 18 }}>
              <div>
                <Text className="section-index">DEFAULT PACKAGE</Text>
                <div style={{ marginTop: 10, fontSize: 23, fontWeight: 700, letterSpacing: "-.03em" }}>{defaultPackage.name}</div>
                <Paragraph type="secondary" style={{ margin: "8px 0 0" }}>兑换后增加 <Text strong>{defaultPackage.points} 分</Text>，新生成 CDK 会优先使用此套餐。</Paragraph>
              </div>
              <div style={{ minWidth: 74, padding: "11px 12px", border: "1px solid #ead6ca", background: "#fff5ef", textAlign: "center" }}>
                <Text type="secondary">额度</Text>
                <div style={{ color: "#c0582d", font: '600 23px "IBM Plex Mono", monospace' }}>{defaultPackage.points}</div>
              </div>
            </div>
            <div style={{ marginTop: 20, paddingTop: 14, borderTop: "1px solid #e5e2d9", color: "#818985", fontSize: 12 }}>
              <SafetyCertificateOutlined style={{ marginRight: 7, color: "#d46936" }} />默认套餐取首个启用套餐；可在下方套餐列表调整启停状态。
            </div>
          </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无套餐，请先创建" />}
        </Card>
        <Card className="admin-setting-card" title={<span><KeyOutlined /> 批量生成 CDK</span>} extra={<Tag color="processing">一次性兑换码</Tag>}>
          <Paragraph type="secondary" style={{ marginTop: 0 }}>选择套餐并生成指定数量的兑换码，生成结果只在当前页面集中展示，支持一键复制。</Paragraph>
          <Space.Compact block>
            <Select<number>
              value={generatorPackageId}
              onChange={setGeneratorPackageId}
              placeholder="选择套餐"
              options={packages.map((item) => ({ value: item.id, label: `${item.name} · ${item.points} 分`, disabled: !item.enabled }))}
              style={{ flex: 1 }}
              notFoundContent="暂无可用套餐"
            />
            <InputNumber min={1} max={500} precision={0} value={quantity} onChange={(value) => setQuantity(value || 1)} addonAfter="个" style={{ width: 132 }} />
          </Space.Compact>
          <Button type="primary" block icon={<PlusOutlined />} loading={generating} disabled={!enabledPackages.length} onClick={() => void generate()} style={{ marginTop: 14 }}>生成 CDK</Button>
        </Card>
      </div>

      <Card className="admin-setting-card" title="套餐管理" extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCreatePackage}>新增套餐</Button>} style={{ marginBottom: 20 }}>
        <Table className="dense-table" rowKey="id" size="small" loading={packageLoading} columns={packageColumns} dataSource={packages} pagination={false} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 CDK 套餐" /> }} scroll={{ x: 760 }} />
      </Card>

      {generatedItems.length > 0 && <Card className="admin-setting-card" title={<span><CopyOutlined /> 本次生成结果</span>} extra={<Button size="small" icon={<CopyOutlined />} onClick={copyGenerated}>复制全部</Button>} style={{ marginBottom: 20 }}>
        <Alert type="success" showIcon message={`已生成 ${generatedItems.length} 个 CDK`} description="请及时复制并妥善保存；离开页面后仍可在下方 CDK 列表中按关键词查找。" style={{ marginBottom: 14 }} />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 8 }}>
          {generatedItems.map((item) => <div key={item.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, minWidth: 0, padding: "8px 10px", background: "#f3f5ef", border: "1px solid #dce3d9" }}><Text code ellipsis style={{ minWidth: 0 }}>{item.code}</Text><Text copyable={{ text: item.code, tooltips: ["复制", "已复制"] }} /></div>)}
        </div>
      </Card>}

      <Card className="admin-setting-card" title={<span><KeyOutlined /> CDK 列表</span>} extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => void loadCdks()}>刷新</Button>}>
        <div className="toolbar" style={{ margin: "0 -1px 16px" }}>
          <div className="mailbox-filters">
            <Input.Search allowClear value={keyword} onChange={(event) => { const value = event.target.value; setKeyword(value); if (!value) setAppliedKeyword(""); }} onSearch={(value) => setAppliedKeyword(value.trim())} placeholder="搜索 CDK、用户或套餐" style={{ width: 285 }} />
            <Select allowClear value={status || undefined} onChange={(value) => setStatus(value || "")} placeholder="全部状态" style={{ width: 125 }} options={[{ value: "unused", label: "未使用" }, { value: "redeemed", label: "已兑换" }, { value: "disabled", label: "已停用" }]} />
            <Select allowClear value={packageFilter} onChange={setPackageFilter} placeholder="全部套餐" style={{ width: 165 }} options={packages.map((item) => ({ value: item.id, label: item.name }))} />
          </div>
          <Badge status="default" text={`显示 ${cdks.length} 条`} />
        </div>
        <Table className="dense-table" rowKey="id" size="small" loading={cdkLoading} columns={cdkColumns} dataSource={cdks} pagination={false} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合条件的 CDK" /> }} scroll={{ x: 940 }} />
      </Card>

      <Modal title={editingPackage ? "编辑 CDK 套餐" : "新增 CDK 套餐"} open={packageModalOpen} confirmLoading={savingPackage} onOk={() => void savePackage()} onCancel={() => setPackageModalOpen(false)} okText="保存" cancelText="取消" destroyOnClose>
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item label="套餐名称" name="name" rules={[{ required: true, message: "请输入套餐名称" }]}><Input placeholder="例如：标准套餐" maxLength={100} /></Form.Item>
          <Form.Item label="积分额度" name="points" rules={[{ required: true, message: "请输入积分额度" }]}><InputNumber min={1} precision={0} style={{ width: "100%" }} addonAfter="分" /></Form.Item>
          <Form.Item label="购买链接" name="purchase_url" rules={[{ type: "url", warningOnly: true, message: "建议填写有效 URL" }]}><Input prefix={<LinkOutlined />} placeholder="https://...（可选）" maxLength={500} /></Form.Item>
          <Form.Item label="允许生成和兑换" name="enabled" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}
