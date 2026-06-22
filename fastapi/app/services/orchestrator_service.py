"""
멀티 에이전트 오케스트레이터 서비스.

설계 원칙:
  - 하나의 시스템 프롬프트로 Qwen 14B에 "누가, 무슨 성격으로, 어떤 순서로 답하는지"를 지시한다.
  - 모드(기본/토론/소크라테스/상황극)에 따라 프롬프트가 완전히 달라진다.
  - JSON 파싱 실패 시 안전 폴백한다.
  - 기존 Spring Boot ↔ FastAPI 통신 계약(agentId, agentName, answer 등)을 유지한다.
"""
import json
import logging
import os
import re
import time
import urllib.request
import urllib.parse
from typing import Any, Dict, Generator, List, Optional

from app.schemas.multi_chat_schema import (
    AgentAnswer,
    AgentProfile,
    MultiChatRequest,
    MultiChatResponse,
    PreviousAnswer,
)

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1) 에이전트 정보 → 프롬프트용 JSON
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _agents_to_json_list(agents: List[AgentProfile]) -> List[Dict[str, Any]]:
    result = []
    for a in agents:
        result.append({
            "id": a.agentId or f"agent-{a.id}",
            "이름": a.name,
            "유형": a.role or "학습 지원",
            "답변 톤": (
                a.personality
                or getattr(a, "personalityLabel", None)
                or getattr(a, "tone", None)
                or getattr(a, "style", None)
                or "친절형"
            ),
            "학습자 수준": (
                a.knowledgeLevel
                or getattr(a, "knowledgeLevelLabel", None)
                or "학사 수준"
            ),
            "추가요청": (
                getattr(a, "customInstruction", None)
                or getattr(a, "custom_instruction", None)
                or getattr(a, "persona", None)
                or ""
            ),
        })
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2) 모드별 시스템 프롬프트 빌더
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _common_header(agents_json: str) -> str:
    """모든 모드에 공통으로 들어가는 프롬프트 헤더."""
    return f"""[역할]
당신은 '멀티 에이전트 스터디룸'의 오케스트레이터(총괄 감독)입니다.

[절대 규칙]
- 각 에이전트는 부여받은 성격(톤)을 답변 전체에 걸쳐 반드시 유지해야 한다.
- 냉소적이면 실제로 비꼬듯 말하고, 친절하면 따뜻하게 말하라. 밋밋하게 통일하지 마라.
- 질문에 대해 직접 답변하라. "교과서를 참고하세요" 같은 회피성 답변 금지.
- **모든 답변은 매우 상세하고 깊이 있게 작성하라. 단답형을 절대 피하고, 충분한 분량으로 풍부한 지식과 논리를 전개하라.**
- 이전 대화 내역이 주어질 경우, 문맥을 자연스럽게 이어가며 흐름이 끊기지 않게 답변하라.
- 모든 답변은 한국어로 작성한다.

[참여 중인 AI 메이트]
{agents_json}"""


def _output_format() -> str:
    """공통 JSON 출력 형식 지시."""
    return """
[출력 형식]
반드시 아래 형식의 유효한 JSON 배열만 출력하세요. 마크다운 백틱(```), 설명, 머리말, 꼬리말 전부 금지.

[
  {
    "agentId": "에이전트 id",
    "agentName": "에이전트 이름",
    "answer": "해당 에이전트의 답변 (마크다운 지원)"
  }
]"""


