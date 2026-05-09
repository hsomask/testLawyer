import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  InputNumber,
  Row,
  Space,
  Table,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import "./App.css";

const { Title, Text } = Typography;

const BG = "#F8FAFC";

type RepaymentRow = {
  repayment_date: Dayjs | null;
  amount: number | null;
};

type ApiLine = {
  fee_category: string;
  stage_description: string;
  principal_base: string;
  rate_standard: string;
  period_start: string;
  period_end: string;
  day_count: number;
  amount: string;
};

type ApiResult = {
  ok: boolean;
  rule_version: string;
  assumptions_used: string[];
  lines: ApiLine[];
  messages: string[];
};

function formatApiError(data: unknown): string {
  if (typeof data === "object" && data !== null && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d))
      return d
        .map((x: { msg?: string }) => (typeof x === "object" && x && "msg" in x ? String(x.msg) : JSON.stringify(x)))
        .join("；");
  }
  return "请求失败";
}

function buildPayload(values: {
  principal: number;
  loan_date: Dayjs;
  end_date: Dayjs;
  repayments: RepaymentRow[];
  filing_date?: Dayjs | null;
  lpr_document_month?: Dayjs | null;
  agreed_annual_rate?: number | null;
  due_date?: Dayjs | null;
}) {
  const repayments = (values.repayments || [])
    .filter((r) => r.repayment_date && r.amount != null && r.amount !== undefined)
    .map((r) => ({
      repayment_date: r.repayment_date!.format("YYYY-MM-DD"),
      amount: String(r.amount),
    }));

  const body: Record<string, unknown> = {
    principal: String(values.principal),
    loan_date: values.loan_date.format("YYYY-MM-DD"),
    end_date: values.end_date.format("YYYY-MM-DD"),
    repayments,
    convention: "civil_365_simple",
  };

  if (values.filing_date) body.filing_date = values.filing_date.format("YYYY-MM-DD");
  if (values.lpr_document_month)
    body.lpr_document_month = values.lpr_document_month.format("YYYY-MM-DD");
  if (values.agreed_annual_rate != null && values.agreed_annual_rate !== undefined) {
    body.agreed_annual_rate = String(values.agreed_annual_rate);
  }
  if (values.due_date) body.due_date = values.due_date.format("YYYY-MM-DD");

  return body;
}

