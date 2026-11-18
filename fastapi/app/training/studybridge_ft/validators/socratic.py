import re
from .base import BaseValidator, ValidationResult

_STAGE_MARKERS = ["힌트", "유도", "부분 정리", "최종 정리", "정리하면", "왜", "어떻게"]


class SocraticValidator(BaseValidator):
    name = "socratic"

    def validate(self, sample: dict) -> ValidationResult:
        a = next((m.get("content", "") for m in sample.get("messages", [])
                  if m.get("role") == "assistant"), "").strip()
        if not a:
            return ValidationResult(False, "empty_answer")
        first = re.split(r"(?<=[.!?。])\s", a, maxsplit=1)[0]
        if ("정답은" in first or "답은" in first) and "?" not in first and "？" not in first:
            return ValidationResult(False, "socratic_direct_answer")
        q = a.count("?") + a.count("？")
        if q < 2:
            return ValidationResult(False, "socratic_too_few_questions")
        if sum(1 for m in _STAGE_MARKERS if m in a) < 3:
            return ValidationResult(False, "socratic_missing_stages")
        return ValidationResult(True)