def build_basic_prompt(agents: List[AgentProfile]) -> str:
    """기본 설명 모드: 질문에 답 + 에이전트 간 상호 피드백."""
    agents_json = json.dumps(_agents_to_json_list(agents), ensure_ascii=False, indent=2)
    return f"""{_common_header(agents_json)}

[모드: 기본 설명 + 상호 피드백]
이 모드의 핵심은 "정확하고 압도적으로 풍부한 개념 설명"입니다.
1. 질문의 맥락에 가장 적합한 1~3명의 에이전트가 먼저 답변한다.
2. 설명 시 전문적인 비유, 구체적인 코드/실무 예시, 동작 원리를 상세히 풀어서 다루어야 한다.
3. 두 번째 이후 에이전트는 앞 에이전트의 답변을 참조하여 심화된 내용을 덧붙이거나 보완한다.
   - 예: "친절봇이 개념을 설명했으니, 저는 실제 활용 사례와 주의점을 추가로 말씀드릴게요~"
4. 마지막 에이전트는 앞선 답변들의 허점이나 놓친 부분을 날카롭게 검증(피드백)한다.
5. 각 에이전트의 성격이 답변 톤에 분명히 드러나야 하며, 대화가 유기적으로 엮여야 한다.
{_output_format()}"""


def build_debate_prompt(agents: List[AgentProfile]) -> str:
    """토론 모드: 찬반 입장으로 논쟁."""
    agents_json = json.dumps(_agents_to_json_list(agents), ensure_ascii=False, indent=2)
    n = len(agents)
    role_assign = ""
    if n >= 3:
        role_assign = f"""
- "{agents[0].name}"은 찬성 입장을 맡는다.
- "{agents[1].name}"은 반대 입장을 맡는다.
- "{agents[2].name}"은 중립 심판/정리 역할을 맡는다."""
    elif n == 2:
        role_assign = f"""
- "{agents[0].name}"은 찬성 입장을 맡는다.
- "{agents[1].name}"은 반대 입장을 맡는다."""
    else:
        role_assign = f"""
- "{agents[0].name}"이 찬반 양쪽 논점을 모두 제시한다."""

    return f"""{_common_header(agents_json)}

[모드: 토론]
이 모드에서는 에이전트들이 주제에 대해 서로 다른 입장에서 치열하고 심도 있게 논쟁한다.

[역할 배정]
{role_assign}

[토론 흐름 규칙]
1. 찬성 에이전트가 먼저 자신의 입장과 탄탄한 논리적 근거, 예시를 상세히 제시한다.
2. 반대 에이전트가 찬성 측의 주장을 직접 인용하며 날카롭고 길게 반박한다.
   - "~라고 했는데, 그건 ~한 이유로 치명적인 결함이 있다" 식으로 구체적으로 반론을 펼쳐라.
3. 중립 에이전트(있을 경우)가 양측 논점을 종합적으로 정리하고, 두 관점을 모두 아우르는 통찰이나 빠진 관점을 보충한다.
4. 각 에이전트의 성격이 논쟁 스타일에 분명히 반영되어야 한다.
   - 냉소적이면 상대 논거의 허점을 비꼬며 찌르고, 친절하면 부드럽게 설득한다.
5. 단순히 각자 의견만 나열하지 마라. 반드시 상대방 발언의 핵심을 정확히 찌르며 풍성한 대화를 만들어라.
{_output_format()}"""


def build_socratic_prompt(agents: List[AgentProfile]) -> str:
    """소크라테스 모드: 답을 주지 않고 질문으로 유도."""
    agents_json = json.dumps(_agents_to_json_list(agents), ensure_ascii=False, indent=2)
    return f"""{_common_header(agents_json)}

[모드: 소크라테스 문답법]
이 모드에서는 정답을 바로 주지 않고, 사용자가 스스로 깨달을 수 있도록 깊은 사고를 유도한다.

[소크라테스 규칙]
1. 에이전트는 정답을 직접 말하지 않는다.
2. 대신 사용자의 사고를 확장시키는 날카롭고 깊이 있는 꼬리 질문과 반례를 상세히 제시한다.
   - "그러면 ~한 예외적인 상황에서도 그게 성립할까? 예를 들어..."
   - "~의 근본적인 원리가 무엇이라고 생각하시나요?"
3. 답변의 70% 이상이 질문이어야 한다. 설명은 사용자가 길을 잃지 않도록 돕는 충분한 배경지식 힌트 수준으로 제공한다.
4. 여러 에이전트가 참여할 경우, 앞 에이전트의 질문 방향을 이어받아 더 복잡하고 고차원적인 질문으로 발전시킨다.
5. 각 에이전트의 성격에 따라 질문 스타일이 달라야 한다.
   - 친절한 에이전트: "지금까지 아주 잘 접근했어요! 혹시 이런 측면도 고려해볼 수 있을까요?"
   - 냉소적인 에이전트: "그게 다라고 생각하는 건 아니지? 이 한계점을 설명해볼 수 있어?"
   - 논리적인 에이전트: "제시한 전제에 따르면 모순이 발생합니다. 조건 X를 추가하면 어떻게 변할까요?"
{_output_format()}"""


