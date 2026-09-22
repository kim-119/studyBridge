"""중복 가드: 실측 복제(80자 공통) 검출, 정상 교수 간 용어 공유는 통과, prefix guard 조기 중단."""
from app.studymate import quality as Q

KIM = "캐시 메모리에 대해 궁금해하는군요! 아주 좋은 질문이에요. 캐시 메모리는 컴퓨터가 데이터를 더 빠르게 처리할 수 있도록 도와주는 역할을 하죠. 그런데 왜 이렇게 중요한 역할을 하게 되었는지 생각해보면 더 깊이 이해할 수 있어요."
LEE_COPY = "캐시 메모리에 대해 궁금해하는군요! 아주 좋은 질문이에요. 캐시 메모리는 컴퓨터가 데이터를 더 빠르게 처리할 수 있도록 도와주는 역할을 하죠. 캐시 메모리가 없을 경우, 데이터를 처리하는 데 시간이 더 많이 걸릴 수 있어요."
PARK = "캐시 메모리가 데이터 처리 속도를 높이는 데 중요한 역할을 한다는 점을 이미 짚었고, 그 없이 컴퓨터 성능이 어떻게 떨어질 수 있는지에 대한 질문도 나왔어요."
TCP_A = "TCP는 연결 지향형 프로토콜로 3-way handshake 후 데이터를 보낸다. 신뢰성을 위해 재전송을 한다."
TCP_B = "UDP와 달리 TCP는 연결 지향형 프로토콜이다. 흐름 제어와 혼잡 제어로 네트워크 상태에 적응한다."


def test_observed_socratic_copy_is_duplicate():
    v = Q.duplicate_against(LEE_COPY, [KIM])
    assert v.duplicate and v.lcs >= Q.DUP_LCS


def test_normal_different_answers_not_duplicate():
    assert not Q.duplicate_against(PARK, [KIM, LEE_COPY]).duplicate
    assert not Q.duplicate_against(TCP_B, [TCP_A]).duplicate


def test_prefix_guard_aborts_early_copy():
    guard = Q.prefix_guard([KIM])
    assert guard(LEE_COPY[:40]) is None
    assert guard(LEE_COPY[:110]) is not None
    assert Q.prefix_guard([TCP_A])(TCP_B[:120]) is None


def test_novel_claims():
    assert Q.novel_claims(["캐시는 읽기 지연을 줄인다", "무효화가 어렵다"], ["캐시는 읽기 지연을 줄인다"]) == ["무효화가 어렵다"]


def test_executor_aborts_duplicate_and_regenerates_once(monkeypatch):
    from app.studymate.agent_executor import RenderSpec, execute
    from app.studymate.budget import TurnBudget
    from app.studymate.cancellation import CancelToken
    from app.studymate.profile_contract import canonicalize_agent
    from tests.studymate_fakes import FakeOllama, install, PERSONA_TEXT
    outputs = [LEE_COPY + " 계속 같은 말", PERSONA_TEXT["friendly"].format(topic="캐시", agent="새로운 관점의 교수")]
    fake = install(monkeypatch, FakeOllama(render=lambda req: outputs.pop(0) if outputs else "x"))
    a = canonicalize_agent({"agentId": 2, "name": "이교수", "personality": "friendly", "knowledgeLevel": "bachelor"}, 1)
    spec = RenderSpec(agent=a, mode="basic", role="challenge", question="캐시", turn_id="t", request_id="r", prior_texts=[KIM])
    out = execute(spec, cancel=CancelToken(), budget=TurnBudget.for_kind("basic_multi"))
    assert out.status == "SUCCESS" and out.trace.regenerationCount == 1 and not Q.duplicate_against(out.text, [KIM]).duplicate
