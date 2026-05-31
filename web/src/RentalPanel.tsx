import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
  Typography,
  message,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { BG, formatApiError, lineColumns, type ApiResult, type RentalSummary } from "./calcShared";

const { Title, Text } = Typography;

type ExtraFeeRow = {
  category: "utility" | "property" | "other";
  name: string;
  amount: number | null;
  due_date: Dayjs | null;
};

function moneyStr(n: number): string {
  return n.toFixed(2);
}

function buildRentalPayload(values: {
  monthly_rent: number;
  paid_rent_amount?: number | null;
  arrears_period_start: Dayjs;
  arrears_period_end: Dayjs;
  rent_due_day_of_month: number;
  contract_termination_date: Dayjs;
  actual_vacate_date?: Dayjs | null;
  filing_date?: Dayjs | null;
  lease_start?: Dayjs | null;
  lease_end?: Dayjs | null;
  extra_fee_items?: ExtraFeeRow[];
}) {
  const body: Record<string, unknown> = {
    monthly_rent: moneyStr(values.monthly_rent),
    arrears_period_start: values.arrears_period_start.format("YYYY-MM-DD"),
    arrears_period_end: values.arrears_period_end.format("YYYY-MM-DD"),
    rent_due_day_of_month: values.rent_due_day_of_month,
    contract_termination_date: values.contract_termination_date.format("YYYY-MM-DD"),
  };
  if (values.paid_rent_amount != null && values.paid_rent_amount > 0) {
    body.paid_rent_amount = moneyStr(values.paid_rent_amount);
  }
  if (values.actual_vacate_date)
    body.actual_vacate_date = values.actual_vacate_date.format("YYYY-MM-DD");
  if (values.filing_date) body.filing_date = values.filing_date.format("YYYY-MM-DD");
  if (values.lease_start) body.lease_start = values.lease_start.format("YYYY-MM-DD");
  if (values.lease_end) body.lease_end = values.lease_end.format("YYYY-MM-DD");
  // 额外费用项目
  if (values.extra_fee_items?.length) {
    body.extra_fee_items = values.extra_fee_items
      .filter((it) => it.amount != null && it.amount > 0 && it.due_date && it.name.trim())
      .map((it) => ({
        category: it.category,
        name: it.name.trim(),
        amount: moneyStr(it.amount!),
        due_date: it.due_date!.format("YYYY-MM-DD"),
      }));
  }
  return body;
}

function renderSummaryCard(rs: RentalSummary) {
  const items: [string, string][] = [
    ["应收租金小计", rs.rent_receivable_subtotal],
    ["已支付租金合计", rs.paid_rent_amount],
    ["欠租本金小计", rs.arrears_principal_subtotal],
    ["租金滞纳金小计", rs.rent_late_fee_subtotal],
    ["水电费滞纳金小计", rs.utility_late_fee_subtotal],
    ["物业费滞纳金小计", rs.property_late_fee_subtotal],
    ["其他费用滞纳金小计", rs.other_late_fee_subtotal],
    ["房屋占用费小计", rs.occupancy_fee_subtotal],
  ];
  return (
    <Card size="small" title="费用汇总" style={{ background: BG }}>
      {items.map(([label, value]) => (
        <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
          <Text>{label}</Text>
          <Text strong>{value}</Text>
        </div>
      ))}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          padding: "8px 0 0",
          borderTop: "1px solid #e8e8e8",
          marginTop: 4,
        }}
      >
        <Text strong>最终总计</Text>
        <Text strong style={{ fontSize: 16 }}>{rs.grand_total}</Text>
      </div>
    </Card>
  );
}

