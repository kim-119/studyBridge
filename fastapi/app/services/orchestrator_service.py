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

# ── per-agent 헬퍼: 에이전트 한 명에게 집중한 프롬프트로 1회 호출 ────────────────

def _min_gap_seconds() -> float:
    """답변 사이 최소 간격(초). env STUDYMATE_MIN_ANSWER_GAP_SECONDS로 조절(기본 4)."""
    try:
        return max(0.0, float(os.getenv("STUDYMATE_MIN_ANSWER_GAP_SECONDS", "4")))
    except (TypeError, ValueError):
        return 4.0


def _agent_personality_label(agent: AgentProfile) -> str:
    return (
        agent.personality
        or getattr(agent, "personalityLabel", None)
        or getattr(agent, "tone", None)
        or getattr(agent, "style", None)
        or "친절형"
    )


def _agent_custom_instruction(agent: AgentProfile) -> Optional[str]:
    return (
        getattr(agent, "customInstruction", None)
        or getattr(agent, "custom_instruction", None)
        or getattr(agent, "persona", None)
    )


def _mode_role_directive(mode: str, position: int = 0, total: int = 1) -> str:
    """단일 에이전트용 모드 역할 지시. 토론은 위치별로 논제정의/찬성/반대/중립을 분담한다."""
    m = (mode or "basic").strip().lower()
    if m in ("debate", "토론", "토론 모드"):
        base = (
            "[모드: 토론 — 설명이 아니라 '입장'을 주장한다]\n"
            "★ 절대 규칙: 개념을 중립적으로 설명·요약하지 마라. 너는 한쪽 입장을 가진 토론자다.\n"
            "- 첫 문장에서 사용자 말/대화의 쟁점을 '논제: ~인가?' 한 줄로 정의(첫 발언자만).\n"
            "- 그다음 반드시 '나는 ~다(찬성/반대). 왜냐하면 ① … ② …' 형식으로 네 입장을 근거로 주장/반박하라."
        )
        if total >= 3:
            role = {
                0: "너의 역할: '논제 정의 + 찬성'. \"논제: ~인가?\"로 정의하고 \"나는 찬성한다. 왜냐하면…\"으로 주장하라.",
                1: "너의 역할: '반대'. 논제는 새로 만들지 말고, \"나는 반대한다. 앞 주장은 ~ 점에서 약하다. 왜냐하면…\"으로 반박하라.",
            }.get(position, "너의 역할: '중립 심판'. 양측 핵심을 한 줄씩 요약하고 \"종합하면 …\"으로 판정하라.")
        elif total == 2:
            role = {
                0: "너의 역할: '논제 정의 + 찬성'. 논제를 정의하고 찬성 입장을 주장하라.",
            }.get(position, "너의 역할: '반대'. \"나는 반대한다. 왜냐하면…\"으로 반박하라.")
        else:
            role = "혼자이니 '논제: ~인가?' 정의 후, 찬성 근거와 반대 근거를 각각 \"찬성 측: … / 반대 측: …\"로 대비시켜라."
        return base + "\n- " + role
    if m in ("socratic", "소크라테스", "소크라테스 모드"):
        if total <= 1 or position == total - 1:
            closing = "→ ④ 마지막 한 문장에서만 '이걸 네 말로 설명해볼래?'로 자기설명을 유도하라."
        else:
            closing = ("→ 너는 마지막 차례가 아니다. 마무리 자기설명 요청은 하지 말고, "
                       "앞 메이트와 '겹치지 않는 다른 각도'의 질문만 던져라.")
        return (
            "[모드: 소크라테스 — 질문으로만 답한다]\n"
            "너는 개념을 '설명'하는 사람이 아니라, 사용자가 스스로 답을 찾게 '질문'만 던지는 안내자다.\n"
            "★ 절대 규칙(어기면 실패): 평서문으로 개념을 정의·설명·요약하지 마라. "
            "답변의 거의 모든 문장이 물음표('?')로 끝나는 질문이어야 한다. 정답을 직접 말하지 마라.\n"
            "흐름: ① 사용자의 현재 생각을 묻는 질문 → ② 핵심으로 좁히는 꼬리질문 1~2개 "
            "→ ③ 막히면 힌트도 '혹시 ~ 때문일까?'처럼 질문 형태로\n"
            + closing + "\n"
            "[형식 예시] '지금 이게 왜 필요하다고 생각해? 만약 이게 없으면 어떤 문제가 생길까? "
            "그 문제를 해결하려면 무엇이 가장 중요할까?'"
        )
    if m in ("simulation", "상황극", "상황극 모드", "situation", "roleplay"):
        return "[모드: 상황극] 주제와 관련된 가상 시나리오 속 인물이 되어 생생한 대사와 상황 묘사로 답하라. 마지막에 사용자에게 선택지나 행동을 묻는 질문을 던져라."
    return (
        "[모드: 기본 대화]\n"
        "- 가벼운 질문이나 잡담에는 짧게 반응하고, 개념 설명이 필요하면 깊이 있게 답하라.\n"
        "- ★[중요] 무조건 착하거나 친절하게 대답하려 하지 마라. '너의 성격(톤)'을 유지하는 것이 1순위다.\n"
        "- 성격(톤)은 분명히 살리되, 비판은 사실·근거에 기반하라. 조롱·비아냥·인신공격·한숨('한심하다','이걸 아직도')은 금지 — 날카롭되 건설적으로.\n"
        "- ★[경고] 앵무새처럼 매번 똑같은 첫 문장(예: '와, 이걸 아직도', '방향은 맞는데', '결론:')을 기계적으로 반복하지 마라! 맥락에 맞게 매번 새로운 표현과 어휘로 자연스럽게 성격을 드러내라."
    )


