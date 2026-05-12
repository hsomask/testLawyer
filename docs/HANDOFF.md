# 对话续作说明（Handoff）

**产品口径（分期、UI、业务规则、HTTP/前端约定）以 PRD 为准**，请勿与本页重复造不一致描述：

- `PRDs/Product_System_Architecture.md`（含 **§2.4** 当前仓库交付快照）
- `PRDs/UI_Design_Spec.md`（含 **§2.1.1** 金额计算原型 Tabs）
- `PRDs/Legal_Logic_Implementation.md`（含 **§4** 前端与 HTTP 交付）

把本页贴进新对话即可续开发（例如：HTTPS、权限、案件表等）。

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
- **改规则**：先改 `PRDs/Legal_Logic_Implementation.md`（含 **§0.1 业务定稿补充**），再改 `private_lending.py` / `rental/engine.py` 与 pytest，并同步检查 PRD §0/§1–§3 是否与代码一致

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
