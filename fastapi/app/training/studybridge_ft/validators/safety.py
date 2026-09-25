from .base import BaseValidator, ValidationResult
from ..utils.sanitize import scan_sample


class SafetyValidator(BaseValidator):
    name = "safety"

    def validate(self, sample: dict) -> ValidationResult:
        if scan_sample(sample):
            return ValidationResult(False, "pii_secret")
        asst = [m.get("content", "") for m in sample.get("messages", [])
                if m.get("role") == "assistant"]
        if any(not (c or "").strip() for c in asst):
            return ValidationResult(False, "empty_answer")
        return ValidationResult(True)
