from typing import Any

from app.shared.config.settings import settings


class BusinessRulesConfig:
    def __init__(self, yaml_path: str | None = None) -> None:
        self._rules: dict[str, Any] = self._defaults()
        if yaml_path:
            self._load_yaml(yaml_path)

    def _defaults(self) -> dict[str, Any]:
        return {
            "invoice": {
                "require_invoice_number": True,
                "require_amount": True,
                "amount_stamp_duty_threshold": settings.AMOUNT_STAMP_DUTY_THRESHOLD,
                "require_materai_above_threshold": settings.REQUIRE_MATERAI_ABOVE_THRESHOLD,
                "require_signature": settings.REQUIRE_SIGNATURE_FOR_INVOICE,
                "require_stamp": settings.REQUIRE_STAMP_FOR_INVOICE,
                "require_barcode": settings.REQUIRE_BARCODE_FOR_INVOICE,
            },
            "delivery_note": {
                "required_signature_count": settings.DELIVERY_NOTE_REQUIRED_SIGNATURE_COUNT,
                "required_stamp_count": settings.DELIVERY_NOTE_REQUIRED_STAMP_COUNT,
                "require_colored_stamp": True,
            },
            "confidence": {
                "threshold": settings.CONFIDENCE_THRESHOLD,
                "min_object_confidence": 0.25,
                "min_ocr_field_confidence": 0.60,
            },
            "document": {
                "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
                "min_image_width": settings.MIN_IMAGE_WIDTH,
                "min_image_height": settings.MIN_IMAGE_HEIGHT,
                "max_page_count": settings.MAX_PAGE_COUNT,
            },
        }

    def _load_yaml(self, path: str) -> None:
        try:
            import yaml
            with open(path) as f:
                override = yaml.safe_load(f)
            if override:
                self._deep_merge(self._rules, override)
        except (FileNotFoundError, ImportError):
            pass

    def _deep_merge(self, base: dict, override: dict) -> None:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    def get(self, *keys: str) -> Any:
        val: Any = self._rules
        for k in keys:
            val = val.get(k, {})
        return val

    def snapshot(self) -> dict[str, Any]:
        return dict(self._rules)


business_rules = BusinessRulesConfig()
