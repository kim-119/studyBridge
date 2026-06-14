"""
LLM Intent Router — 자료보관함/그룹스터디/학습메이트 공통 의도·위험도·라우팅 판정기.

  POST /api/ai/intent/route
    req:  {text, surface, context{materialId, roomId, mode, tone,
           learnerLevel, hasMaterialContext, hasPreviousQuestion}}
    resp: {intent, riskLevel, routeAction, confidence, directReply, reason,
           normalizedText, needsMaterialContext, needsQuizPipeline,
           warningMessage, fallbackUsed}

설계 원칙:
  - Router는 절대 실제 답변을 생성하지 않는다. 사용자 입력을 "어디로 보낼지"만 판단한다.
  - 주 판정은 Ollama(qwen3:14b) LLM 문맥 판단. 욕설 단어 하드코딩 차단을 쓰지 않는다.
  - LLM 실패(연결/timeout/JSON 파싱/enum 검증 실패) 시 deterministic fallback으로만 안전하게 라우팅.
    fallback은 "최소 안전망"이며 정밀한 의도 분류를 시도하지 않는다.
  - 이 Router 실패가 전체 AI 채팅을 죽이면 안 된다 → 어떤 예외에서도 200 + fallback 응답.
  - 기존 SSE/Streaming 구조와 독립. EC2 Spring/React는 이 endpoint만 호출하면 된다.
"""
import asyncio
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/intent", tags=["Intent Router"])

# ── 환경변수 ──────────────────────────────────────────────────────────────────
INTENT_ROUTER_MODEL = os.getenv("INTENT_ROUTER_MODEL", os.getenv("OLLAMA_MODEL", "qwen3:14b"))
INTENT_ROUTER_TIMEOUT_SEC = int(os.getenv("INTENT_ROUTER_TIMEOUT_SEC", "5"))
INTENT_ROUTER_ENABLED = os.getenv("INTENT_ROUTER_ENABLED", "true").strip().lower() == "true"

# ── enum 정의 ─────────────────────────────────────────────────────────────────
INTENTS = {
    "GREETING", "SMALLTALK", "LEARNING_QUESTION", "MATERIAL_QA",
    "QUIZ_GENERATION", "SUMMARY_REQUEST", "ROADMAP_REQUEST",
    "MODE_CHANGE_REQUEST", "REWRITE_REQUEST", "ADMIN_OR_SYSTEM_REQUEST",
    "UNSAFE_PROFANITY", "UNSAFE_HARASSMENT", "UNSAFE_THREAT",
    "UNSAFE_SELF_HARM", "UNSAFE_ILLEGAL", "UNKNOWN",
}
RISK_LEVELS = {"ALLOW", "WARN", "BLOCK"}
ROUTE_ACTIONS = {
    "DIRECT_REPLY", "ARCHIVE_AI_AGENT", "MATERIAL_QA_AGENT", "GROUP_STUDY_AGENT",
    "LEARNING_MATE_AGENT", "LEARNING_MATE_AGENT_REWRITE", "QUIZ_PIPELINE",
    "SUMMARY_PIPELINE", "ROADMAP_PIPELINE", "WARN", "BLOCK", "CLARIFY",
}
SURFACES = {"archive_chat", "group_study_chat", "learning_mate"}

# UNSAFE_* intent → 위험도 매핑 (LLM 결과 정합성 보정 + fallback 안전망 공용)
UNSAFE_INTENTS = {
    "UNSAFE_PROFANITY", "UNSAFE_HARASSMENT", "UNSAFE_THREAT",
    "UNSAFE_SELF_HARM", "UNSAFE_ILLEGAL",
}

# surface별 기본 에이전트 라우팅 (fallback "그 외" 정책)
SURFACE_DEFAULT_ROUTE = {
    "archive_chat": "ARCHIVE_AI_AGENT",
    "group_study_chat": "GROUP_STUDY_AGENT",
    "learning_mate": "LEARNING_MATE_AGENT",
}


# ── 요청/응답 모델 ────────────────────────────────────────────────────────────
class IntentContext(BaseModel):
    materialId: Optional[Any] = None
    roomId: Optional[Any] = None
    mode: Optional[str] = None
    tone: Optional[str] = None
    learnerLevel: Optional[str] = None
    hasMaterialContext: bool = False
    hasPreviousQuestion: bool = False