def _position_role(position: int, total: int) -> str:
    """턴 내 위치별 역할(분담). 같은 비판을 N번 반복/복붙하는 걸 막고 흐름을 유동적으로 만든다."""
    if total <= 1:
        return ""
    if position == 0:
        return (
            "[이번 턴 너의 역할: 첫 설명자]\n"
            "- 네가 가장 먼저 답한다. 질문에 대해 네 성격 톤으로 '개념을 직접 설명/답변'하라.\n"
            "- 아직 평가할 앞 답변이 없다. 비판·반박하지 말고, '방향은 맞는데' 같은 평가성 표현도 쓰지 마라."
        )
    if position == total - 1:
        return (
            "[이번 턴 너의 역할: 검증·정리자]\n"
            "- 앞 메이트들의 답을 근거로 검증하고, 빠진 점·오류·한계를 짚어 보완하라.\n"
            "- 이미 나온 설명을 통째로 반복하지 말고, 새로 더할 지적/정리만 간결히 하라."
        )
    return (
        "[이번 턴 너의 역할: 심화·확장자]\n"
        "- 앞 답에 없는 새로운 관점·예시·심화 내용을 더하라. 같은 설명을 반복하지 마라."
    )


def _short_persona_tone(agent: AgentProfile) -> str:
    """소크라테스/토론용 '말투 톤'만 추출(개조식·answerShape 같은 형식 지시는 제외 — 모드 형식과 충돌하므로)."""
    from app.services.personality_prompt_builder import get_profile
    label = _agent_personality_label(agent)
    profile = get_profile(label)
    name = profile.get("displayName") or label
    tone = profile.get("toneProfile") or ""
    line = f"[성격 톤] '{name}' 말투를 살려라: {tone}".strip()
    if str(profile.get("speechRegister", "")).strip() == "반말":
        line += " (반드시 반말, 존댓말 금지. 단 조롱·인신공격은 금지.)"
    return line


