"""
Hallucination / Factuality Validator — AI 답변의 환각·근거이탈 위험 판정기.

판정 대상:
- 답변이 질문에 근거해 타당한가(관련성).
- 근거(RAG/evidence) 밖의 강한 단정이 있는가(grounding).
- 수치·날짜·명령어·설정값·파일명·시스템 상태에 대한 무근거 단정이 있는가.
- 내부 모순이 있는가.

설계 원칙(프로젝트 규약 준수):
- 기본은 LLM을 호출하지 않는 deterministic rule-based precheck(빠르고 비용 0, 데모 안전).
  AI_HALLUCINATION_LLM_JUDGE=true일 때만 보조 LLM 판정을 추가한다(기본 off).
- 검증 함수가 실패해도 전체 답변 생성을 실패시키지 않는다 → status="unavailable"로 내려간다.
- evidence가 없다고 해서 무조건 high risk로 과장하지 않는다(근거 부족은 medium/unknown 성격).
- 가짜 출처·허위 수치를 만들지 않는다(이 모듈은 '판정만' 한다. 생성하지 않는다).
- secret/prompt 원문을 로그에 남기지 않는다.

반환 구조(dict):
    {
      "status": "ok" | "unavailable",
      "factuality_score": float,            # 0.0 ~ 1.0
      "hallucination_risk": "low"|"medium"|"high"|"unknown",
      "unsupported_claims": list[str],
      "contradictions": list[str],
      "missing_evidence_notes": list[str],
      "safe_revision_hint": str,
      "checks": dict,                        # 진단용 세부 신호(점수 계산 근거)
    }
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)


# ── env 헬퍼 ────────────────────────────────────────────────────────────────
def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def llm_judge_enabled() -> bool:
    return _flag("AI_HALLUCINATION_LLM_JUDGE", False)


# ── 패턴 ────────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。?!])\s+|\n+")

# 무근거 시 의심: 수치/퍼센트/날짜/버전
_NUMERIC_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d{4}\s?년|\bv?\d+\.\d+(?:\.\d+)?\b|\b\d{1,3}(?:,\d{3})+\b")
# 명령어/설정값/파일명/경로/시스템 상태 단정
_SYSTEMY_RE = re.compile(
    r"sudo\s+\w+|systemctl|/etc/\S+|/var/\S+|\.(?:py|sh|conf|yaml|yml|json|env|service)\b|"
    r"--[a-z][\w-]+|:\d{2,5}\b|localhost|127\.0\.0\.1|chmod|chown|export\s+[A-Z_]+=",
    re.IGNORECASE,
)
# 강한 단정 표현(근거 없으면 감점 신호)
_ABSOLUTE_RE = re.compile(
    r"항상|무조건|반드시|절대|100\s?%|전혀|모든\s|언제나|예외\s*없(?:이|다)|결코|확실(?:히|하)",
)
# 자기모순 후보(같은 문장군 내 상반 표현)
_CONTRA_PAIRS = [
    ("가능", "불가능"), ("맞다", "틀리다"), ("있다", "없다"),
    ("지원한다", "지원하지 않"), ("된다", "안 된다"), ("필요하다", "필요 없"),
    ("증가", "감소"), ("참", "거짓"),
]
# 검증 불가/실패 마커(LLM이 망가진 출력을 줬을 때)
_FAIL_MARKERS = ("[Ollama", "[GPT", "OPENAI_API_KEY", "비활성화")


# Latin/숫자 run 과 한글 run 을 분리(한국어 조사가 붙은 "SSH가"/"API를" 같은 토큰 대응)
_RUN_RE = re.compile(r"[0-9A-Za-z]+|[가-힣]+")


def _tokens(text: str) -> List[str]:
    out: List[str] = []
    for raw in _TOKEN_RE.findall(text or ""):
        for run in _RUN_RE.findall(raw):
            if len(run) > 1:
                out.append(run.lower())
    return out


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]


def _evidence_text(retrieved_context: Optional[str],
                   evidence_chunks: Optional[Sequence[Union[str, Dict[str, Any]]]]) -> str:
    parts: List[str] = []
    if retrieved_context and str(retrieved_context).strip():
        parts.append(str(retrieved_context))
    for ch in (evidence_chunks or []):
        if isinstance(ch, str):
            parts.append(ch)
        elif isinstance(ch, dict):
            parts.append(" ".join(str(ch.get(k, "")) for k in ("title", "content", "snippet", "text")))
    return "\n".join(p for p in parts if p and p.strip())


def _relevance(question: str, answer: str) -> float:
    q = set(_tokens(question))
    a = set(_tokens(answer))
    if not q or not a:
        return 0.0
    return len(q & a) / max(2, len(q))


def _grounding_ratio(answer_tokens: set, evidence_tokens: set) -> float:
    if not answer_tokens or not evidence_tokens:
        return 0.0
    return len(answer_tokens & evidence_tokens) / max(1, len(answer_tokens))


def _detect_contradictions(answer: str) -> List[str]:
    out: List[str] = []
    text = answer or ""
    for pos, neg in _CONTRA_PAIRS:
        if pos in text and neg in text:
            out.append(f"상반된 표현이 함께 나타남: '{pos}' ↔ '{neg}' (동일 대상에 대한 모순인지 확인 필요)")
    return out[:5]


def _detect_unsupported(sentences: List[str], evidence_tokens: set, has_evidence: bool) -> List[str]:
    """수치/날짜/명령/설정/파일/시스템 상태 단정 중 근거에 없는 것을 모은다."""
    out: List[str] = []
    for s in sentences:
        risky = bool(_NUMERIC_RE.search(s) or _SYSTEMY_RE.search(s))
        if not risky:
            continue
        if has_evidence:
            s_tokens = set(_tokens(s))
            covered = _grounding_ratio(s_tokens, evidence_tokens)
            if covered >= 0.5:
                continue  # 근거로 충분히 뒷받침됨
        out.append(s[:160])
    # 근거가 아예 없을 때만 별도로 강한 단정도 후보에 추가(과장 방지: 최대 소량)
    if not has_evidence:
        for s in sentences:
            if _ABSOLUTE_RE.search(s) and s[:160] not in out:
                out.append(s[:160])
    # 중복 제거 + 상한
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq[:8]


def _looks_failed(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return True
    return any(m in t[:60] for m in _FAIL_MARKERS)


def _risk_bucket(score: float, unsupported: int, contradictions: int, has_evidence: bool) -> str:
    if contradictions > 0 or unsupported >= 3:
        return "high"
    if score < 0.30:
        # 관련성이 매우 낮음. 근거 유무와 무관하게 위험.
        return "high"
    if unsupported >= 1 or score < 0.55:
        return "medium"
    if not has_evidence:
        # 근거 없음 + 의심 신호 없음 → 과장하지 않고 낮은~중간으로.
        return "low" if score >= 0.7 else "medium"
    return "low"


def assess_factuality(
    user_question: str,
    answer: str,
    *,
    agent_profile: Any = None,
    retrieved_context: Optional[str] = None,
    evidence_chunks: Optional[Sequence[Union[str, Dict[str, Any]]]] = None,
    stage: Optional[Union[int, str]] = None,
) -> Dict[str, Any]:
    """답변의 환각/근거이탈 위험을 deterministic precheck(+선택 LLM)로 판정한다.

    실패해도 예외를 던지지 않고 status="unavailable"로 안전하게 내려간다.
    """
    try:
        q = (user_question or "").strip()
        a = (answer or "").strip()

        # 답변 자체가 생성 실패/빈 응답이면 검증 자체가 무의미 → unavailable
        if not a or _looks_failed(a):
            return {
                "status": "unavailable",
                "factuality_score": 0.0,
                "hallucination_risk": "unknown",
                "unsupported_claims": [],
                "contradictions": [],
                "missing_evidence_notes": ["답변 본문이 비었거나 생성에 실패해 사실성 검증을 수행할 수 없습니다."],
                "safe_revision_hint": "정상 본문을 먼저 생성한 뒤 다시 검증하세요.",
                "checks": {"reason": "empty_or_failed_answer"},
            }

        evidence = _evidence_text(retrieved_context, evidence_chunks)
        has_evidence = bool(evidence.strip())
        evidence_tokens = set(_tokens(evidence)) if has_evidence else set()

        sentences = _sentences(a)
        relevance = _relevance(q, a)
        contradictions = _detect_contradictions(a)
        unsupported = _detect_unsupported(sentences, evidence_tokens, has_evidence)

        grounding = _grounding_ratio(set(_tokens(a)), evidence_tokens) if has_evidence else None

        # ── 점수 합성 ──
        # 관련성 기반 베이스 + grounding 보너스 - 무근거 단정/모순 패널티
        score = 0.45 + 0.45 * min(1.0, relevance * 1.4)
        if has_evidence and grounding is not None:
            score += 0.10 * min(1.0, grounding * 2.0)
        score -= 0.07 * len(unsupported)
        score -= 0.15 * len(contradictions)
        score = max(0.0, min(1.0, round(score, 3)))

        risk = _risk_bucket(score, len(unsupported), len(contradictions), has_evidence)

        missing_notes: List[str] = []
        if not has_evidence:
            missing_notes.append("외부 근거(RAG/검색)가 제공되지 않아 개념 일관성 중심으로만 점검했습니다(근거 부족 ≠ 오류).")
        elif grounding is not None and grounding < 0.2:
            missing_notes.append("답변 내용이 제공된 근거와 어휘적으로 거의 겹치지 않습니다. 근거 인용을 보강하세요.")
        if relevance < 0.25:
            missing_notes.append("답변이 질문 핵심어와 거의 맞물리지 않습니다. 질문에 직접 답하는지 확인하세요.")

        hint_parts: List[str] = []
        if unsupported:
            hint_parts.append("근거 없이 단정한 수치·명령어·설정값·시스템 상태는 '추정'임을 밝히거나 출처와 함께 표기하세요")
        if contradictions:
            hint_parts.append("상반되는 서술이 같은 대상을 가리키면 하나로 정리해 모순을 제거하세요")
        if relevance < 0.25:
            hint_parts.append("질문의 핵심에 직접 답하도록 도입부를 다시 쓰세요")
        if not hint_parts:
            hint_parts.append("핵심 주장과 근거를 분리해 제시하면 신뢰도가 올라갑니다")
        safe_revision_hint = ". ".join(hint_parts) + "."

        result: Dict[str, Any] = {
            "status": "ok",
            "factuality_score": score,
            "hallucination_risk": risk,
            "unsupported_claims": unsupported,
            "contradictions": contradictions,
            "missing_evidence_notes": missing_notes,
            "safe_revision_hint": safe_revision_hint,
            "checks": {
                "relevance": round(relevance, 3),
                "grounding": (round(grounding, 3) if grounding is not None else None),
                "has_evidence": has_evidence,
                "sentence_count": len(sentences),
                "stage": stage,
                "llm_judge": False,
            },
        }

        # ── 선택적 LLM 보조 판정(기본 off) ──
        if llm_judge_enabled():
            try:
                _merge_llm_judgment(result, q, a, evidence)
            except Exception as e:  # noqa: BLE001
                logger.info("[hallucination] LLM 보조 판정 생략(deterministic 유지): %s", e)

        return result
    except Exception as e:  # noqa: BLE001 — 검증 실패가 답변 생성을 깨면 안 됨
        logger.warning("[hallucination] 검증 실패 → unavailable: %s", e)
        return {
            "status": "unavailable",
            "factuality_score": 0.0,
            "hallucination_risk": "unknown",
            "unsupported_claims": [],
            "contradictions": [],
            "missing_evidence_notes": ["검증기 내부 오류로 사실성 점검을 수행하지 못했습니다."],
            "safe_revision_hint": "",
            "checks": {"reason": "validator_exception"},
        }


def _merge_llm_judgment(result: Dict[str, Any], question: str, answer: str, evidence: str) -> None:
    """OpenAI(검증 전용)로 보조 판정을 받아 deterministic 결과와 보수적으로 병합한다.

    - LLM이 더 높은 위험을 제시하면 위험을 상향(보수적), 낮추는 방향으로는 강제 하향하지 않는다.
    - 실패/파싱불가 시 아무것도 바꾸지 않는다(호출부에서 예외를 흡수).
    """
    from app.services.llm_engine_router import call_verifier_llm
    import json

    sys = (
        "너는 사실성/환각 검증기다. 답변이 질문에 근거해 타당한지, 근거 없는 단정/모순이 있는지 "
        "판정하고 JSON만 출력한다. 설명/마크다운/코드블록 없이 순수 JSON 하나만."
    )
    ev_block = f"\n[근거]\n{evidence[:1500]}\n" if evidence.strip() else "\n[근거] 없음\n"
    user = (
        f"[질문]\n{question[:800]}\n\n[답변]\n{answer[:2000]}\n{ev_block}\n"
        '아래 JSON만 출력: {"hallucination_risk":"low|medium|high",'
        '"unsupported_claims":["..."],"contradictions":["..."]}'
    )
    raw = call_verifier_llm(sys, user, max_tokens=400)
    if not raw or _looks_failed(raw):
        return
    s = raw.strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return
    data = json.loads(s[start:end + 1])
    if not isinstance(data, dict):
        return

    order = {"low": 0, "medium": 1, "high": 2, "unknown": 1}
    llm_risk = str(data.get("hallucination_risk", "")).strip().lower()
    if llm_risk in order and order[llm_risk] > order.get(result["hallucination_risk"], 1):
        result["hallucination_risk"] = llm_risk  # 보수적 상향만
    for key in ("unsupported_claims", "contradictions"):
        extra = [str(x).strip() for x in (data.get(key) or []) if str(x).strip()]
        if extra:
            merged = list(dict.fromkeys([*result.get(key, []), *extra]))
            result[key] = merged[:10]
    result["checks"]["llm_judge"] = True


# 의미가 같은 별칭(호출부 네이밍 유연성). 동일 결과를 반환한다.
def validate_hallucination_risk(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return assess_factuality(*args, **kwargs)


def validate_answer_grounding(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return assess_factuality(*args, **kwargs)
