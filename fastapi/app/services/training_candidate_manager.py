"""
[레거시] 학습 후보 자동 수집/검수 관리자 — 보완판.

예전 동작의 결함(재현 테스트: tests/test_training_legacy_scoring_repro.py)
  1. _auto_score 의 '사실성' 항목이 무조건 +15 였다 → 길이/키워드만 맞으면 틀린 답도 90점↑ → auto_approved.
  2. rag_grounding_score 를 받기만 하고 점수/상태에 반영하지 않았다.
  3. 같은 Q/A 를 다시 보내면 중복 검사에서 조기 반환 → 나중에 들어온 부정 피드백이 기존 승인 항목을 철회하지 못했다.
  4. 운영 venv 에 asyncpg 가 없고 RDS ai.training_candidate 스키마도 코드와 달라 저장이 한 번도 성공할 수 없었다.

보완
  - _auto_score 는 '분류용 휴리스틱(triage)' 이며 정답 증거가 아니다. 사실성 점수는 근거 점수가 있을 때만 그 비율로 준다.
  - 이 경로는 더 이상 학습 승인 상태를 만들지 않는다(auto_approved 항상 False). 새 후보 저장은 동의/권리 정보를 담은
    training-sample.v1(/collect-v1) 으로만 가능하다.
  - 부정 피드백은 중복 여부와 무관하게 v2 저장소의 같은 contentHash 후보에 반영(철회 + manifest 무효화)한다.
"""
import logging

logger = logging.getLogger(__name__)

# 품질 점수 기준(레거시 분류용 — 학습 자격과 무관)
AUTO_APPROVE_MIN = 90
HOLDOUT_MIN = 70


async def collect_candidate(
    question: str,
    answer: str,
    system_prompt: str = "",
    knowledge_level: str = "학사",
    personality: str = "친절_설명형",
    *,
    user_feedback_score: int | None = None,
    user_feedback_text: str | None = None,
    rag_grounding_score: float | None = None,
    request_id: str | None = None,
) -> dict:
    """
    레거시 수집 진입점. 학습 후보를 새로 저장하지 않는다(동의/권리 정보가 없음).

    Returns:
        {"candidate_uuid": str|None, "quality_status": str, "quality_score": int, "stored": False,
         "auto_approved": False, "safety_status": str, "duplicate_status": str, "reason": str, "state": str|None}
    """
    from app.contracts.training_sample_v1 import compute_content_hash
    from app.training_pipeline.collection_hook import collection_enabled
    from app.utils.pii_filter import scan_pii

    q_scan, a_scan = scan_pii(question), scan_pii(answer)
    safety = "safe" if (q_scan.clean and a_scan.clean) else ("pii_check_error" if "ERROR" in (q_scan.status, a_scan.status) else "pii")
    score = await _auto_score(question, answer, knowledge_level, personality, rag_grounding_score=rag_grounding_score)
    base = {"candidate_uuid": None, "quality_score": score, "stored": False, "auto_approved": False,
            "safety_status": safety, "duplicate_status": "unknown", "state": None}

    negative = user_feedback_score is not None and user_feedback_score < 0
    if negative:
        # 부정 피드백은 수집 플래그와 무관하게 항상 철회 경로를 탄다(안전 방향).
        from app.training_pipeline.candidate_service import Actor, record_feedback
        from app.training_pipeline.repository import RepositoryUnavailable, get_repository
        try:
            repo = get_repository()
            existing = await repo.find_by_content_hash(compute_content_hash(question, answer))
        except RepositoryUnavailable:
            return {**base, "quality_status": "feedback_pending", "reason": "TRAINING_REPOSITORY_UNAVAILABLE"}
        except Exception as e:  # noqa: BLE001
            logger.warning("부정 피드백 반영 실패(저장소): %s", type(e).__name__)
            return {**base, "quality_status": "feedback_pending", "reason": "TRAINING_REPOSITORY_ERROR"}
        if existing is None:
            return {**base, "quality_status": "feedback_no_candidate", "duplicate_status": "unique",
                    "reason": "해당 Q/A 학습 후보 없음"}
        res = await record_feedback(repo, existing.candidate_id, -1, actor=Actor("service:legacy-collect", "service", request_id),
                                    reason_code="LEGACY_COLLECT_NEGATIVE")
        return {**base, "candidate_uuid": existing.candidate_id, "quality_status": res.status.lower(),
                "duplicate_status": "duplicate", "state": res.state, "reason": "부정 피드백으로 기존 후보 철회/재검수"}

    if not collection_enabled():
        return {**base, "quality_status": "collection_disabled", "reason": "AI_TRAINING_COLLECTION_ENABLED=false"}
    if safety != "safe":
        return {**base, "quality_status": "unsafe", "reason": "개인정보/비밀정보 감지 또는 검사 실패"}
    return {**base, "quality_status": "consent_required",
            "reason": "레거시 payload 에 동의/권리 정보가 없음 — training-sample.v1(/collect-v1) 사용"}


async def _auto_score(
    question: str,
    answer: str,
    knowledge_level: str,
    personality: str,
    *,
    rag_grounding_score: float | None = None,
) -> int:
    """
    질문/답변 분류용 휴리스틱 점수(0~100). **정답 정확도의 증거가 아니다.**

    채점 기준 (총 100점):
      1. 질문 명확성 (15점)
      2. 답변 완성도 (20점)
      3. 성격/말투 반영 (15점)
      4. 지식수준 반영 (15점)
      5. 근거 일치도 (20점) — rag_grounding_score 가 있을 때만 그 비율. 없으면 0점(예전: 무조건 +15)
      6. 학습 가치 (15점)
    """
    score = 0

    # 1. 질문 명확성
    q_len = len(question.strip())
    if q_len >= 15:
        score += 15
    elif q_len >= 8:
        score += 8

    # 2. 답변 완성도
    a_len = len(answer.strip())
    if a_len >= 200:
        score += 20
    elif a_len >= 80:
        score += 12
    elif a_len >= 30:
        score += 5

    # 3. 성격/말투 반영
    personality_keywords = {
        "친절_설명형":  ["이렇게", "쉽게", "비유", "예시"],
        "비판적_분석형": ["문제", "실수", "개선", "사실은"],
        "논리적_탐구형": ["왜냐하면", "따라서", "결과적으로", "원인"],
        "창의적_확장형": ["만약", "다르게", "새로운", "연결"],
        "간결_요약형":  ["핵심", "요약", "정리", "결론"],
    }
    kws = personality_keywords.get(personality, [])
    if any(kw in answer for kw in kws):
        score += 15
    elif len(answer) > 100:
        score += 7

    # 4. 지식수준 반영
    level_indicators = {
        "입문":    ["쉽게", "비유", "예시", "간단"],
        "학사":    ["개념", "원리", "작동", "기본"],
        "석사":    ["구조", "한계", "비교", "트레이드오프"],
        "박사":    ["이론", "근거", "예외", "확장"],
        "전문가":  ["운영", "장애", "비용", "모니터링"],
    }
    lvl_kws = level_indicators.get(knowledge_level, [])
    if any(kw in answer for kw in lvl_kws):
        score += 15
    elif len(answer) > 150:
        score += 7

    # 5. 근거 일치도 — 검증 신호가 없으면 점수를 주지 않는다.
    if rag_grounding_score is not None:
        score += round(20 * max(0.0, min(1.0, float(rag_grounding_score))))

    # 6. 학습 가치 — 짧거나 오류 메시지면 감점
    if not answer.startswith("[") and len(answer) > 50:
        score += 15
    elif len(answer) > 20:
        score += 5

    return min(100, score)