def _build_single_agent_system_prompt(agent: AgentProfile, mode: str, all_agents: List[AgentProfile], social: bool = False, position: int = 0, total: int = 1) -> str:
    """에이전트 한 명에게 집중한 system 프롬프트(성격 행동지시문 + 지식수준 + 모드 + 위치 역할).

    social=True(인사/잡담/짧은 사회적 입력)이면 공격적 비판 대신 가볍게 인사로 받는다.
    """
    from app.services.personality_prompt_builder import build_personality_prompt

    persona_block = build_personality_prompt(_agent_personality_label(agent), _agent_custom_instruction(agent))
    name = agent.name or "AI"
    level = agent.knowledgeLevel or getattr(agent, "knowledgeLevelLabel", None) or "학사 수준"
    # 사용자 지침(페르소나 정의/additionalRequest): 톤은 성격(coreDirective)이 잡고, 답변의 '내용·형식'은 이 지침을 따른다.
    _ci = _agent_custom_instruction(agent)
    custom_block = f"\n[사용자 지침 — 답변의 내용·구성·형식을 이 지침에 맞춰라(말투/톤은 위 성격 유지)]\n{_ci.strip()}\n" if (_ci and _ci.strip()) else ""
    others = [a.name for a in all_agents if a is not agent and a.name]
    # 다른 메이트의 '이름'은 일부러 노출하지 않는다(모델이 'X:'처럼 호명/머리표로 쓰는 걸 막기 위해).
    peers = (
        "\n[함께 있는 다른 메이트] 너 말고 다른 메이트들도 같은 질문에 답한다 — 그들과 똑같은 말투·구조로 쓰지 말고 너만의 성격·관점을 내라."
        "\n- ★ 다른 메이트의 이름/닉네임을 문장에 부르지 말고, 'OOO:' 같은 머리표도 절대 쓰지 마라."
    ) if others else ""
    m = (mode or "basic").strip().lower()
    is_basic = m in ("", "basic", "default")
    # 위치별 역할 분담(설명/심화/검증)은 basic 모드 전용. 소크라테스/토론/상황극엔 적용하지 않는다.
    role_block = _position_role(position, total) if is_basic else ""

    # 인사/잡담이면: 성격 톤은 살짝 유지하되 공격하지 말고 짧고 가볍게 받는다(없는 내용 비판 금지).
    if social:
        return f"""[역할] 너는 '{name}'(이)다. 사용자와 대화하는 상대다.
{persona_block}

[지금은 인사/잡담이다]
- 학습 질문이 아니다. 비판·지적·분석을 하지 말고, 네 성격 톤만 살짝 살려 1~2문장으로 가볍게 받아라.
- 없는 내용을 트집잡거나 길게 늘어놓지 마라. 자연스럽게 인사하고, 필요하면 무엇을 도와줄지 한 번 물어봐라.{peers}

[규칙] 한국어로, 머리말/꼬리말/JSON 없이 본문만. 같은 문장 반복 금지."""

    # 비-basic 모드(소크라테스/토론/상황극): 모드 지시가 지배한다.
    # basic 전용 프레이밍(역할분담·'깊이있게 설명하라'·비판규칙)은 넣지 않는다 — 소크라테스가 일반 설명으로 변질되는 걸 막는다.
    if not is_basic:
        # 소크라테스/토론/상황극: 모드 형식이 절대 우선. 성격은 '말투 톤'으로만, 지식수준은 '난이도'로만 반영.
        # (풀 coreDirective·customInstruction은 '설명하라'를 강제해 모드와 충돌하므로 여기선 넣지 않는다.)
        return f"""[역할] 너는 '{name}'(이)다.
{_short_persona_tone(agent)}
[상대 수준] 상대는 '{level}' 수준 — 질문/논증의 난이도와 용어를 여기에 맞춰라.

{_mode_role_directive(mode, position, total)}

[절대 규칙 — 모드 형식이 최우선]
- 위 [모드] 지시의 '형식'을 무엇보다 우선한다. 성격·지식수준은 말투와 난이도에만 반영하고, 모드 형식을 절대 바꾸지 마라.
- (소크라테스) 개념을 설명·정의·요약하지 마라. '결론/핵심/정의' 나열 금지. 질문 → 단계별 힌트 → "네 말로 설명해볼래?"만.
- (토론) 그냥 설명하지 마라. 논제를 정의하고 네 입장(찬성/반대/중립)을 근거·예시로 주장/반박하라.
- 조롱·비아냥·인신공격 금지. 한국어로, JSON·머리말·꼬리말 없이 본문만. 같은 표현 반복 금지.{peers}"""

    role_section = f"\n{role_block}\n" if role_block else "\n"

    return f"""[역할] 너는 '{name}'(이)다. 사용자와 대화하는 상대이자, 필요할 때 도와주는 메이트다.
{persona_block}
{role_section}{custom_block}
[상대 수준] 상대는 '{level}' 수준이다. 이 수준에 걸맞은 깊이로 답하되, 네 역할 범위 안에서만 답하라(첫 설명자=설명, 검증자=검증). 뻔한 말은 하지 마라.

{_mode_role_directive(mode)}{peers}

[비판 규칙 — 비난은 하되 조롱은 금지]
- 비판·지적은 반드시 사실과 근거(제공된 자료·맥락·앞선 답변)에 기반하라. 추측으로 깎아내리지 마라.
- 비아냥·조롱·인신공격·한숨('한심하다', '이걸 아직도' 등)은 절대 금지. 날카롭되 내용은 정확하고 건설적이어야 한다.

[대화 규칙]
- 이전 대화 맥락이 주어지면 그 흐름을 자연스럽게 이어가라(앞 이야기를 기억하는 것처럼).
- 위 성격(톤)이 답변 문장에 분명히 드러나야 한다. GPT처럼 무색무취하게 쓰지 마라.
- 모든 답변은 한국어로 작성한다.
- JSON·머리말·꼬리말 없이, 너의 답변 본문만 작성하라."""


