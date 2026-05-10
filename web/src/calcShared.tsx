import { Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

const { Text } = Typography;

export const BG = "#F8FAFC";

export type ApiLine = {
  fee_category: string;
  stage_description: string;
  principal_base: string;
  rate_standard: string;
  period_start: string;
  period_end: string;
  day_count: number;
  amount: string;
};

export type ApiResult = {
  ok: boolean;
  rule_version: string;
  assumptions_used: string[];
  lines: ApiLine[];
  messages: string[];
};

export function formatApiError(data: unknown): string {
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

export const lineColumns: ColumnsType<ApiLine & { key: string }> = [
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
];