export default function App() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<ApiResult | null>(null);

  const lineColumns: ColumnsType<ApiLine & { key: string }> = useMemo(
    () => [
      {
        title: "费用类目",
        dataIndex: "fee_category",
        width: 220,
        render: (_, row) => (
          <span>
            {row.fee_category}
            {row.stage_description ? (
              <Text type="secondary" style={{ display: "block", fontSize: 12 }}>
                {row.stage_description}
              </Text>
            ) : null}
          </span>
        ),
      },
      { title: "计算基数", dataIndex: "principal_base", align: "right" },
      { title: "利率标准", dataIndex: "rate_standard", ellipsis: true },
      { title: "起始日", dataIndex: "period_start", width: 110 },
      { title: "截止日", dataIndex: "period_end", width: 110 },
      { title: "天数", dataIndex: "day_count", width: 72, align: "center" },
      { title: "金额", dataIndex: "amount", align: "right" },
    ],
    []
  );

  const getPayload = async () => {
    const v = await form.validateFields();
    return buildPayload(v);
  };

  const handleCalculate = async () => {
    setLoading(true);
    setResult(null);
    try {
      const payload = await getPayload();
      const res = await fetch("/api/calculate", {
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
      message.error(e instanceof Error ? e.message : "请求异常");
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const payload = await getPayload();
      const res = await fetch("/api/export/excel", {
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
      a.download = "民间借贷计算书.xlsx";
      a.click();
      URL.revokeObjectURL(url);
      message.success("已下载 Excel");
    } catch (e) {
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
    <div className="app-root" style={{ background: BG, minHeight: "100vh", padding: 24 }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <Title level={3} style={{ color: "#0F172A", marginBottom: 8 }}>
          民间借贷利息计算（原型）
        </Title>
        <Text type="secondary">背景与主色遵循 UI 规范；请先启动后端 API（端口 8000）。</Text>

        <Card style={{ marginTop: 24 }} bordered={false}>
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              principal: 200000,
              loan_date: dayjs("2020-07-01"),
              end_date: dayjs("2021-06-30"),
              agreed_annual_rate: 0.15,
              filing_date: dayjs("2021-05-10"),
              lpr_document_month: dayjs("2021-06-01"),
              repayments: [
                { repayment_date: dayjs("2020-09-10"), amount: 12000 },
                { repayment_date: dayjs("2020-12-01"), amount: 8000 },
                { repayment_date: dayjs("2021-03-15"), amount: 15000 },
              ],
            }}
          >
            <Row gutter={16}>
              <Col xs={24} sm={12} md={8}>
                <Form.Item
                  name="principal"
                  label="本金（元）"
                  rules={[{ required: true, message: "请输入本金" }]}
                >
                  <InputNumber min={0.01} precision={2} style={{ width: "100%" }} />
                </Form.Item>
              </Col>
              <Col xs={24} sm={12} md={8}>
                <Form.Item
                  name="loan_date"
                  label="借款日"
                  rules={[{ required: true, message: "请选择借款日" }]}
                >
                  <DatePicker style={{ width: "100%" }} />
                </Form.Item>
              </Col>
              <Col xs={24} sm={12} md={8}>
                <Form.Item
                  name="end_date"
                  label="截止计息日"
                  rules={[{ required: true, message: "请选择截止日" }]}
                >
                  <DatePicker style={{ width: "100%" }} />
                </Form.Item>
              </Col>
            </Row>

            <Row gutter={16}>
              <Col xs={24} sm={12} md={8}>
                <Form.Item name="agreed_annual_rate" label="约定年化利率（小数，如 0.12 即 12%）">
                  <InputNumber min={0} max={1} step={0.0001} style={{ width: "100%" }} />
                </Form.Item>
              </Col>
              <Col xs={24} sm={12} md={8}>
                <Form.Item name="due_date" label="到期日（无约定利率时必填）">
                  <DatePicker style={{ width: "100%" }} />
                </Form.Item>
              </Col>
              <Col xs={24} sm={12} md={8}>
                <Form.Item name="filing_date" label="起诉日（可选）">
                  <DatePicker style={{ width: "100%" }} />
                </Form.Item>
              </Col>
            </Row>

            <Row gutter={16}>
              <Col xs={24} sm={12} md={8}>
                <Form.Item name="lpr_document_month" label="文档所属月（可选，未起诉时 LPR×4 参考）">
                  <DatePicker picker="month" style={{ width: "100%" }} />
                </Form.Item>
              </Col>
            </Row>

            <Title level={5}>还款记录</Title>
            <Form.List name="repayments">
              {(fields, { add, remove }) => (
                <>
                  <Table
                    size="small"
                    pagination={false}
                    dataSource={fields.map((f, idx) => ({
                      key: f.key,
                      idx,
                      field: f,
                    }))}
                    columns={[
                      {
                        title: "还款日",
                        render: (_, r) => (
                          <Form.Item
                            name={[r.field.name, "repayment_date"]}
                            rules={[{ required: true, message: "请选择" }]}
                            style={{ marginBottom: 0 }}
                          >
                            <DatePicker style={{ width: "100%" }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: "金额（元）",
                        render: (_, r) => (
                          <Form.Item
                            name={[r.field.name, "amount"]}
                            rules={[{ required: true, message: "请输入金额" }]}
                            style={{ marginBottom: 0 }}
                          >
                            <InputNumber min={0} precision={2} style={{ width: "100%" }} />
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
                  <Button type="dashed" onClick={() => add({ repayment_date: null, amount: null })} block style={{ marginTop: 8 }}>
                    添加还款
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
                规则版本：<Text strong>{result.rule_version}</Text>{" "}
                {result.ok ? <Text type="success">（成功）</Text> : null}
              </Text>
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
              <Table
                columns={lineColumns}
                dataSource={tableData}
                scroll={{ x: 900 }}
                pagination={false}
                size="small"
              />
            </Space>
          </Card>
        )}
      </div>
    </div>
  );
}