def build_simulation_prompt(agents: List[AgentProfile]) -> str:
    """상황극 모드: 가상 시나리오 역할극."""
    agents_json = json.dumps(_agents_to_json_list(agents), ensure_ascii=False, indent=2)
    return f"""{_common_header(agents_json)}

[모드: 상황극]
이 모드에서는 질문 주제와 관련된 가상 시나리오를 만들고, 에이전트들이 그 속의 인물이 된다.

[상황극 규칙]
1. 첫 번째 에이전트가 시나리오를 설정한다: 상황 배경, 등장인물, 사용자의 역할.
2. 나머지 에이전트들은 시나리오 속 인물이 되어 대사를 말한다.
3. 마지막에 사용자에게 선택지나 행동을 요구하는 질문을 던진다.
4. 각 에이전트의 성격이 캐릭터 연기에 반영되어야 한다.
{_output_format()}"""


def build_system_prompt(mode: str, agents: List[AgentProfile]) -> str:
    """모드에 따라 적절한 시스템 프롬프트를 반환한다."""
    m = (mode or "basic").strip().lower()
    if m in ("debate", "토론", "토론 모드"):
        return build_debate_prompt(agents)
    if m in ("socratic", "소크라테스", "소크라테스 모드"):
        return build_socratic_prompt(agents)
    if m in ("simulation", "상황극", "상황극 모드", "situation", "roleplay"):
        return build_simulation_prompt(agents)
    return build_basic_prompt(agents)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3) LLM JSON 응답 파싱 (에러 핸들링 포함)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    # 방법 1: 전체가 JSON
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except json.JSONDecodeError:
        pass

    # 방법 2: [ ] 구간 추출
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # 방법 3: 개별 { } 객체 추출
    objects = []
    for match in re.finditer(r"\{[^{}]*\}", text, re.DOTALL):
        try:
            obj = json.loads(match.group())
            if "answer" in obj or "text" in obj or "agentId" in obj:
                objects.append(obj)
        except json.JSONDecodeError:
            continue
    if objects:
        return objects

    return None


def parse_orchestrator_response(raw_text: str, agents: List[AgentProfile]) -> List[Dict[str, Any]]:
    cleaned = _strip_markdown_fences(raw_text)
    parsed = _extract_json_array(cleaned)

    if parsed:
        normalized = []
        for item in parsed:
            entry = {
                "agentId": item.get("agentId", item.get("agent_id", "")),
                "agentName": item.get("agentName", item.get("agent_name", item.get("name", ""))),
                "answer": item.get("answer", item.get("text", item.get("content", ""))),
            }
            if not entry["agentName"] and agents:
                matched = next(
                    (a for a in agents if (a.agentId == entry["agentId"] or f"agent-{a.id}" == entry["agentId"])),
                    None,
                )
                if matched:
                    entry["agentName"] = matched.name
            normalized.append(entry)
        logger.info("[Orchestrator] JSON 파싱 성공: %d개 응답", len(normalized))
        return normalized

    fallback_name = agents[0].name if agents else "AI"
    fallback_id = agents[0].agentId if agents else "agent-1"
    logger.warning("[Orchestrator] JSON 파싱 실패 → 폴백 (원문 길이=%d)", len(raw_text))
    return [{
        "agentId": fallback_id,
        "agentName": fallback_name,
        "answer": raw_text.strip(),
    }]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4) 이전 대화 컨텍스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_conversation_context(previous_answers: Optional[List[PreviousAnswer]], max_items: int = 20) -> str:
    if not previous_answers:
        return ""
    items = previous_answers[-max_items:]
    lines = []
    for ans in items:
        name = getattr(ans, "agentName", None) or "사용자"
        role = getattr(ans, "role", None) or ""
        content = getattr(ans, "answer", "") or ""
        if role.upper() == "USER":
            lines.append(f"[사용자] {content}")
        else:
            lines.append(f"[{name}] {content[:500]}")
    return "[이전 대화 내역]\n" + "\n".join(lines)