export default function RentalPanel() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<ApiResult | null>(null);

  const getPayload = async () => {
    const v = await form.validateFields();
    return buildRentalPayload(v);
  };

  const handleCalculate = async () => {
    setLoading(true);
    setResult(null);
    try {
      const payload = await getPayload();
      const res = await fetch("/api/rental/calculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        message.error(formatApiError(data));
        return;
      }
      setResult(data as ApiResult);
      message.success("计算完成");
    } catch (e) {
      if (e instanceof Error && e.message === "validation") return;
      message.error(e instanceof Error ? e.message : "请求异常");
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const payload = await getPayload();
      const res = await fetch("/api/rental/export/excel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        message.error(formatApiError(err));
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "房屋租赁计算书.xlsx";
      a.click();
      URL.revokeObjectURL(url);
      message.success("已下载 Excel");
    } catch (e) {
      if (e instanceof Error && e.message === "validation") return;
      message.error(e instanceof Error ? e.message : "导出异常");
    } finally {
      setExporting(false);
    }
  };

  const tableData = useMemo(() => {
    if (!result?.lines?.length) return [];
    return result.lines.map((ln, i) => ({
      ...ln,
      key: `${i}-${ln.period_start}-${ln.period_end}`,
    }));
  }, [result]);

  return (
    <>
      <Card bordered={false}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            monthly_rent: 3000,
            arrears_period_start: dayjs("2025-01-01"),
            arrears_period_end: dayjs("2025-01-31"),
            rent_due_day_of_month: 26,
            contract_termination_date: dayjs("2025-03-01"),
            actual_vacate_date: null,
            filing_date: dayjs("2025-04-01"),
            lease_start: null,
            lease_end: null,
            paid_rent_amount: null,
            extra_fee_items: [],
          }}
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="滞纳金不再按 LPR 发布日分段，取违约开始日的固定 LPR。占用费按自然月天数拆分。欠租本金按自然月折算。"
          />

          <Row gutter={16}>
            <Col xs={24} sm={12} md={8}>
              <Form.Item
                name="monthly_rent"
                label="月租金（元）"
                rules={[{ required: true, message: "请输入月租金" }]}
              >
                <InputNumber min={0.01} precision={2} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item
                name="rent_due_day_of_month"
                label="应交租日：每月第几日（1–31，大于当月天数则按月末）"
                rules={[{ required: true, message: "请输入" }]}
              >
                <InputNumber min={1} max={31} precision={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item
                name="contract_termination_date"
                label="合同解除日"
                rules={[{ required: true, message: "请选择" }]}
              >
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>

          <Title level={5}>欠租本金</Title>
          <Row gutter={16}>
            <Col xs={24} sm={12} md={8}>
              <Form.Item
                name="paid_rent_amount"
                label="已支付租金合计（元，可选；仅扣减欠租本金小计，不影响滞纳金基数）"
              >
                <InputNumber min={0} precision={2} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>

          <Title level={5}>欠租统计区间（本金统计用）</Title>
          <Row gutter={16}>
            <Col xs={24} sm={12} md={8}>
              <Form.Item
                name="arrears_period_start"
                label="起点（含）"
                rules={[{ required: true, message: "请选择" }]}
              >
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item
                name="arrears_period_end"
                label="终点（含）"
                rules={[{ required: true, message: "请选择" }]}
              >
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>

          <Title level={5}>搬离与诉讼</Title>
          <Row gutter={16}>
            <Col xs={24} sm={12} md={8}>
              <Form.Item name="actual_vacate_date" label="实际搬离日（可选）">
                <DatePicker style={{ width: "100%" }} allowClear />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item
                name="filing_date"
                label="起诉日（必填，滞纳金计算至该日）"
                rules={[{ required: true, message: "请选择起诉日" }]}
              >
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>

          <Title level={5}>租期裁剪（可选）</Title>
          <Row gutter={16}>
            <Col xs={24} sm={12} md={8}>
              <Form.Item name="lease_start" label="租期起">
                <DatePicker style={{ width: "100%" }} allowClear />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item name="lease_end" label="租期止">
                <DatePicker style={{ width: "100%" }} allowClear />
              </Form.Item>
            </Col>
          </Row>

          <Title level={5}>额外费用项目（水电费 / 物业费 / 其他）</Title>
          <Form.List name="extra_fee_items">
            {(fields, { add, remove }) => (
              <>
                <Table
                  size="small"
                  pagination={false}
                  dataSource={fields.map((f) => ({ key: f.key, field: f }))}
                  locale={{ emptyText: "暂无额外费用" }}
                  columns={[
                    {
                      title: "类别",
                      width: 110,
                      render: (_, r) => (
                        <Form.Item
                          name={[r.field.name, "category"]}
                          rules={[{ required: true }]}
                          style={{ marginBottom: 0 }}
                        >
                          <Select
                            options={[
                              { value: "utility", label: "水电费" },
                              { value: "property", label: "物业费" },
                              { value: "other", label: "其他" },
                            ]}
                          />
                        </Form.Item>
                      ),
                    },
                    {
                      title: "名称",
                      render: (_, r) => (
                        <Form.Item
                          name={[r.field.name, "name"]}
                          rules={[{ required: true, message: "请输入" }]}
                          style={{ marginBottom: 0 }}
                        >
                          <Input placeholder="如：电费 2025-03" />
                        </Form.Item>
                      ),
                    },
                    {
                      title: "金额（元）",
                      width: 140,
                      render: (_, r) => (
                        <Form.Item
                          name={[r.field.name, "amount"]}
                          rules={[{ required: true, message: "请输入" }]}
                          style={{ marginBottom: 0 }}
                        >
                          <InputNumber min={0.01} precision={2} style={{ width: "100%" }} />
                        </Form.Item>
                      ),
                    },
                    {
                      title: "应付日",
                      width: 150,
                      render: (_, r) => (
                        <Form.Item
                          name={[r.field.name, "due_date"]}
                          rules={[{ required: true, message: "请选择" }]}
                          style={{ marginBottom: 0 }}
                        >
                          <DatePicker style={{ width: "100%" }} />
                        </Form.Item>
                      ),
                    },
                    {
                      title: "操作",
                      width: 80,
                      render: (_, r) => (
                        <Button type="link" danger onClick={() => remove(r.field.name)}>
                          删除
                        </Button>
                      ),
                    },
                  ]}
                />
                <Button
                  type="dashed"
                  onClick={() => add({ category: "utility", name: "", amount: null, due_date: null })}
                  block
                  style={{ marginTop: 8 }}
                >
                  添加费用项目
                </Button>
              </>
            )}
          </Form.List>

          <Space style={{ marginTop: 24 }} wrap>
            <Button type="primary" onClick={handleCalculate} loading={loading}>
              开始计算
            </Button>
            <Button onClick={handleExport} loading={exporting}>
              下载 Excel
            </Button>
          </Space>
        </Form>
      </Card>

      {result && (
        <Card title="计算结果" style={{ marginTop: 24 }} bordered={false}>
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <Text>
              规则版本：<Text strong>{result.rule_version}</Text> {result.ok ? <Text type="success">（成功）</Text> : null}
            </Text>
            {result.messages?.length ? (
              <Alert
                type="warning"
                message="提示"
                description={
                  <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                    {result.messages.map((m, i) => (
                      <li key={i}>{m}</li>
                    ))}
                  </ul>
                }
              />
            ) : null}
            {result.assumptions_used?.length ? (
              <Alert
                type="info"
                message="计算口径说明"
                description={
                  <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                    {result.assumptions_used.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                }
              />
            ) : null}
            {result.rental_summary ? renderSummaryCard(result.rental_summary) : null}
            <Table columns={lineColumns} dataSource={tableData} scroll={{ x: 1000 }} pagination={false} size="small" />
          </Space>
        </Card>
      )}
    </>
  );
}
