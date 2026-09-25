"""Rolling Summary — 요청 경로 밖(백그라운드)에서 갱신하고, 다음 턴이 읽기만 한다.

- 턴 완료 후 schedule_update() 가 단일 워커 스레드에 작업을 넣는다(동일 scope 중복 작업 스킵).
- 이력 턴 수가 SUMMARY_EVERY 의 배수를 넘을 때만 LLM 요약을 만든다(매 턴 GPU 호출 금지).
- 저장: Redis `studybridge:multi-chat:summary:<scope>:<id>` = {version, updatedAt, turnCount, summary}
- 실패해도 현재 답변에 영향 없음(로그 + 다음 기회에 재시도).
- 읽기(load_summary_sync)는 짧은 타임아웃의 동기 Redis 호출. 실패 시 "".
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

logger = logging.getLogger("studybridge.studymate.summary")

SUMMARY_VERSION = 1
SUMMARY_EVERY = int(os.getenv("STUDYMATE_SUMMARY_EVERY_TURNS", "6"))
_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sm-summary")
_RUNNING: set = set()
_LOCK = threading.Lock()


def _key(request: Any) -> Optional[str]:
    try:
        from app.services.multi_chat_redis_memory import _scope_from_request, _memory_key
        scope, sid = _scope_from_request(request)
        if not scope or not sid:
            return None
        return _memory_key(scope, sid).replace(":memory:", ":summary:")
    except Exception:
        return None


def load_summary_sync(request: Any) -> str:
    key = _key(request)
    if not key:
        return ""
    try:
        from app.studymate import redis_sync
        r = redis_sync.client()
        if r is None:
            return ""
        raw = r.get(key)
        if not raw:
            return ""
        obj = json.loads(raw)
        return str(obj.get("summary") or "")[:1200]
    except Exception as e:
        logger.warning("[SUMMARY] load failed: %s", type(e).__name__)
        return ""


def _turns(request: Any) -> List[str]:
    out = []
    for pa in (getattr(request, "previousAnswers", None) or []):
        role = (getattr(pa, "role", "") or "").upper()
        who = "사용자" if role == "USER" else (pa.agentName or "교수")
        text = " ".join((pa.answer or "").split())
        if text:
            out.append(f"{who}: {text[:400]}")
    return out


def schedule_update(request: Any, final_text: str = "") -> bool:
    key = _key(request)
    turns = _turns(request)
    if final_text:
        turns.append(f"교수들: {final_text[:600]}")
    if not key or len(turns) < SUMMARY_EVERY:
        return False
    if os.getenv("STUDYMATE_ROLLING_SUMMARY", "on").strip().lower() in ("off", "0", "false"):
        return False
    with _LOCK:
        if key in _RUNNING:
            return False
        _RUNNING.add(key)
    _EXEC.submit(_update, key, turns)
    return True


def _update(key: str, turns: List[str]) -> None:
    try:
        from app.studymate import redis_sync
        from app.studymate import llm_gateway as G
        r = redis_sync.client()
        prev: Dict[str, Any] = {}
        if r is not None:
            raw = r.get(key)
            prev = json.loads(raw) if raw else {}
        if prev.get("turnCount") and len(turns) - int(prev["turnCount"]) < SUMMARY_EVERY:
            return
        system = ("너는 학습 대화 요약기다. 학습자가 무엇을 물었고, 어떤 개념을 이해/오해했는지, "
                  "아직 남은 질문은 무엇인지 6줄 이내 한국어 불릿으로 요약한다. 새 사실을 지어내지 않는다.")
        user = (f"[이전 요약]\n{prev.get('summary', '')}\n\n" if prev.get("summary") else "") + \
            "[최근 대화]\n" + "\n".join(turns[-12:])
        text = G.ask_text(system, user, task="summary")
        obj = {"version": SUMMARY_VERSION, "updatedAt": int(time.time()), "turnCount": len(turns),
               "summary": text.strip()[:1500]}
        if r is not None:
            r.set(key, json.dumps(obj, ensure_ascii=False), ex=7 * 24 * 3600)
        logger.info("[SUMMARY] updated key=%s turns=%d chars=%d", key, len(turns), len(obj["summary"]))
    except Exception as e:
        logger.warning("[SUMMARY] background update failed (답변에는 영향 없음): %s", type(e).__name__)
    finally:
        with _LOCK:
            _RUNNING.discard(key)