def _build_single_agent_user_prompt(
    agent: AgentProfile, request: MultiChatRequest, wiki_context: str, context: str,
    peer_answers: Optional[List[Dict[str, Any]]] = None,
) -> str:
    from app.services.personality_prompt_builder import build_persona_directive

    parts: List[str] = []
    if context:
        parts.append(context)
    if wiki_context:
        parts.append(wiki_context)
    parts.append(f"[사용자의 최근 메시지] {request.message}")
    parts.append("위 대화 흐름을 이어서, 이 메시지에 자연스럽게 응답하라.")
    if peer_answers:
        peer_lines = [f"- {str(p.get('answer',''))[:150]}" for p in peer_answers]
        parts.append(
            "[앞에서 이미 나온 요지 — 중복 방지용, 되풀이 금지]\n" + "\n".join(peer_lines) +
            "\n→ 위는 이미 나왔다. 점별로 반박하거나 같은 말을 되풀이하지 말고, 네 역할대로 '네가 새로 더할 한 가지'에만 집중하라"
            "(심화자=앞에 없던 새 관점·예시 1개, 검증자=가장 중요한 빠진 점·주의점 1개). "
            "★ 다른 메이트의 이름/'OOO:' 머리표를 쓰지 마라. 굳이 짚을 땐 '앞 설명은 ~를 놓쳤다'처럼 내용 중심으로, 단 한 번만. "
            "같은 문장·표현을 반복하지 말고(특히 한 답변 안에서 같은 말 재탕 금지), 상투구('방향은 맞는데')도 쓰지 마라. 조롱 없이 근거로."
        )
    parts.append(build_persona_directive(_agent_personality_label(agent), _agent_custom_instruction(agent)))
    return "\n\n".join(parts)


def _is_social_input(request: MultiChatRequest) -> bool:
    """인사/잡담/자기소개/불명확(내용 없는 사회적 입력)인지. guardrail 라우터 재사용."""
    try:
        from app.services import guardrail_router as _g
        route = _g.classify_route(
            request.message, mode=request.mode, learning_mode=getattr(request, "learningMode", None)
        ).route
        return route in (_g.GREETING, _g.SMALL_TALK, _g.SELF_INTRO, _g.UNCLEAR)
    except Exception:
        return False


def _cross_feedback_enabled(request: MultiChatRequest, agents: List[AgentProfile]) -> bool:
    """동료 피드백(앞 메이트 의견 참조)을 '어쩔 때만' 켠다.
    env STUDYMATE_CROSS_FEEDBACK: auto(기본)/on/off.
      - off: 항상 끔 / on: 2명↑이면 항상
      - auto: 2명↑ & 사회적 입력(인사/잡담/자기소개/불명확)이 아닐 때만.
              (사회적 입력에 피드백을 켜면 서로 답을 복붙하므로 끈다.)
    """
    if len(agents) < 2:
        return False
    mode = (os.getenv("STUDYMATE_CROSS_FEEDBACK", "auto") or "auto").strip().lower()
    if mode == "off":
        return False
    if mode == "on":
        return True
    # auto: 사회적 입력이면 끄고, 실제 질문이면 켠다.
    try:
        return not _is_social_input(request)
    except Exception:
        return True


