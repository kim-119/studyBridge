"""
학습 후보 데이터 다중 기준 검증기.

각 후보에 대해 7개 세부 점수를 계산하고 전체 품질 점수를 산출한다.
기존 training_candidate_manager._auto_score() 보다 엄격한 기준을 적용한다.

검증 기준:
  - knowledge_level_score:     지식수준 반영 여부
  - personality_score:         성격/말투 반영 여부
  - factual_consistency_score: 사실성·근거성
  - rag_grounding_score:       RAG 근거 포함 여부 (system_prompt 기반 추정)
  - format_score:              포맷 적합성 (길이, 오류 메시지 없음 등)
  - duplication_score:         중복 가능성 (낮을수록 좋음)
  - safety_score:              안전성 (PII, secret, 위험 내용)
  - overall_quality_score:     가중 합산

기본 동작: 규칙 기반 (빠르고 비용 없음).
GPT 검증은 별도 optional 플래그로만 사용한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── 검증 기준값 ────────────────────────────────────────────────────────────────

@dataclass
class ValidationCriteria:
    min_overall_quality_score: float = 0.80
    min_knowledge_level_score: float = 0.75
    min_personality_score: float = 0.75
    min_rag_grounding_score: float = 0.70
    max_duplication_score: float = 0.30
    require_safety_pass: bool = True
    min_answer_length: int = 40
    max_answer_length: int = 4000


DEFAULT_CRITERIA = ValidationCriteria()


@dataclass
class ValidationResult:
    candidate_uuid: str
    knowledge_level_score: float = 0.0
    personality_score: float = 0.0
    factual_consistency_score: float = 0.0
    rag_grounding_score: float = 0.0
    format_score: float = 0.0
    duplication_score: float = 0.0   # 낮을수록 좋음 (중복 가능성)
    safety_score: float = 0.0
    overall_quality_score: float = 0.0
    passed: bool = False
    failure_reasons: list[str] = field(default_factory=list)


# ── 지식수준별 지표 키워드 ───────────────────────────────────────────────────
_LEVEL_MARKERS: dict[str, list[str]] = {
    "입문": ["쉽게", "비유", "예시", "간단히", "쉬운", "생각해보면", "이렇게", "처럼"],
    "학사": ["개념", "원리", "기본", "작동", "정의", "핵심", "이해", "특징"],
    "석사": ["구조", "트레이드오프", "한계", "비교", "분석", "성능", "접근", "관점"],
    "박사": ["이론", "근거", "엣지 케이스", "엄밀", "수학적", "논리적", "예외", "확장"],
    "전문가": ["운영", "장애", "비용", "모니터링", "SLA", "가용성", "의사결정", "실서비스"],
}

# ── 성격별 지표 키워드 ──────────────────────────────────────────────────────
_PERSONALITY_MARKERS: dict[str, list[str]] = {
    "친절_설명형": [
        "이렇게", "쉽게", "걱정하지", "어렵지 않아", "단계별", "예를 들면",
        "생각하면", "느낌이에요", "요!", "해요!", "해드릴게요",
    ],
    "비판적_분석형": [
        "문제는", "실수하는", "주의할", "잘못", "개선", "사실은",
        "그렇게만", "반은 맞고", "여기서 많이", "한계",
    ],
    "논리적_탐구형": [
        "왜냐하면", "따라서", "결과적으로", "원인", "근거", "증명",
        "전제", "결론", "그러므로", "이유는",
    ],
    "창의적_확장형": [
        "만약", "다르게", "새로운", "연결", "오, 이렇게", "상상", "확장",
        "다른 분야", "재미있는", "비유하자면",
    ],
    "간결_요약형": [
        "핵심", "요약", "결론", "•", "-", "①", "②", "③", "1.", "2.", "3.",
    ],
}

# ── 보안 위험 패턴 ─────────────────────────────────────────────────────────
_SECRET_PATTERNS = re.compile(
    r"(sk-[a-zA-Z0-9]{20,}|"         # OpenAI API key
    r"AKIA[0-9A-Z]{16}|"              # AWS Access Key
    r"-----BEGIN (RSA|EC|DSA|PRIVATE)|"  # PEM key
    r"(password|passwd|secret|token)\s*=\s*['\"][^'\"]{4,}['\"]|"
    r"postgresql://[^:]+:[^@]+@|"     # DB URL with password
    r"mysql://[^:]+:[^@]+@)",
    re.IGNORECASE,
)

# ── 위험 내용 패턴 ─────────────────────────────────────────────────────────
_DANGER_PATTERNS = re.compile(
    r"(폭탄|폭발물|자살|자해|살인|마약|불법|테러|해킹|계정.탈취|크래킹)",
    re.IGNORECASE,
)


def validate_candidate(
    row: dict,
    criteria: ValidationCriteria | None = None,
) -> ValidationResult:
    """
    단일 학습 후보를 검증한다.

    Args:
        row:      DB row dict (question, answer, system_prompt, knowledge_level, personality 포함)
        criteria: 검증 기준 (None이면 DEFAULT_CRITERIA 사용)

    Returns:
        ValidationResult — passed 필드로 합격 여부 확인
    """
    if criteria is None:
        criteria = DEFAULT_CRITERIA

    result = ValidationResult(
        candidate_uuid=str(row.get("candidate_uuid", ""))
    )

    question   = str(row.get("question",   "") or "").strip()
    answer     = str(row.get("answer",     "") or "").strip()
    sys_prompt = str(row.get("system_prompt", "") or "").strip()
    level      = str(row.get("knowledge_level", "학사") or "학사")
    personality = str(row.get("personality", "친절_설명형") or "친절_설명형")

    reasons: list[str] = []

    # 1. 포맷 점수 ────────────────────────────────────────────────────────
    result.format_score = _score_format(question, answer, criteria)
    if result.format_score < 0.5:
        reasons.append("포맷 불량 (빈 답변 또는 오류 메시지)")

    # 2. 안전성 점수 ─────────────────────────────────────────────────────
    result.safety_score = _score_safety(question, answer, sys_prompt)
    if criteria.require_safety_pass and result.safety_score < 1.0:
        reasons.append("안전성 미통과 (PII, secret, 또는 위험 내용 감지)")

    # 3. 지식수준 점수 ───────────────────────────────────────────────────
    result.knowledge_level_score = _score_knowledge_level(answer, level)
    if result.knowledge_level_score < criteria.min_knowledge_level_score:
        reasons.append(f"지식수준({level}) 반영 부족")

    # 4. 성격 점수 ───────────────────────────────────────────────────────
    result.personality_score = _score_personality(answer, personality)
    if result.personality_score < criteria.min_personality_score:
        reasons.append(f"성격({personality}) 반영 부족")

    # 5. 사실성·근거성 점수 ─────────────────────────────────────────────
    result.factual_consistency_score = _score_factual_consistency(question, answer)

    # 6. RAG grounding 점수 ─────────────────────────────────────────────
    result.rag_grounding_score = _score_rag_grounding(answer, sys_prompt)
    if result.rag_grounding_score < criteria.min_rag_grounding_score:
        reasons.append("RAG 근거 신뢰도 부족")

    # 7. 중복 가능성 점수 ────────────────────────────────────────────────
    result.duplication_score = _estimate_duplication_risk(question, answer)
    if result.duplication_score > criteria.max_duplication_score:
        reasons.append("중복 위험 높음")

    # 8. 전체 품질 점수 (가중 합산) ─────────────────────────────────────
    result.overall_quality_score = _compute_overall(result)

    # 최종 합격 판정
    result.failure_reasons = reasons
    result.passed = (
        result.overall_quality_score >= criteria.min_overall_quality_score
        and (not criteria.require_safety_pass or result.safety_score >= 1.0)
        and result.format_score >= 0.5
    )

    return result


def validate_candidates_batch(
    rows: list[dict],
    criteria: ValidationCriteria | None = None,
) -> list[ValidationResult]:
    """여러 후보를 일괄 검증한다."""
    return [validate_candidate(row, criteria) for row in rows]


# ── 세부 점수 계산 함수 ────────────────────────────────────────────────────────

def _score_format(question: str, answer: str, criteria: ValidationCriteria) -> float:
    """포맷 적합성 점수 (0~1)."""
    if not answer:
        return 0.0
    # 오류 메시지 패턴
    if answer.startswith("[") and any(
        kw in answer for kw in ["오류", "실패", "error", "Error", "Timeout", "연결"]
    ):
        return 0.1
    # 너무 짧음
    if len(answer) < criteria.min_answer_length:
        return 0.3
    # 너무 긺
    if len(answer) > criteria.max_answer_length:
        return 0.6
    # 질문이 비어 있음
    if len(question) < 5:
        return 0.4
    return 1.0


def _score_safety(question: str, answer: str, sys_prompt: str) -> float:
    """안전성 점수 (0 = 위험, 1 = 안전)."""
    combined = f"{question} {answer} {sys_prompt}"

    # PII 감지
    try:
        from app.utils.pii_filter import has_pii
        if has_pii(combined):
            return 0.0
    except Exception:
        pass

    # Secret/키 감지
    if _SECRET_PATTERNS.search(combined):
        return 0.0

    # 위험 내용 감지
    if _DANGER_PATTERNS.search(combined):
        return 0.0

    return 1.0


def _score_knowledge_level(answer: str, level: str) -> float:
    """지식수준 반영 여부 점수 (0~1)."""
    markers = _LEVEL_MARKERS.get(level, _LEVEL_MARKERS["학사"])
    hits = sum(1 for m in markers if m in answer)
    # 키워드 2개 이상 → 만점, 1개 → 중간, 0개 → 낮음
    if hits >= 2:
        return 1.0
    if hits == 1:
        return 0.75
    # 길이 기반 보정: 박사/전문가는 긴 답변이 유리
    if level in ("박사", "전문가") and len(answer) >= 400:
        return 0.78
    if level in ("석사",) and len(answer) >= 250:
        return 0.76
    if level in ("입문",) and len(answer) <= 300:
        return 0.76
    return 0.60


def _score_personality(answer: str, personality: str) -> float:
    """성격/말투 반영 여부 점수 (0~1)."""
    markers = _PERSONALITY_MARKERS.get(personality, [])
    if not markers:
        return 0.8  # custom instruction은 기본 통과

    hits = sum(1 for m in markers if m in answer)
    if hits >= 2:
        return 1.0
    if hits == 1:
        return 0.80
    # 간결형은 목록 기호만 있어도 충분
    if personality == "간결_요약형":
        if any(c in answer for c in ["•", "①", "②", "-", "\n1.", "\n2."]):
            return 0.85
    return 0.65


def _score_factual_consistency(question: str, answer: str) -> float:
    """
    사실성·근거성 점수 (0~1).
    규칙 기반 휴리스틱:
    - 너무 짧으면 낮음 (설명 불충분)
    - 오류 메시지 형태면 낮음
    - 적절한 길이이면 기본 통과
    """
    if len(answer) < 50:
        return 0.5
    if answer.startswith("[") and "오류" in answer:
        return 0.2
    # 답변에 "모르겠"·"알 수 없"·"확인 불가"가 많으면 약간 감점
    uncertainty_count = sum(
        1 for kw in ["모르겠", "알 수 없", "확인 불가", "정보가 없"]
        if kw in answer
    )
    if uncertainty_count >= 2:
        return 0.7
    return 0.85


def _score_rag_grounding(answer: str, sys_prompt: str) -> float:
    """
    RAG 근거 신뢰도 점수 (0~1).
    system_prompt에 PDF_RAG_CONTEXT가 있으면 RAG 기반 답변 여부를 확인한다.
    없으면 일반 답변 (기본 통과).
    """
    if "PDF_RAG_CONTEXT" not in sys_prompt:
        # RAG를 사용하지 않은 답변 — grounding 조건이 없으므로 기본 통과
        return 1.0

    # RAG를 사용한 경우: 자료 언급 여부 확인
    rag_mentions = [
        "자료", "문서", "참고", "출처", "강의", "내용에 따르면",
        "자료에", "문서에", "기반", "따르면",
    ]
    hits = sum(1 for m in rag_mentions if m in answer)
    if hits >= 1:
        return 1.0
    # RAG를 사용했는데 자료 언급이 없으면 약간 낮춤
    if len(answer) >= 200:
        return 0.75  # 긴 답변이면 어느 정도 신뢰
    return 0.70


def _estimate_duplication_risk(question: str, answer: str) -> float:
    """
    중복 가능성 추정 (0~1, 낮을수록 중복 가능성 낮음).
    규칙 기반: 매우 짧거나 일반적인 패턴이면 중복 위험 높음.
    실제 hash 기반 중복 검사는 수집 시점에 이미 완료되어 있으므로
    여기서는 내용 기반 리스크만 추정한다.
    """
    # 질문이 매우 짧고 일반적이면 중복 위험
    if len(question) <= 10:
        return 0.6
    # 답변이 fallback/오류 메시지 패턴이면 중복 위험
    fallback_patterns = [
        "일시적인 오류", "다시 시도", "연결할 수 없습니다",
        "API Key", "설정되지 않았습니다",
    ]
    if any(p in answer for p in fallback_patterns):
        return 0.7
    # 정상 패턴
    return 0.1


def _compute_overall(r: ValidationResult) -> float:
    """
    전체 품질 점수 (0~1). 가중 합산.

    가중치 설계:
    - safety_score:              MUST PASS (통과 실패 시 전체 실격)
    - format_score:              기본 기준
    - knowledge_level_score:     학습 품질의 핵심
    - personality_score:         학습 품질의 핵심
    - factual_consistency_score: 신뢰성
    - rag_grounding_score:       자료 근거
    - duplication_score:         낮을수록 좋음 (역방향)
    """
    # 안전성 실패 시 전체 실격
    if r.safety_score < 1.0:
        return 0.0

    weights = {
        "format_score":              0.10,
        "knowledge_level_score":     0.25,
        "personality_score":         0.20,
        "factual_consistency_score": 0.20,
        "rag_grounding_score":       0.15,
        # duplication은 역방향: (1 - duplication_score) * 0.10
    }

    score = sum(
        getattr(r, k) * w for k, w in weights.items()
    )
    # 중복 점수 역방향 반영
    score += (1.0 - r.duplication_score) * 0.10

    return round(min(1.0, max(0.0, score)), 4)
