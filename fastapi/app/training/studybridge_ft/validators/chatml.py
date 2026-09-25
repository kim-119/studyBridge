from .base import BaseValidator, ValidationResult


class ChatMLValidator(BaseValidator):
    name = "chatml"

    def validate(self, sample: dict) -> ValidationResult:
        msgs = sample.get("messages")
        if not isinstance(msgs, list) or not msgs:
            return ValidationResult(False, "schema_error")
        roles = [m.get("role") for m in msgs]
        if not ({"system", "user", "assistant"} <= set(roles)):
            return ValidationResult(False, "schema_error")
        if roles[0] != "system":
            return ValidationResult(False, "schema_error")
        asst = [m.get("content", "") for m in msgs if m.get("role") == "assistant"]
        if any(not (c or "").strip() for c in asst):
            return ValidationResult(False, "empty_answer")
        return ValidationResult(True)