class IntentRouteRequest(BaseModel):
    text: str = ""
    surface: str = "learning_mate"
    context: Optional[IntentContext] = None


class IntentRouteResponse(BaseModel):
    intent: str
    riskLevel: str
    routeAction: str
    confidence: float
    directReply: Optional[str] = None
    reason: str
    normalizedText: str
    needsMaterialContext: bool = False
    needsQuizPipeline: bool = False
    warningMessage: Optional[str] = None
    fallbackUsed: bool = False


# ── 프롬프트 ──────────────────────────────────────────────────────────────────
def _system_prompt() -> str:
    return (
        "You are an Intent Router for the StudyBridge learning platform. "
        "You DO NOT answer the user. You ONLY classify the user's message into a routing decision. "
        "Judge intent, risk and safety from CONTEXT and MEANING, never from a fixed banned-word list — "
        "profanity used merely for emphasis on a learning topic is NOT unsafe; a genuine threat or "
        "self-harm or harassment IS unsafe regardless of wording.\n\n"
        "Output ONE JSON object only. No markdown, no commentary, no <think>.\n\n"
        "Allowed values:\n"
        "intent: GREETING | SMALLTALK | LEARNING_QUESTION | MATERIAL_QA | QUIZ_GENERATION | "
        "SUMMARY_REQUEST | ROADMAP_REQUEST | MODE_CHANGE_REQUEST | REWRITE_REQUEST | "
        "ADMIN_OR_SYSTEM_REQUEST | UNSAFE_PROFANITY | UNSAFE_HARASSMENT | UNSAFE_THREAT | "
        "UNSAFE_SELF_HARM | UNSAFE_ILLEGAL | UNKNOWN\n"
        "riskLevel: ALLOW | WARN | BLOCK\n"
        "routeAction: DIRECT_REPLY | ARCHIVE_AI_AGENT | MATERIAL_QA_AGENT | GROUP_STUDY_AGENT | "
        "LEARNING_MATE_AGENT | LEARNING_MATE_AGENT_REWRITE | QUIZ_PIPELINE | SUMMARY_PIPELINE | "
        "ROADMAP_PIPELINE | WARN | BLOCK | CLARIFY\n\n"
        "Routing rules:\n"
        "- GREETING/SMALLTALK -> DIRECT_REPLY (provide a short directReply in the user's language).\n"
        "- A conceptual learning question -> LEARNING_MATE_AGENT on learning_mate; "
        "MATERIAL_QA_AGENT on archive_chat when a material is in context; GROUP_STUDY_AGENT on group_study_chat.\n"
        "- A question explicitly about the attached material/PDF -> MATERIAL_QA / MATERIAL_QA_AGENT.\n"
        "- Asking to generate quiz/test/problems -> QUIZ_GENERATION / QUIZ_PIPELINE.\n"
        "- Asking to summarize -> SUMMARY_REQUEST / SUMMARY_PIPELINE.\n"
        "- Asking for a study roadmap/plan -> ROADMAP_REQUEST / ROADMAP_PIPELINE.\n"
        "- Asking to re-explain in another mode/style (e.g. Socratic, simpler) -> "
        "MODE_CHANGE_REQUEST or REWRITE_REQUEST / LEARNING_MATE_AGENT_REWRITE.\n"
        "- Unsafe content: WARN (mild) sets routeAction=WARN with a warningMessage; "
        "BLOCK (threat/self-harm/serious harassment/illegal) sets routeAction=BLOCK.\n"
        "- Empty or unclear -> UNKNOWN / CLARIFY.\n\n"
        "JSON schema (every key required):\n"
        '{ "intent": "<enum>", "riskLevel": "<enum>", "routeAction": "<enum>", '
        '"confidence": 0.0, "directReply": null, "reason": "<one short sentence>", '
        '"needsMaterialContext": false, "needsQuizPipeline": false, '
        '"warningMessage": null }'
    )


def _user_prompt(req: IntentRouteRequest, ctx: IntentContext) -> str:
    return (
        f"surface: {req.surface}\n"
        f"context.mode: {ctx.mode}\n"
        f"context.tone: {ctx.tone}\n"
        f"context.learnerLevel: {ctx.learnerLevel}\n"
        f"context.hasMaterialContext: {ctx.hasMaterialContext}\n"
        f"context.hasPreviousQuestion: {ctx.hasPreviousQuestion}\n"
        f"user message:\n{req.text}\n\n"
        "Return the routing JSON only."
    )


