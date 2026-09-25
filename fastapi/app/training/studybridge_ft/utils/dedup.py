"""중복 제거 — 기존 dataset_deduplicator.compute_sample_hash 재사용."""
from app.training.dataset_deduplicator import compute_sample_hash


def _roles(sample: dict) -> tuple[str, str, str]:
    sys_, usr, asst = "", "", ""
    for m in sample.get("messages", []):
        if m.get("role") == "system":
            sys_ = m.get("content", "")
        elif m.get("role") == "user":
            usr = m.get("content", "")
        elif m.get("role") == "assistant":
            asst = m.get("content", "")
    return sys_, usr, asst


def sample_hash(sample: dict) -> str:
    s, u, a = _roles(sample)
    return compute_sample_hash(s, u, a)


class Deduper:
    def __init__(self):
        self.seen: set[str] = set()

    def is_dup(self, sample: dict) -> bool:
        h = sample_hash(sample)
        if h in self.seen:
            return True
        self.seen.add(h)
        return False
