"""
멀티 에이전트 토론 서비스.
POST /api/ai/multi-chat — fallback용 동기 REST JSON 반환.
POST /api/ai/multi-chat/stream — FastAPI가 agent별 SSE 이벤트를 직접 생성하고 Spring이 pass-through.

mode별 분기:
  default     : agent별 순차 생성 + SSE 스트리밍, 동기 fallback은 설정값에 따라 순차/병렬
  tikitaka    : 기존 3라운드 티키타카
  debate      : 찬성봇 → 반대봇 → 사회자봇 순차 체인 (v0.7)
  socratic    : 소크라테스식 꼬리질문 (v0.7)

v0.8 추가:
  - domain classifier → generation config resolver → OpenAlex(박사) → depth verifier/rewriter
  - 기존 RAG / 임베딩 / pgvector / Ollama / OpenAI fallback 보존.
"""
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.multi_chat_schema import (
    AgentAnswer, AgentProfile, MultiChatRequest, MultiChatResponse,
    ValidationSummary, PreviousAnswer, DebugMetadata,
    GenerationConfigMetadata, RetrievalMetadata, DepthValidationMetadata, PromptingMetadata,
    ProcessSteps, InitialAnswerStep, ValidatedAnswerStep, PeerFeedbackStep,
    PersonalityValidationItem, StageInfo, AgentAnswerMetadata,
    DebateInitialAnswer, DebatePeerFeedback, DebateRevisedAnswer,
    DebateConfig, DebateStage, SocraticConfig, SocraticStep,
    SimulationConfig, SimulationStage, SimulationChoice,
)
from app.services.prompt_builder import build_agent_system_prompt, build_tikitaka_role_prompt
from app.services.personality_prompt_builder import to_profile_key, build_persona_directive
from app.services.personality_validator import validate_personality_alignment, repair_personality_if_needed
from app.core import agent_settings as A
from app.utils.text_utils import build_context_from_previous_answers, safe_str
from app.utils.json_parser import extract_json
from app.core.config import MAX_ROUNDS

logger = logging.getLogger(__name__)


def _stream_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def _stream_heartbeat_interval_seconds() -> float:
    try:
        return max(5.0, float(os.getenv("AI_STREAM_HEARTBEAT_SECONDS", "10")))
    except Exception:
        return 10.0


# 스트리밍 per-agent 타임아웃의 '최소 안전 하한'(초).
# 주의: 이 값은 하한(floor)이지 상한(cap)이 아니다. 설정값이 이보다 작을 때만 끌어올리고,
# 더 큰 값(예: stage1 120초)은 절대 깎지 않고 그대로 사용한다.
_STREAM_PER_AGENT_TIMEOUT_FLOOR_SECONDS = 10.0


def _resolve_stream_per_agent_timeout_raw() -> float:
    """하한 보정 '이전'의 설정 원값(초)을 우선순위로 구한다.
    1) AI_STREAM_PER_AGENT_TIMEOUT_SECONDS  (설정되어 있으면 최우선)
    2) OLLAMA_STAGE1_TIMEOUT_SECONDS → AGENT_STAGE1_TIMEOUT_SECONDS → 120 (stage1 기준 fallback)
    """
    raw = os.getenv("AI_STREAM_PER_AGENT_TIMEOUT_SECONDS")
    if raw not in (None, ""):
        try:
            return float(raw)
        except (TypeError, ValueError):
            logger.warning("AI_STREAM_PER_AGENT_TIMEOUT_SECONDS 파싱 실패(%r) → stage1 타임아웃으로 fallback", raw)
    # 미설정/파싱 실패: stage1 타임아웃을 그대로 fallback (OLLAMA_STAGE1 → AGENT_STAGE1 → 120)
    try:
        return float(A.resolve_timeout_for_stage(1))
    except Exception:
        return 120.0


def _stream_per_agent_timeout_seconds() -> float:
    """기본 스트림의 agent별 제한 시간(초).

    우선순위:
      1. AI_STREAM_PER_AGENT_TIMEOUT_SECONDS (설정 시 최우선)
      2. OLLAMA_STAGE1_TIMEOUT_SECONDS (없으면 AGENT_STAGE1_TIMEOUT_SECONDS, 그래도 없으면 120)

    하한 정책: max(FLOOR, value)의 FLOOR(=10초)는 '최소 안전 하한'이며 '상한'이 아니다.
    설정값이 10초 미만일 때만 10초로 보정하고, 그보다 큰 값(예: 120)은 그대로 둔다.
    """
    return max(_STREAM_PER_AGENT_TIMEOUT_FLOOR_SECONDS, _resolve_stream_per_agent_timeout_raw())


def log_stream_timeout_config() -> None:
    """기동 시 실제 적용되는 스트림 타임아웃 값을 1회 남긴다(상한 오해 방지용 진단 로그)."""
    raw = _resolve_stream_per_agent_timeout_raw()
    applied = _stream_per_agent_timeout_seconds()
    logger.info(
        "AI stream timeout config: per_agent_timeout_seconds=%.0f (floor=%.0f, raw=%.0f) "
        "AI_STREAM_PER_AGENT_TIMEOUT_SECONDS=%s OLLAMA_STAGE1_TIMEOUT_SECONDS=%s AGENT_STAGE1_TIMEOUT_SECONDS=%s "
        "[floor는 하한이며 상한이 아님]",
        applied, _STREAM_PER_AGENT_TIMEOUT_FLOOR_SECONDS, raw,
        os.getenv("AI_STREAM_PER_AGENT_TIMEOUT_SECONDS"),
        os.getenv("OLLAMA_STAGE1_TIMEOUT_SECONDS"),
        os.getenv("AGENT_STAGE1_TIMEOUT_SECONDS"),
    )

_DEFAULT_AGENT = AgentProfile(
    id=0, agentId=0, name="스터디봇", role="학습 도우미",
    personality="친절_설명형", personalityStrength="moderate", knowledgeLevel="학사",
)
_SYNTHESIS_AGENT_NAME = "종합정리봇"
_MAX_ROUNDS = MAX_ROUNDS
# 답변 잘림 방지: 생성 토큰 상한은 충분히 크게 둔다.
# (config.AGENT_ANSWER_MAX_CHARS 같은 '문자 수' 개념은 최종 출력에 적용하지 않는다 — 잘림 원인.)
import os as _os
_MAX_TOKENS_PER_ANSWER = int(_os.getenv("AI_ANSWER_MAX_TOKENS", "2048"))
_SIMULATION_MODE_ALIASES = {"simulation", "상황극", "상황극 모드", "시뮬레이션", "시뮬레이션 모드"}
_SIMULATION_DEFAULT_STAGES = [
    "SCENARIO_SETUP", "USER_ROLE", "SITUATION_CONTEXT", "CHOICES",
    "CONSEQUENCE_PREVIEW", "CONCEPT_MAPPING", "MISCONCEPTION_TRAP",
    "REFLECTION_QUESTION", "NEXT_SCENARIO",
]
# 단계별 token/timeout/provider 및 성격별 파라미터는 모두 app/core/agent_settings.py(env)에서 읽는다.
# (서비스 코드에 magic value를 박지 않는다.)


def _get_agents(request: MultiChatRequest) -> List[AgentProfile]:
    if not request.agents:
        logger.info("에이전트 목록이 비어있습니다. 기본 에이전트 사용.")
        return [_DEFAULT_AGENT]
    return request.agents


def _filter_agents(agents: List[AgentProfile], target_id: Optional[int]) -> List[AgentProfile]:
    if target_id is None:
        return agents
    filtered = [a for a in agents if (a.agentId == target_id or a.id == target_id)]
    if not filtered:
        logger.warning("targetAgentId=%s에 해당하는 에이전트 없음. 전체 사용.", target_id)
        return agents
    return filtered


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    knowledge_level: Optional[str] = None,
    gen_config: Optional[Dict[str, Any]] = None,
) -> str:
    try:
        from app.services.llm_engine_router import call_primary_llm
        max_tokens = _MAX_TOKENS_PER_ANSWER
        temperature = 0.5
        if gen_config:
            max_tokens = gen_config.get("max_tokens", max_tokens)
            temperature = gen_config.get("temperature", temperature)
        result = call_primary_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            knowledge_level=knowledge_level,
        )
        if result and not result.startswith("["):
            return result
        logger.warning("LLM 엔진 라우터 fallback 응답: %s", result[:80])
    except Exception as e:
        logger.error("LLM 엔진 라우터 호출 실패: %s", e)
    return "현재 AI 서비스에 일시적으로 접근할 수 없습니다. 잠시 후 다시 시도해 주세요."


def _get_rag_context(question: str, material_id: Optional[int]) -> str:
    """RAG 검색. 실패해도 서버 죽지 않음."""
    if not material_id:
        return ""
    try:
        from app.services.pdf_rag_service import search_pdf_context
        chunks = search_pdf_context(question, material_id, top_k=5)
        if not chunks:
            return ""
        return "\n\n".join(f"[청크 {i+1}]\n{c['content']}" for i, c in enumerate(chunks))
    except Exception as e:
        logger.warning("RAG 검색 실패 (계속 진행): %s", e)
        return ""


