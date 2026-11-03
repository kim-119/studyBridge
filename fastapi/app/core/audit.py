"""관리/학습 작업 감사 로그(append-only JSONL, 해시 체인).

원문(질문/답변/PDF)은 절대 기록하지 않는다. actor/role/requestId/대상 ID/결과 코드만 남긴다.
경로: AI_AUDIT_LOG_PATH (기본 ~/.local/state/studybridge/audit/ai_admin_audit.jsonl, 0600).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("studybridge.audit")
_lock = threading.Lock()
_prev = {"hash": "GENESIS"}
_ALLOWED_EXTRA = {"count", "status", "datasetId", "state", "fromState", "toState", "reasonCodes", "errorCode",
                  "manifestSha256", "sampleCount", "taskType", "score", "qualityStatus"}


def _path() -> Path:
    p = os.getenv("AI_AUDIT_LOG_PATH") or str(Path.home() / ".local/state/studybridge/audit/ai_admin_audit.jsonl")
    return Path(p)


def audit_event(event_type: str, *, actor: str, role: str, request_id: Optional[str], outcome: str,
                target_ids: Optional[List[str]] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    safe_extra = {k: v for k, v in (extra or {}).items() if k in _ALLOWED_EXTRA}
    with _lock:
        rec = {"at": datetime.now(timezone.utc).isoformat(), "type": event_type, "actor": actor, "role": role,
               "requestId": request_id, "outcome": outcome, "targets": (target_ids or [])[:50],
               "extra": safe_extra, "prevHash": _prev["hash"]}
        rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        _prev["hash"] = rec["hash"]
        line = json.dumps(rec, ensure_ascii=False)
        try:
            path = _path()
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                os.close(fd)
        except OSError as e:
            # 감사 파일 실패는 로거로만 남긴다(원문 없음). 관리 작업 자체는 호출자가 판단한다.
            logger.error("[AUDIT] file write failed: %s", type(e).__name__)
        logger.info("[AUDIT] %s", line)
    return rec
