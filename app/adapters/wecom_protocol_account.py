from typing import Any

import httpx


class WeComProtocolAccountError(RuntimeError):
    pass


class WeComProtocolAccount:
    """Control-plane client for the isolated sender account gateway."""

    def __init__(
        self,
        *,
        base_url: str | None,
        api_path: str,
        token: str | None,
        guid: str | None,
        timeout_seconds: float,
    ) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_path = "/" + api_path.strip().lstrip("/")
        self.token = (token or "").strip()
        self.guid = (guid or "").strip()
        self.timeout_seconds = timeout_seconds

    def status(self) -> dict[str, Any]:
        missing = self._missing_config()
        if missing:
            return {
                "backend": "protocol",
                "stage": "not_configured",
                "online": False,
                "missing": missing,
            }
        payload = self._invoke("/login/checkLogin")
        data = self._data(payload)
        online = self._is_online(data)
        return {
            "backend": "protocol",
            "stage": "logged_in" if online else "logged_out",
            "online": online,
            "account_name": self._first_text(data, "name", "userName", "nickname"),
        }

    def start_login(self) -> dict[str, Any]:
        self._require_config()
        payload = self._invoke("/login/getLoginQrcode")
        data = self._data(payload)
        qr_code = self._first_text(
            data,
            "qrCodeUrl",
            "qrcodeUrl",
            "qrCode",
            "qrcode",
            "url",
        )
        if not qr_code:
            raise WeComProtocolAccountError("协议网关未返回登录二维码")
        return {
            "backend": "protocol",
            "stage": "qr_code",
            "online": False,
            "qr_code": qr_code,
        }

    def poll_login(self) -> dict[str, Any]:
        self._require_config()
        payload = self._invoke("/login/checkLoginQrcode")
        data = self._data(payload)
        online = self._is_online(data)
        verification_required = self._verification_required(data)
        status = str(data.get("status", "")).strip().lower()
        return {
            "backend": "protocol",
            "stage": (
                "logged_in"
                if online
                else "verification_code"
                if verification_required
                else "login_pending"
                if status in {"2", "6", "succeeded", "qr_login_succeeded"}
                else "qr_code"
            ),
            "online": online,
            "verification_required": verification_required,
        }

    def verify_login(self, verification_value: str) -> dict[str, Any]:
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in verification_value
        ):
            raise ValueError("身份校验信息不能包含控制字符")
        normalized = verification_value.strip()
        if not normalized or len(normalized) > 64:
            raise ValueError("请输入有效的身份校验信息")
        self._require_config()
        payload = self._invoke(
            "/login/verifyLoginQrcode", {"verificationValue": normalized}
        )
        data = self._data(payload)
        return {
            "backend": "protocol",
            "stage": "logged_in" if self._is_online(data) else "login_pending",
            "online": self._is_online(data),
        }

    def logout(self) -> dict[str, Any]:
        self._require_config()
        self._invoke("/login/logout")
        return {"backend": "protocol", "stage": "logged_out", "online": False}

    def _invoke(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        request_params["guid"] = self.guid
        try:
            response = httpx.post(
                f"{self.base_url}{self.api_path}",
                headers={"WECOM-TOKEN": self.token, "Content-Type": "application/json"},
                json={"method": method, "params": request_params},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise WeComProtocolAccountError(
                f"协议网关连接失败：{type(exc).__name__}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise WeComProtocolAccountError(
                f"协议网关返回非 JSON，HTTP {response.status_code}"
            ) from exc
        if response.status_code >= 400:
            raise WeComProtocolAccountError(f"协议网关 HTTP {response.status_code}")
        if not isinstance(payload, dict):
            raise WeComProtocolAccountError("协议网关返回格式不正确")
        code = payload.get("code")
        if code not in (None, 0, "0"):
            message = payload.get("msg") or payload.get("message") or "未知错误"
            raise WeComProtocolAccountError(f"协议网关拒绝请求：{message}")
        return payload

    def _missing_config(self) -> list[str]:
        values = {
            "WECOM_PROTOCOL_ACCOUNT_BASE_URL": self.base_url,
            "WECOM_PROTOCOL_ACCOUNT_TOKEN": self.token,
            "WECOM_PROTOCOL_ACCOUNT_GUID": self.guid,
        }
        return [name for name, value in values.items() if not value]

    def _require_config(self) -> None:
        missing = self._missing_config()
        if missing:
            raise WeComProtocolAccountError(f"协议账号缺少配置：{', '.join(missing)}")

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _is_online(data: dict[str, Any]) -> bool:
        for key in ("online", "isOnline", "isLogin", "loggedIn"):
            if key in data:
                value = data[key]
                return value is True or value in (1, "1", "true", "online")
        return False

    @staticmethod
    def _verification_required(data: dict[str, Any]) -> bool:
        return data.get("status") in (10, "10", "needs_verification") or any(
            data.get(key) is True or data.get(key) in (1, "1", "true")
            for key in ("needVerify", "needVerification", "verifyRequired")
        )

    @staticmethod
    def _first_text(data: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
