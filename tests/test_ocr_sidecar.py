import base64
from io import BytesIO

from PIL import Image

from ocr_sidecar.main import Settings, TencentOCRClient, _format_response, _is_pdf, _prepare_image


def test_detects_pdf_from_filename():
    assert _is_pdf("notice.pdf", "file", base64.b64encode(b"anything").decode("ascii"))


def test_detects_pdf_from_magic_bytes():
    assert _is_pdf("notice.bin", "file", base64.b64encode(b"%PDF-1.7").decode("ascii"))


def test_format_response_joins_detected_text_and_confidence():
    result = _format_response(
        [
            {
                "TextDetections": [
                    {"DetectedText": "案件(2026)黔0281民初3118号", "Confidence": 99},
                    {"DetectedText": "诉讼费400元", "Confidence": 97},
                ]
            }
        ],
        provider="tencent",
    )

    assert result["success"] is True
    assert result["provider"] == "tencent"
    assert "诉讼费400元" in result["raw_text"]
    assert result["confidence"] == 0.98


def test_pdf_processes_pages_up_to_configured_limit(monkeypatch):
    client = TencentOCRClient(
        Settings(
            TENCENT_OCR_SECRET_ID="id",
            TENCENT_OCR_SECRET_KEY="key",
            TENCENT_OCR_PDF_MAX_PAGES=3,
        )
    )
    calls = []

    def fake_call(payload):
        calls.append(payload)
        return {
            "PdfPageSize": 5,
            "TextDetections": [{"DetectedText": f"第{payload['PdfPageNumber']}页", "Confidence": 99}],
        }

    monkeypatch.setattr(client, "_call_api", fake_call)
    result = client._extract_pdf("pdf")

    assert [item["PdfPageNumber"] for item in calls] == [1, 2, 3]
    assert result["metadata"]["pdf_page_count"] == 5
    assert result["metadata"]["processed_pages"] == 3


def test_image_preprocessing_returns_normalized_png():
    source = BytesIO()
    Image.new("RGB", (20, 10), color=(220, 220, 220)).save(source, format="JPEG")

    prepared = _prepare_image(base64.b64encode(source.getvalue()).decode("ascii"))

    image = Image.open(BytesIO(base64.b64decode(prepared)))
    assert image.format == "PNG"
    assert image.size == (20, 10)
