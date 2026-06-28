# OCR Sidecar

This small FastAPI service adapts Tencent Cloud OCR to the main app's sidecar
contract:

```http
POST /ocr/extract
```

Request:

```json
{"provider":"tencent","media_type":"image","filename":"notice.png","content_base64":"..."}
```

Response:

```json
{"success":true,"provider":"tencent","raw_text":"...","confidence":0.98,"metadata":{}}
```

Environment:

```env
TENCENT_OCR_SECRET_ID=
TENCENT_OCR_SECRET_KEY=
TENCENT_OCR_REGION=ap-guangzhou
TENCENT_OCR_PDF_MAX_PAGES=1
TENCENT_OCR_TIMEOUT_SECONDS=20
```

Run:

```bash
uvicorn ocr_sidecar.main:app --host 127.0.0.1 --port 9002
```
