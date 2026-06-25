from .base import BaseValidator, ValidationResult

_MARKERS = ["주장", "반박", "재반박", "검증", "결론"]


class DebateValidator(BaseValidator):
    name = "debate"

    def validate(self, sample: dict) -> ValidationResult:
        a = next((m.get("content", "") for m in sample.get("messages", [])
                  if m.get("role") == "assistant"), "")
        if sum(1 for m in _MARKERS if m in a) < 4:
            return ValidationResult(False, "debate_missing_structure")
        return ValidationResult(True)
