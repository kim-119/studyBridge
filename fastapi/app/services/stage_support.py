"""
Stage orchestration 보조 모듈 — 기본 질문 모드 full-stage 스트리밍/검증 공용 헬퍼.

제공:
- 표준 stage 이벤트 페이로드 빌더(requestId/sessionId/roomId/stage/agentId/agentName/content/status/timestamp).
- stage 정책 해석(stagePolicy/enableDeepening/enablePeerFeedback/enableHallucinationValidation).
- hallucination 검증 래퍼(hallucination_validator.assess_factuality → 스펙 출력 구조 매핑, 절대 예외 전파 안 함).
- non-stream 응답용 stageResults/hallucinationCheck 조립 헬퍼(camelCase).

설계 원칙:
- 순수/안전 함수 모음. 검증 실패가 답변 생성을 깨뜨리지 않는다(validation_status=unavailable).
- 오류 문구를 답변 본문으로 만들지 않는다. 내부 진단은 meta/checks 로만 남긴다.
- 신규 파일(autodeploy git reset 생존). 호출부(multi_agent_service/main 등)는 tracked.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

# ── canonical stage 이름(대문자 enum 통일) ─────────────────────────────────────
STAGE_FIRST_ANSWER = "FIRST_ANSWER"
STAGE_DEEPENING = "DEEPENING"
STAGE_PEER_FEEDBACK = "PEER_FEEDBACK"
STAGE_HALLUCINATION_VALIDATION = "HALLUCINATION_VALIDATION"
STAGE_FINAL_SUMMARY = "FINAL_SUMMARY"
STAGE_ALL_COMPLETE = "ALL_COMPLETE"

_VALID_STATUS = {"success", "partial", "failed", "warning", "start", "error"}


def iso_now() -> str:
    """ISO-8601(UTC) 타임스탬프."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _norm_status(status: Optional[str]) -> str:
    s = str(status or "success").strip().lower()
    return s if s in _VALID_STATUS else "success"