# ── enum 정규화 ───────────────────────────────────────────────────────────────
def _norm(value: Any, allowed: set) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    return v if v in allowed else None


def _norm_surface(value: Any) -> str:
    if not value:
        return "learning_mate"
    v = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return v if v in SURFACES else "learning_mate"


# ── LLM 호출 + 파싱 ───────────────────────────────────────────────────────────
def _call_router_ollama(system_prompt: str, user_prompt: str) -> Optional[str]:
    """
    Ollama /api/chat 직접 호출. ollama_client.ask_ollama 대신 직접 호출하는 이유:
      qwen3 계열은 thinking 모델이라 think 블록이 num_predict 예산을 모두 소진해
      JSON 본문이 빈 응답으로 잘린다. Router는 추론이 필요 없으므로 think=false로
      비활성화하면 ~1초 내 JSON만 응답한다(5초 예산 내 안정적). ask_ollama는
      think 파라미터를 노출하지 않아 여기서만 별도 호출한다.
    예외/오류 시 None을 반환 → 호출부가 deterministic fallback으로 전환.
    """
    import requests
    from app.core.config import OLLAMA_BASE_URL

    payload = {
        "model": INTENT_ROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,  # qwen3 thinking 비활성 — Router는 추론 불필요, 속도/예산 확보
        "options": {"temperature": 0.0, "num_predict": 300, "num_ctx": 4096},
    }
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=INTENT_ROUTER_TIMEOUT_SEC
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return content.strip() or None
    except requests.Timeout:
        logger.warning("intent/route Ollama timeout(%ss)", INTENT_ROUTER_TIMEOUT_SEC)
        return None
    except requests.ConnectionError:
        logger.warning("intent/route Ollama 연결 실패 (%s)", OLLAMA_BASE_URL)
        return None
    except Exception as e:
        logger.warning("intent/route Ollama 호출 예외: %s", e)
        return None


