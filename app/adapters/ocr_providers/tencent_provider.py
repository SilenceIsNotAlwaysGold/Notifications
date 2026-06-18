from app.adapters.ocr_providers.sidecar_provider import SidecarOCRProvider


class TencentOCRProvider(SidecarOCRProvider):
    def __init__(self) -> None:
        super().__init__("tencent")
