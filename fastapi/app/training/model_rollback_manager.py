"""
모델 롤백 관리.

오류율 또는 품질 저하 감지 시 이전 모델(rollback)로 복구한다.

주의:
  - production 모델을 덮어쓰기 전에 반드시 registry에 rollback 엔트리를 저장한다.
  - rollback은 되돌릴 수 있는 안전한 작업이다.
  - rollback 이력은 registry에 기록된다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class RollbackStatus:
    can_rollback: bool
    production_path: str | None = None
    rollback_path: str | None = None
    last_rollback_at: str | None = None
    last_rollback_reason: str | None = None
    message: str = ""


class RollbackManager:
    """ModelRegistry 기반 롤백 관리자."""

    def __init__(self, registry_path: str | None = None):
        from app.training.model_registry import ModelRegistry
        self._registry = ModelRegistry(registry_path) if registry_path else None

    def _get_registry(self):
        if self._registry is None:
            from app.training.model_registry import get_registry
            return get_registry()
        return self._registry

    # ── 상태 조회 ──────────────────────────────────────────────────────────────

    def get_status(self) -> RollbackStatus:
        reg = self._get_registry()
        data = reg.load()
        prod    = data.get("production")
        rb_entry = data.get("rollback")

        return RollbackStatus(
            can_rollback=rb_entry is not None,
            production_path=prod["path"] if prod else None,
            rollback_path=rb_entry["path"] if rb_entry else None,
            message=(
                "rollback 가능" if rb_entry
                else "rollback 모델 없음 — production 배포 이력이 없거나 이미 rollback됨"
            ),
        )

    # ── rollback 실행 ──────────────────────────────────────────────────────────

    def trigger_rollback(self, reason: str) -> bool:
        """
        production을 rollback 모델로 복원한다.

        Returns:
            True: rollback 성공
            False: rollback 실패 (rollback 모델 없음)
        """
        reg = self._get_registry()
        data = reg.load()

        rollback_entry = data.get("rollback")
        if not rollback_entry:
            logger.warning("rollback 실패: rollback 모델 없음")
            return False

        old_production = data.get("production")

        # rollback → production
        data["production"] = {
            **rollback_entry,
            "status": "production",
            "rollback_reason": reason,
            "restored_at": datetime.now(timezone.utc).isoformat(),
        }
        data["rollback"] = None

        # 이전 production은 별도 이력으로 보존
        history = data.get("rollback_history", [])
        if old_production:
            history.append({
                **old_production,
                "rolled_back_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
            })
        data["rollback_history"] = history[-10:]  # 최근 10개만 보존

        reg.save(data)
        logger.warning(
            "ROLLBACK 실행: %s → %s (이유: %s)",
            old_production.get("path", "?") if old_production else "?",
            rollback_entry.get("path", "?"),
            reason,
        )
        return True

    # ── 자동 health 모니터링 ───────────────────────────────────────────────────

    async def check_and_auto_rollback(
        self,
        current_error_rate: float,
        max_error_rate: float = 0.05,
    ) -> bool:
        """
        오류율이 임계치를 초과하면 자동으로 rollback한다.

        Args:
            current_error_rate: 현재 API 오류율 (0~1)
            max_error_rate:     허용 최대 오류율

        Returns:
            True: rollback 실행됨
            False: rollback 불필요 또는 불가
        """
        if current_error_rate <= max_error_rate:
            return False

        logger.error(
            "오류율 임계치 초과 (%.2f%% > %.2f%%) — 자동 rollback 실행",
            current_error_rate * 100,
            max_error_rate * 100,
        )
        reason = f"자동 rollback: 오류율 {current_error_rate:.2%} (임계치 {max_error_rate:.2%})"
        return self.trigger_rollback(reason)

    def get_rollback_history(self) -> list[dict]:
        reg = self._get_registry()
        return reg.load().get("rollback_history", [])