def _classify_with_llm(req: IntentRouteRequest, ctx: IntentContext) -> Optional[Dict[str, Any]]:
    """Ollama Router 호출 → 정규화된 dict. 실패 시 None(→ fallback)."""
    from app.utils.json_parser import extract_json

    raw = _call_router_ollama(_system_prompt(), _user_prompt(req, ctx))
    if not raw:
        return None
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        logger.warning("intent/route LLM 응답 JSON 파싱 실패 (len=%d)", len(raw or ""))
        return None

    intent = _norm(parsed.get("intent"), INTENTS)
    risk = _norm(parsed.get("riskLevel"), RISK_LEVELS)
    route = _norm(parsed.get("routeAction"), ROUTE_ACTIONS)
    if not intent or not risk or not route:
        logger.warning(
            "intent/route enum 검증 실패 intent=%r risk=%r route=%r",
            parsed.get("intent"), parsed.get("riskLevel"), parsed.get("routeAction"),
        )
        return None

    try:
        conf = float(parsed.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7

    return {
        "intent": intent,
        "riskLevel": risk,
        "routeAction": route,
        "confidence": max(0.0, min(1.0, conf)),
        "directReply": _clean_str(parsed.get("directReply")),
        "reason": _clean_str(parsed.get("reason")) or "Routed by LLM intent classification.",
        "needsMaterialContext": bool(parsed.get("needsMaterialContext", False)),
        "needsQuizPipeline": bool(parsed.get("needsQuizPipeline", False)),
        "warningMessage": _clean_str(parsed.get("warningMessage")),
    }


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


# ── 후처리: 위험도·라우팅·파생필드 정합성 보정 ────────────────────────────────
def _finalize(decision: Dict[str, Any], ctx: IntentContext, fallback_used: bool) -> IntentRouteResponse:
    """LLM/fallback 공통 후처리: UNSAFE↔BLOCK/WARN 정합성, needs* 파생값 강제."""
    intent = decision["intent"]
    risk = decision["riskLevel"]
    route = decision["routeAction"]

    # UNSAFE intent인데 ALLOW로 온 경우 최소 WARN으로 끌어올린다(안전 우선).
    if intent in UNSAFE_INTENTS and risk == "ALLOW":
        risk = "WARN"

    # 위험도와 routeAction 정합성: BLOCK은 BLOCK, WARN은 WARN으로 보낸다.
    if risk == "BLOCK":
        route = "BLOCK"
    elif risk == "WARN" and route not in ("WARN", "BLOCK"):
        route = "WARN"

    warning = decision.get("warningMessage")
    if risk in ("WARN", "BLOCK") and not warning:
        warning = (
            "안전하지 않은 표현이 감지되어 요청을 차단했습니다."
            if risk == "BLOCK"
            else "표현을 다듬어 다시 시도해 주세요."
        )
    if risk == "ALLOW":
        warning = None

    # 파생필드는 최종 route/intent에서 deterministic하게 산출(LLM 값보다 신뢰).
    needs_quiz = route == "QUIZ_PIPELINE"
    # 자료보관함 에이전트·MATERIAL_QA·자료 기반 파이프라인(퀴즈/요약/로드맵)은 자료 컨텍스트가 필요.
    # LLM이 명시적으로 needsMaterialContext=true를 준 경우도 존중.
    needs_material = (
        route in ("MATERIAL_QA_AGENT", "ARCHIVE_AI_AGENT",
                  "QUIZ_PIPELINE", "SUMMARY_PIPELINE", "ROADMAP_PIPELINE")
        or intent == "MATERIAL_QA"
        or bool(decision.get("needsMaterialContext"))
    )

    direct_reply = decision.get("directReply")
    if route != "DIRECT_REPLY":
        direct_reply = None

    return IntentRouteResponse(
        intent=intent,
        riskLevel=risk,
        routeAction=route,
        confidence=round(float(decision["confidence"]), 2),
        directReply=direct_reply,
        reason=decision.get("reason") or "",
        normalizedText=decision["normalizedText"],
        needsMaterialContext=needs_material,
        needsQuizPipeline=needs_quiz,
        warningMessage=warning,
        fallbackUsed=fallback_used,
    )


# ── deterministic fallback (최소 안전망) ──────────────────────────────────────
# 명백한 위협/자해 신호는 LLM이 죽었을 때를 위한 최소한의 백스톱만 둔다.
# 이것은 1차 차단 수단이 아니라 LLM 부재 시의 안전망이다.
_THREAT_HINTS = ("죽여버", "죽여 버", "죽인다", "kill you", "i will kill")
_SELF_HARM_HINTS = ("자살", "죽고 싶", "죽고싶", "목숨을 끊", "kill myself", "suicide")
_QUIZ_HINTS = ("퀴즈", "문제 만들", "문제만들", "문제 내", "객관식", "주관식", "ox 문제", "시험문제", "quiz")
_SUMMARY_HINTS = ("요약", "정리해", "summarize", "summary")
_ROADMAP_HINTS = ("로드맵", "학습 계획", "학습계획", "공부 계획", "roadmap", "커리큘럼")
_GREETING_HINTS = ("안녕", "하이", "헬로", "hello", "hi", "반가워", "ㅎㅇ", "좋은 아침")


def _fallback_decision(text: str, surface: str, ctx: IntentContext) -> Dict[str, Any]:
    norm = (text or "").strip()
    low = norm.lower()

    base = {
        "normalizedText": norm,
        "confidence": 0.4,
        "directReply": None,
        "needsMaterialContext": False,
        "needsQuizPipeline": False,
        "warningMessage": None,
    }

    # 1) 빈 입력 → CLARIFY
    if not norm:
        return {**base, "intent": "UNKNOWN", "riskLevel": "ALLOW", "routeAction": "CLARIFY",
                "confidence": 0.5,
                "reason": "입력이 비어 있어 명확화가 필요합니다.",
                "directReply": "무엇을 도와드릴까요? 질문이나 요청을 입력해 주세요."}

    # 2) 명백한 위협/자해 (최소 안전망)
    if any(h in low for h in _THREAT_HINTS):
        return {**base, "intent": "UNSAFE_THREAT", "riskLevel": "BLOCK", "routeAction": "BLOCK",
                "confidence": 0.6, "reason": "위협으로 해석될 수 있는 표현이 감지되었습니다(안전망)."}
    if any(h in low for h in _SELF_HARM_HINTS):
        return {**base, "intent": "UNSAFE_SELF_HARM", "riskLevel": "BLOCK", "routeAction": "BLOCK",
                "confidence": 0.6, "reason": "자해 위험 신호가 감지되었습니다(안전망)."}

    # 3) 짧은 인사 → DIRECT_REPLY
    if len(norm) <= 12 and any(low.startswith(h) or low == h for h in _GREETING_HINTS):
        return {**base, "intent": "GREETING", "riskLevel": "ALLOW", "routeAction": "DIRECT_REPLY",
                "confidence": 0.7, "reason": "짧은 인사로 보입니다.",
                "directReply": "안녕하세요! 무엇을 도와드릴까요?"}

    # 4) 명확한 퀴즈/문제 생성 요청 → QUIZ_PIPELINE
    if any(h in low for h in _QUIZ_HINTS):
        return {**base, "intent": "QUIZ_GENERATION", "riskLevel": "ALLOW", "routeAction": "QUIZ_PIPELINE",
                "confidence": 0.6, "reason": "문제/퀴즈 생성 요청으로 보입니다."}

    # 5) 명확한 요약 요청 → SUMMARY_PIPELINE
    if any(h in low for h in _SUMMARY_HINTS):
        return {**base, "intent": "SUMMARY_REQUEST", "riskLevel": "ALLOW", "routeAction": "SUMMARY_PIPELINE",
                "confidence": 0.6, "reason": "요약 요청으로 보입니다."}

    # 5b) 명확한 로드맵 요청 → ROADMAP_PIPELINE
    if any(h in low for h in _ROADMAP_HINTS):
        return {**base, "intent": "ROADMAP_REQUEST", "riskLevel": "ALLOW", "routeAction": "ROADMAP_PIPELINE",
                "confidence": 0.55, "reason": "학습 로드맵 요청으로 보입니다."}

    # 6) 그 외 → surface별 기본 에이전트
    if surface == "archive_chat":
        route = "MATERIAL_QA_AGENT" if ctx.hasMaterialContext else "ARCHIVE_AI_AGENT"
        intent = "MATERIAL_QA" if ctx.hasMaterialContext else "LEARNING_QUESTION"
    else:
        route = SURFACE_DEFAULT_ROUTE.get(surface, "LEARNING_MATE_AGENT")
        intent = "LEARNING_QUESTION"

    return {**base, "intent": intent, "riskLevel": "ALLOW", "routeAction": route,
            "confidence": 0.45, "reason": f"기본 라우팅({surface})으로 처리합니다."}


# ── 엔드포인트 ────────────────────────────────────────────────────────────────
@router.post("/route", response_model=IntentRouteResponse, summary="LLM 기반 의도/위험도/라우팅 판정")
async def route_intent(req: IntentRouteRequest) -> IntentRouteResponse:
    ctx = req.context or IntentContext()
    surface = _norm_surface(req.surface)
    norm_text = (req.text or "").strip()

    # LLM 비활성 또는 빈 입력은 곧바로 fallback (LLM 호출 낭비 방지).
    if not INTENT_ROUTER_ENABLED or not norm_text:
        fb = _fallback_decision(req.text, surface, ctx)
        return _finalize(fb, ctx, fallback_used=True)

    decision: Optional[Dict[str, Any]] = None
    try:
        decision = await asyncio.wait_for(
            asyncio.to_thread(_classify_with_llm, req, ctx),
            timeout=INTENT_ROUTER_TIMEOUT_SEC + 2,  # ask_ollama 자체 timeout 바깥 안전벽
        )
    except asyncio.TimeoutError:
        logger.warning("intent/route LLM timeout(%ss) → fallback", INTENT_ROUTER_TIMEOUT_SEC)
    except Exception as e:
        logger.warning("intent/route LLM 예외 → fallback: %s", e)

    if decision is None:
        fb = _fallback_decision(req.text, surface, ctx)
        result = _finalize({**fb, "normalizedText": norm_text}, ctx, fallback_used=True)
        logger.info("intent/route surface=%s intent=%s route=%s risk=%s fallback=True",
                    surface, result.intent, result.routeAction, result.riskLevel)
        return result

    decision["normalizedText"] = norm_text
    result = _finalize(decision, ctx, fallback_used=False)
    logger.info("intent/route surface=%s intent=%s route=%s risk=%s conf=%.2f fallback=False",
                surface, result.intent, result.routeAction, result.riskLevel, result.confidence)
    return result
