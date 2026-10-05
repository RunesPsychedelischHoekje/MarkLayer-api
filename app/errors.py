"""One error shape for every failure: {"error": {"code": ..., "message": ...}}."""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's own parameter checks (bad `kind`, `quality` out of range...), in our shape.

    `fields` lists each problem, so clients can point at the right input.
    """
    fields = []
    for e in exc.errors():
        # loc looks like ("body", "quality") or ("query", "url"): drop where it came from.
        name = ".".join(str(p) for p in e.get("loc", ())[1:]) or "request"
        fields.append({"field": name, "message": e.get("msg", "invalid value")})
    message = "; ".join(f"{f['field']}: {f['message']}" for f in fields) or "Invalid request."
    return JSONResponse(status_code=422,
                        content={"error": {"code": "invalid_request", "message": message, "fields": fields}})
