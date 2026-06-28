import base64

from ocr_sidecar.main import _format_response, _is_pdf


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
