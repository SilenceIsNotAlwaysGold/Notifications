from app.adapters.ocr_providers.sidecar_provider import SidecarOCRProvider


class AliyunOCRProvider(SidecarOCRProvider):
    def __init__(self) -> None:
        super().__init__("aliyun")