def _fetch_wikipedia_context(query: str) -> str:
    """사용자 질문을 기반으로 한국어 위키백과에서 관련 문서를 검색하여 요약을 반환한다."""
    try:
        # 1. 문서 제목 검색
        # 검색어 처리를 위해 간단히 쪼개서 가장 긴 단어들을 위주로 검색하거나 원문 전체를 던짐
        encoded_query = urllib.parse.quote(query)
        search_url = f"https://ko.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded_query}&utf8=&format=json&srlimit=2"
        
        req = urllib.request.Request(search_url, headers={'User-Agent': 'StudyBridge/1.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
        
        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            return ""
            
        titles = [res["title"] for res in search_results]
        
        # 2. 문서 요약(Extract) 가져오기
        titles_param = urllib.parse.quote("|".join(titles))
        extract_url = f"https://ko.wikipedia.org/w/api.php?format=json&action=query&prop=extracts&exintro=true&explaintext=true&redirects=1&titles={titles_param}"
        
        req2 = urllib.request.Request(extract_url, headers={'User-Agent': 'StudyBridge/1.0'})
        with urllib.request.urlopen(req2, timeout=3) as response2:
            data2 = json.loads(response2.read().decode())
            
        pages = data2.get("query", {}).get("pages", {})
        extracts = []
        for page_id, page_info in pages.items():
            if "extract" in page_info and page_info["extract"].strip():
                # 내용을 500자 이내로 잘라서 제공
                extracts.append(f"▶ {page_info['title']}: {page_info['extract'][:500]}...")
                
        if extracts:
            logger.info(f"[Wikipedia] '{query}' 검색 완료. {len(extracts)}개 문서 참조.")
            return "[신뢰할 수 있는 참고 자료 (위키백과)]\n" + "\n".join(extracts) + "\n위 자료를 바탕으로 더욱 정확하고 풍부하게 답변을 구성하세요."
    except Exception as e:
        logger.warning(f"[Wikipedia] API 연동 실패: {e}")
    return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5) 실효 모드 결정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MODE_KEYS = {"basic", "default", "debate", "socratic", "simulation"}


def _resolve_effective_mode(request: MultiChatRequest) -> str:
    lm = (getattr(request, "learningMode", None) or "").strip().lower()
    raw = (request.mode or "default").strip().lower()
    if lm in _MODE_KEYS:
        return lm
    if raw in _MODE_KEYS:
        return raw
    return "basic"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6) 핵심 실행 함수 (동기 / 스트리밍)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_orchestrator(request: MultiChatRequest, agents: List[AgentProfile]) -> MultiChatResponse:
    """
    모드별 시스템 프롬프트로 Qwen 14B를 1회 호출하고,
    JSON 응답을 파싱하여 MultiChatResponse를 반환한다.
    """
    from app.services.ollama_client import ask_ollama

    effective_mode = _resolve_effective_mode(request)
    system_prompt = build_system_prompt(effective_mode, agents)

    parts = []
    
    # 1. 이전 대화 내역 추가
    context = _build_conversation_context(request.previousAnswers)
    if context:
        parts.append(context)
        
    # 2. 위키백과 보충 자료 추가
    wiki_context = _fetch_wikipedia_context(request.message)
    if wiki_context:
        parts.append(wiki_context)
        
    # 3. 사용자 메시지 추가
    parts.append(f"[사용자 메시지] {request.message}")
    
    user_prompt = "\n\n".join(parts)

    temperature = request.temperature if request.temperature is not None else 0.55
    max_tokens = request.maxTokens or int(os.getenv("AI_ORCHESTRATOR_MAX_TOKENS", "4096"))

    logger.info(
        "[Orchestrator] mode=%s agents=%d temp=%.2f max_tokens=%d",
        effective_mode, len(agents), temperature, max_tokens,
    )
    t0 = time.time()

    raw_response = ask_ollama(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        think=False,
    )

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info("[Orchestrator] 응답 수신 elapsed=%dms len=%d", elapsed_ms, len(raw_response))

    parsed_items = parse_orchestrator_response(raw_response, agents)

    answers: List[AgentAnswer] = []
    for idx, item in enumerate(parsed_items):
        answers.append(AgentAnswer(
            agentId=item.get("agentId", ""),
            agentName=item.get("agentName", "AI"),
            answer=item.get("answer", ""),
            role="assistant",
            displayOrder=idx + 1,
            displayDelayMs=idx * 500,
            status="SUCCESS",
        ))

    return MultiChatResponse(
        mode=effective_mode,
        learningMode=effective_mode,
        answers=answers,
    )


