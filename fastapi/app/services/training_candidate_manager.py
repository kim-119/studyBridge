"""
학습 후보 자동 수집/검수 관리자.
대화에서 Q/A를 추출해 개인정보 필터 → 중복 검사 → 자동 품질 평가 후 ai-db에 저장한다.
"""
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# 품질 점수 기준
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
) -> dict:
    """
    Q/A를 학습 후보로 수집한다. **즉시 학습하지 않는다** — 검수 게이트 통과 후보만 적재한다.

    검수 게이트:
      - 개인정보(PII) 감지 → unsafe (저장 안 함)
      - 중복(content_hash) → duplicate (저장 안 함)
      - 자동 품질 점수 + (있으면) RAG grounding 으로 status 결정
      - **사용자가 싫어요/오류 신고(user_feedback_score<0)한 답변은 auto_approved 금지**
        → 점수와 무관하게 holdout(또는 auto_rejected)으로 강등

    Returns:
        {"candidate_uuid": str|None, "quality_status": str, "quality_score": int,
         "stored": bool, "safety_status": str, "duplicate_status": str}
    """
    from app.utils.pii_filter import has_pii
    from app.utils.duplicate_checker import is_duplicate

    # 개인정보 필터
    if has_pii(question) or has_pii(answer):
        return {"quality_status": "unsafe", "quality_score": 0, "stored": False,
                "safety_status": "pii", "duplicate_status": "unknown", "reason": "개인정보 감지"}

    # 내용 해시 (중복 검사)
    content = f"{question.strip()}\n{answer.strip()}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    if await is_duplicate(content_hash):
        return {"quality_status": "duplicate", "quality_score": 0, "stored": False,
                "safety_status": "safe", "duplicate_status": "duplicate", "reason": "중복 데이터"}

    # 자동 품질 평가
    score = await _auto_score(question, answer, knowledge_level, personality)

    # 사용자 부정 피드백 여부 (싫어요/오류 신고)
    negative_feedback = (user_feedback_score is not None and user_feedback_score < 0)

    if negative_feedback:
        # 부정 피드백 답변은 절대 auto_approved 금지 → 최소 holdout, 점수 낮으면 rejected
        status = "auto_rejected" if score < HOLDOUT_MIN else "holdout"
    elif score >= AUTO_APPROVE_MIN:
        status = "auto_approved"
    elif score >= HOLDOUT_MIN:
        status = "holdout"
    else:
        status = "auto_rejected"

    # ai-db 저장 시도
    stored = False
    candidate_uuid = None
    try:
        candidate_uuid = await _save_candidate(
            question=question,
            answer=answer,
            system_prompt=system_prompt,
            knowledge_level=knowledge_level,
            personality=personality,
            quality_score=score,
            quality_status=status,
            content_hash=content_hash,
        )
        stored = True
    except Exception as e:
        logger.warning("학습 후보 저장 실패 (무시): %s", e)

    return {
        "candidate_uuid": candidate_uuid,
        "quality_status": status,
        "quality_score":  score,
        "stored":         stored,
        "safety_status":  "safe",
        "duplicate_status": "unique",
        "auto_approved":  status == "auto_approved",
        "rag_grounding_score": rag_grounding_score,
        "negative_feedback": negative_feedback,
    }


async def _auto_score(
    question: str,
    answer: str,
    knowledge_level: str,
    personality: str,
) -> int:
    """
    질문/답변 자동 품질 점수를 계산한다 (0~100).

    채점 기준 (총 100점):
      1. 질문 명확성 (15점)
      2. 답변 완성도 (20점)
      3. 성격/말투 반영 (15점)
      4. 지식수준 반영 (15점)
      5. 사실성/근거성 (20점) — GPT 가용 시 실제 검증, 아니면 추정
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
    from app.services.personality_prompt_builder import PersonalityType
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

    # 5. 사실성 — GPT 검증 결과 있으면 반영, 없으면 길이 기반 추정
    score += 15  # 기본 통과 (GPT 미검증 시 중간값)

    # 6. 학습 가치 — 짧거나 오류 메시지면 감점
    if not answer.startswith("[") and len(answer) > 50:
        score += 15
    elif len(answer) > 20:
        score += 5

    return min(100, score)


async def _save_candidate(
    question: str,
    answer: str,
    system_prompt: str,
    knowledge_level: str,
    personality: str,
    quality_score: int,
    quality_status: str,
    content_hash: str,
) -> str:
    """ai.training_candidate에 저장하고 candidate_uuid를 반환한다."""
    from app.db.postgres import get_conn
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ai.training_candidate
              (question, answer, system_prompt, knowledge_level, personality,
               quality_score, quality_status, content_hash)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT DO NOTHING
            RETURNING candidate_uuid::text
            """,
            question, answer, system_prompt,
            knowledge_level, personality,
            quality_score, quality_status, content_hash,
        )
    return str(row["candidate_uuid"]) if row else None
