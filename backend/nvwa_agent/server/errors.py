"""统一错误响应（§9）：{code, message} + HTTP 状态码映射（§18 REST通用）。"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from nvwa_agent.core.log import get_core_logger
from nvwa_agent.core.plugin_runtime.runtime import PluginOpError

_log = get_core_logger()

# 错误码 -> HTTP 状态码
HTTP_STATUS = {
    "VALIDATION_ERROR": 400,
    "NOT_FOUND": 404,
    "PLUGIN_STATE_INVALID": 409,
    "PLUGIN_ID_CONFLICT": 409,
    "FILE_TOO_LARGE": 413,
    "INTERNAL_ERROR": 500,
}


class ApiError(Exception):
    """业务错误：携带错误码与 HTTP 状态。"""

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or HTTP_STATUS.get(code, 400)


def error_response(code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=HTTP_STATUS.get(code, 400),
                        content={"code": code, "message": message})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status,
                            content={"code": exc.code, "message": exc.message})

    @app.exception_handler(PluginOpError)
    async def _plugin_error(_req: Request, exc: PluginOpError):
        status = HTTP_STATUS.get(exc.code, 409)
        return JSONResponse(status_code=status,
                            content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = first.get("msg", "请求参数校验失败")
        return JSONResponse(status_code=400, content={
            "code": "VALIDATION_ERROR", "message": f"{loc}: {msg}" if loc else msg,
        })

    @app.exception_handler(Exception)
    async def _internal(_req: Request, exc: Exception):
        _log.error("未分类内部异常: %s", exc, exc_info=exc)  # 完整堆栈仅写后端日志
        return JSONResponse(status_code=500, content={
            "code": "INTERNAL_ERROR", "message": "服务内部错误，请查看后端日志",
        })