def stage_event_data(
    *,
    request_id: str,
    stage: str,
    content: str = "",
    status: str = "success",
    agent_id: Any = None,
    agent_name: Optional[str] = None,
    session_id: Any = None,
    room_id: Any = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """표준 stage 이벤트 data 페이로드를 만든다(스펙 최소 필드 + 선택 확장).

    content 가 비어 있으면 호출부가 agent_answer 류 이벤트로 보내지 않도록 별도 판단해야 한다.
    """
    data: Dict[str, Any] = {
        "requestId": request_id,
        "sessionId": session_id,
        "roomId": room_id,
        "stage": stage,
        "agentId": agent_id,
        "agentName": agent_name,
        "content": content or "",
        "status": _norm_status(status),
        "timestamp": iso_now(),
    }
    if extra:
        for k, v in extra.items():
            data.setdefault(k, v)
    return data


# ── stage 정책 해석 ───────────────────────────────────────────────────────────
def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _req_bool(request: Any, attr: str) -> Optional[bool]:
    val = getattr(request, attr, None)
    if isinstance(val, bool):
        return val
    if isinstance(val, str) and val.strip():
        return val.strip().lower() in ("1", "true", "yes", "on", "full")
    return None


def resolve_stage_policy(request: Any) -> Dict[str, Any]:
    """기본 질문 모드 full-stage 정책을 해석한다.

    우선순위: 요청 필드(있으면) → env(AI_STAGE_*) → 기본값(full/true).
    기본은 'full' — 기본 질문 모드에서도 1차만 하고 끝나지 않게 한다.
    """
    stage_policy = (
        getattr(request, "stagePolicy", None)
        or os.getenv("AI_STAGE_POLICY")
        or "full"
    )
    stage_policy = str(stage_policy).strip().lower() or "full"

    def _resolve(attr: str, env: str) -> bool:
        r = _req_bool(request, attr)
        if r is not None:
            return r
        if stage_policy in ("none", "minimal", "first_only", "first"):
            return False
        return _flag(env, True)

    return {
        "stagePolicy": stage_policy,
        "enableDeepening": _resolve("enableDeepening", "AI_ENABLE_DEEPENING"),
        "enablePeerFeedback": _resolve("enablePeerFeedback", "AI_ENABLE_PEER_FEEDBACK"),
        "enableHallucinationValidation": _resolve(
            "enableHallucinationValidation", "AI_ENABLE_HALLUCINATION_VALIDATION"
        ),
        "enableFinalSummary": _resolve("enableFinalSummary", "AI_ENABLE_FINAL_SUMMARY"),
    }


# ── hallucination 검증 래퍼 ───────────────────────────────────────────────────
def run_hallucination_validation(
    user_question: str,
    answer: str,
    *,
    agent_profile: Any = None,
    retrieved_context: Optional[str] = None,
    evidence_chunks: Optional[Any] = None,
    stage: Optional[Any] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """hallucination_validator.assess_factuality 를 호출하고 스펙 출력 구조로 매핑한다.

    출력(dict):
      factuality_score, hallucination_risk, unsupported_claims, contradictions,
      missing_evidence_notes, safe_revision_hint, validation_status("available"|"unavailable")
    검증기 부재/실패 시에도 예외 없이 validation_status="unavailable" 로 내려간다.
    """
    base = {
        "factuality_score": 0.0,
        "hallucination_risk": "unknown",
        "unsupported_claims": [],
        "contradictions": [],
        "missing_evidence_notes": [],
        "safe_revision_hint": "",
        "validation_status": "unavailable",
    }
    try:
        from app.services.hallucination_validator import assess_factuality
    except Exception:
        base["missing_evidence_notes"] = ["환각 검증기를 로드할 수 없어 사실성 점검을 건너뜁니다."]
        return base

    try:
        r = assess_factuality(
            user_question or "",
            answer or "",
            agent_profile=agent_profile,
            retrieved_context=retrieved_context,
            evidence_chunks=evidence_chunks,
            stage=stage,
        )
    except Exception:
        base["missing_evidence_notes"] = ["환각 검증 중 내부 오류가 발생해 점검을 수행하지 못했습니다."]
        return base

    if not isinstance(r, dict):
        return base

    status_ok = str(r.get("status", "unavailable")).strip().lower() == "ok"
    return {
        "factuality_score": r.get("factuality_score", 0.0),
        "hallucination_risk": r.get("hallucination_risk", "unknown"),
        "unsupported_claims": r.get("unsupported_claims", []) or [],
        "contradictions": r.get("contradictions", []) or [],
        "missing_evidence_notes": r.get("missing_evidence_notes", []) or [],
        "safe_revision_hint": r.get("safe_revision_hint", "") or "",
        "validation_status": "available" if status_ok else "unavailable",
    }


def hallucination_check_camel(result: Dict[str, Any]) -> Dict[str, Any]:
    """run_hallucination_validation 결과를 non-stream 응답용 camelCase 로 변환한다."""
    r = result or {}
    return {
        "factualityScore": r.get("factuality_score", 0.0),
        "hallucinationRisk": r.get("hallucination_risk", "unknown"),
        "unsupportedClaims": r.get("unsupported_claims", []) or [],
        "contradictions": r.get("contradictions", []) or [],
        "missingEvidenceNotes": r.get("missing_evidence_notes", []) or [],
        "safeRevisionHint": r.get("safe_revision_hint", "") or "",
        "validationStatus": r.get("validation_status", "unavailable"),
    }


def validation_event_payload(
    result: Dict[str, Any],
    *,
    request_id: str,
    agent_id: Any = None,
    agent_name: Optional[str] = None,
    session_id: Any = None,
    room_id: Any = None,
) -> Dict[str, Any]:
    """validation_result SSE 이벤트 data(표준 envelope + camelCase 검증 결과)."""
    camel = hallucination_check_camel(result)
    status = "success" if camel["validationStatus"] == "available" else "warning"
    data = stage_event_data(
        request_id=request_id,
        stage=STAGE_HALLUCINATION_VALIDATION,
        content="",
        status=status,
        agent_id=agent_id,
        agent_name=agent_name,
        session_id=session_id,
        room_id=room_id,
        extra={"hallucinationCheck": camel, **camel},
    )
    return data


def assemble_stage_results(
    *,
    first_answer: str = "",
    deepening: str = "",
    peer_feedback: str = "",
    final_summary: str = "",
) -> Dict[str, str]:
    """non-stream 응답의 stageResults 구조."""
    return {
        "firstAnswer": first_answer or "",
        "deepening": deepening or "",
        "peerFeedback": peer_feedback or "",
        "finalSummary": final_summary or "",
    }


def summarize_peer_feedback(peer_steps: List[Any]) -> str:
    """peer feedback step 목록을 한 덩어리 텍스트로 합친다(stageResults.peerFeedback 용)."""
    parts: List[str] = []
    for s in peer_steps or []:
        frm = getattr(s, "fromAgent", None) or ""
        fb = getattr(s, "feedback", None) or ""
        if fb.strip():
            parts.append(f"[{frm}] {fb}".strip())
    return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# Stage 프롬프트 지시(directive) 빌더 + 할루시네이션 가드 + 답변 안전 검증
#
# multi_agent_service 의 1/2/3차 stage 프롬프트 끝에 덧붙여 단계별 역할을 강하게 고정한다.
# 기존 prompt 를 대체하지 않고 강화한다(순수 함수, 부작용/예외 전파 없음).
# 단계 매핑: FIRST_ANSWER=1차 초안 / DEEPENING(=2차 검증·정제) / PEER_FEEDBACK=3차 상호 피드백.
# ══════════════════════════════════════════════════════════════════════════════

# 프롬프트 레벨 할루시네이션 가드(요청서 5.E). 모든 1·2차 답변에 공통 주입.
HALLUCINATION_GUARD_DIRECTIVE = (
    "[정확성·불확실성 규칙 — 반드시 지켜라]\n"
    "- 모르는 내용은 '모른다' 또는 '확실하지 않다'고 말한다. 아는 척 지어내지 않는다.\n"
    "- 제공된 자료/대화 맥락에 없는 사실을 단정하지 않는다. 추론은 '추정' 또는 '~로 보인다'로 표시한다.\n"
    "- 최신 정보·외부 사실·수치·법/정책/가격/일정은 '확인 필요'로 표시한다.\n"
    "- 근거가 없으면 '근거 부족'이라고 솔직히 적는다. 과장된 확신 표현('무조건','100%','확실히')을 쓰지 않는다."
)


def hallucination_guard_directive() -> str:
    """프롬프트 레벨 할루시네이션 가드 문구."""
    return HALLUCINATION_GUARD_DIRECTIVE


def first_answer_directive(*, with_guard: bool = True) -> str:
    """1차 빠른 초안(FIRST_ANSWER) 단계 지시."""
    base = (
        "[이번 단계: 1차 빠른 초안]\n"
        "- 핵심 정의 → 대표 예시 → 한 줄 결론 순서로 빠르게 답한다.\n"
        "- 완벽히 길게 쓰려 하지 말고, 질문에 바로 도움이 되는 핵심만 담는다.\n"
        "- 너의 성격과 지식수준이 드러나게 쓴다."
    )
    return f"{base}\n\n{HALLUCINATION_GUARD_DIRECTIVE}" if with_guard else base


def validation_directive(*, with_guard: bool = True) -> str:
    """2차 검증/심화(DEEPENING) 단계 지시 — 1차 초안을 self-check 하고 더 정확·깊게 정제."""
    base = (
        "[이번 단계: 2차 검증·심화 답안]\n"
        "- 1차 초안의 오류·누락·개념 혼동·과장을 점검해 바로잡는다(사실/추론/추측을 분리).\n"
        "- 애매한 부분은 '확실하지 않음'으로 표시하고, 보수적으로 수정한다.\n"
        "- SQL/프로그래밍/수학/과학 개념은 정확성을 최우선으로 한다(예: DML 과 DDL 을 섞지 마라).\n"
        "- 1차 초안을 그대로 반복하지 말고, 더 정확하고 깊은 답으로 보완한다."
    )
    return f"{base}\n\n{HALLUCINATION_GUARD_DIRECTIVE}" if with_guard else base


def peer_feedback_directive(target_names: str = "") -> str:
    """3차 상호 피드백(PEER_FEEDBACK) 단계 지시 — 다른 에이전트를 명시적으로 비판/보완."""
    who = f"다른 에이전트({target_names})" if target_names else "다른 에이전트"
    return (
        "[이번 단계: 3차 상호 피드백]\n"
        f"- {who}의 답변을 너의 성격·관점에서 구체적으로 평가한다.\n"
        "- 각 답변의 좋은 점 / 부족한 점 / 개선 방향을 분리해 짚는다.\n"
        "- 단순 칭찬·동어 반복은 금지한다. 실제로 도움이 되는 보완을 제시한다.\n"
        "- 상대 답변의 사실 오류·과장·근거 부족을 발견하면 반드시 지적한다."
    )


# ── 답변 안전/품질 휴리스틱 검증(후처리 레벨) ────────────────────────────────────
_OVERCONFIDENCE_TERMS = ("무조건", "100%", "100 %", "절대적으로", "반드시 옳", "확실히 맞", "틀림없이", "의심의 여지없")
_FALLBACK_HINTS = (
    "현재 Ollama", "AI 응답이", "Ollama 응답", "현재 AI 서비스", "일시적으로 접근할 수 없",
    "일시적인 오류", "[GPT", "[Ollama 오류]",
)


def _compact(text: str) -> str:
    return " ".join(str(text or "").split())


def validate_answer_safety(
    answer: str,
    question: str = "",
    *,
    context: str = "",
    stage: Optional[str] = None,
    min_chars: int = 20,
) -> Dict[str, Any]:
    """답변의 안전/품질을 휴리스틱으로 점검한다(LLM 호출 없음, 절대 예외 전파 안 함).

    반환:
      {
        ok: bool,                # 치명 문제(empty/fallback) 없으면 True
        severity: "ok"|"warning"|"error",
        issues: [str],           # 사람이 읽는 문제 목록
        flags: {                 # 개별 신호
          empty, tooShort, fallback, overconfident, offTopic, injectionEcho
        },
      }
    호출부는 ok=False(또는 error)면 재생성/보수적 처리에 쓰고, 사용자에게 내부 진단을 노출하지 않는다.
    """
    a = str(answer or "")
    a_compact = _compact(a)
    issues: List[str] = []
    flags = {
        "empty": False, "tooShort": False, "fallback": False,
        "overconfident": False, "offTopic": False, "injectionEcho": False,
    }
    try:
        if not a_compact:
            flags["empty"] = True
            issues.append("빈 답변")
        else:
            if any(h in a for h in _FALLBACK_HINTS):
                flags["fallback"] = True
                issues.append("LLM fallback/오류 메시지로 보임")
            if len(a_compact) < max(1, min_chars):
                flags["tooShort"] = True
                issues.append(f"답변이 너무 짧음(<{min_chars}자)")
            low = a.lower()
            if any(t in a for t in _OVERCONFIDENCE_TERMS):
                flags["overconfident"] = True
                issues.append("과잉 확신 표현 사용")
            if any(p in low for p in ("ignore previous", "system prompt", "이전 지시", "규칙을 무시")):
                flags["injectionEcho"] = True
                issues.append("프롬프트 인젝션성 문구 반향")
            # off-topic: 질문의 의미 토큰이 답변에 하나도 안 나타나면 의심(짧은 질문/긴 답변 기준 보호)
            q_tokens = [t for t in re_split_tokens(question) if len(t) >= 2]
            if q_tokens and len(a_compact) >= 40:
                hit = sum(1 for t in q_tokens[:12] if t in a)
                if hit == 0:
                    flags["offTopic"] = True
                    issues.append("질문 키워드가 답변에 전혀 없음(주제 이탈 의심)")
    except Exception:
        # 검증 자체가 답변 생성을 깨뜨리지 않도록 한다.
        return {"ok": True, "severity": "ok", "issues": [], "flags": flags}

    if flags["empty"] or flags["fallback"]:
        severity = "error"
    elif any(flags[k] for k in ("tooShort", "overconfident", "offTopic", "injectionEcho")):
        severity = "warning"
    else:
        severity = "ok"
    return {"ok": severity != "error", "severity": severity, "issues": issues, "flags": flags}


def re_split_tokens(text: str) -> List[str]:
    """질문에서 토큰을 추출한다(검증용, 가벼운 분해).

    ASCII 영문/숫자 런과 한글 런을 분리해 추출한다.
    (예: 'RAG란' → ['RAG','란'] — 조사가 붙어 영문 키워드 매칭이 깨지는 것을 방지.)
    """
    import re
    return re.findall(r"[A-Za-z0-9]+|[가-힣]+", str(text or ""))
