import base64
import hashlib
import hmac
import json
import time
from io import BytesIO
from typing import Any

import httpx
from fastapi import FastAPI
from PIL import Image, ImageEnhance, ImageOps
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tencent_secret_id: str = Field(default="", alias="TENCENT_OCR_SECRET_ID")
    tencent_secret_key: str = Field(default="", alias="TENCENT_OCR_SECRET_KEY")
    tencent_region: str = Field(default="ap-guangzhou", alias="TENCENT_OCR_REGION")
    tencent_endpoint: str = Field(default="ocr.tencentcloudapi.com", alias="TENCENT_OCR_ENDPOINT")
    tencent_language_type: str = Field(default="zh", alias="TENCENT_OCR_LANGUAGE_TYPE")
    pdf_max_pages: int = Field(default=20, ge=1, le=20, alias="TENCENT_OCR_PDF_MAX_PAGES")
    timeout_seconds: int = Field(default=20, ge=1, alias="TENCENT_OCR_TIMEOUT_SECONDS")


class OCRRequest(BaseModel):
    provider: str = "tencent"
    media_type: str
    filename: str
    content_base64: str


class TencentOCRClient:
    service = "ocr"
    action = "GeneralBasicOCR"
    version = "2018-11-19"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, content_base64: str, filename: str, media_type: str) -> dict[str, Any]:
        if not self.settings.tencent_secret_id or not self.settings.tencent_secret_key:
            return {"success": False, "error": "缺少 TENCENT_OCR_SECRET_ID 或 TENCENT_OCR_SECRET_KEY"}

        if _is_pdf(filename, media_type, content_base64):
            return self._extract_pdf(content_base64)
        return self._extract_image(content_base64)

    def _extract_image(self, content_base64: str) -> dict[str, Any]:
        prepared = _prepare_image(content_base64)
        result = self._recognize_image(prepared)
        selected_rotation = 0
        if result["confidence"] < 0.75:
            candidates = [(0, prepared, result)]
            for angle in (90, 180, 270):
                rotated = _rotate_image(prepared, angle)
                candidates.append((angle, rotated, self._recognize_image(rotated)))
            selected_rotation, _content, result = max(
                candidates,
                key=lambda item: (item[2]["confidence"], len(item[2]["raw_text"])),
            )
        result["metadata"].update(
            {
                "preprocessed": True,
                "auto_contrast": True,
                "sharpness_factor": 1.5,
                "selected_rotation": selected_rotation,
            }
        )
        return result

    def _recognize_image(self, content_base64: str) -> dict[str, Any]:
        data = self._call_api(
            {"ImageBase64": content_base64, "LanguageType": self.settings.tencent_language_type}
        )
        return _format_response([data], provider="tencent")

    def _extract_pdf(self, content_base64: str) -> dict[str, Any]:
        first_page = self._call_api(
            {
                "ImageBase64": content_base64,
                "IsPdf": True,
                "PdfPageNumber": 1,
                "LanguageType": self.settings.tencent_language_type,
            }
        )
        page_count = int(first_page.get("PdfPageSize") or 1)
        max_pages = min(page_count, self.settings.pdf_max_pages)
        pages = [first_page]
        for page in range(2, max_pages + 1):
            pages.append(
                self._call_api(
                    {
                        "ImageBase64": content_base64,
                        "IsPdf": True,
                        "PdfPageNumber": page,
                        "LanguageType": self.settings.tencent_language_type,
                    }
                )
            )
        result = _format_response(pages, provider="tencent")
        result["metadata"]["pdf_page_count"] = page_count
        result["metadata"]["processed_pages"] = len(pages)
        return result

    def _call_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        timestamp = int(time.time())
        date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
        authorization = self._authorization(body, timestamp, date)
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": self.settings.tencent_endpoint,
            "X-TC-Action": self.action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": self.version,
            "X-TC-Region": self.settings.tencent_region,
        }
        url = f"https://{self.settings.tencent_endpoint}"
        response = httpx.post(url, content=body.encode("utf-8"), headers=headers, timeout=self.settings.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        if data.get("Response", {}).get("Error"):
            error = data["Response"]["Error"]
            raise RuntimeError(f"{error.get('Code')}: {error.get('Message')}")
        return data.get("Response", {})

    def _authorization(self, body: str, timestamp: int, date: str) -> str:
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{self.settings.tencent_endpoint}\n"
        signed_headers = "content-type;host"
        hashed_request_payload = hashlib.sha256(body.encode("utf-8")).hexdigest()
        canonical_request = "\n".join(
            [
                http_request_method,
                canonical_uri,
                canonical_querystring,
                canonical_headers,
                signed_headers,
                hashed_request_payload,
            ]
        )

        algorithm = "TC3-HMAC-SHA256"
        credential_scope = f"{date}/{self.service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = "\n".join([algorithm, str(timestamp), credential_scope, hashed_canonical_request])

        secret_date = _sign(("TC3" + self.settings.tencent_secret_key).encode("utf-8"), date)
        secret_service = _sign(secret_date, self.service)
        secret_signing = _sign(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        return (
            f"{algorithm} Credential={self.settings.tencent_secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _prepare_image(content_base64: str) -> str:
    image = Image.open(BytesIO(base64.b64decode(content_base64)))
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Sharpness(image).enhance(1.5)
    return _encode_png(image)


def _rotate_image(content_base64: str, angle: int) -> str:
    image = Image.open(BytesIO(base64.b64decode(content_base64))).convert("RGB")
    return _encode_png(image.rotate(angle, expand=True))


def _encode_png(image: Image.Image) -> str:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _is_pdf(filename: str, media_type: str, content_base64: str) -> bool:
    if media_type.lower() == "pdf" or filename.lower().endswith(".pdf"):
        return True
    try:
        return base64.b64decode(content_base64[:64] + "==", validate=False).startswith(b"%PDF")
    except Exception:
        return False


def _format_response(pages: list[dict[str, Any]], provider: str) -> dict[str, Any]:
    texts: list[str] = []
    confidences: list[float] = []
    for index, page in enumerate(pages, start=1):
        detections = page.get("TextDetections") or []
        page_texts = [str(item.get("DetectedText") or "") for item in detections if item.get("DetectedText")]
        texts.extend(page_texts)
        confidences.extend(float(item.get("Confidence") or 0) for item in detections if item.get("Confidence") is not None)
        if len(pages) > 1 and page_texts:
            texts[-len(page_texts)] = f"[第{index}页] {texts[-len(page_texts)]}"
    confidence = (sum(confidences) / len(confidences) / 100) if confidences else 0
    return {
        "success": True,
        "provider": provider,
        "raw_text": "\n".join(texts),
        "confidence": round(confidence, 4),
        "metadata": {"pages": len(pages), "line_count": len(texts)},
    }


settings = Settings()
app = FastAPI(title="Legal OCR Sidecar")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": "tencent",
        "configured": bool(settings.tencent_secret_id and settings.tencent_secret_key),
        "region": settings.tencent_region,
    }


@app.post("/ocr/extract")
def extract(payload: OCRRequest) -> dict[str, Any]:
    if payload.provider != "tencent":
        return {"success": False, "error": f"不支持的 OCR provider: {payload.provider}"}
    try:
        return TencentOCRClient(settings).extract(payload.content_base64, payload.filename, payload.media_type)
    except Exception as exc:
        return {"success": False, "provider": "tencent", "error": str(exc)}
