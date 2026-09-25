"""생성 실행 재현성 manifest."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from . import jsonl_io  # noqa: F401 (의존 명시용; 실제 json 사용)
from .. import paths


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Manifest:
    run_id: str
    git_commit: str
    model_name: str
    model_digest: str
    generation_config: dict
    input_seed: int
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    accepted: int = 0
    rejected: int = 0
    repaired: int = 0
    deduped: int = 0
    category_counts: dict = field(default_factory=dict)

    @classmethod
    def new(cls, run_id, git_commit, model_name, model_digest, generation_config, input_seed):
        return cls(run_id=run_id, git_commit=git_commit, model_name=model_name,
                   model_digest=model_digest, generation_config=generation_config,
                   input_seed=input_seed)

    def record(self, accepted=0, rejected=0, repaired=0, deduped=0, category=None):
        self.accepted += accepted
        self.rejected += rejected
        self.repaired += repaired
        self.deduped += deduped
        if category is not None:
            self.category_counts[category] = self.category_counts.get(category, 0) + accepted

    def finish(self):
        self.finished_at = _now()

    def save(self) -> Path:
        paths.ensure_dirs()
        out = paths.SUBDIRS["manifests"] / f"manifest_{self.run_id}.json"
        out.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return out
