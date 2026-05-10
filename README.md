# workbench / legal-calc

法律计算器 **Python 包**（与 `PRDs/Legal_Logic_Implementation.md` 对齐）。民间借贷 **单利 365** 与房屋租赁滞纳金/占用费已实现；**金融类 360/复利** 在 `PrivateLendingRequest` 层 **直接拒绝** 并提示不适用。

## 开发

```bash
pip install -e ".[dev]"
python -m pytest
```

### 交付层（FastAPI + React 原型）

**后端**（仓库根目录）：

```bash
pip install -e ".[dev,api]"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- `GET /health`：健康检查  
- `POST /api/calculate`：请求体 `PrivateLendingRequest`（JSON）  
- `POST /api/export/excel`：民间借贷 Excel（含审计页）  
- `POST /api/rental/calculate`：请求体 `RentalRequest`  
- `POST /api/rental/export/excel`：房屋租赁 Excel（含审计页）

**前端**（`web/`，需 Node.js）：

```bash
cd web
npm install
npm run dev
```

浏览器访问 Vite 默认端口（一般为 `http://127.0.0.1:5173`）。开发时通过 Vite 代理转发 `/api`、`/health` 到后端 `8000`。

UI：页面背景 `#F8FAFC`，Ant Design 主题主色 `#1D4ED8`。

**服务器 Docker 部署**（前后端分离镜像 + Compose）：见 [`docs/DEPLOY_DOCKER.md`](docs/DEPLOY_DOCKER.md)。根目录已提供 `Dockerfile.api`、`Dockerfile.web`、`docker-compose.yml`、`docker/nginx.conf`。

## 包结构

- `legal_calc.common`：日期分段、`LprProvider` 接口、`JsonFileLprProvider`（默认读 `legal_calc/data/lpr_1y_cny.json`）
- `legal_calc.private_lending`：模块文件 `private_lending.py`，入口 `calculate_private_lending`
- `legal_calc.rental`：滞纳金（欠租区间∩租期、LPR 按日）+ 占用费；`export_rental_workbook`
- `legal_calc.export`（`export.py`）：`write_report_workbook`，Sheet「计算明细」「审计信息」，openpyxl
