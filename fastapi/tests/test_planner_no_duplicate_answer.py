"""플래너 경로에서 '같은 화자의 의미 중복 답변'이 2개 이상 렌더링되지 않는지 검증.

핵심 시나리오(라이브 SSH 버그):
  에이전트 1명 → 플래너가 [DIRECT_ANSWER, WRAP] 를 만든다. WRAP 이 직전 정의를
  표현만 바꿔 재진술하면 같은 교수가 의미상 같은 답변을 2번 내보낸다. 이때
  turn_semantic_dedup 이 WRAP 을 억제해 agent_answer 가 1개만 남아야 한다.
  단, 억제 시 dangling agent_start('답변 작성 중')도 함께 사라져야 한다.
"""
import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import orchestrator_service as orch


@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    monkeypatch.setattr(orch, "_fetch_wikipedia_context", lambda q: "")
    monkeypatch.setattr(orch, "_min_gap_seconds", lambda: 0.0)
    monkeypatch.setenv("STUDYMATE_DISCUSSION_PLANNER", "on")
    monkeypatch.setenv("STUDYMATE_DISCUSSION_SEED", "3")
    monkeypatch.setenv("TURN_SEMANTIC_DEDUP", "on")


_DEF = (
    "SSH는 Secure Shell의 약자로 원격 접속을 위한 암호화된 프로토콜이다. "
    "클라이언트와 서버 사이에 암호화된 통신 채널을 만들어 명령을 실행하거나 파일을 전송한다."
)
_RESTATE = "SSH는 원격 서버에 안전하게 접속하기 위한 암호화 통신 프로토콜이다. 더 궁금한 점은 무엇인가?"
_EXPAND = (
    "개인키 권한을 600으로 두고 비밀번호 로그인을 끄며 known_hosts 검증을 켜는 것이 "
    "보안 핵심이다. 가장 먼저 점검할 것은 개인키 파일 권한이다. 어디부터 확인해볼까?"
)


def _one_agent():
    return [AgentProfile(id=1, agentId="prof", name="개념 정리 교수",
                         personality="전문적", knowledgeLevel="학사")]


def _run(monkeypatch, wrap_text):
    # DIRECT 는 정의, WRAP 은 주어진 텍스트를 반환하도록 스텁.
    calls = {"n": 0}

    def _fake(**k):
        calls["n"] += 1
        return _DEF if calls["n"] == 1 else wrap_text

    monkeypatch.setattr("app.services.ollama_client.ask_ollama", _fake)
    req = MultiChatRequest(message="SSH가 뭐야?", agents=_one_agent())
    return list(orch.build_orchestrator_stream(req, _one_agent()))


def test_single_agent_wrap_restate_is_suppressed(monkeypatch):
    events = _run(monkeypatch, _RESTATE)
    answers = [e["data"] for e in events if e["event"] == "agent_answer"]
    assert len(answers) == 1, [a.get("actType") for a in answers]
    assert answers[0]["actType"] == "DIRECT_ANSWER"
    # 억제된 WRAP 의 agent_start 도 남지 않아야 한다(dangling '작성 중' 방지).
    starts = [e["data"] for e in events if e["event"] == "agent_start"]
    assert all(s.get("actType") != "WRAP" for s in starts), starts
    # all_complete 의 answers 에도 중복이 들어가지 않는다.
    ac = next(e["data"] for e in events if e["event"] == "all_complete")
    assert len(ac["answers"]) == 1


def test_single_agent_distinct_wrap_is_kept(monkeypatch):
    # WRAP 이 '새로운 정보(보안 심화)'면 억제되지 않고 그대로 나온다.
    events = _run(monkeypatch, _EXPAND)
    answers = [e["data"] for e in events if e["event"] == "agent_answer"]
    act_types = [a["actType"] for a in answers]
    assert "DIRECT_ANSWER" in act_types and "WRAP" in act_types, act_types
    assert len(answers) == 2


def test_displayorder_contiguous_after_suppression(monkeypatch):
    # 억제가 일어나도 displayOrder 는 1..N 으로 연속이어야 한다(구멍 금지).
    events = _run(monkeypatch, _RESTATE)
    answers = [e["data"] for e in events if e["event"] == "agent_answer"]
    orders = [a["displayOrder"] for a in answers]
    assert orders == list(range(1, len(orders) + 1)), orders
