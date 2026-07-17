from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


class NotFoundError(Exception):
    """資源不存在 → 404 {"error": "not found"}。"""


class DomainError(Exception):
    """業務規則違反（如 exercise 不存在、名稱重複）→ 400 {"error": message}。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UnknownExerciseError(Exception):
    """log_workout 內含動作庫比對不到的動作名（雙語皆未命中）→ 整包拒絕不寫入。"""

    def __init__(self, unknown: list[str], suggestions: list[str]) -> None:
        self.unknown = unknown
        self.suggestions = suggestions
        super().__init__(f"unknown exercise: {', '.join(unknown)}")


class ConflictError(Exception):
    """冪等鍵衝突（client_uuid 已用於其他 workout 或已刪除的組）→ 409。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def validation_message(exc: RequestValidationError | ValidationError) -> str:
    """驗證錯誤 → 單行人話（REST handler 與 MCP tools 共用，避免兩套訊息 drift）。"""
    first = exc.errors()[0]
    field = str(first["loc"][-1]) if first["loc"] else "body"
    if first["type"] == "missing":
        return f"{field} required"
    return f"{field} invalid: {first['msg']}"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(status.HTTP_400_BAD_REQUEST, validation_message(exc))

    @app.exception_handler(UnknownExerciseError)
    async def on_unknown_exercise(request: Request, exc: UnknownExerciseError) -> JSONResponse:
        # 目前只有 MCP 走 log_workout；註冊 handler 讓未來 REST 曝露時不會 500
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "unknown exercise",
                "unknown": exc.unknown,
                "suggestions": exc.suggestions,
            },
        )

    @app.exception_handler(NotFoundError)
    async def on_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return _error(status.HTTP_404_NOT_FOUND, "not found")

    @app.exception_handler(DomainError)
    async def on_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return _error(status.HTTP_400_BAD_REQUEST, exc.message)

    @app.exception_handler(ConflictError)
    async def on_conflict(request: Request, exc: ConflictError) -> JSONResponse:
        return _error(status.HTTP_409_CONFLICT, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "error"
        return _error(exc.status_code, detail)
