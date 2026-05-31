"""
法律计算器 HTTP 服务：民间借贷计算与 Excel 导出。

运行（仓库根目录）::

    pip install -e ".[api]"
    uvicorn main:app --reload --host 127.0.0.1 --port 8000

排障日志：

- 环境变量 ``LOG_LEVEL``：默认 ``INFO``；设为 ``DEBUG`` 时，计算类接口在通过校验后会打出请求体 JSON（含金额，仅供本地排障）。
- 每条请求有 ``X-Request-ID`` 响应头，可与控制台 ``[id]`` 对应。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from legal_calc.export import export_private_lending_workbook, export_rental_workbook
from legal_calc.private_lending import PrivateLendingRequest, calculate_private_lending
from legal_calc.rental import RentalRequest, calculate_rental
from legal_calc.report_models import CalculationResult

_LOG = logging.getLogger("legal_calc.api")


def _setup_logging() -> None:
    if getattr(_setup_logging, "_done", False):
        return
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    setattr(_setup_logging, "_done", True)


_setup_logging()


def _rid(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = uuid.uuid4().hex[:12]
        request.state.request_id = rid
    return rid


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


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    _rid(request)
    path = request.url.path
    quiet = path == "/health"
    if not quiet:
        _LOG.info("[%s] --> %s %s", _rid(request), request.method, path)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        _LOG.exception("[%s] !! %s %s unhandled", _rid(request), request.method, path)
        raise
    ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Request-ID"] = _rid(request)
    if quiet:
        _LOG.debug("[%s] <-- %s %s %s %.1fms", _rid(request), request.method, path, response.status_code, ms)
    else:
        _LOG.info("[%s] <-- %s %s %s %.1fms", _rid(request), request.method, path, response.status_code, ms)
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    _LOG.warning(
        "[%s] 422 参数校验失败 %s %s: %s",
        _rid(request),
        request.method,
        request.url.path,
        exc.errors(),
    )
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(HTTPException)
async def logged_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 500:
        _LOG.error(
            "[%s] %s %s -> %s: %s",
            _rid(request),
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
    else:
        _LOG.warning(
            "[%s] %s %s -> %s: %s",
            _rid(request),
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
    return await http_exception_handler(request, exc)


def _log_result(tag: str, request: Request, result: CalculationResult) -> None:
    extra = ""
    if result.interest_subtotal is not None:
        extra = (
            f" interest_subtotal={result.interest_subtotal}"
            f" remaining_principal={result.remaining_principal}"
            f" total_pi={result.total_principal_and_interest}"
        )
    if result.rental_summary is not None:
        rs = result.rental_summary
        extra = (
            f" arrears_principal={rs.arrears_principal_subtotal}"
            f" rent_late={rs.rent_late_fee_subtotal}"
            f" occup={rs.occupancy_fee_subtotal}"
            f" grand_total={rs.grand_total}"
        )
    _LOG.info(
        "[%s] %s ok=%s rule_version=%s lines=%d amount_sum=%s%s",
        _rid(request),
        tag,
        result.ok,
        result.rule_version,
        len(result.lines),
        str(result.line_amount_sum()),
        extra,
    )
    if result.messages:
        _LOG.info("[%s] %s messages=%s", _rid(request), tag, result.messages)


def _debug_body(request: Request, tag: str, body: object) -> None:
    if not _LOG.isEnabledFor(logging.DEBUG):
        return
    if hasattr(body, "model_dump"):
        payload = body.model_dump(mode="json")
    else:
        payload = body
    _LOG.debug("[%s] %s request_json=%s", _rid(request), tag, json.dumps(payload, ensure_ascii=False))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/calculate")
def api_calculate(request: Request, body: PrivateLendingRequest) -> dict:
    """执行 ``calculate_private_lending``，返回可 JSON 序列化的计算结果。"""
    _debug_body(request, "private_lending.calculate", body)
    try:
        result = calculate_private_lending(body)
        _log_result("private_lending.calculate", request, result)
        return result.model_dump(mode="json")
    except ValueError as e:
        _LOG.warning("[%s] private_lending.calculate ValueError: %s", _rid(request), e)
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/export/excel")
def api_export_excel(request: Request, body: PrivateLendingRequest) -> Response:
    """根据同一请求体重新计算并下载 Excel 计算书（含审计页）。"""
    _debug_body(request, "private_lending.export", body)
    try:
        result = calculate_private_lending(body)
        _log_result("private_lending.export", request, result)
        bio = export_private_lending_workbook(body, result)
        data = bio.getvalue()
        _LOG.info("[%s] private_lending.export xlsx_bytes=%d", _rid(request), len(data))
        fname = "民间借贷计算书.xlsx"
        cd = f"attachment; filename=report.xlsx; filename*=UTF-8''{quote(fname)}"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": cd},
        )
    except ValueError as e:
        _LOG.warning("[%s] private_lending.export ValueError: %s", _rid(request), e)
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/rental/calculate")
def api_rental_calculate(request: Request, body: RentalRequest) -> dict:
    _debug_body(request, "rental.calculate", body)
    try:
        result = calculate_rental(body)
        _log_result("rental.calculate", request, result)
        return result.model_dump(mode="json")
    except ValueError as e:
        _LOG.warning("[%s] rental.calculate ValueError: %s", _rid(request), e)
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/rental/export/excel")
def api_rental_export_excel(request: Request, body: RentalRequest) -> Response:
    _debug_body(request, "rental.export", body)
    try:
        result = calculate_rental(body)
        _log_result("rental.export", request, result)
        bio = export_rental_workbook(body, result)
        data = bio.getvalue()
        _LOG.info("[%s] rental.export xlsx_bytes=%d", _rid(request), len(data))
        fname = "房屋租赁计算书.xlsx"
        cd = f"attachment; filename=rental-report.xlsx; filename*=UTF-8''{quote(fname)}"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": cd},
        )
    except ValueError as e:
        _LOG.warning("[%s] rental.export ValueError: %s", _rid(request), e)
        raise HTTPException(status_code=400, detail=str(e)) from e
