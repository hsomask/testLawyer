# 法律计算器核心业务逻辑实现 (民间借贷 & 房屋租赁)

代码包：`legal_calc`（`RULE_VERSION` 见 `legal_calc/version.py`）。**审计**：每次计算应保存规则版本号、输入快照、输出明细（业务确认 §12）。**HTTP 与 Web 原型约定**见本文 **§4**；**实现与 PRD 差异表**见 **§3.2**（与《[Product_System_Architecture.md](./Product_System_Architecture.md)》§2.4、《[UI_Design_Spec.md](./UI_Design_Spec.md)》§2.1.1 对齐）。

---

## 0. 业务确认备忘（已定稿口径）

| 编号 | 事项 | 业务结论 |
|------|------|----------|
| 1 | 民间借贷：利率分界日 | **`2020-08-19`（含）为旧规则最后一日**；**`2020-08-20` 起为新规则段**；跨分界须**强制拆两段**。 |
| 2.1 | 未起诉时 LPR×4 用哪月 | **输入文档当月**。实现：请求中 `lpr_document_month`（该月内任一日期），无则回退 **计息末日 `D_eff` 所在月**（月末回溯）。 |
| 2.2 | LPR 期限 | **一年期 LPR**（与 `lpr_1y_cny.json` 说明一致），固定写进规则。 |
| 3.1 | 有约定与上限 | **未超上限依然有效** ⇒ 有效年化 = `min(约定, 司法上限)`（旧段 24%；新段 `LPR×4` 取起诉/文档月末回溯）。 |
| 3.2 | 无约定 | **仅一年期 LPR，不适用四倍上限**；**期内至到期日不产生利息**；**自到期日次日起**逾期部分按 LPR（按发布日分段）计息。 |
| 4.1 | 同日多笔还款 | **允许**；**可按日合并**录入。 |
| 4.2 | 本金清零后 | **不再计息**至计息末日 **`D_eff`**（§1.B.2；与 §0.1 第 13 条一致）。 |
| 4.3 | 还款日计息归属 | **还款当日不计入「还款前一段」**；若仍欠本金，**自还款日当日起计入下一段**（实现为半开区间 `[锚点, 还款日)`，下段自 `还款日` 起算）。 |
| 5 | 单利/复利 | 民间借贷默认 **单利、365 天/年**。**银行/金融公司复利、360 天/年产品**：请求中 **不接受** `finance_360_compound`，`PrivateLendingRequest` 校验将 **直接报错** 并提示改用民间借贷口径或专业金融系统。 |
| 6.1 | 租赁交租日 | 请求字段 **`rent_due_day_of_month`（1–31）**：每月第几日为应交租日；大于当月天数时钳为当月最后一日（`due_date_by_day_of_month`）。 |
| 6.2 | 滞纳金 | **按日累计**；**除 LPR×4 外不设总额上限**；租赁滞纳金 **不适用四倍**（见 7）。 |
| 7 | 租赁 LPR | **与民间借贷共用 JSON 表（一年期）**；**滞纳金按一年期 LPR、无四倍**。 |
| 8.1–8.2 | 占用费止日 | **有实际搬离**则至搬离日（含）；**无搬离则用起诉日+30（含）**；需 `filing_date`。 |
| 9 | 占用费单价 | **`(月租金/30)×占用自然日×2**。 |
| 10 | 舍入 | **四舍五入到分**；**单笔分段先 round 再相加**形成冲抵与本表小计口径。 |
| 11 | LPR 数据源 | **人民银行公布**（本仓库示例为自 2020-01 起的手工 JSON，可自行扩展）。回溯规则：`as_of` 取「报价发布日 ≤ as_of」最新一条。 |
| 12 | 审计字段 | **要**：规则版本、`PrivateLendingRequest`/`RentalRequest` 快照、输出 `ReportLineItem` 列表。 |

### 0.1 业务定稿补充（2026-05-12，书面一句话）

以下与《第一版问题汇总》回复稿对齐，**实现以随后代码与 `RULE_VERSION` 为准**；本节为产品口径源。

| 编号 | 事项 | 业务结论 |
|------|------|----------|
| 13 | 民间借贷：同时存在「截止计息日」与「起诉日」时，计息/展示用哪一日作为**末日（含）** | **`max(截止计息日, 起诉日)`**（取较晚者）。 |
| 14 | 民间借贷：无约定利率、约定年化利率为 0 时，逾期等「算到哪一日」是否与上条同一公式 | **是**，与第 13 条**同一公式**（仍以到期日次日为逾期起点等既有条款为前提，见 §1）。 |
| 15 | 房屋租赁：欠租统计区间与滞纳金 | **欠租统计区间仅用于欠租本金统计**；**不作为**租金滞纳金的计息区间边界。 |
| 16 | 房屋租赁：哪些自然月要计租金滞纳金 | **凡合同下各自然月应交租义务**，只要已超过该月**应交租日次日**且该月应付租仍未付清，则该月纳入滞纳金计算，**一律自应交租日次日起算至起诉日（含）**；与欠租统计区间**脱钩**（租期/合同期裁剪若保留，另见实现迭代）。 |
| 17 | 界面「20 号」等展示 | **本期关闭待办**：不修改；后续版本再讨论。 |
| 18 | 水电费、物业费滞纳金（新需求）与租金规则关系 | **与「改完之后的」租金滞纳金规则同构**（LPR 按日、舍入、区间至起诉日等一致）；**不是**与旧版线上引擎一致。 |

---

## 1. 民间借贷计算逻辑 (Private Lending)

### A. 规则定义
- **利率分界**: **`2020-08-19`（含）为旧规则最后一日**；自 **`2020-08-20`** 起为新规则段。
- **旧段上限**: 年化 `24%`。
- **新段上限**: `一年期 LPR × 4`（取起诉日所在月；未起诉则取文档月；以**该自然月末日**回溯报价）。
- **天数基数（默认口径）**: `365` 天/年，单利。

### B. 核心算法（先息后本、还款冲抵）

1. **输入**: 本金 `P`，借款日 `D1`，还款列表（同日可合并），截止日 `D_end`（**含当日**），可选用约定年化、到期日、`filing_date` / `lpr_document_month`。
2. **计息末日（含）**：记 `D_eff = D_end`；若请求中同时提供 **`filing_date`**，则 **`D_eff = max(D_end, filing_date)`**（与 §0.1 第 13、14 条一致）。分段、最后一程计息、展示均以 **`D_eff`** 替代原 **`D_end`** 参与「计到哪一天」的边界（半开实现仍为 **`[cursor, D_eff+1 日)`**）。
3. **分段**: 在时间上切开 **分界日**，及（无约定时）**到期日次日**逾期起点；逾期且无约定的区间再按 **LPR 报价发布日**细分。
4. **计息区间**: `[计息锚点, 还款日)` **半开**（**还款日当日不计入本段**）；下一段从 **还款日当日**起算。最后一程至 **`D_eff` 含当日**（实现为 **`[cursor, D_eff+1 日)`**）。
5. **还款**: `I_total += 当期利息(round 后之和)`；若 `还款 > I_total`，剩余冲本金；否则冲减应付息余额。本金归零后不计息。
6. **输出**: `ReportLineItem` 明细；冲抵次序与行间舍入对齐。

**注**：§0 备忘行 4.2「本金清零后不再计息」之止算日与 **`D_eff`**（§1.B.2）一致。

Python 入口：`legal_calc.private_lending.calculate_private_lending`。HTTP：`POST /api/calculate`、`POST /api/export/excel`（请求体 `PrivateLendingRequest`）。Excel：`legal_calc.export.export_private_lending_workbook`。

---

## 2. 房屋租赁计算逻辑 (House Rental)

### A. 租金滞纳金

- **应交租日**：每月 **`rent_due_day_of_month` 日**（1–31）；若大于当月天数则钳为当月最后一日（`due_date_by_day_of_month`）。
- **滞纳金计息**：自应交租日**次日**起至 **`filing_date`（含）**；半开上界为 **`filing_date + 1 日`**。
- **欠租统计区间** `arrears_period_start`～`arrears_period_end`：**仅用于本金统计口径**（写入 `assumptions_used`），**不参与**滞纳金起止裁切（§0.1 第 15–16 条）。
- **滞纳金所涉自然月范围**：起点日为 **`lease_start`（若填）否则 `arrears_period_start`**；终点日为 **`min(lease_end, filing_date)`（若填 `lease_end`）否则 `filing_date`**；对该闭区间内的每个自然月分别生成滞纳金行（各月未单独建模「是否已付租」时，按每月一行义务处理，与业务「未付清则计」在实现上等同为逐月出表）。
- **利率**：一年期 LPR÷365×自然日×月租金（**无四倍**）；按报价发布日切段。
- **舍入**：各分段先四舍五入到分再累加。

### B. 占用费

- **起算**：**合同解除日次日**。
- **止算**：有 **实际搬离日** 则至该日（含）；否则 **起诉日 + 30 日**（含）。若止日早于起算日，**不产生占用费行**（在 `messages` 中说明）。
- **标准**：`(月租金 / 30) × 2 × 自然日数`（全程 `Decimal`）。

Python 入口：`legal_calc.rental.calculate_rental`。Excel：`legal_calc.export.export_rental_workbook`。HTTP：`POST /api/rental/calculate`、`POST /api/rental/export/excel`。

---

## 3. 输出要求 (Excel 结构)

工作簿由 `legal_calc.export.write_report_workbook` 生成，含 **「计算明细」** 与 **「审计信息」** 两个 Sheet。

**计算明细** 表头（见 `legal_calc.export.REPORT_HEADERS`，严格顺序）：

- 费用类目（含阶段说明，以「｜」拼入同列）
- 计算基数
- 利率标准
- 起始日、截止日、天数
- 金额

**审计信息**：`RULE_VERSION`、`Input_Snapshot`（JSON）、计算所用 **LPR 原始 JSON**（默认读取包内 `lpr_1y_cny.json`）、以及 `assumptions_used`、`messages`、行合计。

小计与总计可在导出层对「金额」列求和（与「先舍入再求和」一致）。

### 3.1 民间借贷：利息小计与本息合计（已定稿，导出/UI 待迭代）

与 §0.1 回复稿一致，**待**在导出与前端结果区增加：

- **利息小计**：所有「利息」类 `ReportLineItem` 行之金额之和（民间借贷不含滞纳金扩展）。
- **本息合计**：本金经还款冲抵后的余额口径 + 利息小计（展示时点与冲抵后本金一致，见业务回复稿）。

当前试算 JSON 仍为 `lines` 列表；合数字段可在 `CalculationResult` 扩展或仅在 Excel 层追加行，实现前以本节为口径源。

### 3.2 实现状态（与 `RULE_VERSION` 同步）

| 能力 | 状态 | 说明 |
|------|------|------|
| 民间借贷分界 `2020-08-19`/`2020-08-20` | **已实现** | `legal_calc/private_lending.py` |
| 民间借贷计息末日 `D_eff=max(end_date,filing_date)` | **已实现** | 有 `filing_date` 时冲抵与末段均用 `D_eff` |
| 民间借贷利息小计 / 本息合计 | **未实现** | 见 §3.1 |
| 约定利率 0 与无约定分支的专项展示 | **部分**：仍走既有分支；可按 §0.1 第 14 条复查 |
| 租赁 `rent_due_day_of_month` + 滞纳至起诉日 + 欠租不裁滞纳金 | **已实现** | `legal_calc/rental/` |
| 水电 / 物业费滞纳金 | **未实现** | §0.1 第 18 条 |
| 界面「20 号」等展示 | **本期不做** | §0.1 第 17 条 |

---

## 4. 前端与 HTTP 交付（与架构、UI 规范同步）

本节描述 **workbench** 中与计算相关的联调约定；**产品级分期与布局愿景**仍以《[Product_System_Architecture.md](./Product_System_Architecture.md)》§2.4、《[UI_Design_Spec.md](./UI_Design_Spec.md)》§2.1.1 为准。若实现与本文不一致，**以代码为事实**，并回写 PRD。

### 4.1 民间借贷

| 项 | 约定 |
|----|------|
| 试算 | `POST /api/calculate`，JSON 与 `PrivateLendingRequest` 一致（金额字段为字符串小数、`convention` 如 `civil_365_simple`） |
| 导出 | `POST /api/export/excel`，请求体同试算；响应为 XLSX |
| 前端 Tab 文案 | 「民间借贷」 |
| 下载文件名 | `民间借贷计算书.xlsx`（浏览器端 `download` 属性；服务端 `Content-Disposition` 另带 UTF-8 `filename*`） |

**拒绝口径**：请求 `finance_360_compound` 等金融类 360/复利约定时，API 校验拒绝（与 §0 备忘 5 一致）。

### 4.2 房屋租赁

| 项 | 约定 |
|----|------|
| 试算 | `POST /api/rental/calculate`，JSON 与 `RentalRequest` 一致 |
| 导出 | `POST /api/rental/export/excel` |
| 前端 Tab 文案 | 「房屋租赁」 |
| 下载文件名 | `房屋租赁计算书.xlsx` |

**字段与校验（摘要）**：`monthly_rent`、`arrears_period_start` / `arrears_period_end`（本金统计）、**`rent_due_day_of_month`（1–31）**、`contract_termination_date` 必填；`filing_date` 在计滞纳金时**必填**（与引擎 `assert` 一致；无搬离时亦用于占用费止日+30）。`actual_vacate_date` 与 `filing_date` 至少其一满足占用费规则（见 §0 备忘 8.x）。可选 `lease_start` / `lease_end`：用于限定滞纳金所涉**月份范围**的起止（与欠租区间脱钩）。

**前端预校验**：无「实际搬离日」且无「起诉日」时，宜在调用 API 前提示用户，与后端 `RentalRequest` 一致。

### 4.3 结果 JSON 与 UI

试算响应为 `CalculationResult` 的 JSON：`ok`、`rule_version`、`assumptions_used`、`lines`（与 §3 列语义一致）、`messages`。前端以表格展示 `lines`，并展示 `rule_version` 与 `assumptions_used`；`messages` 在租赁等场景可能非空，建议用 `Alert` 展示。

### 4.4 源码索引

- 后端入口：`main.py`
- 前端：`web/src/App.tsx`、`PrivateLendingPanel.tsx`、`RentalPanel.tsx`、`calcShared.tsx`
- 联调：`web` 开发服务器将 `/api`、`/health` 代理至后端 **8000**（见 `web/vite.config.ts`）

### 4.5 服务端日志（排障）

- 环境变量 `LOG_LEVEL`（默认 `INFO`）；`DEBUG` 时在一次请求通过 Pydantic 校验后，可将请求体 JSON 记入日志（含金额字段，**仅供本地/受控环境排障**）。
- 响应头 `X-Request-ID` 与控制台中带 `[id]` 的访问行、业务摘要行对应；`/health` 在 `INFO` 下不刷屏（详见 `main.py` 模块说明）。
