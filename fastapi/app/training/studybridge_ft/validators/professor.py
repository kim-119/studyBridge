import re
from .base import BaseValidator, ValidationResult

_LABEL = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


class ProfessorValidator(BaseValidator):
    name = "professor"

    def validate(self, sample: dict) -> ValidationResult:
        a = next((m.get("content", "") for m in sample.get("messages", [])
                  if m.get("role") == "assistant"), "")
        speakers, bodies = [], []
        for ln in a.splitlines():
            mt = _LABEL.match(ln.strip())
            if mt:
                speakers.append(mt.group(1).strip())
                bodies.append(mt.group(2).strip())
        if not speakers:
            return ValidationResult(False, "schema_error")
        expected = (sample.get("metadata") or {}).get("expected_speaker")
        if expected and any(sp != expected for sp in speakers):
            return ValidationResult(False, "professor_speaker_mismatch")
        norm = [re.sub(r"\s+", " ", b).strip() for b in bodies if b]
        if len(norm) >= 2 and len(set(norm)) < len(norm):
            return ValidationResult(False, "professor_duplicate_answers")
        return ValidationResult(True)
