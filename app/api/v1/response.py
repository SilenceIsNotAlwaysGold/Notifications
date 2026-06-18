from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


def ok(message: str, data: Any = None) -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def fail(message: str, code: int = 1) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": code, "message": message, "data": None})


def raise_fail(message: str, code: int = 1, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message, "data": None})
