"""생성 산출(cleaned shard) 일괄 검증."""
import sys
from pathlib import Path
from . import paths
from .utils import jsonl_io
from .validators.chatml import ChatMLValidator
from .validators.safety import SafetyValidator
from .validators.quiz import QuizValidator
from .validators.socratic import SocraticValidator
from .validators.debate import DebateValidator
from .validators.professor import ProfessorValidator

_CAT = {"quiz": [QuizValidator()], "socratic": [SocraticValidator()],
        "debate": [DebateValidator()], "professor": [ProfessorValidator()]}
_COMMON = [ChatMLValidator(), SafetyValidator()]


def validate_rows(rows, category=None) -> dict:
    vals = _COMMON + _CAT.get(category, [])
    out = {"ok": 0, "bad": 0, "reasons": {}}
    for s in rows:
        bad_reason = None
        for v in vals:
            r = v.validate(s)
            if not r.ok:
                bad_reason = r.reason
                break
        if bad_reason:
            out["bad"] += 1
            out["reasons"][bad_reason] = out["reasons"].get(bad_reason, 0) + 1
        else:
            out["ok"] += 1
    return out


def validate_cleaned_dir(cleaned_dir=None) -> dict:
    d = Path(cleaned_dir) if cleaned_dir else paths.BASE / "cleaned"
    agg = {"ok": 0, "bad": 0, "reasons": {}}
    for f in sorted(d.glob("*.clean.jsonl")):
        cat = f.name.split("_")[0]
        r = validate_rows(jsonl_io.read_jsonl(f), cat)
        agg["ok"] += r["ok"]
        agg["bad"] += r["bad"]
        for k, v in r["reasons"].items():
            agg["reasons"][k] = agg["reasons"].get(k, 0) + v
    return agg


def main():
    r = validate_cleaned_dir()
    print(r)
    sys.exit(1 if r["bad"] else 0)


if __name__ == "__main__":
    main()
