"""
모델 레지스트리.

어떤 모델이 base / candidate / production / rollback 상태인지 추적한다.
상태는 JSON 파일(registry.json)로 유지한다.

구조:
  {
    "base":        { "path": "...", "notes": "..." },
    "candidate":   { "path": "...", "dataset_version": "...", "trained_at": "...", ... },
    "production":  { ... },
    "rollback":    { ... }
  }
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "models", "qlora", "registry.json")
)


@dataclass
class ModelEntry:
    path: str
    dataset_version: str = ""
    trained_at: str = ""
    eval_scores: dict[str, float] = field(default_factory=dict)
    notes: str = ""
    status: str = "unknown"   # base | candidate | staging | production | rollback


class ModelRegistry:
    """파일 기반 모델 레지스트리."""

    def __init__(self, registry_path: str = _DEFAULT_REGISTRY_PATH):
        self.registry_path = Path(registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 읽기 ───────────────────────────────────────────────────────────────────

    def load(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"base": None, "candidate": None, "production": None, "rollback": None}
        try:
            with self.registry_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("registry 읽기 실패: %s", e)
            return {}

    def get_production(self) -> dict | None:
        return self.load().get("production")

    def get_candidate(self) -> dict | None:
        return self.load().get("candidate")

    def get_rollback(self) -> dict | None:
        return self.load().get("rollback")

    def get_base(self) -> dict | None:
        return self.load().get("base")

    # ── 쓰기 ───────────────────────────────────────────────────────────────────

    def save(self, data: dict) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        with self.registry_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("registry 저장: %s", self.registry_path)

    def register_candidate(
        self,
        model_path: str,
        dataset_version: str,
        eval_scores: dict | None = None,
        notes: str = "",
    ) -> None:
        data = self.load()
        data["candidate"] = asdict(ModelEntry(
            path=model_path,
            dataset_version=dataset_version,
            trained_at=datetime.now(timezone.utc).isoformat(),
            eval_scores=eval_scores or {},
            notes=notes,
            status="candidate",
        ))
        self.save(data)
        logger.info("candidate 모델 등록: %s", model_path)

    def promote_candidate_to_production(self) -> bool:
        """candidate를 production으로 승격하고 이전 production을 rollback으로 저장한다."""
        data = self.load()
        candidate = data.get("candidate")
        if not candidate:
            logger.warning("promote 실패: candidate 모델 없음")
            return False

        old_production = data.get("production")
        if old_production:
            data["rollback"] = {**old_production, "status": "rollback"}

        data["production"] = {**candidate, "status": "production"}
        data["candidate"]  = None
        self.save(data)
        logger.info("production 승격 완료: %s", candidate["path"])
        return True

    def set_production(self, model_path: str, notes: str = "") -> None:
        """직접 production 모델을 설정한다 (수동 배포용)."""
        data = self.load()
        old = data.get("production")
        if old:
            data["rollback"] = {**old, "status": "rollback"}
        data["production"] = asdict(ModelEntry(
            path=model_path,
            notes=notes,
            status="production",
        ))
        self.save(data)

    def activate_rollback(self) -> bool:
        """rollback 모델을 production으로 복원한다."""
        data = self.load()
        rollback = data.get("rollback")
        if not rollback:
            logger.warning("rollback 실패: rollback 모델 없음")
            return False
        data["production"] = {**rollback, "status": "production"}
        data["rollback"]   = None
        self.save(data)
        logger.info("rollback 활성화: %s", rollback["path"])
        return True

    def to_summary_dict(self) -> dict:
        data = self.load()
        return {
            "base":       data.get("base"),
            "candidate":  data.get("candidate"),
            "production": data.get("production"),
            "rollback":   data.get("rollback"),
        }


# 기본 싱글턴 인스턴스
_registry: ModelRegistry | None = None


def get_registry(registry_path: str = _DEFAULT_REGISTRY_PATH) -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry(registry_path)
    return _registry