def build_orchestrator_stream(
    request: MultiChatRequest,
    agents: List[AgentProfile],
) -> Generator[Dict[str, Any], None, None]:
    """
    SSE 스트림 제너레이터.
    turn_start → agent_start → agent_answer (×N) → all_complete
    """
    yield {
        "event": "turn_start",
        "data": {
            "type": "turn_start",
            "message": "에이전트가 답변을 준비하고 있습니다...",
            "phase": "FIRST_DRAFT",
            "visible": True,
        },
    }

    try:
        response = run_orchestrator(request, agents)
    except Exception as e:
        logger.error("[Orchestrator] 실행 실패: %s", e)
        yield {
            "event": "error",
            "data": {
                "type": "error",
                "phase": "ERROR",
                "visible": True,
                "message": "AI 응답 생성 중 오류가 발생했습니다.",
                "detail": str(e),
            },
        }
        return

    for idx, ans in enumerate(response.answers or []):
        yield {
            "event": "agent_start",
            "data": {
                "type": "agent_start",
                "agentIndex": idx + 1,
                "agentName": ans.agentName,
                "agentId": ans.agentId,
                "phase": "FIRST_DRAFT",
                "visible": True,
            },
        }
        yield {
            "event": "agent_answer",
            "data": {
                "type": "agent_answer",
                "agentIndex": idx + 1,
                "agentName": ans.agentName,
                "agentId": ans.agentId,
                "answer": ans.answer,
                "displayOrder": ans.displayOrder,
                "stage": 1,
                "phase": "FIRST_DRAFT",
                "visible": True,
                "status": "SUCCESS",
            },
        }

    all_answers = []
    for ans in (response.answers or []):
        all_answers.append({
            "agentId": ans.agentId,
            "agentName": ans.agentName,
            "answer": ans.answer,
            "displayOrder": ans.displayOrder,
            "stage": 1,
            "status": "SUCCESS",
        })

    yield {
        "event": "all_complete",
        "data": {
            "type": "all_complete",
            "mode": response.mode,
            "learningMode": response.learningMode,
            "answers": all_answers,
            "status": "COMPLETED",
            "phase": "ALL_COMPLETE",
            "visible": True,
        },
    }
