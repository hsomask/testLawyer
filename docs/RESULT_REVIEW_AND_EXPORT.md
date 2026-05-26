# 结果复核与导出说明

## 计算结果模型

### CalculationResult

每次计算（民间借贷 / 房屋租赁）的统一返回结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | bool | 业务规则实现完整且通过自检时为 True |
| `rule_version` | string | 规则版本号，对应 `legal_calc/version.py` |
| `assumptions_used` | list[str] | 本次计算采用的计算口径说明 |
| `lines` | list[ReportLineItem] | 逐行明细 |
| `messages` | list[str] | 警告或提示信息 |
| `interest_subtotal` | Decimal \| null | **民间借贷专属**：利息类金额小计 |
| `remaining_principal` | Decimal \| null | **民间借贷专属**：冲抵后剩余本金 |
| `total_principal_and_interest` | Decimal \| null | **民间借贷专属**：本息合计 |
| `rental_summary` | RentalSummary \| null | **房屋租赁专属**：结构化汇总 |

> 民间借贷计算中 `rental_summary` 为 `null`；房屋租赁计算中 `interest_subtotal`、`remaining_principal`、`total_principal_and_interest` 均为 `null`。

### RentalSummary

房屋租赁计算结果的结构化汇总，所有字段均为 `Decimal`：

| 字段 | 说明 |
|------|------|
| `rent_receivable_subtotal` | 应收租金小计（按自然月拆分折算） |
| `paid_rent_amount` | 已支付租金合计 |
| `arrears_principal_subtotal` | 欠租本金小计 = 应收租金 − 已支付租金 |
| `rent_late_fee_subtotal` | 租金滞纳金小计（固定 LPR，不再分段） |
| `utility_late_fee_subtotal` | 水电费滞纳金小计 |
| `property_late_fee_subtotal` | 物业费滞纳金小计 |
| `other_late_fee_subtotal` | 其他费用滞纳金小计 |
| `occupancy_fee_subtotal` | 房屋占用费小计（按自然月拆分） |
| `grand_total` | 最终总计 = 以上各小计之和 |

> `paid_rent_amount` 仅扣减欠租本金小计，不影响租金滞纳金基数。

### ReportLineItem

明细行的字段含义：

| 字段 | 说明 |
|------|------|
| `fee_category` | 费用类目，如「利息」「欠租本金」「租金滞纳金」「物业费滞纳金」「水电费滞纳金」「其他费用滞纳金」「房屋占用费」 |
| `stage_description` | 阶段说明，描述该行的计算逻辑（如适用时间段、规则依据） |
| `principal_base` | 计算基数（本金或计费基数），单位：元 |
| `rate_standard` | 适用利率标准（展示用文案） |
| `period_start` | 计息起始日（含） |
| `period_end` | 计息截止日（含） |
| `day_count` | 计算天数 |
| `amount` | 应付金额（元） |

## Excel 计算书结构

Excel 文件包含两个 Sheet：

### 1. 计算明细

- 表头：费用类目、计算基数、利率标准、起始日、截止日、天数、金额
- 每行对应一个 `ReportLineItem`
- 费用类目列包含「费用类目｜阶段说明」合并文本
- **民间借贷**：明细末尾追加三行合计
  - 【利息小计】
  - 【冲抵后剩余本金】
  - 【本息合计】
- **房屋租赁**：明细末尾追加九行汇总
  - 【应收租金小计】
  - 【已支付租金合计】
  - 【欠租本金小计】
  - 【租金滞纳金小计】
  - 【水电费滞纳金小计】
  - 【物业费滞纳金小计】
  - 【其他费用滞纳金小计】
  - 【房屋占用费小计】
  - 【最终总计】

### 2. 审计信息

用于律师复核与归档，包含：

| 字段 | 内容 |
|------|------|
| `RULE_VERSION` | 规则版本号 |
| `Input_Snapshot (JSON)` | 输入参数快照 |
| `LPR_Data_Source` | LPR 数据来源文件路径 |
| `LPR_Raw_JSON` | 计算所用 LPR 原始数据 |
| `assumptions_used` | 计算口径说明（逐条） |
| `messages` | 警告/提示信息 |
| `line_amount_sum` | 明细行金额合计 |
| `interest_subtotal` | 利息小计（仅民间借贷） |
| `remaining_principal` | 冲抵后剩余本金（仅民间借贷） |
| `total_principal_and_interest` | 本息合计（仅民间借贷） |
| `rental_summary` | 房屋租赁结构化汇总 JSON（仅租赁） |

## 如何验证计算结果

### 1. API JSON 验证

```bash
# 民间借贷
curl -s -X POST http://127.0.0.1:8000/api/calculate \
  -H "Content-Type: application/json" \
  -d '{"principal":"10000","loan_date":"2020-09-01","end_date":"2020-10-31","agreed_annual_rate":"0.12","filing_date":"2020-10-15","repayments":[]}' \
  | python -m json.tool

# 房屋租赁
curl -s -X POST http://127.0.0.1:8000/api/rental/calculate \
  -H "Content-Type: application/json" \
  -d '{"monthly_rent":"3000","arrears_period_start":"2025-01-01","arrears_period_end":"2025-01-31","rent_due_day_of_month":26,"contract_termination_date":"2025-03-01","filing_date":"2025-04-01"}' \
  | python -m json.tool
```

一致性检查要点：
- `interest_subtotal` 等于所有 `fee_category == "利息"` 的行的 `amount` 之和
- `total_principal_and_interest` 等于 `interest_subtotal + remaining_principal`
- `line_amount_sum()`（或前端的 `sumLineAmounts`）等于所有行的 `amount` 之和

### 2. Excel 验证

下载 Excel 后检查：
1. 「计算明细」Sheet 表头完整
2. 「审计信息」Sheet 包含 RULE_VERSION、Input_Snapshot、LPR 数据等
3. 民间借贷明细末尾有【利息小计】【冲抵后剩余本金】【本息合计】
4. 房屋租赁**不应**出现上述三行合计

### 3. 运行自动化测试

```bash
python -m pytest -v
```

测试覆盖：
- Excel 导出结构完整性（Sheet、表头、审计字段、合计行）
- `line_amount_sum` 与明细行求和一致性
- API 返回字段一致性
- 错误路径（金融惯例拒绝、无约定利率无到期日、租赁无搬离日无起诉日）

## 重要声明

- **金额计算由确定性规则引擎（`legal_calc` 包）完成，LLM 不参与任何金额计算路径**
- Excel 计算书审计页用于律师复核与案件归档
- 前端金额小计（`sumLineAmounts` / `sumByFeeCategory`）仅作复核展示，不替代后端计算
