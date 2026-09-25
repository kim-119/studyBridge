from dataclasses import dataclass


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None


class BaseValidator:
    name = "base"

    def validate(self, sample: dict) -> ValidationResult:
        raise NotImplementedError
