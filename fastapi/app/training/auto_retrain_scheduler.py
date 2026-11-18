"""
자동 재학습 스케줄러.

설정 기반으로 주기적 재학습을 관리한다.
APScheduler가 설치된 경우 cron 기반으로 자동 실행한다.
미설치 시에는 수동 CLI 실행 안내만 제공한다.

기본값: autoRetrainEnabled=false, autoTrain=false
→ 명시적으로 config를 수정하거나 env를 설정해야만 자동 학습이 활성화된다.

환경변수 오버라이드:
  AUTO_RETRAIN_ENABLED=true   autoRetrainEnabled 활성화
  AUTO_TRAIN=true             autoTrain 활성화 (실제 학습 실행)
  AUTO_DEPLOY=true            autoDeploy 활성화
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.debug("APScheduler 미설치 — 스케줄러 비활성화 (CLI 실행 권장)")


@dataclass
class SchedulerStatus:
    enabled: bool
    has_apscheduler: bool
    running: bool
    schedule: str
    auto_train: bool
    auto_deploy: bool
    next_run_at: str | None
    last_run_at: str | None
    last_run_status: str | None
    message: str


class AutoRetrainScheduler:
    """자동 재학습 스케줄 관리자."""

    def __init__(self):
        self._scheduler = None
        self._last_run_at: str | None = None
        self._last_run_status: str | None = None
        self._config = None

    def _load_config(self):
        """auto_retrain_config.json + 환경변수를 합쳐서 설정을 반환한다."""
        from app.training.auto_retrain_runner import load_config
        cfg = load_config()

        # 환경변수 오버라이드 (운영 배포 시 .env로 제어)
        if os.environ.get("AUTO_RETRAIN_ENABLED", "").lower() == "true":
            cfg.auto_retrain_enabled = True
        if os.environ.get("AUTO_TRAIN", "").lower() == "true":
            cfg.auto_train = True
        if os.environ.get("AUTO_DEPLOY", "").lower() == "true":
            cfg.auto_deploy = True

        self._config = cfg
        return cfg

    def start(self) -> bool:
        """
        APScheduler 기반 스케줄러를 시작한다.

        Returns:
            True: 스케줄러 시작 성공
            False: 비활성화 상태이거나 APScheduler 미설치
        """
        cfg = self._load_config()

        if not cfg.auto_retrain_enabled:
            logger.info("autoRetrainEnabled=false — 스케줄러 시작 안 함")
            return False

        if not HAS_APSCHEDULER:
            logger.warning(
                "APScheduler 미설치 — 스케줄러 비활성화.\n"
                "  pip install apscheduler 로 설치하거나\n"
                "  crontab -e 로 직접 CLI 스크립트를 등록하세요:\n"
                "  %s python -m scripts.run_auto_retrain --yes",
                _load_schedule_str(),
            )
            return False

        self._scheduler = AsyncIOScheduler()
        cron_str = _load_schedule_str()

        try:
            trigger = CronTrigger.from_crontab(cron_str)
        except Exception:
            # fallback: 매주 일요일 3시
            trigger = CronTrigger(day_of_week="sun", hour=3, minute=0)

        self._scheduler.add_job(
            self._run_job,
            trigger=trigger,
            id="auto_retrain",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info("자동 재학습 스케줄러 시작: cron=%s", cron_str)
        return True

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("자동 재학습 스케줄러 종료")

    async def run_once(self, dry_run: bool = False) -> dict:
        """스케줄에 상관없이 즉시 한 번 실행한다."""
        cfg = self._load_config()
        return await _execute_pipeline(cfg, dry_run=dry_run)

    async def _run_job(self) -> None:
        """스케줄러 콜백."""
        logger.info("=== 자동 재학습 스케줄 실행 ===")
        cfg = self._load_config()
        result = await _execute_pipeline(cfg, dry_run=False)
        self._last_run_at = datetime.now(timezone.utc).isoformat()
        self._last_run_status = result.get("status", "unknown")

    def get_status(self) -> SchedulerStatus:
        cfg = self._config or self._load_config()
        next_run = None

        if self._scheduler and self._scheduler.running:
            job = self._scheduler.get_job("auto_retrain")
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

        running = bool(self._scheduler and HAS_APSCHEDULER and self._scheduler.running)
        msg_parts = []
        if not HAS_APSCHEDULER:
            msg_parts.append("APScheduler 미설치 (pip install apscheduler)")
        if not cfg.auto_retrain_enabled:
            msg_parts.append("autoRetrainEnabled=false")
        if not cfg.auto_train:
            msg_parts.append("autoTrain=false (dataset 생성까지만 수행)")
        if not cfg.auto_deploy:
            msg_parts.append("autoDeploy=false (production 자동 반영 안 함)")

        return SchedulerStatus(
            enabled=cfg.auto_retrain_enabled,
            has_apscheduler=HAS_APSCHEDULER,
            running=running,
            schedule=_load_schedule_str(),
            auto_train=cfg.auto_train,
            auto_deploy=cfg.auto_deploy,
            next_run_at=next_run,
            last_run_at=self._last_run_at,
            last_run_status=self._last_run_status,
            message=" / ".join(msg_parts) if msg_parts else "정상 동작 중",
        )

    # ── enable / disable ───────────────────────────────────────────────────────

    def enable(self) -> bool:
        """설정 파일에서 autoRetrainEnabled를 true로 변경한다."""
        return _update_config_flag("autoRetrainEnabled", True)

    def disable(self) -> bool:
        """설정 파일에서 autoRetrainEnabled를 false로 변경한다."""
        return _update_config_flag("autoRetrainEnabled", False)


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

async def _execute_pipeline(config: Any, dry_run: bool) -> dict:
    """run_auto_retrain을 실행하고 결과를 dict으로 반환한다."""
    from app.training.auto_retrain_runner import run_auto_retrain
    import dataclasses
    result = await run_auto_retrain(config=config, dry_run=dry_run)
    return dataclasses.asdict(result)


def _load_schedule_str() -> str:
    import json, os
    from app.training.auto_retrain_runner import _DEFAULT_CONFIG_PATH
    try:
        with open(_DEFAULT_CONFIG_PATH, "r") as f:
            return json.load(f).get("schedule", "0 3 * * 0")
    except Exception:
        return "0 3 * * 0"


def _update_config_flag(key: str, value: bool) -> bool:
    """auto_retrain_config.json에서 최상위 키를 업데이트한다."""
    import json
    from app.training.auto_retrain_runner import _DEFAULT_CONFIG_PATH
    try:
        with open(_DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data[key] = value
        with open(_DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("config 업데이트: %s=%s", key, value)
        return True
    except Exception as e:
        logger.error("config 업데이트 실패: %s", e)
        return False


# 기본 싱글턴
_scheduler_instance: AutoRetrainScheduler | None = None


def get_scheduler() -> AutoRetrainScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = AutoRetrainScheduler()
    return _scheduler_instance