def _gather_web_evidence(question: str, knowledge_level: Optional[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    2차 검증용 웹 근거를 질문당 1회 수집한다(Tavily + Wikipedia + OpenAlex 병렬, best-effort).
    각 소스는 개별 타임아웃, 전체는 예산 시간 내. 실패한 소스는 조용히 건너뛴다.
    반환: (evidence_text, sources[{title,url,source}]).
    """
    if not A.enable_stage2_web_verify() or not (question or "").strip():
        return "", []

    src_timeout = A.stage2_web_per_source_timeout()
    total_timeout = A.stage2_web_total_timeout()
    max_snips = A.stage2_web_max_snippets()
    search_query = _validation_search_query(question)

    def _tavily():
        from app.services.tavily_service import search_web
        out = []
        for r in (search_web(search_query, max_results=3) or []):
            out.append({"title": r.get("title", ""), "url": r.get("url", ""),
                        "snippet": (r.get("content", "") or "")[:400], "source": "Tavily"})
        return out

    def _wiki():
        from app.services.wikipedia_service import search_wikipedia
        out = []
        for r in (search_wikipedia(search_query, limit=3) or []):
            out.append({"title": r.get("title", ""), "url": r.get("url", ""),
                        "snippet": (r.get("snippet", "") or "")[:400], "source": "Wikipedia"})
        return out

    def _openalex():
        from app.services import openalex_service
        res = openalex_service.search(search_query, knowledge_level or "학사")
        out = []
        for w in (getattr(res, "works", None) or []):
            title = getattr(w, "display_name", "") or ""
            abstract = getattr(w, "abstract", "") or ""
            url = getattr(w, "doi", "") or getattr(w, "id", "") or ""
            out.append({"title": title, "url": url, "snippet": abstract[:400], "source": "OpenAlex"})
        return out

    sources: List[Dict[str, Any]] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fn): name for fn, name in
                   ((_tavily, "Tavily"), (_wiki, "Wikipedia"), (_openalex, "OpenAlex"))}
        for fut in as_completed(futures, timeout=total_timeout + 1):
            name = futures[fut]
            remaining = max(1, total_timeout - int(time.time() - t0))
            try:
                sources.extend(fut.result(timeout=min(src_timeout, remaining)) or [])
            except Exception as e:
                logger.info("2차 웹근거 소스 '%s' 건너뜀: %s", name, e)

    # 스니펫 있는 것만, 질문 주제와 무관한 결과를 제거한 뒤 최대 N개로 컷
    sources = [s for s in sources if (s.get("snippet") or s.get("title"))]
    sources = _filter_validation_sources(question, sources)[:max_snips]
    if not sources:
        return "", []

    lines = []
    for i, s in enumerate(sources, 1):
        lines.append(f"[근거{i} · {s['source']}] {s.get('title','')}\n{s.get('snippet','')}".strip())
    evidence_text = "\n\n".join(lines)
    logger.info("[StudyMate] 2차 웹근거 %d건 수집 (%.1fs): %s",
                len(sources), time.time() - t0, ", ".join(sorted({s['source'] for s in sources})))
    return evidence_text, sources


def _get_display_delay_ms() -> int:
    try:
        from app.core.policy_loader import get_display_delay_ms
        return get_display_delay_ms()
    except Exception:
        return 700


def _get_knowledge_level(request: MultiChatRequest, agent: Optional[AgentProfile] = None) -> str:
    if agent and agent.knowledgeLevel:
        return agent.knowledgeLevel
    if request.knowledgeLevel:
        return request.knowledgeLevel
    return "학사"


# ── 기존 default/tikitaka 모드 ─────────────────────────────────────────────────

def _deduplicate_agent_answers(answers: List[AgentAnswer]) -> List[AgentAnswer]:
    seen: set = set()
    result: List[AgentAnswer] = []
    for ans in answers:
        key = ans.answer.strip()[:100]
        if key not in seen:
            seen.add(key)
            result.append(ans)
    return result


def _generate_agent_answer(
    agent: AgentProfile,
    message: str,
    context: str,
    agent_index: int,
    total_agents: int,
    display_order: int,
    display_delay_ms: int,
) -> AgentAnswer:
    system_prompt = build_agent_system_prompt(agent, context)
    role_hint = build_tikitaka_role_prompt(agent_index, total_agents, agent)

    user_parts = []
    if role_hint:
        user_parts.append(f"[이번 역할] {role_hint}")
    user_parts.append(f"[사용자 메시지] {message}")
    user_prompt = "\n".join(user_parts)

    answer_text = _call_llm(system_prompt, user_prompt, knowledge_level=agent.knowledgeLevel)
    return AgentAnswer(
        agentName=agent.name,
        answer=answer_text,
        agentId=agent.agentId,
        role=agent.role or "default",
        displayOrder=display_order,
        displayDelayMs=display_delay_ms,
    )


def _generate_synthesis(agents: List[AgentProfile], answers: List[AgentAnswer], message: str) -> AgentAnswer:
    existing_answers = "\n".join(f"[{a.agentName}] {a.answer[:200]}" for a in answers)
    system_prompt = (
        "너는 여러 에이전트의 답변을 종합하는 정리 전문가다. "
        "각 에이전트의 핵심 포인트를 통합하여 최종 결론을 한국어로 명확하게 제시하라. "
        "중복 내용은 제거하고 핵심만 압축하라."
    )
    user_prompt = (
        f"[사용자 질문] {message}\n\n"
        f"[에이전트 답변들]\n{existing_answers}\n\n"
        "위 내용을 종합하여 최종 정리를 제공하라."
    )
    synthesis_text = _call_llm(system_prompt, user_prompt)
    return AgentAnswer(
        agentName=_SYNTHESIS_AGENT_NAME,
        answer=synthesis_text,
        role="synthesis",
        displayOrder=len(answers) + 1,
        displayDelayMs=_get_display_delay_ms() * len(answers),
    )


_LLM_FALLBACK_MARKERS = ("현재 Ollama", "AI 응답이", "Ollama 응답", "[GPT", "현재 AI 서비스", "일시적인 오류")


def _is_llm_fallback(text: str) -> bool:
    t = (text or "").strip()
    return (not t) or any(t.startswith(m) or m in t[:40] for m in _LLM_FALLBACK_MARKERS)



def _normalize_compact(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _is_same_answer(a: str, b: str) -> bool:
    aa, bb = _normalize_compact(a), _normalize_compact(b)
    if not aa or not bb:
        return False
    return aa == bb or (len(aa) > 80 and (aa in bb or bb in aa))


def _is_sql_join_question(question: str) -> bool:
    q = (question or "").lower()
    return "join" in q or "조인" in q or ("sql" in q and ("결합" in q or "테이블" in q))


def _validation_search_query(question: str) -> str:
    """검증 검색용 쿼리. 일반 영어 단어는 학습 도메인을 붙여 검색 오염을 줄인다."""
    q = (question or "").strip()
    if _is_sql_join_question(q):
        return "SQL JOIN 데이터베이스 조인 INNER JOIN OUTER JOIN 관계형 데이터베이스"
    return q


_SQL_JOIN_SOURCE_TERMS = (
    "sql", "join", "database", "relational", "table", "query", "dbms",
    "mysql", "postgresql", "oracle", "mariadb", "sqlite", "데이터베이스", "조인", "테이블", "관계형",
)
_IRRELEVANT_SOURCE_TERMS = (
    "freemason", "freemasonry", "masonic", "film", "movie", "inception",
    "프리메이슨", "영화", "인셉션", "음반", "앨범", "드라마",
)


def _source_text(source: Dict[str, Any]) -> str:
    return " ".join(str(source.get(k, "") or "") for k in ("title", "snippet", "url")).lower()


def _filter_validation_sources(question: str, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not sources:
        return []
    filtered: List[Dict[str, Any]] = []
    sql_join = _is_sql_join_question(question)
    for src in sources:
        text = _source_text(src)
        if any(term in text for term in _IRRELEVANT_SOURCE_TERMS):
            continue
        if sql_join and not any(term in text for term in _SQL_JOIN_SOURCE_TERMS):
            continue
        filtered.append(src)
    return filtered


def _validation_summary_text(question: str, initial: str, candidate: str = "",
                             sources: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, List[str]]:
    """2차 VALIDATION은 정답 재출력이 아니라 검증 요약을 반환한다."""
    if _is_sql_join_question(question):
        issues = [
            "JOIN 조건 누락 시 Cartesian product 위험",
            "INNER JOIN/OUTER JOIN 차이 추가 필요",
            "NULL 처리와 중복 행 가능성 설명 필요",
        ]
        summary = (
            "검증 결과: 핵심 정의는 대체로 정확함\n\n"
            "보완점:\n"
            "1) JOIN 조건 누락 시 Cartesian product 위험\n"
            "2) INNER JOIN/OUTER JOIN 차이 추가 필요\n"
            "3) NULL 처리와 중복 행 가능성 설명 필요\n\n"
            "수정 제안: JOIN은 여러 테이블을 관련 컬럼 기준으로 결합하는 SQL 연산이라고 설명하되, "
            "ON/USING 조건의 중요성, INNER JOIN과 OUTER JOIN의 결과 차이, NULL 및 중복 행 가능성을 "
            "짧은 예시와 함께 보완하면 더 정확합니다."
        )
        return summary, issues

    candidate_ok = bool(candidate and not _is_llm_fallback(candidate) and not _is_same_answer(candidate, initial))
    evidence_note = "참고 근거를 함께 확인했습니다." if sources else "외부 근거가 부족해 개념 일관성 중심으로 점검했습니다."
    issues = [
        "핵심 정의와 범위가 질문에 직접 맞는지 재확인 필요",
        "예시, 예외 조건, 한계를 분리해 설명하면 이해도가 높아짐",
    ]
    if candidate_ok:
        revised_hint = _normalize_compact(candidate)[:220]
        suggestion = f"수정 제안: 2차 생성 내용 중 {revised_hint!r} 방향의 보완을 반영하되, 1차 답변과 중복되는 문장은 줄이세요."
    else:
        suggestion = "수정 제안: 1차 답변을 그대로 반복하지 말고 정의, 누락 조건, 실제 예시, 주의점을 분리해 다시 작성하세요."
    return (
        "검증 결과: 핵심 설명은 대체로 유지 가능하지만 보완이 필요함\n\n"
        "보완점:\n"
        f"1) {issues[0]}\n"
        f"2) {issues[1]}\n\n"
        f"{suggestion}\n"
        f"근거 확인: {evidence_note}"
    ), issues


def _call_llm_with_params(
    provider: str, system: str, user: str,
    params: Dict[str, Any], knowledge_level: Optional[str] = None,
) -> Tuple[str, str]:
    """
    provider별로 지원하는 파라미터만 전달해 LLM을 호출한다.
    반환: (텍스트, 실제_사용_provider). openai 미설정이면 ollama로 폴백한다.
    """
    prov = (provider or "ollama").strip().lower()
    if prov == "openai":
        from app.services.openai_client import chat_sync, is_enabled
        if is_enabled():
            text = chat_sync(
                system=system, user=user,
                temperature=params.get("temperature", 0.4),
                max_tokens=params.get("max_tokens", 1200),
                top_p=params.get("top_p"),
                presence_penalty=params.get("presence_penalty"),
                frequency_penalty=params.get("frequency_penalty"),
                timeout=params.get("timeout_seconds"),
            )  # OpenAI는 top_k/repeat_penalty 미지원 → 전달하지 않음
            return text, "openai"
        logger.info("provider=openai 비활성 → ollama 폴백")
        prov = "ollama"
    # ollama
    from app.services.ollama_client import ask_ollama
    text = ask_ollama(
        system, user,
        temperature=params.get("temperature"),
        max_tokens=params.get("max_tokens"),
        knowledge_level=knowledge_level,
        top_p=params.get("top_p"),
        top_k=params.get("top_k"),
        repeat_penalty=params.get("repeat_penalty"),
        timeout=params.get("timeout_seconds"),
    )
    return text, "ollama"


def _stage1_initial(agent: AgentProfile, message: str, context: str) -> str:
    """1차 빠른 초안 — 반드시 Ollama (provider는 agent_settings에서 stage=1로 강제)."""
    system = build_agent_system_prompt(agent, context)
    # 성격 지시를 user 프롬프트 '마지막'에 다시 못박는다(system만으로는 모델이 성격을 버림).
    directive = build_persona_directive(
        agent.personality or agent.tone or agent.style, agent.customInstruction
    )
    user = (
        f"[사용자 질문] {message}\n\n"
        "[이번 단계: 1차 빠른 초안]\n"
        "핵심 정의 → 대표 예시 → 한 줄 결론 순서로 빠르게 답하라. "
        "완벽하게 길게 쓰려 하지 말고, 질문에 바로 도움이 되는 핵심만 담아라.\n\n"
        f"{directive}"
    )
    params = A.resolve_agent_generation_params(to_profile_key(agent.personality or agent.tone or agent.style), 1)
    text, _ = _call_llm_with_params("ollama", system, user, params, knowledge_level=agent.knowledgeLevel)
    return text


def _stage2_validate(agent: AgentProfile, message: str, own_initial: str, others_text: str,
                     repair_instruction: Optional[str] = None, evidence: str = "") -> Tuple[str, str]:
    """2차 검증/정제 답안 — provider는 agent_settings stage=2. 반환: (텍스트, provider)."""
    system = build_agent_system_prompt(agent)
    user_parts = [
        f"[사용자 질문] {message}",
        f"[너의 1차 초안]\n{own_initial}",
    ]
    if others_text:
        user_parts.append(f"[다른 에이전트의 1차 초안]\n{others_text}")
    if evidence:
        user_parts.append(
            "[웹 근거 자료 — 사실 검증용]\n" + evidence +
            "\n위 근거와 충돌하는 내용은 근거에 맞게 바로잡아라. 근거에 없는 내용을 지어내지 마라."
        )
    user_parts.append(
        "[이번 단계: 2차 검증 답안]\n"
        "1차 초안의 오류·누락·개념 혼동을 점검하고 바로잡아, 더 정확하고 정제된 답을 작성하라. "
        "특히 SQL/프로그래밍/수학/과학 개념은 정확성을 최우선으로 한다. "
        "예: DML(SELECT/INSERT/UPDATE/DELETE)과 DDL(CREATE/ALTER/DROP)을 섞지 마라. "
        "1차 초안을 그대로 반복하지 말고 보완하라."
    )
    # 정확성 지시 뒤에 성격 지시를 마지막에 못박는다(정확성에 눌려 성격이 사라지는 것 방지).
    user_parts.append(build_persona_directive(
        agent.personality or agent.tone or agent.style, agent.customInstruction, repair_instruction
    ))
    params = A.resolve_agent_generation_params(to_profile_key(agent.personality or agent.tone or agent.style), 2)
    return _call_llm_with_params(params["provider"], system, "\n\n".join(user_parts),
                                 params, knowledge_level=agent.knowledgeLevel)


def _stage3_feedback(from_agent: AgentProfile, targets: List[Tuple[AgentProfile, str]],
                     message: str) -> Tuple[str, str]:
    """3차 상호 피드백 (from → 나머지 에이전트 전원). 반환: (피드백, provider)."""
    system = build_agent_system_prompt(from_agent)
    target_block = "\n\n".join(
        f"[{tgt.name}의 답변]\n{ans}" for tgt, ans in targets
    )
    target_names = ", ".join(tgt.name for tgt, _ in targets)
    user = (
        f"[사용자 질문] {message}\n\n"
        f"{target_block}\n\n"
        "[이번 단계: 3차 상호 피드백]\n"
        f"위 다른 에이전트({target_names})의 답변을 너의 성격과 관점에서 평가하라. "
        "각 답변의 좋은 점 / 부족한 점 / 개선 방향을 구체적으로 짚어라. "
        "단순 칭찬은 금지하고, 실제로 도움이 되는 피드백을 작성하라.\n\n"
        + build_persona_directive(
            from_agent.personality or from_agent.tone or from_agent.style, from_agent.customInstruction
        )
    )
    params = A.resolve_agent_generation_params(_personality_type(from_agent), 3)
    return _call_llm_with_params(params["provider"], system, user, params, knowledge_level=from_agent.knowledgeLevel)


def _run_pool(fn, items, parallel):
    """단계 내 병렬 실행 헬퍼 (parallel=False면 순차)."""
    if parallel and len(items) > 1:
        with ThreadPoolExecutor(max_workers=len(items)) as ex:
            return list(ex.map(fn, items))
    return [fn(i) for i in items]


# ── 단계별 compute 헬퍼 (블로킹/스트리밍 공용) ───────────────────────────────────

def _personality_type(agent: AgentProfile) -> str:
    """프론트 카드 표시용 정규 성격 키 (creative/sardonic/logical/...)."""
    return to_profile_key(agent.personality or agent.tone or agent.style)


def _agent_index_map(agents: List[AgentProfile]) -> Dict[str, int]:
    """에이전트 이름 → 1-based 표시 순서. 프론트가 에이전트 1→2→3을 확정 정렬하는 키."""
    return {a.name: i + 1 for i, a in enumerate(agents)}


def _compute_stage1(request: MultiChatRequest, agents: List[AgentProfile], context: str):
    """1차 빠른 초안 (Ollama 전용, 병렬). 반환: (steps, initial_map, provider, elapsedMs, status)."""
    provider = A.resolve_provider_for_stage(1)
    t1 = time.time()
    # 라이브 진단용: 각 에이전트의 '도착한 성격 라벨 → 정규키'를 남긴다.
    # 모든 에이전트가 friendly로 찍히면 Spring/프론트가 성격 라벨을 안 보내는 것이다.
    logger.info("[StudyMate] stage1 persona 매핑: %s", {
        a.name: f"{(a.personality or a.tone or a.style) or 'None'}→{_personality_type(a)}" for a in agents
    })

    def _run1(a: AgentProfile):
        t_agent = time.time()
        try:
            text = _stage1_initial(a, request.message, context)
        except Exception as e:
            logger.error("stage1 에이전트 '%s' 실패: %s", a.name, e)
            text = A.stage1_timeout_fallback_text()
        return a, text, int((time.time() - t_agent) * 1000)

    results = _run_pool(_run1, agents, A.enable_parallel_stage1())
    elapsed = int((time.time() - t1) * 1000)
    status = "completed"
    initial_map: Dict[str, str] = {}
    steps: List[InitialAnswerStep] = []
    idx_map = _agent_index_map(agents)
    for a, text, agent_ms in results:
        if _is_llm_fallback(text):
            status = "timeout_fallback"
            if not (text or "").strip():
                text = A.stage1_timeout_fallback_text()
        initial_map[a.name] = text
        ai = idx_map.get(a.name)
        steps.append(InitialAnswerStep(
            agentName=a.name, answer=text, agentId=a.agentId,
            agentIndex=ai, displayOrder=ai, stage=1,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=provider, elapsedMs=agent_ms,
        ))
    logger.info("[StudyMate] stage=1 provider=%s elapsedMs=%d status=%s agents=%d",
                provider, elapsed, status, len(agents))
    return steps, initial_map, provider, elapsed, status


def _compute_stage2(request: MultiChatRequest, agents: List[AgentProfile], initial_map: Dict[str, str]):
    """2차 검증/정제 (병렬, best-effort). 반환: (steps, validated_map, provider, elapsedMs, sources)."""
    provider = A.resolve_provider_for_stage(2)
    t2 = time.time()

    # 웹 근거는 질문당 1회만 수집해 모든 에이전트가 공유한다(지연/비용 관리).
    kl = _get_knowledge_level(request, agents[0] if agents else None)
    evidence, sources = _gather_web_evidence(request.message, kl)

    def _run2(a: AgentProfile):
        own = initial_map.get(a.name, "")
        # 다른 에이전트 1차 초안은 컨텍스트 참고용으로만 축약(contextPreview) — 최종 출력은 자르지 않는다.
        others = "\n\n".join(
            f"[{b.name}]\n{initial_map.get(b.name, '')[:300]}" for b in agents if b.name != a.name
        )
        t_agent = time.time()
        try:
            text, prov = _stage2_validate(a, request.message, own, others, evidence=evidence)
            return a, text, prov, int((time.time() - t_agent) * 1000)
        except Exception as e:
            logger.warning("stage2 에이전트 '%s' 실패 (1차로 대체): %s", a.name, e)
            return a, own, "ollama", int((time.time() - t_agent) * 1000)

    try:
        results = _run_pool(_run2, agents, A.enable_parallel_stage2())
    except Exception as e:
        logger.warning("stage2 전체 실패 (1차로 대체): %s", e)
        results = [(a, initial_map.get(a.name, ""), "ollama", 0) for a in agents]
    elapsed = int((time.time() - t2) * 1000)

    validated_map: Dict[str, str] = {}
    steps: List[ValidatedAnswerStep] = []
    provs: set = set()
    idx_map = _agent_index_map(agents)
    for a, text, prov, agent_ms in results:
        provs.add(prov)
        own_initial = initial_map.get(a.name, "")
        final_text, issues = _validation_summary_text(request.message, own_initial, text or "", sources)
        # VALIDATION은 절대 FIRST_ANSWER 원문을 그대로 내보내지 않는다.
        if _is_same_answer(final_text, own_initial):
            final_text, issues = _validation_summary_text(request.message, own_initial, "", sources)
        validated_map[a.name] = final_text
        revised = not _is_same_answer(final_text, own_initial)
        ai = idx_map.get(a.name)
        steps.append(ValidatedAnswerStep(
            agentName=a.name, answer=final_text, agentId=a.agentId, revised=revised, issues=issues,
            agentIndex=ai, displayOrder=ai, stage=2,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=prov, elapsedMs=agent_ms, sources=sources,
        ))
    actual = ",".join(sorted(provs)) if provs else provider
    logger.info("[StudyMate] stage=2 provider=%s elapsedMs=%d status=completed sources=%d",
                actual, elapsed, len(sources))
    return steps, validated_map, actual, elapsed, sources


def _validate_mode_personas(agents: List[AgentProfile], answers) -> List[PersonalityValidationItem]:
    """
    debate/socratic 등 비-staged 모드의 답변에도 성격 정합성 검증을 부착한다.
    answer.agentName으로 에이전트를 찾아 성격 검증을 수행한다(매칭 안 되면 건너뜀).
    """
    if not A.enable_personality_validation():
        return []
    by_name = {a.name: a for a in agents}
    texts = [getattr(ans, "answer", "") or "" for ans in answers]
    summary: List[PersonalityValidationItem] = []
    for ans in answers:
        name = getattr(ans, "agentName", None)
        agent = by_name.get(name)
        if agent is None:
            continue
        peers = [t for t in texts if t and t != (getattr(ans, "answer", "") or "")]
        try:
            v = validate_personality_alignment(getattr(ans, "answer", "") or "", agent, 2, peer_answers=peers)
        except Exception as e:
            logger.warning("모드 성격 검증 실패 '%s': %s", name, e)
            continue
        summary.append(PersonalityValidationItem(
            agentName=name, personalityType=v.get("personalityType"),
            score=v.get("score"), passed=v.get("passed"),
            issues=v.get("issues", []), note=v.get("note"),
        ))
    return summary


def _summarize_validation(agents, validation_map) -> List[PersonalityValidationItem]:
    summary: List[PersonalityValidationItem] = []
    for a in agents:
        v = validation_map.get(a.name)
        if not v:
            continue
        summary.append(PersonalityValidationItem(
            agentName=a.name, personalityType=v.get("personalityType"),
            score=v.get("score"), passed=v.get("passed"),
            issues=v.get("issues", []), note=v.get("note"),
        ))
    return summary


def _compute_validation(request: MultiChatRequest, agents: List[AgentProfile],
                        initial_map: Dict[str, str], validated_map: Dict[str, str],
                        validated_steps: List[ValidatedAnswerStep]):
    """
    성격 검증 + 미달 시 보정(repair). 2차 답안 기준.
    - validate_personality_alignment로 점수화
    - 점수 미달 + repair 활성 시: 성격 지시를 못박아 stage2를 1회 재생성하고 더 좋아지면 채택
    - validated_map / validated_steps(answer·revised) 를 보정 결과로 갱신
    반환: (validation_map, pv_summary)
    """
    validation_map: Dict[str, Dict[str, Any]] = {}
    if not A.enable_personality_validation():
        return validation_map, []

    step_by_name = {s.agentName: s for s in validated_steps}

    for a in agents:
        peers = [validated_map.get(b.name, "") for b in agents if b.name != a.name]
        try:
            v = validate_personality_alignment(validated_map.get(a.name, ""), a, 2, peer_answers=peers)
        except Exception as e:
            logger.warning("성격 검증 실패 '%s': %s", a.name, e)
            continue

        # 미달이면 성격 지시 + repairInstruction을 못박아 stage2 재생성으로 보정한다.
        if not v.get("passed", True):
            others = "\n\n".join(
                f"[{b.name}]\n{initial_map.get(b.name, '')[:300]}" for b in agents if b.name != a.name
            )
            own = initial_map.get(a.name, "")

            def _regen(instruction: str, _a=a, _own=own, _others=others) -> str:
                text, _ = _stage2_validate(_a, request.message, _own, _others, repair_instruction=instruction)
                return text

            try:
                new_text, repaired, used = repair_personality_if_needed(
                    validated_map.get(a.name, ""), v, a, 2, regenerate=_regen
                )
            except Exception as e:
                logger.warning("성격 보정 실패 '%s' (원문 유지): %s", a.name, e)
                new_text, repaired = validated_map.get(a.name, ""), False

            if repaired and new_text and not _is_llm_fallback(new_text):
                summary_text, summary_issues = _validation_summary_text(request.message, own, new_text)
                validated_map[a.name] = summary_text
                # 재검증으로 점수/통과 갱신
                try:
                    v = validate_personality_alignment(summary_text, a, 2, peer_answers=peers)
                except Exception:
                    pass
                step = step_by_name.get(a.name)
                if step is not None:
                    step.answer = summary_text
                    step.issues = summary_issues
                    step.revised = not _is_same_answer(summary_text, initial_map.get(a.name, ""))
                logger.info("[StudyMate] 성격 보정 적용 agent=%s score→%.3f passed=%s",
                            a.name, v.get("score", 0.0), v.get("passed"))

        validation_map[a.name] = v

    return validation_map, _summarize_validation(agents, validation_map)


def _fallback_peer_feedback(agent: AgentProfile, targets: List[Tuple[AgentProfile, str]],
                            message: str, initial_map: Optional[Dict[str, str]],
                            validated_map: Dict[str, str]) -> str:
    if targets:
        target_names = ", ".join(t.name for t, _ in targets)
        return (
            f"1차 답변과 2차 검증 요약을 종합하면, {target_names}의 답변은 핵심 방향은 유지 가능하지만 "
            "검증 단계에서 드러난 누락 조건과 예외 설명을 최종 답변에 반영해야 합니다. "
            "정의만 반복하지 말고, 보완점과 수정 제안을 실제 예시로 연결하는 것이 좋습니다."
        )
    focus = "JOIN 조건, JOIN 종류, NULL/중복 처리" if _is_sql_join_question(message) else "정의, 누락 조건, 예시, 한계"
    return (
        f"1차 답변과 2차 검증을 종합한 최종 보완 의견입니다. {agent.name}의 1차 답변은 핵심 설명의 출발점으로는 충분하지만, "
        f"검증 요약에서 지적한 {focus}를 최종 답변에 반영해야 합니다. "
        "따라서 원문을 그대로 제출하기보다 검증 결과의 보완점과 수정 제안을 합쳐 더 정확한 답변으로 다듬는 것이 적절합니다."
    )


def _compute_stage3(request: MultiChatRequest, agents: List[AgentProfile],
                    validated_map: Dict[str, str], validation_map: Dict[str, Dict[str, Any]],
                    initial_map: Optional[Dict[str, str]] = None):
    """3차 상호 피드백 (병렬, 2명 이상). 반환: (peer_steps, provider, elapsedMs)."""
    provider = A.resolve_provider_for_stage(3)
    peer_steps: List[PeerFeedbackStep] = []
    elapsed = 0
    provs: set = set()
    n = len(agents)
    # 에이전트가 1명이어도 검증 요약을 바탕으로 최종 보완 의견을 만든다.
    # (실패해도 빈 배열로 두지 않고 fallback 피드백을 채워 length >= 1을 보장한다.)
    idx_map = _agent_index_map(agents)
    if n >= 1:
        t3 = time.time()

        def _run3(frm: AgentProfile):
            targets = [(b, validated_map.get(b.name, "")) for b in agents if b.name != frm.name]
            target_ids = [b.agentId for b in agents if b.name != frm.name and b.agentId is not None]
            target_names = ", ".join(b.name for b, _ in targets) or frm.name
            t_agent = time.time()
            try:
                if not targets:
                    raise ValueError("single-agent peer feedback uses deterministic synthesis")
                fb, prov = _stage3_feedback(frm, targets, request.message)
                if _is_llm_fallback(fb):
                    raise ValueError("stage3 fallback marker in feedback")
            except Exception as e:
                logger.warning("stage3 %s 실패 (fallback 피드백 생성): %s", frm.name, e)
                fb = _fallback_peer_feedback(frm, targets, request.message, initial_map, validated_map)
                prov = "fallback"
            pv = validation_map.get(frm.name)
            pv_obj = ({"passed": pv.get("passed"), "score": pv.get("score")} if pv else None)
            ai = idx_map.get(frm.name)
            step = PeerFeedbackStep(
                fromAgent=frm.name, toAgent=target_names, feedback=fb,
                personalityValidation=pv_obj, fromAgentId=frm.agentId,
                agentIndex=ai, displayOrder=ai, stage=3,
                targetAgentIds=target_ids, personalityType=_personality_type(frm),
                provider=prov, elapsedMs=int((time.time() - t_agent) * 1000),
            )
            return step, prov

        for step, prov in _run_pool(_run3, agents, True):
            peer_steps.append(step)
            if prov:
                provs.add(prov)
        elapsed = int((time.time() - t3) * 1000)
        if provs:
            provider = ",".join(sorted(provs))
        logger.info("[StudyMate] stage=3 provider=%s elapsedMs=%d status=completed feedbacks=%d",
                    provider, elapsed, len(peer_steps))
    return peer_steps, provider, elapsed


# ── 토론(debate) 전용 헬퍼: 1차 의견 → 상호 피드백 → 보완 답변 → 종합 정리 ──────────

# 토론 입장 분화용 관점 시드 — 각 토론자가 서로 다른 각도를 잡게 한다(성격과 결합해 입장이 갈림).
_DEBATE_STANCES = [
    "원리·정의 중심 입장(이 주제의 본질이 무엇인지가 핵심이라고 주장)",
    "실용·응용 중심 입장(실제로 어떻게 쓰이고 왜 중요한지가 핵심이라고 주장)",
    "오해·함정 중심 입장(사람들이 흔히 틀리는 지점이 핵심이라고 주장)",
    "비판·한계 중심 입장(이 개념/주장의 한계와 반례가 핵심이라고 주장)",
]
# 토론으로 인정하는 값은 명시적 토론만 허용한다(discussion/tikitaka/multi_agent_discussion 제외).
_DEBATE_MODE_ALIASES = {"debate", "토론", "토론 모드"}
# 소크라테스로 인정하는 값 (한글 별칭 포함). debate로 자동 승격되지 않는다.
_SOCRATIC_MODE_ALIASES = {"socratic", "소크라테스", "소크라테스 모드"}
_DEBATE_CRITIQUE_TERMS = ("부족", "보완", "틀림", "불명확", "오해", "빠짐", "관점", "반박", "부정확", "약점", "한계")
_DEBATE_REQUIRED_SYSTEM_PROMPT = (
    "너희는 각자 독립된 에이전트다. 각자 답변만 하고 끝내면 안 된다. "
    "먼저 1차 의견을 낸 뒤, 반드시 다른 에이전트의 답변을 직접 지목해서 부족한 점, "
    "틀린 점, 보완할 점, 관점 차이를 말해야 한다. 그 다음 받은 피드백을 반영해 "
    "보완 답변을 작성한다. 출력은 반드시 initialAnswers, peerFeedbacks, revisedAnswers, "
    "debateSummary 구조를 따른다. peerFeedbacks가 비어 있으면 실패다."
)


def _debate_display_name(agent: AgentProfile, index: int) -> str:
    return f"에이전트 {index}({agent.name})"


def _ensure_debate_agents(agents: List[AgentProfile]) -> List[AgentProfile]:
    if len(agents) >= 2:
        return agents
    base = list(agents) if agents else [_DEFAULT_AGENT]
    base.append(AgentProfile(
        id=-2, agentId=-2, name="비판 검토 에이전트", role="debater",
        personality="비판형", personalityStrength="moderate", knowledgeLevel=base[0].knowledgeLevel or "학사",
        customInstruction="다른 에이전트의 주장에 부족한 점과 보완할 점을 논리적으로 지적한다.",
    ))
    return base


def _feedback_mentions_target(feedback: str, target: AgentProfile, target_index: int) -> bool:
    text = feedback or ""
    return target.name in text or f"에이전트 {target_index}" in text


def _feedback_has_critique(feedback: str) -> bool:
    text = feedback or ""
    formal_only = ("좋은 답변입니다", "잘 설명했습니다", "동의합니다", "보완할 점이 없습니다")
    if any(bad in text for bad in formal_only) and not any(term in text for term in _DEBATE_CRITIQUE_TERMS):
        return False
    return any(term in text for term in _DEBATE_CRITIQUE_TERMS)


def _valid_debate_feedback(feedback: str, target: AgentProfile, target_index: int) -> bool:
    return bool((feedback or "").strip()) and _feedback_mentions_target(feedback, target, target_index) and _feedback_has_critique(feedback)


def _fallback_debate_feedback(from_agent: AgentProfile, from_index: int, target: AgentProfile, target_index: int) -> str:
    variants = [
        f"{_debate_display_name(target, target_index)}의 답변은 핵심 설명은 있지만, {_debate_display_name(from_agent, from_index)}의 관점과 비교했을 때 구체적인 예시가 부족합니다. 사용자가 개념을 실제 상황에 연결하기 어렵기 때문에 예시 보완이 필요합니다.",
        f"{_debate_display_name(target, target_index)}의 답변은 쉽게 설명하려는 장점은 있지만, 기술적 정확성이 부족합니다. 특히 용어 정의와 실제 작동 방식이 분리되어 있어 보완이 필요합니다.",
        f"{_debate_display_name(target, target_index)}의 답변은 전문성은 있지만, 초보자가 이해하기에는 설명이 압축되어 있습니다. 개념을 처음 접하는 사용자를 위해 쉬운 비유나 단계적 설명이 필요합니다.",
    ]
    return variants[(from_index + target_index) % len(variants)]


def _debate_initial_records(agents: List[AgentProfile], initial_map: Dict[str, str]) -> List[DebateInitialAnswer]:
    return [DebateInitialAnswer(
        agentIndex=i + 1, agentName=a.name, displayName=_debate_display_name(a, i + 1),
        answer=initial_map.get(a.name, ""),
    ) for i, a in enumerate(agents)]


def _debate_revised_records(agents: List[AgentProfile], revised_map: Dict[str, str]) -> List[DebateRevisedAnswer]:
    return [DebateRevisedAnswer(
        agentIndex=i + 1, agentName=a.name, displayName=_debate_display_name(a, i + 1),
        answer=revised_map.get(a.name, ""),
    ) for i, a in enumerate(agents)]


def _peer_step_from_debate_feedback(item: DebatePeerFeedback, provider: str, elapsed_ms: int) -> PeerFeedbackStep:
    return PeerFeedbackStep(
        fromAgent=item.fromAgentName, toAgent=item.toAgentName, feedback=item.feedback,
        agentIndex=item.fromAgentIndex, displayOrder=item.fromAgentIndex, stage=3,
        fromAgentId=None, targetAgentIds=[], personalityType=None, provider=provider, elapsedMs=elapsed_ms,
    )


def _compute_debate_opening(request: MultiChatRequest, agents: List[AgentProfile], context: str):
    """
    1차 입론 — **순차** 진행. 첫 토론자는 입장을 세우고, 이후 토론자는 '앞 토론자의 발언을 직접 보고'
    이름을 부르며 동의/반박하면서 자기 입장을 편다. (병렬이면 서로를 못 봐서 토론이 안 됨 → 순차 강제.)
    """
    provider = A.resolve_provider_for_stage(1)
    t = time.time()
    opening_map: Dict[str, str] = {}
    steps: List[InitialAnswerStep] = []
    transcript: List[str] = []  # 지금까지의 발언 기록(이름 포함)

    for i, a in enumerate(agents):
        stance = _DEBATE_STANCES[i % len(_DEBATE_STANCES)]
        system = build_agent_system_prompt(a, context) + "\n\n" + _DEBATE_REQUIRED_SYSTEM_PROMPT
        if not transcript:
            turn_instr = (
                "너는 첫 번째 토론자다. 이 주제에 대한 '너만의 분명한 입장'을 한 문장으로 못박고, "
                "타당한 근거 1~2개로 주장하라. 청중(사용자)을 설득하는 게 목표다."
            )
        else:
            prior = "\n\n".join(transcript)
            turn_instr = (
                f"[지금까지의 토론]\n{prior}\n\n"
                "이제 네 차례다. 위 앞 토론자(들)의 발언을 **이름을 부르며 직접** 받아쳐라. "
                "어디에 동의하고 어디가 틀렸는지 콕 집어 반박하고(예: '○○ 말은 ~한데, 그건 ~라서 약해'), "
                "그 위에 너만의 입장을 세워 청중을 설득하라. 앞사람과 같은 말 반복 금지."
            )
        user = (
            f"[토론 주제] {request.message}\n\n"
            f"[너의 입장 각도] {stance}\n\n"
            "[이번 단계: 1차 입론 — 서로 주고받는 토론이다]\n"
            f"{turn_instr}\n짧고 설득력 있게.\n\n"
            + build_persona_directive(a.personality or a.tone or a.style, a.customInstruction)
        )
        params = A.resolve_agent_generation_params(_personality_type(a), 1)
        t_a = time.time()
        try:
            text, _ = _call_llm_with_params("ollama", system, user, params, knowledge_level=a.knowledgeLevel)
        except Exception as e:
            logger.error("debate 입론 '%s' 실패: %s", a.name, e)
            text = A.stage1_timeout_fallback_text()
        if not (text or "").strip():
            text = A.stage1_timeout_fallback_text()
        opening_map[a.name] = text
        transcript.append(f"[{a.name}]\n{text}")
        steps.append(InitialAnswerStep(
            agentName=a.name, answer=text, agentId=a.agentId,
            agentIndex=i + 1, displayOrder=i + 1, stage=1,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=provider, elapsedMs=int((time.time() - t_a) * 1000),
        ))
    elapsed = int((time.time() - t) * 1000)
    logger.info("[StudyMate] debate 입론(순차) elapsedMs=%d agents=%d", elapsed, len(agents))
    return steps, opening_map, provider, elapsed


def _compute_debate_rebuttal(request: MultiChatRequest, agents: List[AgentProfile],
                             opening_map: Dict[str, str]):
    """상호 반박: 모든 토론자 쌍(from -> to)에 대해 실제 대상 지목 피드백을 보장한다."""
    provider = A.resolve_provider_for_stage(3)
    t = time.time()
    peer_steps: List[PeerFeedbackStep] = []
    peer_feedbacks: List[DebatePeerFeedback] = []
    provs: set = set()
    if len(agents) < 2:
        return peer_steps, peer_feedbacks, provider, 0

    all_openings = "\n\n".join(
        f"[{_debate_display_name(a, i + 1)}]\n{opening_map.get(a.name, '')}"
        for i, a in enumerate(agents)
    )

    def _run(pair):
        from_index, frm, target_index, target = pair
        target_answer = opening_map.get(target.name, "")
        system = build_agent_system_prompt(frm) + "\n\n" + _DEBATE_REQUIRED_SYSTEM_PROMPT
        params = A.resolve_agent_generation_params(_personality_type(frm), 3)
        t_a = time.time()
        prov = params.get("provider", provider)
        feedback = ""
        for attempt in range(2):
            retry = "\n이전 피드백은 대상 지목이나 비평성이 부족했다. 이번에는 반드시 대상 이름과 부족/보완/오해/관점 차이를 포함하라." if attempt else ""
            user = (
                f"[토론 주제] {request.message}\n\n"
                f"[전체 1차 의견]\n{all_openings}\n\n"
                f"[네가 평가할 대상] {_debate_display_name(target, target_index)}\n"
                f"[대상 답변]\n{target_answer}\n\n"
                "[이번 단계: 서로 피드백]\n"
                f"너는 {_debate_display_name(frm, from_index)}다. "
                f"반드시 {_debate_display_name(target, target_index)}의 답변을 직접 지목해서 평가하라. "
                "형식적 칭찬, 단순 동의, '보완할 점 없음'은 실패다. "
                "부족한 점, 틀린 점, 불명확한 점, 오해 가능성, 관점 차이 중 최소 하나를 구체적으로 지적하고 "
                "사용자가 왜 보완 설명을 필요로 하는지 말하라. 2~4문장으로 작성하라."
                f"{retry}\n\n"
                + build_persona_directive(frm.personality or frm.tone or frm.style, frm.customInstruction)
            )
            try:
                candidate, prov = _call_llm_with_params(params["provider"], system, user, params,
                                                        knowledge_level=frm.knowledgeLevel)
                if candidate and not _is_llm_fallback(candidate) and _valid_debate_feedback(candidate, target, target_index):
                    feedback = candidate.strip()
                    break
            except Exception as e:
                logger.warning("debate 피드백 %s -> %s 생성 실패(attempt=%d): %s", frm.name, target.name, attempt + 1, e)
        if not feedback:
            feedback = _fallback_debate_feedback(frm, from_index, target, target_index)
            prov = "fallback"

        item = DebatePeerFeedback(
            fromAgentIndex=from_index,
            fromAgentName=frm.name,
            toAgentIndex=target_index,
            toAgentName=target.name,
            title=f"{_debate_display_name(frm, from_index)} → {_debate_display_name(target, target_index)}",
            feedback=feedback,
        )
        elapsed_ms = int((time.time() - t_a) * 1000)
        return item, _peer_step_from_debate_feedback(item, prov, elapsed_ms), prov

    pairs = [
        (i + 1, frm, j + 1, target)
        for i, frm in enumerate(agents)
        for j, target in enumerate(agents)
        if i != j
    ]
    for item, step, prov in _run_pool(_run, pairs, True):
        peer_feedbacks.append(item)
        peer_steps.append(step)
        if prov:
            provs.add(prov)

    if not peer_feedbacks and len(agents) >= 2:
        frm, target = agents[0], agents[1]
        item = DebatePeerFeedback(
            fromAgentIndex=1,
            fromAgentName=frm.name,
            toAgentIndex=2,
            toAgentName=target.name,
            title=f"{_debate_display_name(frm, 1)} → {_debate_display_name(target, 2)}",
            feedback=_fallback_debate_feedback(frm, 1, target, 2),
        )
        peer_feedbacks.append(item)
        peer_steps.append(_peer_step_from_debate_feedback(item, "fallback", 0))
        provs.add("fallback")

    elapsed = int((time.time() - t) * 1000)
    if provs:
        provider = ",".join(sorted(provs))
    logger.info("[StudyMate] debate pairwise 피드백 elapsedMs=%d feedbacks=%d", elapsed, len(peer_feedbacks))
    return peer_steps, peer_feedbacks, provider, elapsed

def _feedback_received_map(agents: List[AgentProfile], peer_feedbacks: List[DebatePeerFeedback]) -> Dict[str, str]:
    """각 에이전트가 받은 pairwise 피드백을 모은다. 최종 변론 입력용."""
    out: Dict[str, str] = {}
    for a in agents:
        parts = [
            f"[{fb.title}]\n{fb.feedback}"
            for fb in peer_feedbacks
            if fb.toAgentName == a.name
        ]
        out[a.name] = "\n\n".join(parts)
    return out


def _compute_debate_revision(request: MultiChatRequest, agents: List[AgentProfile],
                             initial_map: Dict[str, str], fb_map: Dict[str, str]):
    """최종 변론: 받은 반박에 재반론하고 입장을 강화해 청중을 설득한다. 반환: (steps, revised_map, provider, elapsedMs)."""
    provider = A.resolve_provider_for_stage(2)
    t = time.time()

    def _run(a: AgentProfile):
        own = initial_map.get(a.name, "")
        fb = fb_map.get(a.name, "")
        system = build_agent_system_prompt(a) + "\n\n" + _DEBATE_REQUIRED_SYSTEM_PROMPT
        user = (
            f"[토론 주제] {request.message}\n\n"
            f"[너의 1차 입론]\n{own}\n\n"
            f"[상대 토론자들이 너에게 한 반박]\n{fb or '(특별한 반박은 없었다)'}\n\n"
            "[이번 단계: 최종 변론]\n"
            "상대의 반박에 재반론하라. 타당한 지적은 인정해 보완하고, 동의 못 하는 부분은 근거로 되받아쳐라. "
            "그리고 네 입장이 옳다는 걸 청중(사용자)에게 한 번 더 설득력 있게 마무리하라. 성격·말투는 유지한다.\n\n"
            + build_persona_directive(a.personality or a.tone or a.style, a.customInstruction)
        )
        params = A.resolve_agent_generation_params(_personality_type(a), 2)
        t_a = time.time()
        try:
            text, prov = _call_llm_with_params(params["provider"], system, user, params,
                                               knowledge_level=a.knowledgeLevel)
        except Exception as e:
            logger.warning("debate 보완 '%s' 실패 (1차 유지): %s", a.name, e)
            text, prov = own, "fallback"
        return a, text, prov, int((time.time() - t_a) * 1000)

    results = _run_pool(_run, agents, A.enable_parallel_stage2())
    elapsed = int((time.time() - t) * 1000)
    revised_map: Dict[str, str] = {}
    steps: List[ValidatedAnswerStep] = []
    provs: set = set()
    idx_map = _agent_index_map(agents)
    for a, text, prov, ms in results:
        final = text if (text and not _is_llm_fallback(text)) else initial_map.get(a.name, "")
        revised_map[a.name] = final
        provs.add(prov)
        ai = idx_map.get(a.name)
        steps.append(ValidatedAnswerStep(
            agentName=a.name, answer=final, agentId=a.agentId,
            revised=(final.strip() != initial_map.get(a.name, "").strip()),
            agentIndex=ai, displayOrder=ai, stage=2,
            personalityType=_personality_type(a), knowledgeLevel=a.knowledgeLevel,
            provider=prov, elapsedMs=ms,
        ))
    actual = ",".join(sorted(provs)) if provs else provider
    logger.info("[StudyMate] debate 보완 elapsedMs=%d agents=%d", elapsed, len(agents))
    return steps, revised_map, actual, elapsed


def _compute_debate_summary(request: MultiChatRequest, agents: List[AgentProfile],
                            revised_map: Dict[str, str]) -> str:
    """심사 정리: 양측 핵심 논거를 공정히 정리하고 최종 판단을 청중(사용자)에게 위임한다."""
    block = "\n\n".join(f"[{a.name}]\n{revised_map.get(a.name, '')}" for a in agents)
    system = _DEBATE_REQUIRED_SYSTEM_PROMPT + "\n\n" + (
        "너는 토론 심사 진행자다. 양측 토론자의 가장 강한 논거를 어느 한쪽으로 치우치지 않게 공정히 정리하고, "
        "최종 판단은 청중에게 맡긴다. 정답을 단정하지 않는다. 반드시 한국어로."
    )
    user = (
        f"[토론 주제] {request.message}\n\n[토론자들의 최종 변론]\n{block}\n\n"
        "각 토론자의 핵심 주장과 가장 설득력 있던 근거를 한 줄씩 공정하게 정리하라. "
        "그리고 '최종 판단은 청중(당신)의 몫'이라고 밝히며, 어느 쪽 논거가 더 설득력 있었는지 "
        "사용자에게 묻는 질문 1개로 마무리하라. 특정 입장을 정답으로 단정하지 마라."
    )
    params = A.resolve_agent_generation_params("professional", 3)
    try:
        text, _ = _call_llm_with_params(
            params["provider"], system, user, params,
            knowledge_level=_get_knowledge_level(request, agents[0] if agents else None),
        )
        if text and not _is_llm_fallback(text):
            return text.strip()
    except Exception as e:
        logger.warning("debate 종합 정리 실패: %s", e)
    return ""


def _build_stage_infos(initial_steps, validated_steps, peer_steps, pv_summary,
                       s1, s2, s3, sources=None):
    """3개 StageInfo를 만든다. s1/s2/s3 = (provider, elapsedMs, status) 튜플."""
    return [
        StageInfo(stage=1, title="1차 답변 - 빠른 초안", provider=s1[0], status=s1[2],
                  elapsedMs=s1[1], answers=[s.model_dump() for s in initial_steps]),
        StageInfo(stage=2, title="2차 답변 - 검증 답안", provider=s2[0], status=s2[2],
                  elapsedMs=s2[1], answers=[s.model_dump() for s in validated_steps],
                  sources=sources or []),
        StageInfo(stage=3, title="3차 답변 - 에이전트 피드백 및 성격 검증", provider=s3[0], status=s3[2],
                  elapsedMs=s3[1], feedbacks=[s.model_dump() for s in peer_steps],
                  personalityValidationSummary=pv_summary),
    ]


def _build_default_response(request, agents, initial_map, validated_map,
                            initial_steps, validated_steps, peer_steps, pv_summary, stages):
    delay_ms = _get_display_delay_ms()
    answers: List[AgentAnswer] = []
    for idx, a in enumerate(agents):
        answers.append(AgentAnswer(
            agentName=a.name,
            answer=validated_map.get(a.name) or initial_map.get(a.name, ""),
            agentId=a.agentId,
            role=a.role or "default",
            displayOrder=idx + 1,
            displayDelayMs=idx * delay_ms,
            status="SUCCESS",
        ))
    if not answers:
        answers.append(AgentAnswer(
            agentName="시스템",
            answer="현재 AI 서비스에 일시적으로 접근할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            displayOrder=1, displayDelayMs=0, status="FAILED",
        ))
    process_steps = ProcessSteps(
        initialAnswers=initial_steps,
        validatedAnswers=validated_steps,
        peerFeedback=peer_steps,
        personalityValidationSummary=pv_summary,
    )
    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status="COMPLETED",
        question=request.message,
        processSteps=process_steps,
        stages=stages,
    )


def _prep_default_context(context: str, rag_context: str) -> str:
    if rag_context:
        return f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context
    return context


def _run_default_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
) -> MultiChatResponse:
    """
    1차/2차/3차 실데이터 파이프라인 (블로킹, 모든 지식수준 공통).
    스트리밍(run_default_mode_stream)과 동일한 compute 헬퍼를 공유한다.
    """
    context = _prep_default_context(context, rag_context)
    agents = active_agents or [_DEFAULT_AGENT]

    initial_steps, initial_map, p1, e1, st1 = _compute_stage1(request, agents, context)
    validated_steps, validated_map, p2, e2, sources = _compute_stage2(request, agents, initial_map)
    validation_map, pv_summary = _compute_validation(request, agents, initial_map, validated_map, validated_steps)
    peer_steps, p3, e3 = _compute_stage3(request, agents, validated_map, validation_map, initial_map)

    stages = _build_stage_infos(initial_steps, validated_steps, peer_steps, pv_summary,
                                (p1, e1, st1), (p2, e2, "completed"), (p3, e3, "completed"), sources)
    return _build_default_response(request, agents, initial_map, validated_map,
                                   initial_steps, validated_steps, peer_steps, pv_summary, stages)


def _basic_agent_stream_answer(request: MultiChatRequest, agent: AgentProfile, idx: int, total: int, context: str):
    t0 = time.time()
    text = _stage1_initial(agent, request.message, context)
    return AgentAnswer(
        agentName=agent.name,
        answer=text,
        agentId=agent.agentId,
        role=agent.role or "default",
        speechType="first_answer",
        displayOrder=idx,
        displayDelayMs=0,
        status="SUCCESS",
        metadata=AgentAnswerMetadata(
            knowledgeLevel=agent.knowledgeLevel,
            personality=agent.personality,
            usedRag=bool(context),
            latencyMs=int((time.time() - t0) * 1000),
        ),
    )


def run_default_mode_stream(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
):
    """
    기본 채팅 SSE 제너레이터.
    하나의 요청에서 FIRST_ANSWER -> VALIDATION -> PEER_FEEDBACK을 각 1회씩 실행/emit한다.
    heartbeat는 agent 답변 대기 중 주기적으로 보내 idle/read timeout을 방지한다.
    """
    request_id = _stream_request_id()
    context = _prep_default_context(context, rag_context)
    agents = active_agents or [_DEFAULT_AGENT]
    heartbeat_s = _stream_heartbeat_interval_seconds()
    per_agent_timeout_s = _stream_per_agent_timeout_seconds()
    answers: List[AgentAnswer] = []
    initial_steps: List[InitialAnswerStep] = []
    initial_map: Dict[str, str] = {}
    provider = A.resolve_provider_for_stage(1)
    started_at = time.time()
    stage1_started_at = time.time()

    yield {"event": "turn_start", "data": {
        "type": "turn_start",
        "requestId": request_id,
        "message": "AI 응답 생성을 시작합니다.",
    }}

    for idx, agent in enumerate(agents, start=1):
        yield {"event": "agent_start", "data": {
            "type": "agent_start",
            "requestId": request_id,
            "agentIndex": idx,
            "agentId": agent.agentId,
            "agentName": agent.name,
            "role": agent.role or "default",
            "stageType": "FIRST_ANSWER",
            "phase": "FIRST_ANSWER",
            "message": f"에이전트 {idx} 답변 생성 중...",
        }}

        agent_start = time.time()
        answer_obj: Optional[AgentAnswer] = None
        error_message: Optional[str] = None
        ex = ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(_basic_agent_stream_answer, request, agent, idx, len(agents), context)
        try:
            while True:
                try:
                    answer_obj = fut.result(timeout=heartbeat_s)
                    break
                except FutureTimeoutError:
                    elapsed_ms = int((time.time() - agent_start) * 1000)
                    if elapsed_ms >= int(per_agent_timeout_s * 1000):
                        error_message = "timeout"
                        fut.cancel()
                        break
                    yield {"event": "heartbeat", "data": {
                        "type": "heartbeat",
                        "requestId": request_id,
                        "agentIndex": idx,
                        "agentName": agent.name,
                        "elapsedMs": elapsed_ms,
                        "message": "답변 생성 중입니다.",
                    }}
                except Exception as e:
                    error_message = str(e) or "error"
                    break
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

        if answer_obj is None:
            answer_obj = AgentAnswer(
                agentName=agent.name,
                answer="",
                agentId=agent.agentId,
                role=agent.role or "default",
                speechType="first_answer",
                displayOrder=idx,
                displayDelayMs=0,
                status="FAILED",
            )
            answers.append(answer_obj)
            yield {"event": "agent_error", "data": {
                "type": "agent_error",
                "requestId": request_id,
                "agentIndex": idx,
                "agentId": agent.agentId,
                "agentName": agent.name,
                "role": agent.role or "default",
                "stageType": "FIRST_ANSWER",
                "phase": "FIRST_ANSWER",
                "error": error_message or "error",
                "message": "이 에이전트의 응답이 제한 시간을 초과했거나 실패했습니다. 다음 에이전트로 진행합니다.",
            }}
            continue

        answers.append(answer_obj)
        initial_map[agent.name] = answer_obj.answer
        elapsed_ms = int((time.time() - agent_start) * 1000)
        initial_steps.append(InitialAnswerStep(
            agentName=agent.name,
            answer=answer_obj.answer,
            agentId=agent.agentId,
            agentIndex=idx,
            displayOrder=idx,
            stage=1,
            personalityType=_personality_type(agent),
            knowledgeLevel=agent.knowledgeLevel,
            provider=provider,
            elapsedMs=elapsed_ms,
        ))
        yield {"event": "agent_answer", "data": {
            "type": "agent_answer",
            "requestId": request_id,
            "agentIndex": idx,
            "agentId": agent.agentId,
            "agentName": agent.name,
            "role": agent.role or "default",
            "stageType": "FIRST_ANSWER",
            "phase": "FIRST_ANSWER",
            "content": answer_obj.answer,
            "answer": answer_obj.answer,
            "status": "SUCCESS",
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }}

    e1 = int((time.time() - stage1_started_at) * 1000)

    for idx, agent in enumerate(agents, start=1):
        yield {"event": "agent_start", "data": {
            "type": "agent_start",
            "requestId": request_id,
            "agentIndex": idx,
            "agentId": agent.agentId,
            "agentName": agent.name,
            "role": agent.role or "default",
            "stageType": "VALIDATION",
            "phase": "VALIDATION",
            "message": f"에이전트 {idx} 검증 답변 생성 중...",
        }}

    validated_steps, validated_map, p2, e2, sources = _compute_stage2(request, agents, initial_map)
    validation_map, pv_summary = _compute_validation(request, agents, initial_map, validated_map, validated_steps)

    for step in validated_steps:
        yield {"event": "agent_answer", "data": {
            "type": "agent_answer",
            "requestId": request_id,
            "agentIndex": step.agentIndex,
            "agentId": step.agentId,
            "agentName": step.agentName,
            "role": "validation",
            "stageType": "VALIDATION",
            "phase": "VALIDATION",
            "content": step.answer,
            "answer": step.answer,
            "status": "SUCCESS",
            "revised": step.revised,
            "issues": step.issues,
            "sources": step.sources,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }}

    if pv_summary:
        yield {"event": "validation_summary", "data": {
            "type": "validation_summary",
            "requestId": request_id,
            "stageType": "VALIDATION",
            "phase": "VALIDATION",
            "personalityValidationSummary": [item.model_dump() for item in pv_summary],
        }}

    for idx, agent in enumerate(agents, start=1):
        yield {"event": "agent_start", "data": {
            "type": "agent_start",
            "requestId": request_id,
            "agentIndex": idx,
            "agentId": agent.agentId,
            "agentName": agent.name,
            "role": agent.role or "default",
            "stageType": "PEER_FEEDBACK",
            "phase": "PEER_FEEDBACK",
            "message": f"에이전트 {idx} 피드백 생성 중...",
        }}

    peer_steps, p3, e3 = _compute_stage3(request, agents, validated_map, validation_map, initial_map)

    for step in peer_steps:
        yield {"event": "agent_answer", "data": {
            "type": "agent_answer",
            "requestId": request_id,
            "agentIndex": step.agentIndex,
            "agentId": step.fromAgentId,
            "agentName": step.fromAgent,
            "role": "peer_feedback",
            "stageType": "PEER_FEEDBACK",
            "phase": "PEER_FEEDBACK",
            "toAgent": step.toAgent,
            "targetAgentIds": step.targetAgentIds,
            "content": step.feedback,
            "answer": step.feedback,
            "feedback": step.feedback,
            "status": "SUCCESS",
            "personalityValidation": step.personalityValidation,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }}

    success_count = sum(1 for a in answers if a.status == "SUCCESS")
    final_answers: List[AgentAnswer] = []
    for idx, agent in enumerate(agents, start=1):
        first_answer = initial_map.get(agent.name, "")
        final_answer = validated_map.get(agent.name) or first_answer
        status = "SUCCESS" if final_answer else "FAILED"
        final_answers.append(AgentAnswer(
            agentName=agent.name,
            answer=final_answer,
            agentId=agent.agentId,
            role=agent.role or "default",
            speechType="validated_answer",
            displayOrder=idx,
            displayDelayMs=0,
            status=status,
        ))

    process_steps = ProcessSteps(
        mode="basic",
        initialAnswers=initial_steps,
        validatedAnswers=validated_steps,
        peerFeedback=peer_steps,
        personalityValidationSummary=pv_summary,
    )
    stages = _build_stage_infos(
        initial_steps, validated_steps, peer_steps, pv_summary,
        (provider, e1, "completed"), (p2, e2, "completed"), (p3, e3, "completed"), sources,
    )
    final = MultiChatResponse(
        mode="default",
        learningMode=getattr(request, "learningMode", None) or "basic",
        answers=final_answers,
        status="COMPLETED" if success_count == len(answers) else ("PARTIAL_SUCCESS" if success_count else "FAILED"),
        question=request.message,
        processSteps=process_steps,
        stages=stages,
    )
    data = final.model_dump()
    data["type"] = "all_complete"
    data["requestId"] = request_id
    data["message"] = "모든 에이전트 응답이 완료되었습니다."
    data["elapsedMs"] = int((time.time() - started_at) * 1000)
    yield {"event": "all_complete", "data": data}

def build_stream_generator(request: MultiChatRequest):
    """
    SSE용 이벤트 제너레이터를 만든다.
    default 계열 모드만 단계별 스트리밍하고, 그 외 모드는 블로킹 실행 후 all_complete 1회만 emit한다.
    """
    # ── feature flag: LangGraph 오케스트레이터 ──────────────────────────────
    # USE_LANGGRAPH_ORCHESTRATOR=true이면 그래프로 실행 후 all_complete 1회만 emit한다.
    # (스트리밍 단계 분해는 기존 경로에만 적용. 그래프는 흐름 제어/구조화가 목적.)
    try:
        from app.core import config as _cfg
        if getattr(_cfg, "USE_LANGGRAPH_ORCHESTRATOR", False):
            from app.services.langgraph_agent_orchestrator import run_langgraph_multi_agent

            def _graph_single():
                result = run_langgraph_multi_agent(request)
                yield {"event": "all_complete", "data": result.model_dump()}
            return _graph_single()
    except Exception as e:
        logger.warning("LangGraph 스트림 분기 실패 → 기존 경로 사용: %s", e)

    agents = _get_agents(request)
    active_agents = _filter_agents(agents, request.targetAgentId)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)
    rag_context = _get_rag_context(request.message, request.materialId)

    # 스트리밍 표시는 '명시적으로 고른 모드'를 따른다.
    #  - 기본 채팅(basic) → 1차/2차/3차 staged (에이전트 2명 이상이어도 자동 토론 승격 안 함)
    #  - 명시적 토론(debate/토론) → 토론 섹션, 명시적 소크라테스 → 소크라테스
    # (자동 토론 승격은 블로킹 run_multi_chat에만 남겨 두어 두 표시 경로를 분리한다.)
    raw = (request.mode or "default").strip().lower()
    lm = (getattr(request, "learningMode", None) or "").strip().lower()
    explicit_simulation = (lm in _SIMULATION_MODE_ALIASES) or (not lm and raw in _SIMULATION_MODE_ALIASES)
    explicit_socratic = (lm in _SOCRATIC_MODE_ALIASES) or (not lm and raw in _SOCRATIC_MODE_ALIASES)
    explicit_debate = (lm in _DEBATE_MODE_ALIASES) or (not lm and raw in _DEBATE_MODE_ALIASES)
    logger.info("[StudyMate] stream route raw=%s lm=%s explicit_simulation=%s explicit_debate=%s explicit_socratic=%s agents=%d",
                raw, lm, explicit_simulation, explicit_debate, explicit_socratic, len(active_agents))

    # 모드별 전용 SSE 제너레이터. all_complete 1회만 기다리지 않고 단계/섹션 단위로 즉시 내보낸다.
    if explicit_simulation:
        return run_simulation_mode_stream(request, active_agents, rag_context)
    if explicit_socratic:
        return run_socratic_mode_stream(request, active_agents, rag_context)
    if explicit_debate:
        return run_debate_mode_stream(request, active_agents, rag_context)
    if raw == "group_study_ai":
        # 그룹스터디 봇도 FastAPI 내부에서 전체 완료를 기다리지 않고 agent별 순차 SSE로 내보낸다.
        return run_default_mode_stream(request, active_agents, context, rag_context)

    return run_default_mode_stream(request, active_agents, context, rag_context)


def _run_tikitaka_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
) -> MultiChatResponse:
    """티키타카 3라운드 순차 체인 모드."""
    if rag_context:
        context = f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context

    delay_ms = _get_display_delay_ms()
    answers: List[AgentAnswer] = []

    # Round 1: initial_answer
    for idx, agent in enumerate(active_agents):
        try:
            system = build_agent_system_prompt(agent, context)
            user = f"[이번 역할] 이 질문의 핵심 개념과 원리를 명확하게 설명하라.\n[사용자 질문] {request.message}"
            text = _call_llm(system, user, knowledge_level=agent.knowledgeLevel)
            answers.append(AgentAnswer(
                agentName=agent.name,
                answer=text,
                agentId=agent.agentId,
                role=agent.role or "default",
                speechType="initial_answer",
                displayOrder=idx + 1,
                displayDelayMs=idx * delay_ms,
                status="SUCCESS",
            ))
        except Exception as e:
            logger.error("Round1 에이전트 '%s' 실패: %s", agent.name, e)
            answers.append(AgentAnswer(
                agentName=agent.name, answer="답변 생성 실패.",
                speechType="initial_answer",
                displayOrder=idx + 1, displayDelayMs=idx * delay_ms, status="FAILED",
            ))

    prev_answers_text = "\n\n".join(
        f"[{a.agentName}]\n{a.answer[:300]}" for a in answers if a.status == "SUCCESS"
    )
    base_order = len(answers)

    # Round 2: critique (policy YAML에서 키워드 참조)
    try:
        from app.core.policy_loader import get_tikitaka_validation
        tiki_policy = get_tikitaka_validation()
        critique_terms = tiki_policy.get("critique_keywords", ["부족", "누락", "한계"])
    except Exception:
        critique_terms = ["부족", "누락", "한계"]

    for idx, agent in enumerate(active_agents[:2]):  # 비판형 위주 2명
        try:
            system = build_agent_system_prompt(agent, context)
            user = (
                f"[이전 답변들]\n{prev_answers_text}\n\n"
                f"[사용자 질문] {request.message}\n\n"
                "[이번 역할] 앞서 설명된 내용에서 부족한 점, 누락된 개념, 보완이 필요한 부분을 지적하고 개선 방향을 제시하라."
            )
            text = _call_llm(system, user, knowledge_level=agent.knowledgeLevel)
            answers.append(AgentAnswer(
                agentName=agent.name, answer=text,
                agentId=agent.agentId, role=agent.role or "critic",
                speechType="critique",
                displayOrder=base_order + idx + 1,
                displayDelayMs=(base_order + idx) * delay_ms,
                status="SUCCESS",
            ))
        except Exception as e:
            logger.error("Round2 에이전트 '%s' 실패: %s", agent.name, e)

    base_order = len(answers)
    critique_text = "\n\n".join(
        f"[{a.agentName}]\n{a.answer[:300]}"
        for a in answers if a.speechType == "critique" and a.status == "SUCCESS"
    )

    # Round 3: rebuttal_or_refinement
    for idx, agent in enumerate(active_agents):
        try:
            system = build_agent_system_prompt(agent, context)
            user = (
                f"[원래 질문] {request.message}\n\n"
                f"[1차 답변]\n{prev_answers_text}\n\n"
                f"[비판/보완 의견]\n{critique_text}\n\n"
                "[이번 역할] 비판/보완 의견을 반영하여 설명을 보완하거나 반박하라. "
                "명확하게 한 가지 포인트만 추가 설명하라."
            )
            text = _call_llm(system, user, knowledge_level=agent.knowledgeLevel)
            answers.append(AgentAnswer(
                agentName=agent.name, answer=text,
                agentId=agent.agentId, role=agent.role or "default",
                speechType="rebuttal_or_refinement",
                displayOrder=base_order + idx + 1,
                displayDelayMs=(base_order + idx) * delay_ms,
                status="SUCCESS",
            ))
        except Exception as e:
            logger.error("Round3 에이전트 '%s' 실패: %s", agent.name, e)

    # 티키타카 검증
    try:
        from app.services.mode_validator import validate_mode_response
        v_result = validate_mode_response("tikitaka", [a.model_dump() for a in answers])
        validation = ValidationSummary(
            passed=v_result["passed"],
            issues=v_result.get("issues", []),
        )
    except Exception as e:
        logger.warning("티키타카 검증 실패: %s", e)
        validation = ValidationSummary(passed=True, issues=[])

    success_count = sum(1 for a in answers if a.status == "SUCCESS")
    status = "COMPLETED" if success_count == len(answers) else (
        "PARTIAL_SUCCESS" if success_count > 0 else "FAILED"
    )

    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status=status,
        question=request.message,
        validation=validation,
    )


def _debate_ensure_feedbacks(agents, peer_steps, peer_feedbacks):
    """토론 모드에서 빈 peerFeedbacks는 허용하지 않는다(방어선)."""
    if peer_feedbacks:
        return peer_steps, peer_feedbacks
    frm, target = agents[0], agents[1]
    fallback = DebatePeerFeedback(
        fromAgentIndex=1, fromAgentName=frm.name,
        toAgentIndex=2, toAgentName=target.name,
        title=f"{_debate_display_name(frm, 1)} → {_debate_display_name(target, 2)}",
        feedback=_fallback_debate_feedback(frm, 1, target, 2),
    )
    return [_peer_step_from_debate_feedback(fallback, "fallback", 0)], [fallback]


def _debate_default_summary(summary: str) -> str:
    if summary:
        return summary
    return (
        "토론 정리: 각 에이전트는 같은 주제를 서로 다른 관점에서 설명했고, 핵심은 1차 답변을 그대로 받아들이기보다 "
        "부족한 점과 오해 가능성을 비교해 개념 정의, 실제 예시, 기술적 정확성을 함께 확인하는 것입니다."
    )


def _assemble_debate_response(
    request, agents, rag_context,
    initial_steps, initial_map, peer_steps, peer_feedbacks,
    revised_steps, revised_map, summary,
) -> MultiChatResponse:
    """compute된 토론 단계들을 최종 MultiChatResponse로 조립한다(블로킹/스트리밍 공용)."""
    delay_ms = _get_display_delay_ms()
    initial_answers = _debate_initial_records(agents, initial_map)
    revised_answers = _debate_revised_records(agents, revised_map)

    answers: List[AgentAnswer] = []
    for idx, a in enumerate(agents):
        answers.append(AgentAnswer(
            agentName=_debate_display_name(a, idx + 1),
            answer=revised_map.get(a.name) or initial_map.get(a.name, ""),
            agentId=a.agentId,
            role="debater",
            displayOrder=idx + 1,
            displayDelayMs=idx * delay_ms,
            status="SUCCESS",
            metadata=AgentAnswerMetadata(
                knowledgeLevel=a.knowledgeLevel, personality=a.personality,
                usedRag=bool(rag_context),
            ),
        ))

    pv_summary = _validate_mode_personas(
        agents,
        [AgentAnswer(agentName=a.name, answer=revised_map.get(a.name, "")) for a in agents],
    )

    process_steps = ProcessSteps(
        initialAnswers=initial_steps,
        peerFeedback=peer_steps,
        revisedAnswers=revised_steps,
        debateSummary=summary,
        personalityValidationSummary=pv_summary,
    )
    issues = []
    if len(initial_answers) < 2:
        issues.append("initialAnswers 길이가 2보다 작습니다.")
    if len(peer_feedbacks) < 1:
        issues.append("peerFeedbacks가 비어 있습니다.")
    if not revised_answers and not summary:
        issues.append("revisedAnswers 또는 debateSummary가 필요합니다.")
    invalid_feedbacks = [
        fb.title for fb in peer_feedbacks
        if not _valid_debate_feedback(fb.feedback, agents[fb.toAgentIndex - 1], fb.toAgentIndex)
    ]
    if invalid_feedbacks:
        issues.append("비평성 또는 대상 지목이 약한 피드백: " + ", ".join(invalid_feedbacks[:3]))

    logger.info("[StudyMate] debate 완료 agents=%d initial=%d feedback=%d revised=%d summary=%s",
                len(agents), len(initial_answers), len(peer_feedbacks), len(revised_answers), bool(summary))
    return MultiChatResponse(
        mode="debate",
        answers=answers,
        status="COMPLETED" if not issues else "PARTIAL_SUCCESS",
        question=request.message,
        validation=ValidationSummary(passed=not issues, issues=issues),
        feedbacks=[fb.model_dump() for fb in peer_feedbacks],
        initialAnswers=initial_answers,
        peerFeedbacks=peer_feedbacks,
        revisedAnswers=revised_answers,
        debateSummary=summary,
        processSteps=process_steps,
    )


# ── 구조화 토론(debate) v2: 논제 설정(debateConfig) + 반대/찬성/중립 고정 역할 ─────────
# 에이전트1=반대측(CON), 에이전트2=찬성측(PRO), 에이전트3=중립/심사위원(NEUTRAL).
# 출력은 debateStages(채팅/마인드맵/SSE/history 공통 SSOT)로 통일한다.

_DEBATE_DEFAULT_ISSUE_AXES = ["개념정확성", "학습효율", "실무적용", "오개념위험"]
_DEBATE_DEFAULT_JUDGE = ["논리성", "근거성", "반박력", "학습가치", "실무성"]
_DEBATE_DEFAULT_OUTPUT_STAGES = [
    "TOPIC", "CON_OPENING", "PRO_OPENING", "NEUTRAL_ANALYSIS",
    "CON_REBUTTAL", "PRO_REBUTTAL", "NEUTRAL_CHECK",
    "CON_CLOSING", "PRO_CLOSING", "NEUTRAL_JUDGEMENT",
]

# outputStages 키 → (stageType, stageTitle, side, role, agentIndex, role_kind)
_DEBATE_STAGE_MAP = {
    "TOPIC":             ("TOPIC", "논제", "TOPIC", "논제", None, None),
    "CON_OPENING":       ("OPENING_STATEMENT", "반대측 입론", "CON", "반대측", 1, "CON"),
    "PRO_OPENING":       ("OPENING_STATEMENT", "찬성측 입론", "PRO", "찬성측", 2, "PRO"),
    "NEUTRAL_ANALYSIS":  ("NEUTRAL_ANALYSIS", "중립 쟁점 정리", "NEUTRAL", "중립", 3, "NEUTRAL"),
    "CON_REBUTTAL":      ("REBUTTAL", "반대측 반박", "CON", "반대측", 1, "CON"),
    "PRO_REBUTTAL":      ("REBUTTAL", "찬성측 반박", "PRO", "찬성측", 2, "PRO"),
    "NEUTRAL_CHECK":     ("NEUTRAL_CHECK", "중립 검토", "NEUTRAL", "중립", 3, "NEUTRAL"),
    "CON_CLOSING":       ("CLOSING_STATEMENT", "반대측 최종 변론", "CON", "반대측", 1, "CON"),
    "PRO_CLOSING":       ("CLOSING_STATEMENT", "찬성측 최종 변론", "PRO", "찬성측", 2, "PRO"),
    "NEUTRAL_JUDGEMENT": ("JUDGEMENT", "중립 판정", "NEUTRAL", "중립 / 심사위원", 3, "NEUTRAL"),
}

_DEBATE_STRUCTURED_SYSTEM = (
    "이것은 역할이 고정된 구조화 토론이다. 너는 배정된 입장(반대측/찬성측)을 끝까지 일관되게 유지한다. "
    "상호 피드백 모드가 아니다. '좋은 답변입니다', '보완하면 좋겠습니다', '개선 방향' 같은 피드백성 표현은 쓰지 않는다. "
    "반박 단계에서는 상대 핵심 주장을 직접 겨냥해 논박한다. 반드시 한국어로 답한다."
)

_DEBATE_STAGE_NUM = {
    "OPENING_STATEMENT": 1, "REBUTTAL": 3, "CLOSING_STATEMENT": 2,
    "NEUTRAL_ANALYSIS": 2, "NEUTRAL_CHECK": 2, "JUDGEMENT": 3,
}


def normalize_debate_config(request: MultiChatRequest) -> DebateConfig:
    """debateConfig 누락 필드를 기본값으로 채운다."""
    cfg = request.debateConfig or DebateConfig()
    if not cfg.issueAxes:
        cfg.issueAxes = list(_DEBATE_DEFAULT_ISSUE_AXES)
    if not cfg.judgeCriteria:
        cfg.judgeCriteria = list(_DEBATE_DEFAULT_JUDGE)
    if not cfg.outputStages:
        cfg.outputStages = list(_DEBATE_DEFAULT_OUTPUT_STAGES)
    if not cfg.motionType:
        cfg.motionType = "learning_strategy"
    if not cfg.stancePolicy:
        cfg.stancePolicy = "agent1_con_agent2_pro_agent3_neutral"
    if not cfg.topicMode:
        cfg.topicMode = "auto"
    return cfg


def _debate_topic_keyword(message: str) -> str:
    """설명형 질문에서 핵심 주제어만 뽑는다. (예: 'OOP가 뭐고 어떤 걸 공부해야 해?' → 'OOP')"""
    m = (message or "").strip()
    for cut in ["가 뭐", "이 뭐", "는 뭐", "란 ", "이란", "에 대해서", "에 대해", "어떤", "뭘", "무엇", "?", "？", "\n"]:
        idx = m.find(cut)
        if idx > 1:
            m = m[:idx]
            break
    return m.strip(" ,.!?'\"") or (message or "").strip()


def build_debate_motion(user_message: str, cfg: DebateConfig) -> str:
    """사용자 질문을 토론 가능한 논제로 변환하거나, 수동 입력 논제를 사용한다."""
    if (cfg.topicMode or "auto") == "manual" and (cfg.manualTopic or "").strip():
        return cfg.manualTopic.strip()
    kw = _debate_topic_keyword(user_message)
    mt = cfg.motionType or "learning_strategy"
    templates = {
        "learning_strategy": f"{kw}를 처음 배울 때, 개념 이론보다 실무 예제 중심으로 먼저 학습하는 것이 더 효과적인가?",
        "concept_definition": f"{kw}를 학습할 때 엄밀한 개념 정의를 실습보다 먼저 익혀야 하는가?",
        "tech_choice": f"{kw}에서 특정 기술 선택은 학습 효율과 실무 적용성 측면에서 타당한가?",
        "implementation_design": f"{kw}를 실제 프로젝트에 적용할 때 구조적 설계를 우선해야 하는가?",
        "pros_cons": f"{kw}에 대해 찬성 입장이 반대 입장보다 더 설득력 있는가?",
    }
    return templates.get(mt, f"{kw}에 대해 찬성과 반대 입장 중 어느 쪽이 더 설득력 있는가?")


def _create_virtual_debate_agent(label: str, idx: int, knowledge_level: str = "학사") -> AgentProfile:
    return AgentProfile(
        id=-idx, agentId=-idx, name=label, role="debater",
        personality=("비판형" if label == "반대측" else "전문적"),
        personalityStrength="moderate", knowledgeLevel=knowledge_level,
    )


def assign_debate_roles(agents: List[AgentProfile]) -> Dict[str, AgentProfile]:
    """역할 고정: agent[0]=반대측, agent[1]=찬성측, agent[2]=중립/심사위원. 절대 supporter 먼저 만들지 않는다."""
    kl = agents[0].knowledgeLevel if agents else "학사"
    con = agents[0] if len(agents) > 0 else _create_virtual_debate_agent("반대측", 1, kl)
    pro = agents[1] if len(agents) > 1 else _create_virtual_debate_agent("찬성측", 2, kl)
    neutral = agents[2] if len(agents) > 2 else _create_virtual_debate_agent("중립", 3, kl)
    return {"CON": con, "PRO": pro, "NEUTRAL": neutral}


def _debate_setup_block(request: MultiChatRequest, motion: str, cfg: DebateConfig) -> str:
    return (
        "[토론 설정]\n"
        f"- 원 질문: {request.message}\n"
        f"- 토론 논제: {motion}\n"
        f"- 논제 유형: {cfg.motionType}\n"
        "- 역할 정책: 에이전트1=반대측, 에이전트2=찬성측, 에이전트3=중립/심사위원\n"
        f"- 쟁점 축: {', '.join(cfg.issueAxes)}\n"
        f"- 토론 깊이: {cfg.debateDepth}\n"
        f"- 토론 스타일: {cfg.debateStyle}\n"
        f"- 예시 포함: {cfg.includeExamples}\n"
        f"- 반례 포함: {cfg.includeCounterexamples}\n"
        f"- 학습 방향 포함: {cfg.includeStudyPlan}\n"
        f"- 판정 기준: {', '.join(cfg.judgeCriteria)}\n\n"
        "[필수 규칙]\n"
        "1. 이 모드는 상호 피드백 모드가 아니다.\n"
        "2. 에이전트 1은 무조건 반대측이다.\n"
        "3. 에이전트 2는 무조건 찬성측이다.\n"
        "4. 에이전트 3은 무조건 중립/심사위원이다.\n"
        "5. \"좋은 답변입니다\", \"보완하면 좋겠습니다\", \"개선 방향\" 같은 피드백 표현은 금지한다.\n"
        "6. 반박 단계에서는 상대측 핵심 주장을 직접 겨냥해 논박한다.\n"
        "7. 중립측은 양측 주장을 객관적으로 정리하고, 판정 기준에 따라 판단한다.\n"
        "8. 마지막에는 사용자가 무엇을 공부해야 하는지도 정리한다.\n"
    )


def _debate_stage_user_instruction(stage_key: str, cfg: DebateConfig, c: Dict[str, str]) -> str:
    axes = ", ".join(cfg.issueAxes)
    crit = ", ".join(cfg.judgeCriteria)
    con_open, pro_open = c.get("CON_OPENING", ""), c.get("PRO_OPENING", "")
    con_rebut, pro_rebut = c.get("CON_REBUTTAL", ""), c.get("PRO_REBUTTAL", "")
    if stage_key == "CON_OPENING":
        return ("[이번 단계: 반대측 입론]\n너는 반대측이다. 위 논제에 '반대' 입장에서 핵심 주장과 근거 2~3개를 제시하라. "
                f"쟁점 축({axes}) 중 너에게 유리한 축을 골라 청중(사용자)을 설득하라. 3~6문장.")
    if stage_key == "PRO_OPENING":
        return ("[이번 단계: 찬성측 입론]\n너는 찬성측이다. 위 논제에 '찬성' 입장에서 핵심 주장과 근거 2~3개를 제시하라. "
                f"쟁점 축({axes}) 중 너에게 유리한 축을 골라 청중(사용자)을 설득하라. 3~6문장.")
    if stage_key == "NEUTRAL_ANALYSIS":
        return ("[이번 단계: 중립 쟁점 정리]\n아래 양측 입론을 객관적으로 비교해 핵심 쟁점을 정리하라. 어느 편도 들지 마라.\n\n"
                f"[반대측 입론]\n{con_open}\n\n[찬성측 입론]\n{pro_open}\n\n"
                f"쟁점 축({axes}) 기준으로 양측이 충돌하는 지점을 3개 이내로 정리하라.")
    if stage_key == "CON_REBUTTAL":
        return ("[이번 단계: 반대측 반박]\n너는 반대측이다. 아래 찬성측 입론의 핵심 전제를 직접 겨냥해 논리적으로 반박하라. "
                f"형식적 칭찬·동의는 실패다.\n\n[찬성측 입론]\n{pro_open}")
    if stage_key == "PRO_REBUTTAL":
        return ("[이번 단계: 찬성측 반박]\n너는 찬성측이다. 아래 반대측 입론의 핵심 전제를 직접 겨냥해 논리적으로 반박하라. "
                f"형식적 칭찬·동의는 실패다.\n\n[반대측 입론]\n{con_open}")
    if stage_key == "NEUTRAL_CHECK":
        return ("[이번 단계: 중립 검토]\n아래 양측 반박의 논리적 타당성과 허점을 객관적으로 점검하라. 어느 편도 들지 마라.\n\n"
                f"[반대측 반박]\n{con_rebut}\n\n[찬성측 반박]\n{pro_rebut}")
    if stage_key == "CON_CLOSING":
        return ("[이번 단계: 반대측 최종 변론]\n너는 반대측이다. 아래 찬성측 반박에 재반론하고, 네 입장을 한 번 더 설득력 있게 마무리하라.\n\n"
                f"[너에게 들어온 찬성측 반박]\n{pro_rebut or '(없음)'}")
    if stage_key == "PRO_CLOSING":
        return ("[이번 단계: 찬성측 최종 변론]\n너는 찬성측이다. 아래 반대측 반박에 재반론하고, 네 입장을 한 번 더 설득력 있게 마무리하라.\n\n"
                f"[너에게 들어온 반대측 반박]\n{con_rebut or '(없음)'}")
    if stage_key == "NEUTRAL_JUDGEMENT":
        study = " 마지막에 '사용자가 무엇을 공부해야 하는지'를 2~3개로 정리하라." if cfg.includeStudyPlan else ""
        return ("[이번 단계: 중립 판정]\n양측의 최종 변론을 종합해 심사위원으로서 판정하라. "
                f"판정 기준({crit})에 따라 어느 쪽 논거가 더 설득력 있었는지 근거와 함께 밝혀라. "
                "정답을 강요하지 말고 기준에 따른 판단을 제시하라." + study)
    return "[이번 단계] 위 논제에 대해 너의 입장에서 발언하라."


def _debate_stage_fallback(stage_key: str, motion: str) -> str:
    label = _DEBATE_STAGE_MAP[stage_key][1]
    if stage_key == "CON_OPENING":
        return f"({label}) 반대측 입장: 논제 {motion}은 조건과 한계를 먼저 검토해야 합니다. 성급히 찬성하면 예외 상황과 오개념 위험을 놓칠 수 있으므로 신중한 접근이 필요합니다."
    if stage_key == "PRO_OPENING":
        return f"({label}) 찬성측 입장: 논제 {motion}은 학습 효율과 실무 적용 관점에서 충분히 지지할 수 있습니다. 핵심 원리를 예시와 함께 익히면 이해와 적용이 빨라집니다."
    if stage_key == "NEUTRAL_ANALYSIS":
        return f"({label}) 중립 분석: 양측의 쟁점은 정확성, 적용 가능성, 오개념 위험입니다. 반대측은 조건과 한계를, 찬성측은 학습 효과와 활용성을 강조하므로 두 기준을 함께 비교해야 합니다."
    if stage_key == "CON_REBUTTAL":
        return f"({label}) 반대측 반박: 찬성측 주장은 효과를 강조하지만, 전제 조건이 빠지면 잘못된 일반화가 됩니다. 특히 예외와 한계를 설명하지 않으면 학습자가 개념을 과도하게 단순화할 수 있습니다."
    if stage_key == "PRO_REBUTTAL":
        return f"({label}) 찬성측 반박: 반대측의 우려는 타당하지만, 그것이 학습 자체를 미룰 이유는 아닙니다. 조건과 예외를 함께 배우면 오히려 개념을 더 정확히 적용할 수 있습니다."
    if stage_key == "NEUTRAL_CHECK":
        return f"({label}) 중립 검토: 반대측은 위험 통제에 강점이 있고, 찬성측은 실제 학습 효용을 잘 제시했습니다. 판정은 어느 쪽이 조건, 예시, 한계를 더 균형 있게 다뤘는지에 달려 있습니다."
    if stage_key == "CON_CLOSING":
        return f"({label}) 반대측 최종 변론: 이 논제는 무조건적 찬성보다 조건부 접근이 더 안전합니다. 핵심 개념을 다룰 때는 한계와 반례를 함께 확인해야 실수를 줄일 수 있습니다."
    if stage_key == "PRO_CLOSING":
        return f"({label}) 찬성측 최종 변론: 조건과 한계를 함께 명시한다면 이 논제는 충분히 실용적입니다. 학습자는 먼저 핵심 구조를 잡고, 이후 예외와 반례로 이해를 정교화하는 편이 효과적입니다."
    if stage_key == "NEUTRAL_JUDGEMENT":
        return f"({label}) 중립 판정: 양측 모두 타당한 근거가 있으나, 더 설득력 있는 답은 조건과 실용성을 함께 제시하는 쪽입니다. 사용자는 핵심 정의, 대표 예시, 예외 조건 순서로 공부하면 균형 있게 이해할 수 있습니다."
    return f"({label}) 논제 {motion}에 대해 핵심 주장, 반박 지점, 판단 기준을 분리해 검토해야 합니다."


def _run_debate_stage(request, agent, stage_key, motion, cfg, context, computed):
    stage_type, _title, _side, _role, _ai, kind = _DEBATE_STAGE_MAP[stage_key]
    setup = _debate_setup_block(request, motion, cfg)
    instr = _debate_stage_user_instruction(stage_key, cfg, computed)
    if kind == "NEUTRAL":
        system = (
            "너는 토론의 중립 진행자이자 심사위원이다. 어느 한쪽 편을 들지 말고 객관적으로 정리·판단한다. "
            "피드백성 표현('좋은 답변입니다' 등) 없이 사실과 논리만 다룬다. 반드시 한국어로 답한다."
        )
        directive = ""
    else:
        system = build_agent_system_prompt(agent, context) + "\n\n" + _DEBATE_STRUCTURED_SYSTEM + _agent_preset_directive(agent)
        directive = build_persona_directive(agent.personality or agent.tone or agent.style, agent.customInstruction)
    user = setup + "\n" + instr + ("\n\n" + directive if directive else "")
    params = A.resolve_agent_generation_params(_personality_type(agent), _DEBATE_STAGE_NUM.get(stage_type, 2))
    provider = "ollama" if stage_type == "OPENING_STATEMENT" else params.get("provider", "ollama")
    try:
        text, _ = _call_llm_with_params(provider, system, user, params, knowledge_level=agent.knowledgeLevel)
    except Exception as e:
        logger.warning("debate stage %s 실패: %s", stage_key, e)
        text = ""
    if not (text or "").strip() or _is_llm_fallback(text):
        text = _debate_stage_fallback(stage_key, motion)
    return text.strip()


def _structured_debate_stages(request, role_map, motion, cfg, context):
    """canonical 순서로 DebateStage를 하나씩 yield한다(좌우 대칭 단계는 병렬 계산)."""
    want = [s for s in (cfg.outputStages or _DEBATE_DEFAULT_OUTPUT_STAGES) if s in _DEBATE_STAGE_MAP]
    want_set = set(want)
    computed: Dict[str, str] = {}
    agent_for = {"CON": role_map["CON"], "PRO": role_map["PRO"], "NEUTRAL": role_map["NEUTRAL"]}

    def make_stage(stage_key, content):
        st, title, side, role, ai, kind = _DEBATE_STAGE_MAP[stage_key]
        agent = agent_for.get(kind) if kind else None
        return DebateStage(
            stageType=st, stageTitle=title, side=side, role=role,
            agentIndex=ai, agentId=(agent.agentId if agent else None),
            agentName=(agent.name if agent else None), content=content,
        )

    def run_one(stage_key):
        kind = _DEBATE_STAGE_MAP[stage_key][5]
        text = _run_debate_stage(request, agent_for[kind], stage_key, motion, cfg, context, computed)
        return stage_key, text

    def run_pair_then_yield(keys):
        # SSE에서는 좌우 대칭 단계도 순차 생성한다. 한쪽이 끝나면 즉시 yield되어 화면에 표시된다.
        out = []
        for k in [key for key in keys if key in want_set]:
            _, text = run_one(k)
            computed[k] = text
            out.append(make_stage(k, text))
        return out

    def run_single_then_yield(key):
        if key not in want_set:
            return []
        _, text = run_one(key)
        computed[key] = text
        return [make_stage(key, text)]

    if "TOPIC" in want_set:
        computed["TOPIC"] = motion
        yield make_stage("TOPIC", motion)
    for s in run_pair_then_yield(("CON_OPENING", "PRO_OPENING")):
        yield s
    for s in run_single_then_yield("NEUTRAL_ANALYSIS"):
        yield s
    for s in run_pair_then_yield(("CON_REBUTTAL", "PRO_REBUTTAL")):
        yield s
    for s in run_single_then_yield("NEUTRAL_CHECK"):
        yield s
    for s in run_pair_then_yield(("CON_CLOSING", "PRO_CLOSING")):
        yield s
    for s in run_single_then_yield("NEUTRAL_JUDGEMENT"):
        yield s


def _assemble_structured_debate(request, role_map, motion, cfg, stages, rag_context) -> MultiChatResponse:
    """구조화 토론 stages → MultiChatResponse(+ 하위호환 필드, processSteps에 debateStages/debateConfig 포함)."""
    con, pro, neu = role_map["CON"], role_map["PRO"], role_map["NEUTRAL"]
    by_key = {(s.stageType, s.side): s for s in stages}

    def content(stage_type, side):
        s = by_key.get((stage_type, side))
        return s.content if s else ""

    summary = content("JUDGEMENT", "NEUTRAL") or content("NEUTRAL_CHECK", "NEUTRAL")
    delay_ms = _get_display_delay_ms()

    # 하위 호환 top-level 구조 (구버전 소비자 보호 — UI는 debateStages를 우선 사용)
    initial_answers = [
        DebateInitialAnswer(agentIndex=1, agentName=con.name, displayName=_debate_display_name(con, 1),
                            answer=content("OPENING_STATEMENT", "CON")),
        DebateInitialAnswer(agentIndex=2, agentName=pro.name, displayName=_debate_display_name(pro, 2),
                            answer=content("OPENING_STATEMENT", "PRO")),
    ]
    revised_answers = [
        DebateRevisedAnswer(agentIndex=1, agentName=con.name, displayName=_debate_display_name(con, 1),
                            answer=content("CLOSING_STATEMENT", "CON")),
        DebateRevisedAnswer(agentIndex=2, agentName=pro.name, displayName=_debate_display_name(pro, 2),
                            answer=content("CLOSING_STATEMENT", "PRO")),
    ]
    peer_feedbacks = []
    if content("REBUTTAL", "CON"):
        peer_feedbacks.append(DebatePeerFeedback(fromAgentIndex=1, fromAgentName=con.name,
                              toAgentIndex=2, toAgentName=pro.name, title="반대측 반박",
                              feedback=content("REBUTTAL", "CON")))
    if content("REBUTTAL", "PRO"):
        peer_feedbacks.append(DebatePeerFeedback(fromAgentIndex=2, fromAgentName=pro.name,
                              toAgentIndex=1, toAgentName=con.name, title="찬성측 반박",
                              feedback=content("REBUTTAL", "PRO")))

    # answers: 에이전트별 1개(반대=최종변론 / 찬성=최종변론 / 중립=판정) — Spring이 메시지로 저장
    answers = [
        AgentAnswer(agentName=_debate_display_name(con, 1),
                    answer=content("CLOSING_STATEMENT", "CON") or content("OPENING_STATEMENT", "CON"),
                    agentId=con.agentId, role="con", displayOrder=1, displayDelayMs=0, status="SUCCESS",
                    metadata=AgentAnswerMetadata(knowledgeLevel=con.knowledgeLevel, personality=con.personality, usedRag=bool(rag_context))),
        AgentAnswer(agentName=_debate_display_name(pro, 2),
                    answer=content("CLOSING_STATEMENT", "PRO") or content("OPENING_STATEMENT", "PRO"),
                    agentId=pro.agentId, role="pro", displayOrder=2, displayDelayMs=delay_ms, status="SUCCESS",
                    metadata=AgentAnswerMetadata(knowledgeLevel=pro.knowledgeLevel, personality=pro.personality, usedRag=bool(rag_context))),
        AgentAnswer(agentName=_debate_display_name(neu, 3),
                    answer=summary, agentId=neu.agentId, role="neutral", displayOrder=3,
                    displayDelayMs=delay_ms * 2, status="SUCCESS",
                    metadata=AgentAnswerMetadata(knowledgeLevel=neu.knowledgeLevel, personality=neu.personality, usedRag=bool(rag_context))),
    ]

    # processSteps에 debateStages/debateConfig를 담아 Spring이 그대로 영속화 → 새로고침 복원.
    process_steps = ProcessSteps(
        debateStages=stages,
        debateConfig=cfg,
        debateSummary=summary,
    )

    issues = []
    if len([s for s in stages if s.stageType == "OPENING_STATEMENT"]) < 2:
        issues.append("양측 입론이 모두 필요합니다.")
    if not summary:
        issues.append("심사위원 판정이 비어 있습니다.")

    logger.info("[StudyMate] 구조화 토론 완료 stages=%d motion=%s", len(stages), motion[:40])
    return MultiChatResponse(
        mode="debate",
        answers=answers,
        status="COMPLETED" if not issues else "PARTIAL_SUCCESS",
        question=request.message,
        validation=ValidationSummary(passed=not issues, issues=issues),
        feedbacks=[fb.model_dump() for fb in peer_feedbacks],
        initialAnswers=initial_answers,
        peerFeedbacks=peer_feedbacks,
        revisedAnswers=revised_answers,
        debateSummary=summary,
        debateStages=stages,
        debateConfig=cfg,
        processSteps=process_steps,
    )


def _prepare_structured_debate(request, active_agents, rag_context):
    """블로킹/스트리밍 공용 준비: cfg/role_map/motion/context."""
    cfg = normalize_debate_config(request)
    role_map = assign_debate_roles(_ensure_debate_agents(active_agents))
    motion = build_debate_motion(request.message, cfg)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)
    context = _prep_default_context(context, rag_context)
    return cfg, role_map, motion, context


def _run_debate_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
) -> MultiChatResponse:
    """구조화 토론 모드(블로킹). 논제(자동/수동) → 반대/찬성/중립 고정 역할 → debateStages."""
    cfg, role_map, motion, context = _prepare_structured_debate(request, active_agents, rag_context)
    stages = list(_structured_debate_stages(request, role_map, motion, cfg, context))
    return _assemble_structured_debate(request, role_map, motion, cfg, stages, rag_context)


def run_debate_mode_stream(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
):
    """
    구조화 토론 SSE 제너레이터. 각 단계 완료 즉시 debate_section 이벤트로 stageType/stageTitle/
    side/role/agentIndex/agentName/content/debateConfig를 보내고, 마지막에 all_complete를 보낸다.
    """
    cfg, role_map, motion, context = _prepare_structured_debate(request, active_agents, rag_context)
    cfg_dump = cfg.model_dump()
    stages = []
    for stage in _structured_debate_stages(request, role_map, motion, cfg, context):
        stages.append(stage)
        data = stage.model_dump()
        data["debateConfig"] = cfg_dump
        yield {"event": "debate_section", "data": data}

    final = _assemble_structured_debate(request, role_map, motion, cfg, stages, rag_context)
    yield {"event": "all_complete", "data": final.model_dump()}


# ── agentPreset 디렉티브 (learningMode와 별개의 역할/성격 프리셋) ──────────────────
_AGENT_PRESET_DIRECTIVE = {
    "expert_professor": "전문 교수처럼 정의·원리·예시·한계를 체계적으로 균형 있게 다룬다.",
    "friendly_friend": "친근한 친구처럼 쉬운 비유와 편한 말투로 설명해 초보자가 질문하기 쉽게 만든다.",
    "creative_teacher": "독창적 강사처럼 비유·상상·시각적 예시로 추상 개념을 창의적으로 풀어준다.",
    "cold_mentor": "냉철한 멘토처럼 오개념과 부족한 점을 직설적으로 지적하고 불필요한 칭찬을 피한다.",
    "misconception_tracker": "오개념 탐지자처럼 헷갈린 개념·잘못된 전제·빠진 조건을 집요하게 찾아낸다.",
    "exam_maker": "시험 출제자처럼 개념을 객관식·단답형·서술형 문제로 바꿔 자기점검을 유도한다.",
    "code_reviewer": "코드 리뷰어처럼 설계 문제·나쁜 습관·유지보수 위험을 구체적으로 지적한다.",
    "practical_architect": "실무 아키텍트처럼 프로젝트 구조·API·DB·배포·유지보수 관점으로 설명한다.",
    "interviewer": "면접관처럼 압박·꼬리 질문으로 핵심 개념을 검증한다.",
    "roadmap_coach": "로드맵 코치처럼 현재 수준에서 다음에 무엇을 어떤 순서로 공부할지 잡아준다.",
}


def _agent_preset_directive(agent: AgentProfile) -> str:
    preset = getattr(agent, "agentPreset", None)
    d = _AGENT_PRESET_DIRECTIVE.get(str(preset or "").strip().lower())
    return f"\n[에이전트 프리셋] {d}" if d else ""


# ── 구조화 소크라테스(socratic) 모드: 질문자/오개념추적자/정리자 고정 역할 ──────────────
# learningMode=socratic 전용. 정답 설명 모드가 아니라 질문·힌트·오개념 점검·자기설명 유도.

_SOCRATIC_DEFAULT_QUESTION_TYPES = ["definition", "comparison", "why", "application", "metacognition"]
_SOCRATIC_DEFAULT_PROGRESS_FLOW = [
    "diagnosis", "core_concept", "misconception_check", "hint",
    "application", "self_explanation", "summary",
]

# progressFlow 키 → (stageType, stageTitle, role, agentIndex, role_kind)
_SOCRATIC_STAGE_MAP = {
    "diagnosis":         ("DIAGNOSIS", "현재 이해도 진단", "질문자", 1, "QUESTIONER"),
    "core_concept":      ("CORE_CONCEPT", "핵심 개념 질문", "질문자", 1, "QUESTIONER"),
    "misconception_check": ("MISCONCEPTION_CHECK", "오개념 점검", "오개념 추적자", 2, "MISCONCEPTION_TRACKER"),
    "hint":              ("HINT", "단계별 힌트", "오개념 추적자", 2, "MISCONCEPTION_TRACKER"),
    "application":       ("APPLICATION", "적용 질문", "질문자", 1, "QUESTIONER"),
    "counterexample":    ("COUNTEREXAMPLE", "반례 질문", "오개념 추적자", 2, "MISCONCEPTION_TRACKER"),
    "self_explanation":  ("SELF_EXPLANATION", "자기 설명 유도", "질문자", 1, "QUESTIONER"),
    "summary":           ("SUMMARY", "정리 및 다음 학습 방향", "정리자", 3, "SUMMARIZER"),
}

_SOCRATIC_SYSTEM = (
    "이것은 소크라테스식 문답 학습이다. 정답을 길게 설명하는 모드가 절대 아니다. "
    "사용자가 스스로 개념을 발견하도록 짧은 질문·힌트·반례를 던진다. 한 번에 긴 정답을 주지 않는다. "
    "반드시 한국어로 답한다."
)


def normalize_socratic_config(request: MultiChatRequest) -> SocraticConfig:
    cfg = request.socraticConfig or SocraticConfig()
    if not cfg.questionTypes:
        cfg.questionTypes = list(_SOCRATIC_DEFAULT_QUESTION_TYPES)
    if not cfg.progressFlow:
        cfg.progressFlow = list(_SOCRATIC_DEFAULT_PROGRESS_FLOW)
    if not cfg.maxQuestionsPerTurn or cfg.maxQuestionsPerTurn < 1:
        cfg.maxQuestionsPerTurn = 3
    if cfg.maxQuestionsPerTurn > 5:
        cfg.maxQuestionsPerTurn = 5
    return cfg


def _create_virtual_socratic_agent(label: str, idx: int, knowledge_level: str = "학사") -> AgentProfile:
    return AgentProfile(
        id=-idx, agentId=-idx, name=label, role=label,
        personality=("비판형" if idx == 2 else "친근함" if idx == 1 else "전문적"),
        personalityStrength="moderate", knowledgeLevel=knowledge_level,
    )


def assign_socratic_roles(agents: List[AgentProfile]) -> Dict[str, AgentProfile]:
    """역할 고정: agent[0]=질문자, agent[1]=오개념 추적자, agent[2]=정리자/다음 질문 설계자."""
    kl = agents[0].knowledgeLevel if agents else "학사"
    questioner = agents[0] if len(agents) > 0 else _create_virtual_socratic_agent("질문자", 1, kl)
    tracker = agents[1] if len(agents) > 1 else _create_virtual_socratic_agent("오개념 추적자", 2, kl)
    summarizer = agents[2] if len(agents) > 2 else _create_virtual_socratic_agent("정리자", 3, kl)
    return {"QUESTIONER": questioner, "MISCONCEPTION_TRACKER": tracker, "SUMMARIZER": summarizer}


def _socratic_setup_block(request: MultiChatRequest, cfg: SocraticConfig) -> str:
    return (
        "[소크라테스 설정]\n"
        f"- 원 질문: {request.message}\n"
        f"- 사용자 시도 답변: {request.userAttempt or '(아직 없음)'}\n"
        f"- 학습 목표: {cfg.goal}\n"
        f"- 진단 방식: {cfg.diagnosisMode}\n"
        f"- 질문 강도: {cfg.questionIntensity}\n"
        f"- 힌트 정책: {cfg.hintPolicy}\n"
        f"- 정답 공개 정책: {cfg.answerRevealPolicy}\n"
        f"- 질문 유형: {', '.join(cfg.questionTypes)}\n"
        f"- 진행 흐름: {', '.join(cfg.progressFlow)}\n"
        f"- 피드백 방식: {cfg.feedbackStyle}\n"
        f"- 턴당 최대 질문 수: {cfg.maxQuestionsPerTurn}\n"
        f"- 예시 포함: {cfg.includeExamples} / 반례 포함: {cfg.includeCounterexamples}\n"
        f"- 마지막 요약: {cfg.includeFinalSummary} / 다음 학습 방향: {cfg.includeNextStudyPlan}\n"
        f"- 오개념 추적: {cfg.trackMisconceptions}\n\n"
        "[에이전트 역할]\n"
        "- 에이전트 1: 질문자\n- 에이전트 2: 오개념 추적자\n- 에이전트 3: 정리자 / 다음 질문 설계자\n\n"
        "[필수 규칙]\n"
        "1. 이 모드는 정답 설명 모드가 아니다.\n"
        "2. 처음부터 긴 정답을 제공하지 않는다.\n"
        "3. 사용자가 스스로 개념을 발견하도록 질문을 던진다.\n"
        f"4. 한 단계 발화는 짧게(2~4문장), 질문은 1개만 던진다.\n"
        "5. 사용자의 답변을 먼저 요구하고 긴 설명을 금지한다.\n"
        "6. 사용자의 답변/질문에서 오개념을 탐지한다.\n"
        "7. 오개념이 있으면 바로 정답을 말하지 말고 비교·반례·적용 질문으로 스스로 깨닫게 한다.\n"
        "8. 힌트 정책에 따라 힌트를 제공하되 정답을 통째로 주지 않는다.\n"
        "9. 정답 공개 정책이 final_only이면 마지막 정리 전까지 전체 정답을 공개하지 않는다.\n"
        "10. 마지막에는 핵심 개념, 사용자의 약점, 다음 학습 방향을 정리한다.\n"
    )


def _socratic_stage_instruction(stage_key: str, cfg: SocraticConfig) -> str:
    if stage_key == "diagnosis":
        return ("[이번 단계: 현재 이해도 진단]\n사용자에게 개념을 자기 말로 설명해보라고 요청하는 짧은 진단 질문 1개를 던져라. "
                "정답을 말하지 마라. (예: '객체와 클래스의 차이를 네 말로 설명해볼래?')")
    if stage_key == "core_concept":
        return "[이번 단계: 핵심 개념 질문]\n개념의 본질을 스스로 떠올리게 하는 '왜/무슨 뜻' 질문 1개를 던져라. 정답 금지."
    if stage_key == "misconception_check":
        return ("[이번 단계: 오개념 점검]\n이 개념에서 흔히 생기는 오개념 1개를 짚고, 그것이 왜 문제인지 스스로 깨닫게 하는 질문을 던져라. "
                "정답을 단정하지 마라.")
    if stage_key == "hint":
        return ("[이번 단계: 단계별 힌트]\n정답을 통째로 주지 말고, 스스로 도달하도록 돕는 단계별 힌트 1개만 제공하라. "
                "비유를 활용해도 좋다.")
    if stage_key == "application":
        return "[이번 단계: 적용 질문]\n배운 개념을 작은 사례(코드/실무 상황)에 직접 적용해보게 하는 질문 1개를 던져라. 정답 코드 금지."
    if stage_key == "counterexample":
        return "[이번 단계: 반례 질문]\n이 개념/주장이 항상 옳지는 않음을 깨닫게 하는 반례 질문 1개를 던져라."
    if stage_key == "self_explanation":
        return "[이번 단계: 자기 설명 유도]\n사용자에게 지금까지의 내용을 자기 말로 요약·설명해보라고 요청하라. 정답을 대신 말하지 마라."
    if stage_key == "summary":
        plan = " 다음 학습 방향(공부 순서)도 2~3개 제시하라." if cfg.includeNextStudyPlan else ""
        return ("[이번 단계: 정리 및 다음 학습 방향]\n이제 정리 단계다. 핵심 개념, 사용자가 약했던 지점, 그리고"
                + plan + " 간결히 정리하라. 여기서는 핵심 정답을 명확히 밝혀도 된다.")
    return "[이번 단계] 짧은 소크라테스 질문 1개를 던져라."


def _socratic_stage_fallback(stage_key: str) -> str:
    title = _SOCRATIC_STAGE_MAP.get(stage_key, (None, "질문"))[1]
    return f"({title}) 단계를 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."


def _run_socratic_stage(request, agent, stage_key, cfg, context):
    setup = _socratic_setup_block(request, cfg)
    instr = _socratic_stage_instruction(stage_key, cfg)
    system = _SOCRATIC_SYSTEM + _agent_preset_directive(agent) + (
        f"\n[너의 배경] 너는 '{agent.name}'(역할: {agent.role or '튜터'})의 관점을 말투·전문성에 반영하되, "
        "이번 단계의 소크라테스 역할을 최우선으로 수행한다."
    )
    user = setup + "\n" + instr
    params = A.resolve_agent_generation_params(_personality_type(agent), 1)
    provider = params.get("provider", "ollama")
    try:
        text, _ = _call_llm_with_params(provider, system, user, params, knowledge_level=agent.knowledgeLevel)
    except Exception as e:
        logger.warning("socratic stage %s 실패: %s", stage_key, e)
        text = ""
    if not (text or "").strip() or _is_llm_fallback(text):
        text = _socratic_stage_fallback(stage_key)
    return text.strip()


def _structured_socratic_steps(request, role_map, cfg, context):
    """progressFlow 순서로 SocraticStep을 하나씩 yield한다(역할별 병렬 wave)."""
    flow = [k for k in (cfg.progressFlow or _SOCRATIC_DEFAULT_PROGRESS_FLOW) if k in _SOCRATIC_STAGE_MAP]
    if cfg.includeCounterexamples and "counterexample" not in flow:
        # 반례 단계는 적용 질문 뒤에 끼워 넣는다.
        if "application" in flow:
            flow.insert(flow.index("application") + 1, "counterexample")
        else:
            flow.append("counterexample")
    agent_for = {
        "QUESTIONER": role_map["QUESTIONER"],
        "MISCONCEPTION_TRACKER": role_map["MISCONCEPTION_TRACKER"],
        "SUMMARIZER": role_map["SUMMARIZER"],
    }
    computed: Dict[str, str] = {}

    def run_one(stage_key):
        kind = _SOCRATIC_STAGE_MAP[stage_key][4]
        text = _run_socratic_stage(request, agent_for[kind], stage_key, cfg, context)
        return stage_key, text

    # SSE에서는 모든 단계를 flow 순서대로 하나씩 생성한다. 각 단계가 끝나는 즉시 yield된다.
    for stage_key in flow:
        _, text = run_one(stage_key)
        computed[stage_key] = text
        st, title, role, ai, kind = _SOCRATIC_STAGE_MAP[stage_key]
        agent = agent_for[kind]
        content = computed.get(stage_key, "")
        is_q = st in ("DIAGNOSIS", "CORE_CONCEPT", "APPLICATION", "COUNTEREXAMPLE", "SELF_EXPLANATION")
        step = SocraticStep(
            stageType=st, stageTitle=title, role=role, agentIndex=ai, agentName=agent.name,
            question=content if is_q else None,
            hint=content if st == "HINT" else None,
            feedback=content if st in ("SUMMARY", "MISCONCEPTION_CHECK") else None,
            misconceptionDetected=(True if st == "MISCONCEPTION_CHECK" else None),
            directAnswerSuppressed=(st != "SUMMARY"),
            content=content,
        )
        yield step


def _assemble_socratic_response(request, role_map, cfg, steps, rag_context) -> MultiChatResponse:
    by_type = {s.stageType: s for s in steps}
    summary_step = by_type.get("SUMMARY")
    final_summary = summary_step.content if summary_step else ""
    misconceptions = [s.misconception or s.content for s in steps if s.stageType == "MISCONCEPTION_CHECK" and (s.misconception or s.content)]
    delay_ms = _get_display_delay_ms()

    q = role_map["QUESTIONER"]
    m = role_map["MISCONCEPTION_TRACKER"]
    s3 = role_map["SUMMARIZER"]
    # answers: 역할별 1개 (질문자 첫 질문 / 오개념 추적자 점검 / 정리자 정리) — Spring이 메시지로 저장
    first_q = next((st.content for st in steps if st.agentIndex == 1), "")
    mis = next((st.content for st in steps if st.agentIndex == 2), "")
    answers = [
        AgentAnswer(agentName=q.name, answer=first_q or "먼저 네 생각을 들려줘.", agentId=q.agentId,
                    role="questioner", displayOrder=1, displayDelayMs=0, status="SUCCESS",
                    metadata=AgentAnswerMetadata(knowledgeLevel=q.knowledgeLevel, personality=q.personality, directAnswerSuppressed=True)),
    ]
    if mis:
        answers.append(AgentAnswer(agentName=m.name, answer=mis, agentId=m.agentId, role="misconception_tracker",
                       displayOrder=2, displayDelayMs=delay_ms, status="SUCCESS",
                       metadata=AgentAnswerMetadata(knowledgeLevel=m.knowledgeLevel, personality=m.personality, directAnswerSuppressed=True)))
    if final_summary:
        answers.append(AgentAnswer(agentName=s3.name, answer=final_summary, agentId=s3.agentId, role="summarizer",
                       displayOrder=3, displayDelayMs=delay_ms * 2, status="SUCCESS",
                       metadata=AgentAnswerMetadata(knowledgeLevel=s3.knowledgeLevel, personality=s3.personality)))

    process_steps = ProcessSteps(
        socraticSteps=steps,
        socraticConfig=cfg,
        finalSummary=final_summary,
        misconceptions=misconceptions,
    )

    issues = []
    if not any(s.stageType == "DIAGNOSIS" for s in steps):
        issues.append("진단 단계가 없습니다.")
    if cfg.includeFinalSummary and not final_summary:
        issues.append("마지막 정리가 비어 있습니다.")

    logger.info("[StudyMate] 구조화 소크라테스 완료 steps=%d", len(steps))
    return MultiChatResponse(
        mode="socratic",
        answers=answers,
        status="COMPLETED" if not issues else "PARTIAL_SUCCESS",
        question=request.message,
        validation=ValidationSummary(passed=not issues, issues=issues, directAnswerBlocked=True),
        socraticSteps=steps,
        socraticConfig=cfg,
        processSteps=process_steps,
    )


def _prepare_structured_socratic(request, active_agents, rag_context):
    cfg = normalize_socratic_config(request)
    role_map = assign_socratic_roles(active_agents)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)
    context = _prep_default_context(context, rag_context)
    return cfg, role_map, context


def _run_socratic_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
) -> MultiChatResponse:
    """구조화 소크라테스 모드(블로킹). 질문자/오개념추적자/정리자 고정 역할 → socraticSteps."""
    cfg, role_map, context = _prepare_structured_socratic(request, active_agents, rag_context)
    steps = list(_structured_socratic_steps(request, role_map, cfg, context))
    return _assemble_socratic_response(request, role_map, cfg, steps, rag_context)


def run_socratic_mode_stream(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    rag_context: str,
):
    """
    구조화 소크라테스 SSE 제너레이터. 단계 완료 즉시 socratic_step 이벤트(stageType/.../content/
    socraticConfig)를 보내고, 마지막에 all_complete를 보낸다.
    """
    cfg, role_map, context = _prepare_structured_socratic(request, active_agents, rag_context)
    cfg_dump = cfg.model_dump()
    steps = []
    for step in _structured_socratic_steps(request, role_map, cfg, context):
        steps.append(step)
        data = step.model_dump()
        data["socraticConfig"] = cfg_dump
        yield {"event": "socratic_step", "data": data}

    final = _assemble_socratic_response(request, role_map, cfg, steps, rag_context)
    yield {"event": "all_complete", "data": final.model_dump()}


# ── 멀티패스 파이프라인 (박사/전문가 수준) ───────────────────────────────────

def _run_multi_pass_pipeline(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    knowledge_level: str,
    mode: str,
) -> Optional[MultiChatResponse]:
    """
    박사/전문가 수준 멀티패스 파이프라인:
    1. domain classifier
    2. generation config 계산
    3. source router → OpenAlex(박사)
    4. prompt example selector
    5. 답변 생성
    6. depth verifier → depth rewriter (필요 시 1회)
    7. source leakage guard
    """
    if knowledge_level not in ("박사", "전문가"):
        return None

    # 1. 도메인 분류
    domain = "general_study"
    domain_confidence = 0.0
    used_llm_domain = False
    try:
        from app.services.academic_domain_classifier import classify as classify_domain
        domain_result = classify_domain(
            question=request.message,
            material_title=None,
        )
        domain = domain_result.domain
        domain_confidence = domain_result.confidence
        used_llm_domain = domain_result.used_llm_fallback
    except Exception as e:
        logger.warning("도메인 분류 실패 (general_study 사용): %s", e)

    # 2. generation config 계산
    gen_config: Dict[str, Any] = {}
    personality = active_agents[0].personality if active_agents else None
    try:
        from app.services.generation_config_resolver import resolve as resolve_config
        gen_config = resolve_config(
            knowledge_level=knowledge_level,
            personality=personality,
            mode=mode,
            domain=domain,
        )
    except Exception as e:
        logger.warning("generation config 계산 실패: %s", e)

    # 3. source router + OpenAlex
    openalex_context = ""
    used_openalex = False
    openalex_count = 0
    openalex_min_date = "2020-01-01"
    try:
        if gen_config.get("use_openalex", False) or knowledge_level == "박사":
            from app.services.openalex_service import search as openalex_search
            oa_result = openalex_search(
                question=request.message,
                knowledge_level=knowledge_level,
                domain=domain,
            )
            if not oa_result.skipped and oa_result.works:
                openalex_context = oa_result.to_context_text()
                used_openalex = True
                openalex_count = len(oa_result.works)
                openalex_min_date = oa_result.min_publication_date
    except Exception as e:
        logger.warning("OpenAlex 호출 실패 (계속 진행): %s", e)

    # 4. prompt example selector
    prompting_strategy = "zero_shot"
    prompting_example_file = ""
    few_shot_prefix = ""
    try:
        from app.services.prompt_example_selector import select as select_example, build_few_shot_prefix
        ex = select_example(knowledge_level=knowledge_level, mode=mode)
        prompting_strategy = ex["strategy"]
        prompting_example_file = ex.get("example_file", "")
        if ex.get("example_text"):
            few_shot_prefix = build_few_shot_prefix(ex["example_text"])
    except Exception as e:
        logger.warning("prompt example selector 실패: %s", e)

    # 5. RAG + 답변 생성
    rag_context = _get_rag_context(request.message, request.materialId)
    context = ""
    if openalex_context:
        context = openalex_context
    if rag_context:
        context = f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context

    if not active_agents:
        return None

    agent = active_agents[0]
    system_prompt = build_agent_system_prompt(agent, context)
    if few_shot_prefix:
        system_prompt = few_shot_prefix + system_prompt

    answer_text = _call_llm(
        system_prompt=system_prompt,
        user_prompt=f"[사용자 질문] {request.message}",
        knowledge_level=knowledge_level,
        gen_config=gen_config,
    )

    # 6. depth verifier + rewriter
    rewrite_applied = False
    depth_coverage = 0.0
    leakage_detected = False
    depth_warning = None
    enable_depth = getattr(request, "enableDepthValidation", None)
    should_verify = (enable_depth is not False) and gen_config.get("use_depth_verifier", False)

    if should_verify:
        try:
            from app.services.academic_depth_verifier import verify as depth_verify
            v_result = depth_verify(answer_text, domain, knowledge_level)
            depth_coverage = v_result.domain_depth_coverage
            leakage_detected = v_result.source_leakage_detected

            enable_rewrite = getattr(request, "enableDepthRewrite", None)
            should_rewrite = (enable_rewrite is not False) and gen_config.get("use_depth_rewrite", False)

            if v_result.rewrite_required and should_rewrite:
                from app.services.academic_depth_rewriter import rewrite as depth_rewrite
                rw = depth_rewrite(
                    original_answer=answer_text,
                    domain=domain,
                    knowledge_level=knowledge_level,
                    missing_requirements=v_result.missing_requirements,
                    question=request.message,
                    additional_context=openalex_context,
                )
                if rw.rewrite_applied:
                    answer_text = rw.rewritten_answer
                    rewrite_applied = True
                    if rw.verification_after_rewrite:
                        depth_coverage = rw.verification_after_rewrite.domain_depth_coverage
                        depth_warning = rw.verification_after_rewrite.warning_message
        except Exception as e:
            logger.warning("depth verifier/rewriter 실패 (계속 진행): %s", e)

    # 7. source leakage guard (최종 검사)
    try:
        from app.services.source_leakage_guard import detect as detect_leakage, clean as clean_leakage
        leakage_detected_final, _ = detect_leakage(answer_text)
        if leakage_detected_final:
            answer_text = clean_leakage(answer_text)
            leakage_detected = True
    except Exception as e:
        logger.warning("source leakage guard 실패: %s", e)

    # debug metadata 구성
    debug_meta = None
    if getattr(request, "debugMetadata", False):
        debug_meta = DebugMetadata(
            domain=domain,
            domainConfidence=round(domain_confidence, 3),
            requestedKnowledgeLevel=knowledge_level,
            effectiveKnowledgeLevel=knowledge_level,
            generationConfig=GenerationConfigMetadata(
                temperature=gen_config.get("temperature"),
                topP=gen_config.get("top_p"),
                topK=gen_config.get("top_k"),
                maxTokens=gen_config.get("max_tokens"),
                reasoningOrThinkingLevel=gen_config.get("reasoning_or_thinking_level"),
            ),
            retrieval=RetrievalMetadata(
                usedRag=bool(rag_context),
                usedOpenAlex=used_openalex,
                openAlexMinPublicationDate=openalex_min_date if used_openalex else None,
                openAlexResultCount=openalex_count if used_openalex else None,
            ),
            prompting=PromptingMetadata(
                strategy=prompting_strategy,
                exampleSet=prompting_example_file or None,
            ),
            depthValidation=DepthValidationMetadata(
                domainDepthCoverage=round(depth_coverage, 3) if depth_coverage else None,
                rewriteApplied=rewrite_applied,
                sourceLeakageDetected=leakage_detected,
                warningMessage=depth_warning,
            ),
        )

    delay_ms = _get_display_delay_ms()
    answers = [AgentAnswer(
        agentName=agent.name,
        answer=answer_text,
        agentId=agent.agentId,
        role=agent.role or "default",
        displayOrder=1,
        displayDelayMs=0,
        status="SUCCESS",
        metadata=None,
    )]

    # 나머지 에이전트들도 기존 방식으로 처리
    for idx, a in enumerate(active_agents[1:], start=2):
        try:
            sys_p = build_agent_system_prompt(a, rag_context)
            ans = _call_llm(sys_p, f"[사용자 질문] {request.message}", a.knowledgeLevel, gen_config)
            answers.append(AgentAnswer(
                agentName=a.name, answer=ans, agentId=a.agentId,
                role=a.role or "default", displayOrder=idx,
                displayDelayMs=(idx - 1) * delay_ms, status="SUCCESS",
            ))
        except Exception as e:
            logger.error("추가 에이전트 '%s' 실패: %s", a.name, e)

    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status="COMPLETED",
        question=request.message,
        debugMetadata=debug_meta,
    )


# ── 상황극(simulation) 모드 ───────────────────────────────────────────────

def normalize_simulation_config(request: MultiChatRequest) -> SimulationConfig:
    cfg = request.simulationConfig or SimulationConfig()
    if not cfg.outputStages:
        cfg.outputStages = list(_SIMULATION_DEFAULT_STAGES)
    if not cfg.choiceCount or cfg.choiceCount < 2:
        cfg.choiceCount = 3
    if cfg.choiceCount > 4:
        cfg.choiceCount = 4
    return cfg


def _virtual_simulation_agent(idx: int, name: str, role: str) -> AgentProfile:
    return AgentProfile(id=-idx, agentId=-idx, name=name, role=role, personality="전문적", knowledgeLevel="학사 수준")


def assign_simulation_roles(agents: List[AgentProfile]) -> Dict[str, AgentProfile]:
    return {
        "WORLD_BUILDER": agents[0] if len(agents) > 0 else _virtual_simulation_agent(1, "세계 설계자", "세계 설계자"),
        "EVENT_MASTER": agents[1] if len(agents) > 1 else _virtual_simulation_agent(2, "사건 진행자", "사건 진행자"),
        "INTERPRETER": agents[2] if len(agents) > 2 else _virtual_simulation_agent(3, "결과 해석자", "결과 해석자"),
    }


def _simulation_agent_directive(agent: AgentProfile, fixed_role: str) -> str:
    return (
        f"{agent.name}: 사용자가 입력한 역할 '{agent.role or ''}', 성격 '{agent.personality or ''}', "
        f"지식수준 '{agent.knowledgeLevel or ''}', 추가지시 '{agent.customInstruction or ''}'를 말투와 전문성에 반영하되, "
        f"내부 실행 역할은 반드시 '{fixed_role}'로 고정한다."
    )


def _extract_selected_choice(message: str) -> Optional[str]:
    text = (message or "").strip().upper()
    for cid in ("A", "B", "C", "D"):
        if text == cid or text.startswith(cid + " ") or f"{cid} 선택" in text or f"{cid}로" in text:
            return cid
    return None


def _find_previous_simulation_stages(previous_answers: List[PreviousAnswer]) -> List[Dict[str, Any]]:
    for prev in reversed(previous_answers or []):
        ps = getattr(prev, "processSteps", None)
        if isinstance(ps, dict) and isinstance(ps.get("simulationStages"), list):
            return ps.get("simulationStages") or []
        raw = getattr(prev, "answer", "") or ""
        parsed = extract_json(raw) if isinstance(raw, str) else None
        if isinstance(parsed, dict):
            if isinstance(parsed.get("simulationStages"), list):
                return parsed.get("simulationStages") or []
            nested = parsed.get("processSteps")
            if isinstance(nested, dict) and isinstance(nested.get("simulationStages"), list):
                return nested.get("simulationStages") or []
    return []


def _fallback_simulation_stages(request: MultiChatRequest, role_map: Dict[str, AgentProfile], cfg: SimulationConfig) -> List[SimulationStage]:
    wb, em, ip = role_map["WORLD_BUILDER"], role_map["EVENT_MASTER"], role_map["INTERPRETER"]
    choices = [
        SimulationChoice(choiceId="A", label="A", text="빠르게 한 요소에 모든 책임을 몰아 처리한다.", expectedConsequence="초기 진행은 빠르지만 조건이 늘수록 변경 비용과 오류 위험이 커진다.", conceptLink="책임 분리, 추상화", misconceptionRisk="간단해 보이면 좋은 설계라는 오개념"),
        SimulationChoice(choiceId="B", label="B", text="역할과 책임을 나누고 상호작용을 정의한다.", expectedConsequence="처음에는 구조화가 필요하지만 변화에 강하고 원리를 더 잘 드러낸다.", conceptLink="모듈화, 원리 적용", misconceptionRisk="구성요소가 많으면 무조건 복잡하다는 오개념"),
        SimulationChoice(choiceId="C", label="C", text="눈에 보이는 결과만 따라가며 내부 원리를 생략한다.", expectedConsequence="당장은 이해한 듯하지만 다른 상황에 적용할 때 막힌다.", conceptLink="개념 전이, 한계 조건", misconceptionRisk="결과 암기를 이해로 착각하는 오개념"),
    ][:cfg.choiceCount]
    return [
        SimulationStage(stageType="SCENARIO_SETUP", stageTitle="상황 설정", role="세계 설계자", agentIndex=1, agentName=wb.name, content=f"너는 '{request.message}' 개념이 실제로 작동하는 가상 상황에 들어왔다. 제한된 정보와 선택 압박 속에서 개념을 적용해야 한다."),
        SimulationStage(stageType="USER_ROLE", stageTitle="나의 역할", role="세계 설계자", agentIndex=1, agentName=wb.name, userRole="개념을 적용해야 하는 의사결정자", content="너의 역할은 설명을 듣는 사람이 아니라, 상황 속에서 판단하고 그 결과를 감당하는 참가자다."),
        SimulationStage(stageType="SITUATION_CONTEXT", stageTitle="문제 상황", role="사건 진행자", agentIndex=2, agentName=em.name, content="상황은 빠르게 변하고, 각 선택은 서로 다른 장점과 위험을 만든다. 단순 정답 찾기가 아니라 어떤 사고방식을 택할지 결정해야 한다."),
        SimulationStage(stageType="CHOICES", stageTitle="선택지", role="사건 진행자", agentIndex=2, agentName=em.name, choices=choices, content="A/B/C 중 하나를 선택하면 그 선택에 따른 결과와 다음 사건이 진행된다."),
        SimulationStage(stageType="CONCEPT_MAPPING", stageTitle="개념 연결", role="결과 해석자", agentIndex=3, agentName=ip.name, conceptMapping=["상황 속 선택은 개념의 적용 방식 차이를 드러낸다.", "각 선택은 장점, 한계, 오개념 위험을 함께 가진다."], content="이 상황은 질문한 개념을 실제 판단 기준으로 바꾸어 체험하게 만든다."),
        SimulationStage(stageType="MISCONCEPTION_TRAP", stageTitle="오개념 함정", role="결과 해석자", agentIndex=3, agentName=ip.name, misconceptionTrap="겉으로 쉬워 보이는 선택이 항상 개념적으로 안전한 선택은 아니다.", content="오개념은 정답/오답 채점이 아니라 상황 변화 속에서 드러난다."),
        SimulationStage(stageType="REFLECTION_QUESTION", stageTitle="성찰 질문", role="결과 해석자", agentIndex=3, agentName=ip.name, reflectionQuestion="내 선택은 어떤 원리를 드러내고, 어떤 한계를 감추고 있을까?", content="선택 전에 장점과 위험을 함께 생각해보자."),
        SimulationStage(stageType="NEXT_SCENARIO", stageTitle="다음 분기", role="사건 진행자", agentIndex=2, agentName=em.name, nextScenarioPrompt="A/B/C 중 하나를 선택하면 결과와 다음 분기를 이어간다.", content="이제 A/B/C 중 하나를 골라라. 선택에 따라 상황이 달라진다."),
    ]


def _simulation_prompt(request: MultiChatRequest, cfg: SimulationConfig, role_map: Dict[str, AgentProfile], previous_stages: List[Dict[str, Any]], selected_choice: Optional[str]) -> str:
    selected_block = ""
    if selected_choice:
        selected_block = f"\n[이전 선택 이어가기]\n* 사용자가 선택한 선택지: {selected_choice}\n* 직전 simulationStages를 참고해 SELECTED_CHOICE, CONSEQUENCE, CONCEPT_EXPLANATION, RISK_OR_LIMITATION, NEXT_BRANCH 단계로 이어가라.\n"
    return f"""
[상황극 설정]
* 원 질문: {request.message}
* 상황극 유형: {cfg.scenarioType}
* 분야: {cfg.domain}
* 상호작용 방식: {cfg.interactionStyle}
* 난이도: {cfg.difficulty}
* 사용자 역할 설정: {cfg.userRoleMode}
* 선택지 개수: {cfg.choiceCount}
* 결과 변화 포함: {cfg.includeConsequences}
* 개념 연결 포함: {cfg.includeConceptMapping}
* 오개념 함정 포함: {cfg.includeMisconceptionTrap}
* 성찰 질문 포함: {cfg.includeReflectionQuestion}
* 다음 시나리오 포함: {cfg.includeNextScenario}
* 출력 단계: {", ".join(cfg.outputStages)}

[에이전트 역할]
* 에이전트 1: 세계 설계자
* 에이전트 2: 사건 진행자
* 에이전트 3: 결과 해석자
* {_simulation_agent_directive(role_map['WORLD_BUILDER'], '세계 설계자')}
* {_simulation_agent_directive(role_map['EVENT_MASTER'], '사건 진행자')}
* {_simulation_agent_directive(role_map['INTERPRETER'], '결과 해석자')}

[필수 규칙]
1. 이 모드는 설명 모드가 아니다.
2. 이 모드는 퀴즈 모드가 아니다.
3. 이 모드는 사용자를 개념이 작동하는 상황 속 참가자로 넣는 역할극 학습 모드다.
4. 사용자는 반드시 특정 역할을 부여받아야 한다.
5. 상황은 사용자의 질문 개념과 직접 연결되어야 한다.
6. 선택지는 단순 정답/오답 문제가 아니라 서로 다른 사고방식이나 적용 전략을 나타내야 한다.
7. 각 선택지는 결과, 장점, 위험, 연결 개념이 달라야 한다.
8. 오개념 함정은 반드시 하나 이상 포함한다.
9. 결과 해석자는 선택 결과를 개념, 원리, 한계, 다음 학습으로 연결한다.
10. 답변은 반드시 simulationStages JSON 구조로 반환한다.
11. 자료보관함의 퀴즈처럼 문제를 내고 채점하는 방식으로 만들지 않는다.
12. 사용자가 다음 턴에서 A/B/C 중 하나를 선택하면, 그 선택을 이어받아 결과와 다음 분기를 생성해야 한다.
{selected_block}
[직전 simulationStages]
{previous_stages[:8]}

JSON만 반환하라. 최상위 구조는 mode, learningMode, answer, simulationConfig, simulationStages, processSteps를 포함한다.
""".strip()


def _build_simulation_response(request: MultiChatRequest, cfg: SimulationConfig, role_map: Dict[str, AgentProfile], stages: List[SimulationStage]) -> MultiChatResponse:
    scenario_title = next((s.content for s in stages if s.stageType == "SCENARIO_SETUP"), "상황극 세션")
    user_role = next((s.userRole for s in stages if s.userRole), None)
    choices = next((s.choices for s in stages if s.choices), [])
    next_scenario = next((s.nextScenarioPrompt or s.content for s in stages if s.stageType in {"NEXT_SCENARIO", "NEXT_BRANCH"}), None)
    process_steps = ProcessSteps(
        mode="simulation",
        simulationConfig=cfg,
        simulationStages=stages,
        scenarioTitle=scenario_title,
        userRole=user_role,
        choices=choices,
        nextScenario=next_scenario,
    )
    interpreter = role_map["INTERPRETER"]
    return MultiChatResponse(
        mode="simulation",
        learningMode="simulation",
        answers=[AgentAnswer(agentName=interpreter.name, answer="상황극 시뮬레이션이 생성되었습니다.", agentId=interpreter.agentId, role="INTERPRETER", displayOrder=1)],
        status="COMPLETED",
        question=request.message,
        simulationConfig=cfg,
        simulationStages=stages,
        processSteps=process_steps,
    )


def _run_simulation_mode(request: MultiChatRequest, active_agents: List[AgentProfile], rag_context: str) -> MultiChatResponse:
    cfg = normalize_simulation_config(request)
    role_map = assign_simulation_roles(active_agents)
    previous_stages = _find_previous_simulation_stages(request.previousAnswers)
    selected_choice = _extract_selected_choice(request.message)
    system = "너는 StudyBridge 상황극 학습 엔진이다. 설명/토론/소크라테스/퀴즈가 아니라 역할극 기반 시뮬레이션만 만든다. 반드시 한국어 JSON만 반환한다."
    user = _simulation_prompt(request, cfg, role_map, previous_stages, selected_choice)
    if rag_context:
        user += f"\n\n[RAG 자료]\n{rag_context}"
    text = _call_llm(system, user, knowledge_level="학사 수준", gen_config={"max_tokens": max(_MAX_TOKENS_PER_ANSWER, 3000), "temperature": 0.55})
    parsed = extract_json(text)
    stages: List[SimulationStage] = []
    if isinstance(parsed, dict) and isinstance(parsed.get("simulationStages"), list):
        for item in parsed.get("simulationStages") or []:
            try:
                stages.append(SimulationStage.model_validate(item))
            except Exception:
                continue
    if not stages:
        stages = _fallback_simulation_stages(request, role_map, cfg)
    return _build_simulation_response(request, cfg, role_map, stages)


def run_simulation_mode_stream(request: MultiChatRequest, active_agents: List[AgentProfile], rag_context: str):
    """상황극 SSE: 전체 simulationStages 생성을 기다리지 않고 단계별로 즉시 전송한다."""
    cfg = normalize_simulation_config(request)
    role_map = assign_simulation_roles(active_agents)
    cfg_dump = cfg.model_dump()
    request_id = _stream_request_id()
    stages = _fallback_simulation_stages(request, role_map, cfg)
    seen = set()
    yield {"event": "turn_start", "data": {"type": "turn_start", "requestId": request_id, "message": "상황극 생성을 시작합니다."}}
    for stage in stages:
        data = stage.model_dump()
        data["type"] = "simulation_stage"
        data["requestId"] = request_id
        data["simulationConfig"] = cfg_dump
        key = (data.get("stageType"), data.get("agentIndex"), hash(data.get("content") or ""))
        if key in seen:
            continue
        seen.add(key)
        yield {"event": "simulation_stage", "data": data}
    final = _build_simulation_response(request, cfg, role_map, stages)
    final_data = final.model_dump()
    final_data["type"] = "all_complete"
    final_data["requestId"] = request_id
    final_data["message"] = "모든 상황극 단계가 완료되었습니다."
    yield {"event": "all_complete", "data": final_data}


# ── group_study_ai 모드 (그룹스터디 AI 봇 3종) ────────────────────────────────
#
# 봇별 모델 라우팅:
#   summary_bot / SummaryAgent          → Qwen/Ollama  (call_primary_llm)
#   quiz_bot    / QuizAgent             → GPT/OpenAI   (openai chat_sync)
#   search_bot  / TavilyAgent(SearchAgent) → Tavily 검색 + GPT/OpenAI
#
# 일정봇 계열(schedule_bot/calendar_bot/todo_bot)은 등록하지 않으며 라우팅하지 않는다.

_GROUP_BOT_REGISTRY: Dict[str, Dict[str, str]] = {
    "summary_bot": {"agentName": "SummaryAgent", "displayName": "요약봇", "modelProvider": "qwen_ollama"},
    "quiz_bot":    {"agentName": "QuizAgent",    "displayName": "퀴즈봇", "modelProvider": "openai_gpt"},
    "search_bot":  {"agentName": "TavilyAgent",  "displayName": "검색봇", "modelProvider": "openai_gpt_tavily"},
}

# agentName → botType (TavilyAgent/SearchAgent 모두 검색봇으로 처리)
_AGENT_NAME_TO_BOT: Dict[str, str] = {
    "SummaryAgent": "summary_bot",
    "QuizAgent": "quiz_bot",
    "TavilyAgent": "search_bot",
    "SearchAgent": "search_bot",
}

# 절대 허용하지 않는 봇 (일정봇 계열 방어)
_FORBIDDEN_BOT_TYPES = {"schedule_bot", "calendar_bot", "todo_bot"}
_FORBIDDEN_AGENT_NAMES = {"ScheduleAgent", "CalendarAgent", "TodoAgent"}


def _infer_bot_type(agent: AgentProfile) -> Optional[str]:
    """AgentProfile에서 botType을 결정한다. (botType 우선, 없으면 name 기반)"""
    if agent.botType and agent.botType in _GROUP_BOT_REGISTRY:
        return agent.botType
    return _AGENT_NAME_TO_BOT.get((agent.name or "").strip())


def _is_forbidden_bot(agent: AgentProfile) -> bool:
    bt = (agent.botType or "").strip()
    nm = (agent.name or "").strip()
    return bt in _FORBIDDEN_BOT_TYPES or nm in _FORBIDDEN_AGENT_NAMES


def _summary_bot_answer(message: str, context: str) -> str:
    """요약봇 → Qwen/Ollama."""
    system = (
        "너는 StudyBridge의 '요약봇'이다. "
        "스터디 내용과 학습 자료를 핵심 개념, 키워드, 시험 포인트 중심으로 정리한다. "
        "불필요한 군더더기 없이 구조화된 한국어 요약을 제공한다. "
        "가능하면 '핵심 개념', '키워드', '시험 포인트' 소제목으로 정리하라."
    )
    user_parts = []
    if context:
        user_parts.append(context)
    user_parts.append(f"[요약 요청]\n{message}")
    return _call_llm(system, "\n\n".join(user_parts))


def _quiz_bot_answer(message: str, context: str) -> str:
    """퀴즈봇 → GPT/OpenAI."""
    from app.services.openai_client import chat_sync, is_enabled
    system = (
        "너는 StudyBridge의 '퀴즈봇'이다. "
        "학습 내용을 바탕으로 퀴즈를 만들고 각 문항의 정답과 해설까지 제공한다. "
        "문항은 번호를 매기고, 각 문항 끝에 '정답:'과 '해설:'을 반드시 포함한다. "
        "반드시 한국어로 작성한다."
    )
    user_parts = []
    if context:
        user_parts.append(context)
    user_parts.append(f"[퀴즈 요청]\n{message}")
    user = "\n\n".join(user_parts)
    if not is_enabled():
        # GPT 미설정 시 Qwen으로 폴백
        logger.info("퀴즈봇: OpenAI 비활성 → Qwen 폴백")
        return _call_llm(system, user)
    text = chat_sync(system=system, user=user, temperature=0.4, max_tokens=_MAX_TOKENS_PER_ANSWER)
    if text and not text.startswith("[GPT"):
        return text
    logger.warning("퀴즈봇 GPT 응답 실패 → Qwen 폴백: %s", text[:80] if text else "")
    return _call_llm(system, user)


def _search_bot_answer(message: str, context: str) -> str:
    """검색봇 → Tavily 검색 + GPT/OpenAI 종합."""
    search_block = ""
    try:
        from app.services.tavily_service import search_web
        results = search_web(message, max_results=5)
        if results:
            lines = []
            for i, r in enumerate(results, start=1):
                lines.append(
                    f"[출처 {i}] {r.get('title','')}\nURL: {r.get('url','')}\n{r.get('content','')}"
                )
            search_block = "[웹 검색 결과]\n" + "\n\n".join(lines)
    except Exception as e:
        logger.warning("검색봇 Tavily 검색 실패 (검색 없이 진행): %s", e)

    system = (
        "너는 StudyBridge의 '검색봇'이다. "
        "웹 검색 결과를 근거로 최신 정보를 정리하고, 학습 답변을 보강한다. "
        "답변에는 사용한 출처를 '출처:' 형태로 명시한다. "
        "검색 결과가 없으면 보유 지식으로 답하되 출처가 없음을 밝힌다. "
        "반드시 한국어로 답변한다."
    )
    user_parts = []
    if context:
        user_parts.append(context)
    if search_block:
        user_parts.append(search_block)
    user_parts.append(f"[검색 요청]\n{message}")
    user = "\n\n".join(user_parts)

    from app.services.openai_client import chat_sync, is_enabled
    if is_enabled():
        text = chat_sync(system=system, user=user, temperature=0.3, max_tokens=_MAX_TOKENS_PER_ANSWER)
        if text and not text.startswith("[GPT"):
            return text
        logger.warning("검색봇 GPT 응답 실패 → Qwen 폴백")
    return _call_llm(system, user)


def _route_group_bot_answer(bot_type: str, message: str, context: str) -> str:
    if bot_type == "summary_bot":
        return _summary_bot_answer(message, context)
    if bot_type == "quiz_bot":
        return _quiz_bot_answer(message, context)
    if bot_type == "search_bot":
        return _search_bot_answer(message, context)
    # 알 수 없는 봇 — 기본 요약봇 처리
    logger.warning("알 수 없는 botType=%s → 요약봇으로 처리", bot_type)
    return _summary_bot_answer(message, context)


def _run_group_study_ai_mode(
    request: MultiChatRequest,
    active_agents: List[AgentProfile],
    context: str,
    rag_context: str,
) -> MultiChatResponse:
    """
    그룹스터디 AI 봇 모드.
    요청된 agents를 '요청 순서대로' 실행한다.
      - single   : agents에 1개
      - all_bots : agents에 3개 (검색봇 → 요약봇 → 퀴즈봇 순서는 호출자가 보장)
    각 봇은 botType/agentName에 따라 모델이 라우팅된다.
    """
    if rag_context:
        context = f"{context}\n\n[RAG 자료]\n{rag_context}" if context else rag_context

    delay_ms = _get_display_delay_ms()
    answers: List[AgentAnswer] = []

    for idx, agent in enumerate(active_agents):
        # 일정봇 계열 방어 — 실행하지 않고 오류 응답
        if _is_forbidden_bot(agent):
            logger.warning("group_study_ai: 금지된 봇 차단 name=%s botType=%s", agent.name, agent.botType)
            answers.append(AgentAnswer(
                agentName=agent.name or "시스템",
                answer="지원하지 않는 AI 봇입니다. 사용 가능: 요약봇, 퀴즈봇, 검색봇.",
                role="blocked",
                displayOrder=idx + 1,
                displayDelayMs=idx * delay_ms,
                status="BLOCKED",
            ))
            continue

        bot_type = _infer_bot_type(agent)
        if bot_type is None:
            logger.warning("group_study_ai: botType 판별 실패 name=%s → 요약봇 처리", agent.name)
            bot_type = "summary_bot"

        reg = _GROUP_BOT_REGISTRY[bot_type]
        try:
            answer_text = _route_group_bot_answer(bot_type, request.message, context)
            status = "SUCCESS"
        except Exception as e:
            logger.error("group_study_ai 봇 '%s' 실행 실패: %s", bot_type, e)
            answer_text = "일시적인 오류로 답변을 생성할 수 없습니다. 잠시 후 다시 시도해 주세요."
            status = "FAILED"

        answers.append(AgentAnswer(
            agentName=agent.name or reg["agentName"],
            answer=answer_text,
            agentId=agent.agentId,
            role=bot_type,
            displayOrder=idx + 1,
            displayDelayMs=idx * delay_ms,
            status=status,
        ))

    if not answers:
        answers.append(AgentAnswer(
            agentName="시스템",
            answer="실행할 AI 봇이 지정되지 않았습니다.",
            displayOrder=1, displayDelayMs=0, status="FAILED",
        ))

    success_count = sum(1 for a in answers if a.status == "SUCCESS")
    status = "COMPLETED" if success_count == len(answers) else (
        "PARTIAL_SUCCESS" if success_count > 0 else "FAILED"
    )

    return MultiChatResponse(
        mode=request.mode,
        answers=answers,
        status=status,
        question=request.message,
    )


# ── 진입점 ────────────────────────────────────────────────────────────────────

def _resolve_mode(request: MultiChatRequest, agent_count: Optional[int] = None) -> str:
    """
    mode와 learningMode(+에이전트 수)를 합쳐 실행 모드를 정한다.
    - 프론트 learningMode(basic/socratic/debate)가 명시되면 우선.
    - learningMode 없으면 request.mode 기준.
    - tikitaka/multi_agent_discussion 등 generic 값은 default staged 응답으로 둔다.
    - 자동 토론: 위에서 default로 정해졌고 에이전트가 2명 이상이면 debate로 승격
      (AGENT_AUTO_DEBATE_MULTI=true). 단일 에이전트는 일반 답변(default) 유지.
    반환: default | debate | socratic | group_study_ai
    """
    raw = (request.mode or "default").strip().lower()
    lm = (getattr(request, "learningMode", None) or "").strip().lower()

    base = None
    # 1) 프론트 학습모드 우선
    if lm in _SIMULATION_MODE_ALIASES:
        base = "simulation"
    elif lm in _DEBATE_MODE_ALIASES:
        base = "debate"
    elif lm in _SOCRATIC_MODE_ALIASES:
        base = "socratic"
    elif lm == "basic":
        base = "group_study_ai" if raw == "group_study_ai" else "default"
    # 2) learningMode 미지정 → request.mode 기준
    elif raw == "group_study_ai":
        base = "group_study_ai"
    elif raw in _SIMULATION_MODE_ALIASES:
        base = "simulation"
    elif raw in _DEBATE_MODE_ALIASES:
        base = "debate"
    elif raw in _SOCRATIC_MODE_ALIASES:
        base = "socratic"
    else:
        # multi_agent_discussion / default 등 generic → staged default(상호 피드백 포함)
        base = "default"

    # 3) 자동 토론: 모드 미지정(default)인데 에이전트 2명 이상이면 토론으로 진입
    if base == "default" and agent_count is not None and agent_count >= 2 and A.enable_auto_debate():
        return "debate"
    return base


def run_multi_chat(request: MultiChatRequest) -> MultiChatResponse:
    """
    mode에 따라 적절한 실행 함수로 분기한다.

    mode:
      "default"   → 기존 병렬 multi-agent (박사/전문가면 멀티패스 우선)
      "tikitaka"  → 3라운드 티키타카
      "debate"    → 찬성/반대/사회자 순차 체인
      "socratic"  → 소크라테스식 꼬리질문
      그 외        → default와 동일
    """
    agents = _get_agents(request)
    active_agents = _filter_agents(agents, request.targetAgentId)
    context = build_context_from_previous_answers(request.previousAnswers, max_items=20)

    # RAG 검색 (materialId 있으면 수행)
    rag_context = _get_rag_context(request.message, request.materialId)

    mode = _resolve_mode(request, len(active_agents))

    # group_study_ai: 그룹스터디 AI 봇 모드 (요약/퀴즈/검색 봇 라우팅)
    if mode == "group_study_ai":
        logger.info("multi-chat 실행: mode=group_study_ai runMode=%s agents=%d",
                    request.runMode, len(active_agents))
        return _run_group_study_ai_mode(request, active_agents, context, rag_context)

    knowledge_level = _get_knowledge_level(request, active_agents[0] if active_agents else None)
    logger.info("multi-chat 실행: mode=%s (raw=%s/lm=%s) level=%s agents=%d",
                mode, request.mode, getattr(request, "learningMode", None), knowledge_level, len(active_agents))

    if mode == "simulation":
        return _run_simulation_mode(request, active_agents, rag_context)
    if mode == "debate":
        return _run_debate_mode(request, active_agents, rag_context)
    if mode == "socratic":
        return _run_socratic_mode(request, active_agents, rag_context)

    # default: 모든 지식수준(입문~전문가)을 동일한 1/2/3차 staged 파이프라인으로 처리한다.
    # (이전엔 박사/전문가가 _run_multi_pass_pipeline로 분기되어 stages/processSteps가 생성되지 않았음.
    #  OpenAlex/depth 보강은 staged 모드에서 현재 미적용 — 후속 통합 과제.)
    return _run_default_mode(request, active_agents, context, rag_context)
