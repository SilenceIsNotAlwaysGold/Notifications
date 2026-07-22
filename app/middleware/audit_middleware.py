import json
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs
from typing import Any

from app.db.session import SessionLocal
from app.models.operation_audit_log import OperationAuditLog

logger = logging.getLogger(__name__)

SENSITIVE_KEYWORDS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "webhook",
    "password",
    "private_key",
    "input_text",
    "phone",
    "verification_code",
    "verification_value",
    "identity_number",
)

AUDIT_EXCLUDED_ENDPOINTS = {
    ("GET", "/api/v1/legal/android-device/screenshot"),
}


class OperationAuditMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        method = str(scope.get("method") or "").upper()
        path = str(scope.get("path") or "")
        if (
            scope.get("type") != "http"
            or not path.startswith("/api/v1/legal")
            or (method, path) in AUDIT_EXCLUDED_ENDPOINTS
        ):
            await self.app(scope, receive, send)
            return

        body_messages, body = await self._read_body(receive)
        message_index = 0
        status_code: int | None = None
        response_body = bytearray()

        async def replay_receive() -> dict[str, Any]:
            nonlocal message_index
            if message_index < len(body_messages):
                message = body_messages[message_index]
                message_index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 0)
            elif message.get("type") == "http.response.body" and len(response_body) < 2000:
                chunk = message.get("body") or b""
                response_body.extend(chunk[: 2000 - len(response_body)])
            await send(message)

        try:
            await self.app(scope, replay_receive, send_wrapper)
        finally:
            self._write_audit_log(scope, body, bytes(response_body), status_code)

    @staticmethod
    async def _read_body(receive: Callable[[], Awaitable[dict[str, Any]]]) -> tuple[list[dict[str, Any]], bytes]:
        messages = []
        body_parts = []
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") != "http.request":
                break
            body_parts.append(message.get("body") or b"")
            if not message.get("more_body", False):
                break
        return messages, b"".join(body_parts)

    def _write_audit_log(self, scope: dict[str, Any], request_body: bytes, response_body: bytes, status_code: int | None) -> None:
        db = SessionLocal()
        try:
            path = str(scope.get("path") or "")
            method = str(scope.get("method") or "")
            state = scope.get("state") or {}
            client = scope.get("client") or (None, None)
            log = OperationAuditLog(
                operator=state.get("operator") or "unknown",
                auth_type=state.get("auth_type") or "unknown",
                operator_role=state.get("operator_role"),
                api_key_id=state.get("api_key_id"),
                api_key_prefix=state.get("api_key_prefix"),
                tenant_id=self._extract_tenant_id(scope, request_body),
                action=f"{method} {path}",
                method=method,
                path=path,
                status_code=status_code,
                request_summary_json=json.dumps(self._request_summary(request_body), ensure_ascii=False, default=str),
                response_summary_json=json.dumps(self._response_summary(response_body), ensure_ascii=False, default=str),
                resource_scope_json=json.dumps(self._resource_scope_summary(state.get("resource_scope") or {}), ensure_ascii=False, default=str),
                client_host=client[0] if client else None,
                user_agent=self._header(scope, "user-agent"),
            )
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("写入操作审计日志失败")
        finally:
            db.close()

    @staticmethod
    def _header(scope: dict[str, Any], name: str) -> str | None:
        target = name.lower().encode()
        for key, value in scope.get("headers") or []:
            if key.lower() == target:
                return value.decode("utf-8", errors="ignore")
        return None

    def _request_summary(self, body: bytes) -> dict[str, Any] | None:
        if not body:
            return None
        text = body.decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(text)
            sanitized = self._sanitize(parsed)
            serialized = json.dumps(sanitized, ensure_ascii=False, default=str)
            if len(serialized) > 1000:
                return {"json_excerpt": serialized[:1000], "truncated": True}
            return {"json": sanitized}
        except Exception:
            return {"raw_excerpt": text[:1000], "truncated": len(text) > 1000}

    @staticmethod
    def _response_summary(body: bytes) -> dict[str, Any] | None:
        if not body:
            return None
        try:
            parsed = json.loads(body.decode("utf-8", errors="ignore"))
            return {"code": parsed.get("code"), "message": parsed.get("message")}
        except Exception:
            return None

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: "***" if self._is_sensitive(str(key)) else self._sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        return value

    @staticmethod
    def _is_sensitive(key: str) -> bool:
        lowered = key.lower()
        return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)

    @staticmethod
    def _extract_tenant_id(scope: dict[str, Any], body: bytes) -> str | None:
        query_string = (scope.get("query_string") or b"").decode("utf-8", errors="ignore")
        query = parse_qs(query_string)
        if query.get("tenant_id"):
            return query["tenant_id"][0]
        if body:
            try:
                parsed = json.loads(body.decode("utf-8", errors="ignore"))
                if isinstance(parsed, dict) and parsed.get("tenant_id") is not None:
                    return str(parsed["tenant_id"])
            except Exception:
                return None
        return None

    @staticmethod
    def _resource_scope_summary(scope: dict[str, Any]) -> dict[str, Any]:
        summary = {}
        for key in ("allowed_group_ids", "allowed_case_ids", "allowed_tenant_ids"):
            values = list(scope.get(key) or [])
            summary[key] = {"items": values[:20], "total_count": len(values)}
        return summary
