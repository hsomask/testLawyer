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
  /** 民间借贷 PRD §3.1；租赁试算为 null */
  interest_subtotal?: string | null;
  remaining_principal?: string | null;
  total_principal_and_interest?: string | null;
  /** 房屋租赁结构化汇总；民间借贷为 null */
  rental_summary?: RentalSummary | null;
};

export type RentalSummary = {
  rent_receivable_subtotal: string;
  paid_rent_amount: string;
  arrears_principal_subtotal: string;
  rent_late_fee_subtotal: string;
  utility_late_fee_subtotal: string;
  property_late_fee_subtotal: string;
  other_late_fee_subtotal: string;
  occupancy_fee_subtotal: string;
  grand_total: string;
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

/** 将金额字符串安全转为整数分，避免浮点误差 */
function amountToCents(amount: string): number {
  const s = amount.trim();
  if (!s) return 0;
  // 处理 "123.45" 或 "123" 格式
  const dot = s.indexOf(".");
  if (dot === -1) return Number(s) * 100;
  const intPart = s.slice(0, dot);
  let decPart = s.slice(dot + 1);
  if (decPart.length === 0) return Number(intPart) * 100;
  if (decPart.length === 1) decPart = decPart + "0";
  return Number(intPart) * 100 + Number(decPart.slice(0, 2));
}

/** 整数分转回元字符串，保留两位小数 */
function centsToYuan(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const yuan = Math.floor(abs / 100);
  const fen = abs % 100;
  return `${sign}${yuan}.${fen.toString().padStart(2, "0")}`;
}

/** 明细行金额加总（字符串安全，按分转换后求和） */
export function sumLineAmounts(lines: ApiLine[]): string {
  const totalCents = lines.reduce((sum, ln) => sum + amountToCents(ln.amount), 0);
  return centsToYuan(totalCents);
}

/** 按费用类目分组小计 */
export function sumByFeeCategory(lines: ApiLine[]): Record<string, string> {
  const map = new Map<string, number>();
  for (const ln of lines) {
    const prev = map.get(ln.fee_category) ?? 0;
    map.set(ln.fee_category, prev + amountToCents(ln.amount));
  }
  const result: Record<string, string> = {};
  for (const [cat, cents] of map) {
    result[cat] = centsToYuan(cents);
  }
  return result;
}

export const lineColumns: ColumnsType<ApiLine & { key: string }> = [
  { title: "费用类目", dataIndex: "fee_category", width: 120 },
  {
    title: "阶段说明",
    dataIndex: "stage_description",
    width: 240,
    render: (v: string) => v ? <Text style={{ fontSize: 13 }}>{v}</Text> : null,
  },
  { title: "计算基数", dataIndex: "principal_base", align: "right" },
  { title: "利率标准", dataIndex: "rate_standard", ellipsis: true },
  { title: "起始日", dataIndex: "period_start", width: 110 },
  { title: "截止日", dataIndex: "period_end", width: 110 },
  { title: "天数", dataIndex: "day_count", width: 72, align: "center" },
  { title: "金额", dataIndex: "amount", align: "right" },
];
