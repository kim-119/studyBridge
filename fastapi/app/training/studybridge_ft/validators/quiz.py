import json
from .base import BaseValidator, ValidationResult

REQUIRED = ["question", "choices", "answer", "explanation", "difficulty", "source_hint"]


class QuizValidator(BaseValidator):
    name = "quiz"

    def validate(self, sample: dict) -> ValidationResult:
        asst = next((m.get("content", "") for m in sample.get("messages", [])
                     if m.get("role") == "assistant"), "")
        try:
            p = json.loads(asst)
        except Exception:
            return ValidationResult(False, "quiz_invalid_json")
        if not isinstance(p, dict) or any(k not in p for k in REQUIRED):
            return ValidationResult(False, "quiz_missing_field")
        choices = p.get("choices")
        if not isinstance(choices, list) or len(choices) < 2:
            return ValidationResult(False, "quiz_missing_field")
        ans = p.get("answer")
        valid = (isinstance(ans, int) and 0 <= ans < len(choices)) or (ans in choices)
        if not valid:
            return ValidationResult(False, "quiz_invalid_answer")
        return ValidationResult(True)