def _generate_single_agent_answer(
    agent: AgentProfile, request: MultiChatRequest, mode: str, wiki_context: str, context: str,
    all_agents: List[AgentProfile], peer_answers: Optional[List[Dict[str, Any]]] = None,
    social: bool = False, position: int = 0, total: int = 1,
) -> str:
    """에이전트 한 명에게 Ollama를 1회 호출해 답변 본문을 반환한다(빈응답 가드 포함)."""
    from app.services.ollama_client import ask_ollama
    from app.services.personality_prompt_builder import get_generation_params

    system_prompt = _build_single_agent_system_prompt(agent, mode, all_agents, social=social, position=position, total=total)
    user_prompt = _build_single_agent_user_prompt(agent, request, wiki_context, context, peer_answers)

    gen = get_generation_params(_agent_personality_label(agent))
    temperature = request.temperature if request.temperature is not None else gen.get("temperature", 0.55)
    max_tokens = request.maxTokens or int(os.getenv("AI_ORCHESTRATOR_MAX_TOKENS", "4096"))

    t0 = time.time()
    raw = ask_ollama(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        think=False,
    )
    elapsed_ms = int((time.time() - t0) * 1000)
    answer = (raw or "").strip()
    logger.info("[Orchestrator] agent=%s mode=%s elapsed=%dms len=%d", agent.name, mode, elapsed_ms, len(answer))
    if not answer:
        answer = "(응답을 생성하지 못했어요. 잠시 후 다시 시도해 주세요.)"
    return answer


def _feedback_round_enabled() -> bool:
    """2라운드 피드백(전원 답변 후 서로 보충/반박)을 켤지. env STUDYMATE_FEEDBACK_ROUND=on|1|true (기본 off)."""
    return (os.getenv("STUDYMATE_FEEDBACK_ROUND", "") or "").strip().lower() in ("1", "true", "on", "yes")


def _generate_round2_feedback(agent: AgentProfile, request: MultiChatRequest, mode: str, others_answers: List[Dict[str, Any]]) -> str:
    """2라운드: 다른 메이트들의 1라운드 답을 보고 '가장 중요한 보충/반박 한 가지'만 짧게."""
    from app.services.ollama_client import ask_ollama
    from app.services.personality_prompt_builder import build_personality_prompt, build_persona_directive, get_generation_params

    persona = build_personality_prompt(_agent_personality_label(agent), _agent_custom_instruction(agent))
    sys = (
        f"[역할] 너는 '{agent.name or 'AI'}'(이)다.\n{persona}\n\n"
        "[2라운드: 동료 피드백] 다른 메이트들의 1라운드 답변을 봤다. 네 성격으로 '가장 중요한 보충 또는 반박 한 가지'만 2~3문장으로 말하라.\n"
        "- 다른 메이트의 이름/'OOO:' 머리표를 쓰지 말고, 내용(논점) 중심으로 자연스럽게.\n"
        "- 앞 답을 복붙·재서술하지 마라. 조롱·비아냥 없이 근거로. 길게 늘어놓지 마라.\n"
        "- 한국어로, 머리말/꼬리말/JSON 없이 본문만."
    )
    other_lines = "\n".join(f"- {str(a.get('answer', ''))[:200]}" for a in others_answers)
    usr = (
        f"[사용자 질문] {request.message}\n\n[다른 메이트들의 1라운드 답변]\n{other_lines}\n\n"
        "→ 위에 대해 네가 더할 보충 또는 반박 '한 가지'만 짧게.\n\n"
        + build_persona_directive(_agent_personality_label(agent), _agent_custom_instruction(agent))
    )
    gen = get_generation_params(_agent_personality_label(agent))
    raw = ask_ollama(
        system_prompt=sys, user_prompt=usr,
        max_tokens=min(request.maxTokens or 512, 512),
        temperature=gen.get("temperature", 0.5), think=False,
    )
    return (raw or "").strip()


