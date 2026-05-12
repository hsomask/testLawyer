import { useMemo, useState } from "react";
import { Alert, Button, Card, Col, DatePicker, Form, InputNumber, Row, Space, Table, Typography, message } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { formatApiError, lineColumns, type ApiResult } from "./calcShared";

const { Title, Text } = Typography;

function moneyStr(n: number): string {
  return n.toFixed(2);
}

function buildRentalPayload(values: {
  monthly_rent: number;
  arrears_period_start: Dayjs;
  arrears_period_end: Dayjs;
  rent_due_day_of_month: number;
  contract_termination_date: Dayjs;
  actual_vacate_date?: Dayjs | null;
  filing_date?: Dayjs | null;
  lease_start?: Dayjs | null;
  lease_end?: Dayjs | null;
}) {
  const body: Record<string, unknown> = {
    monthly_rent: moneyStr(values.monthly_rent),
    arrears_period_start: values.arrears_period_start.format("YYYY-MM-DD"),
    arrears_period_end: values.arrears_period_end.format("YYYY-MM-DD"),
    rent_due_day_of_month: values.rent_due_day_of_month,
    contract_termination_date: values.contract_termination_date.format("YYYY-MM-DD"),
  };
  if (values.actual_vacate_date)
    body.actual_vacate_date = values.actual_vacate_date.format("YYYY-MM-DD");
  if (values.filing_date) body.filing_date = values.filing_date.format("YYYY-MM-DD");
  if (values.lease_start) body.lease_start = values.lease_start.format("YYYY-MM-DD");
  if (values.lease_end) body.lease_end = values.lease_end.format("YYYY-MM-DD");
  return body;
}

export default function RentalPanel() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<ApiResult | null>(null);

  const getPayload = async () => {
    const v = await form.validateFields();
    if (!v.actual_vacate_date && !v.filing_date) {
      message.error("未填写「实际搬离日」时，必须填写「起诉日」（用于占用费止日推算）");
      throw new Error("validation");
    }
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
          }}
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="应交租日为每月「几日」（1–31）；滞纳金自交租日次日起算至起诉日（含）。欠租起止日仅作本金统计口径。月份范围：有租期起止则自租期起至 min(租期止,起诉日)；否则自欠租起点至起诉日。占用费规则不变，无搬离须填起诉日。"
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

          <Title level={5}>欠租统计区间（仅本金统计口径）</Title>
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

          <Title level={5}>搬离与诉讼（二选一或都填：有搬离日以搬离为准）</Title>
          <Row gutter={16}>
            <Col xs={24} sm={12} md={8}>
              <Form.Item name="actual_vacate_date" label="实际搬离日（可选）">
                <DatePicker style={{ width: "100%" }} allowClear />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <Form.Item name="filing_date" label="起诉日（无搬离日时必填）">
                <DatePicker style={{ width: "100%" }} allowClear />
              </Form.Item>
            </Col>
          </Row>

          <Title level={5}>租期裁剪（可选，与欠租区间求交后计滞纳金）</Title>
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
              <Alert type="warning" message="提示" description={result.messages.join("；")} />
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
            <Table columns={lineColumns} dataSource={tableData} scroll={{ x: 900 }} pagination={false} size="small" />
          </Space>
        </Card>
      )}
    </>
  );
}
