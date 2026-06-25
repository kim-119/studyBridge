"""생성기 베이스: 생성→파싱→검증→repair(1회)→dedup→shard. quarantine 포함."""
from dataclasses import dataclass, field
from pathlib import Path
from ..utils import jsonl_io
from ..validators.base import ValidationResult


@dataclass
class GenResult:
    accepted: int = 0
    rejected: int = 0
    repaired: int = 0
    deduped: int = 0
    skipped: bool = False
    reject_reasons: dict = field(default_factory=dict)


class BaseGenerator:
    category = "base"
    system_prompt = ""
    validators = []

    def user_prompt(self) -> str:
        raise NotImplementedError

    def parse(self, raw: str) -> dict:
        raise NotImplementedError

    def _validate(self, sample) -> ValidationResult:
        for v in self.validators:
            r = v.validate(sample)
            if not r.ok:
                return r
        return ValidationResult(True)

    def generate(self, n, client, deduper, out_raw_path, out_clean_path,
                 rejected_dir) -> GenResult:
        out_clean_path = Path(out_clean_path)
        rejected_dir = Path(rejected_dir)
        if jsonl_io.count_lines(out_clean_path) >= n:
            return GenResult(skipped=True)
        res = GenResult()
        for _ in range(n):
            raw = client.chat(self.system_prompt, self.user_prompt())
            sample = self.parse(raw)
            jsonl_io.append_jsonl(out_raw_path, sample)
            r = self._validate(sample)
            if not r.ok:  # repair 1회
                raw2 = client.chat(self.system_prompt, self.user_prompt())
                sample2 = self.parse(raw2)
                r2 = self._validate(sample2)
                if r2.ok:
                    sample = sample2
                    res.repaired += 1
                    r = r2
                else:
                    res.rejected += 1
                    res.reject_reasons[r.reason] = res.reject_reasons.get(r.reason, 0) + 1
                    jsonl_io.append_jsonl(rejected_dir / f"{r.reason}.jsonl", sample)
                    continue
            if deduper.is_dup(sample):
                res.deduped += 1
                continue
            jsonl_io.append_jsonl(out_clean_path, sample)
            res.accepted += 1
        return res