def run_orchestrator(request: MultiChatRequest, agents: List[AgentProfile]) -> MultiChatResponse:
    """
    에이전트마다 Qwen 14B를 순차 1회씩 호출(per-agent)해 성격이 도드라지는 답변을 만든다.
    비스트림이므로 인위적 sleep은 없고, displayDelayMs로 프론트 시차 렌더 힌트만 제공한다.
    """
    effective_mode = _resolve_effective_mode(request)
    context = _build_conversation_context(request.previousAnswers)
    wiki_context = _fetch_wikipedia_context(request.message)
    gap_ms = int(_min_gap_seconds() * 1000)

    feedback_on = _cross_feedback_enabled(request, agents)
    social = _is_social_input(request)
    logger.info("[Orchestrator] (sync) mode=%s agents=%d cross_feedback=%s social=%s", effective_mode, len(agents), feedback_on, social)

    answers: List[AgentAnswer] = []
    prior: List[Dict[str, Any]] = []
    for idx, agent in enumerate(agents):
        peer = prior if (feedback_on and prior) else None
        ans_text = _generate_single_agent_answer(agent, request, effective_mode, wiki_context, context, agents, peer, social=social, position=idx, total=len(agents))
        answers.append(AgentAnswer(
            agentId=agent.agentId or f"agent-{agent.id}",
            agentName=agent.name or "AI",
            answer=ans_text,
            role="assistant",
            displayOrder=idx + 1,
            displayDelayMs=idx * gap_ms,
            status="SUCCESS",
        ))
        prior.append({"agentName": agent.name or "AI", "answer": ans_text})

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
    # 성격/지식수준 라벨은 에이전트 key 에서 재계산해 전 이벤트에 싣는다(라벨 계약 SSOT).
    # lazy import 로 multi_agent_service ↔ orchestrator_service 순환을 피한다.
    try:
        from app.services.multi_agent_service import _agent_identity_payload
    except Exception:  # pragma: no cover - 방어
        _agent_identity_payload = lambda a: {}

    effective_mode = _resolve_effective_mode(request)
    context = _build_conversation_context(request.previousAnswers)
    wiki_context = _fetch_wikipedia_context(request.message)
    min_gap = _min_gap_seconds()
    feedback_on = _cross_feedback_enabled(request, agents)
    social = _is_social_input(request)

    # ── basic 모드 후속 발화 게이트 ────────────────────────────────────────────
    # 직전 대화가 있을 때 "아니왜?/왜?/그게 맞아?/예시로/더 쉽게/ㅇㅇ" 같은 후속 발화는
    # 새 질문이 아니므로, 3명이 직전 답변을 통째로 반복하지 않고 짧은 맥락 답변만 낸다.
    # (위치별 역할분담 풀답변 경로와 상보적 — 후속 발화는 애초에 풀답변을 타지 않는다.)
    # 분류는 결정론 우선(+선택적 LLM). 어떤 오류든 기존 풀답변 경로로 폴백(additive).
    if effective_mode == "basic":
        try:
            from app.services.dialogue_act_classifier import (
                build_previous_context,
                classify_dialogue_act,
                NEW_STUDY_QUERY,
            )
            prev_ctx = build_previous_context(request.previousAnswers, mode=effective_mode)
            if prev_ctx.has_context:
                decision = classify_dialogue_act(
                    request.message,
                    previous_context=prev_ctx,
                    mode=request.mode,
                    learning_mode=getattr(request, "learningMode", None),
                )
                if decision.act != NEW_STUDY_QUERY:
                    from app.services.basic_contextual_turn import (
                        run_basic_contextual_turn_stream,
                    )
                    logger.info(
                        "[Orchestrator] basic followup act=%s depth=%s conf=%.2f → contextual turn",
                        decision.act, decision.answer_depth, decision.confidence,
                    )
                    yield from run_basic_contextual_turn_stream(
                        request, agents, decision, prev_ctx, min_gap=min_gap,
                    )
                    return
        except Exception as e:  # pragma: no cover - 방어: 무조건 기존 경로로 폴백
            logger.warning("[Orchestrator] dialogue-act 게이트 건너뜀: %s", e)

    yield {
        "event": "turn_start",
        "data": {
            "type": "turn_start",
            "message": "에이전트가 답변을 준비하고 있습니다...",
            "phase": "FIRST_DRAFT",
            "visible": True,
        },
    }

    n = len(agents)
    all_answers: List[Dict[str, Any]] = []

    # per-agent 순차 호출 + 최소 간격 보장: 답변이 하나씩 시차를 두고 등장한다.
    for idx, agent in enumerate(agents):
        t0 = time.time()
        agent_id = agent.agentId or f"agent-{agent.id}"
        agent_name = agent.name or "AI"
        identity = _agent_identity_payload(agent)  # personality/personalityLabel/knowledgeLevel/knowledgeLevelLabel

        yield {
            "event": "agent_start",
            "data": {
                "type": "agent_start",
                "agentIndex": idx + 1,
                "agentName": agent_name,
                "agentId": agent_id,
                "phase": "FIRST_DRAFT",
                "visible": True,
                **identity,
            },
        }

        try:
            peer = all_answers if (feedback_on and all_answers) else None
            answer = _generate_single_agent_answer(agent, request, effective_mode, wiki_context, context, agents, peer, social=social, position=idx, total=n)
        except Exception as e:
            logger.error("[Orchestrator] 에이전트 생성 실패 %s: %s", agent_name, e)
            answer = "(이 에이전트의 응답 생성 중 오류가 발생했어요.)"

        yield {
            "event": "agent_answer",
            "data": {
                "type": "agent_answer",
                "agentIndex": idx + 1,
                "agentName": agent_name,
                "agentId": agent_id,
                "answer": answer,
                "displayOrder": idx + 1,
                "stage": 1,
                "phase": "FIRST_DRAFT",
                "visible": True,
                "status": "SUCCESS",
                **identity,
            },
        }
        all_answers.append({
            "agentId": agent_id,
            "agentName": agent_name,
            "answer": answer,
            "displayOrder": idx + 1,
            "stage": 1,
            "status": "SUCCESS",
            **identity,
        })

        # 마지막 에이전트 뒤에는 대기하지 않는다. 생성이 빨랐으면 최소 간격까지 채운다.
        if idx < n - 1:
            remaining = min_gap - (time.time() - t0)
            if remaining > 0:
                time.sleep(remaining)

    # ── 2라운드 피드백(플래그 STUDYMATE_FEEDBACK_ROUND). 1라운드 전원 답변 후 서로 보충/반박. ──
    if _feedback_round_enabled() and not social and len(all_answers) >= 2:
        round1 = list(all_answers)
        for idx, agent in enumerate(agents):
            if idx >= len(round1):
                break
            t0 = time.time()
            agent_id = agent.agentId or f"agent-{agent.id}"
            agent_name = agent.name or "AI"
            identity = _agent_identity_payload(agent)
            others = [a for j, a in enumerate(round1) if j != idx]
            yield {
                "event": "agent_start",
                "data": {"type": "agent_start", "agentIndex": idx + 1, "agentName": agent_name,
                         "agentId": agent_id, "phase": "FEEDBACK", "visible": True, **identity},
            }
            try:
                fb = _generate_round2_feedback(agent, request, effective_mode, others)
            except Exception as e:
                logger.error("[Orchestrator] 2라운드 피드백 실패 %s: %s", agent_name, e)
                fb = ""
            if fb:
                entry = {"agentId": agent_id, "agentName": agent_name, "answer": fb,
                         "displayOrder": len(all_answers) + 1, "stage": 2, "status": "SUCCESS", **identity}
                yield {
                    "event": "agent_answer",
                    "data": {"type": "agent_answer", "agentIndex": idx + 1, "agentName": agent_name,
                             "agentId": agent_id, "answer": fb, "displayOrder": entry["displayOrder"],
                             "stage": 2, "phase": "FEEDBACK", "visible": True, "status": "SUCCESS", **identity},
                }
                all_answers.append(entry)
            if idx < len(agents) - 1:
                remaining = min_gap - (time.time() - t0)
                if remaining > 0:
                    time.sleep(remaining)

    yield {
        "event": "all_complete",
        "data": {
            "type": "all_complete",
            "mode": effective_mode,
            "learningMode": effective_mode,
            "answers": all_answers,
            "messages": all_answers,
            "status": "COMPLETED",
            "phase": "ALL_COMPLETE",
            "visible": True,
        },
    }
