# 对话续作说明（Handoff）

**产品口径（分期、UI、业务规则、HTTP/前端约定）以 PRD 为准**，请勿与本页重复造不一致描述：

- `PRDs/Product_System_Architecture.md`（含 **§2.4** 当前仓库交付快照）
- `PRDs/UI_Design_Spec.md`（含 **§2.1.1** 金额计算原型 Tabs）
- `PRDs/Legal_Logic_Implementation.md`（**§0 / §0.1** 业务备忘、**§2** 租赁公式、**§3.2** 实现状态表、**§4** HTTP/前端）

## 最近迭代摘要（新开窗口续作）

以下已合入 **`develop`** 并已推送 **`origin/develop`**；口径以 PRD 为准，**§3.2** 与代码同步。

**民间借贷**

- 利率分界：**2020-08-19（含）旧规则末日**，**2020-08-20** 起新规则（`private_lending`）。
- 计息末日 **`D_eff`**：有 `filing_date` 时为 **`max(end_date, filing_date)`**（含当日）；冲抵、末段、还款晚于 `D_eff` 的 WARN 均按 `D_eff`。
- `lpr_four_x_reference_date`：无起诉/文档月时回退 **计息末日 `D_eff` 所在月**（月末回溯）。
- **利息小计 / 冲抵后剩余本金 / 本息合计**（PRD §3.1）：`CalculationResult` 三字段 **`interest_subtotal`、`remaining_principal`、`total_principal_and_interest`**；试算 JSON、民间借贷 Excel（明细末 + 审计键）、`PrivateLendingPanel` 结果区已对齐；租赁试算该三项为 **`null`**。

**房屋租赁（API 有破坏性变更）**

- 请求字段 **`rent_due_day_of_month`（1–31）`** 表示每月第几日交租（大于当月天数则钳为月末）；**已删除** `rent_due_days_before_month_end`。
- 滞纳金：**自应交租日次日起至 `filing_date`（含）**；**欠租区间**仅作本金统计说明（写入 `assumptions_used`），**不裁**滞纳金。
- 滞纳金所涉**自然月范围**：起点 `lease_start` 否则 `arrears_period_start`；终点 `min(lease_end, filing_date)` 否则 `filing_date`；与欠租区间脱钩。
- **物业费 / 水电费滞纳金（Demo）**：可选 `monthly_property_management_fee`、`monthly_utility_fee`；与租金**同一次** `POST /api/rental/calculate`；规则见 Legal **§2.C**（与 `rent_due_day_of_month` 同序位；定稿前可改）。
- 前端：`web/src/RentalPanel.tsx`（含 Demo 说明 Alert 与可选字段）；`npm run build` 可通过。

**版本与测试**

- `legal_calc/version.py`：`RULE_VERSION = "1.4.0-prd-2026-05-12"`（以文件为准）。
- 全量测试当前：**36 passed**（`python -m pytest`）。

**未完项**：见下文 **「待完成事项」**（与 `Legal_Logic_Implementation.md` **§3.2** 一致）。

**其它**

- `main.py`：排障日志（`LOG_LEVEL`、`X-Request-ID`、业务摘要）已在此前提交。
- 根目录 `DEPLOY.md` 若存在多为本地稿，**未**默认纳入 git。

把本页贴进新对话即可续开发（例如：HTTPS、权限、案件表等）。

---

## 待完成事项（PRD 已定稿或已排队 / 与 §3.2 未完对齐）

新窗口续作时**优先对 PRD 与下表对齐**，避免与 §3.2 漂移。

| 序号 | 事项 | 说明 / 卡住点 | 建议落点 |
|------|------|-----------------|----------|
| 1 | 水电 / 物业费滞纳金 **定稿与扩展** | **Demo** 已实现（Legal **§2.C**：可选月费、与租金同算、同 LPR 规则）；待业务确认：独立应付日、抄表周期、分项/拆 API、与主文表述 | 回写 PRD §2.C 后迭代 `RentalRequest` / `rental/engine.py` |
| 2 | **约定年化利率 = 0** | 业务要求与「无约定」及 `D_eff` 一致（§0.1 **第 14 条**）；代码仍走「有约定」分支时需 **显式分支或归并** | `legal_calc/private_lending.py` + `tests/test_private_lending.py` |
| 3 | 租赁 **「该月已付清则不计滞纳」** | 当前 **无每月实付/欠付** 输入；引擎只能按月份范围 **逐月出表** | `RentalRequest` 增可选「月实付」或标记；`rental/engine.py` |
| 4 | 界面「**20 号**」等展示优化 | Legal §0.1 **第 17 条**：**本期关闭**，待业务再给截图/文案 | `web/src/RentalPanel.tsx` 或后续 |
| 5 | 产品级 backlog（与计算无关） | 从未在本仓库实现：HTTPS、鉴权、案件表、顶栏搜索等 | 见 `Product_System_Architecture.md`、**§2.4** 未纳入项 |

**备注**：改规则仍须 **先改 PRD**（尤其 §0 / §0.1 / §3.2），再改代码与 pytest（见下文「已知注意点」）。

## 项目与仓库

- 路径：`c:\Users\hsoluo\Desktop\testLawyer\workbench`
- Python 包：`legal_calc`（`pyproject.toml` 可 `pip install -e ".[dev,api]"`）

## 实现索引（路径速查，口径见 PRD）

| 模块 | 位置 |
|------|------|
| 民间借贷 | `legal_calc/private_lending.py` |
| 租赁 | `legal_calc/rental/models.py`、`engine.py` |
| LPR | `legal_calc/data/lpr_1y_cny.json`、`legal_calc/common/lpr_json_file.py` |
| 导出 | `legal_calc/export.py`（`REPORT_HEADERS`） |
| 版本 | `legal_calc/version.py`（`RULE_VERSION`） |
| API | `main.py` |
| Web | `web/src/App.tsx`、`PrivateLendingPanel.tsx`、`RentalPanel.tsx`、`calcShared.tsx` |
| Docker | `Dockerfile.api`、`Dockerfile.web`、`docker-compose.yml`、`docker/nginx.conf`；`docs/DEPLOY_DOCKER.md` |

## API 排障日志（`main.py`）

- 环境变量 `LOG_LEVEL`：默认 `INFO`；`DEBUG` 时计算类接口会打印**已通过校验**的请求体 JSON（含敏感金额，仅建议本地排障）。
- 控制台同一请求用方括号中的 **request id** 串起来看；响应头 `X-Request-ID` 与此一致。
- 每条非 `/health` 请求会打：进入行、结束行（含状态码与耗时 ms）、成功时 `rule_version` / 行数 / 金额合计、导出时 `xlsx_bytes`；`400/422` 会打 `ValueError` 或 Pydantic 校验详情；已降低 `uvicorn.access` 噪音，避免与上述重复。

## 测试

- `tests/test_private_lending.py`、`tests/test_rental.py`、`tests/test_main_api.py`、`tests/test_excel_export.py` 等
- 全量：`python -m pytest`

## 已知注意点

- `__pycache__` 等属本地生成，可忽略或清理
- 前端 `npm audit` moderate 可按需处理
- **改规则**：先改 `PRDs/Legal_Logic_Implementation.md`（§0 / §0.1 / §3.2），再改 `private_lending.py` / `rental/` 与 pytest；**租赁 API 字段** `rent_due_day_of_month`（已替代旧 `rent_due_days_before_month_end`）。

## 常用命令

```bash
# 后端
pip install -e ".[dev,api]"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```bash
# 前端
cd web && npm run dev
```

```bash
# 测试
python -m pytest
```

```bash
# Docker
docker compose up -d --build
```
