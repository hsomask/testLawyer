"""
法律计算器 HTTP 服务：民间借贷计算与 Excel 导出。

运行（仓库根目录）::

    pip install -e ".[api]"
    uvicorn main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from legal_calc.export import export_private_lending_workbook, export_rental_workbook
from legal_calc.private_lending import PrivateLendingRequest, calculate_private_lending
from legal_calc.rental import RentalRequest, calculate_rental

app = FastAPI(
    title="法律计算器 API",
    description="民间借贷与房屋租赁：计算与 Excel 导出",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/calculate")
def api_calculate(body: PrivateLendingRequest) -> dict:
    """执行 ``calculate_private_lending``，返回可 JSON 序列化的计算结果。"""
    try:
        result = calculate_private_lending(body)
        return result.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/export/excel")
def api_export_excel(body: PrivateLendingRequest) -> Response:
    """根据同一请求体重新计算并下载 Excel 计算书（含审计页）。"""
    try:
        result = calculate_private_lending(body)
        bio = export_private_lending_workbook(body, result)
        data = bio.getvalue()
        fname = "民间借贷计算书.xlsx"
        cd = f"attachment; filename=report.xlsx; filename*=UTF-8''{quote(fname)}"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": cd},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/rental/calculate")
def api_rental_calculate(body: RentalRequest) -> dict:
    try:
        result = calculate_rental(body)
        return result.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/rental/export/excel")
def api_rental_export_excel(body: RentalRequest) -> Response:
    try:
        result = calculate_rental(body)
        bio = export_rental_workbook(body, result)
        data = bio.getvalue()
        fname = "房屋租赁计算书.xlsx"
        cd = f"attachment; filename=rental-report.xlsx; filename*=UTF-8''{quote(fname)}"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": cd},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
