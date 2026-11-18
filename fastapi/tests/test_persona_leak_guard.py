"""
BASIC 모드 persona/role 메타 문구 유출 가드 테스트.

계약:
  - 답변 본문에 자기 역할/성격/프로필 이름을 노출하지 않는다.
  - 제거 대상은 '이 에이전트 자신의 정체성'을 가리키는 메타 절뿐이다.
  - 일반 서술("실무 관점에서 보면 ...")과 다른 모드의 역할 발화는 건드리지 않는다.
"""
import pytest

from app.schemas.multi_chat_schema import AgentProfile
from app.services import orchestrator_service as OS
from app.services import persona_leak_guard as G


def _agent(name="이선배", role="쉬운 풀이 튜터", personality="친절형", level="입문"):
    return AgentProfile(agentId=12, id=12, name=name, role=role,
                        personality=personality, knowledgeLevel=level)


# ── 프롬프트 계약 ───────────────────────────────────────────────────────────
def test_rule_states_the_contract_in_english_and_korean():
    rule = G.NO_ROLE_EXPOSURE_RULE
    assert "Do not mention, restate, or expose your role/persona/profile name" in rule
    assert "관점에서" in rule and "역할로서" in rule


def test_basic_system_prompt_carries_the_rule():
    prompt = OS._build_single_agent_system_prompt(_agent(), "basic", [_agent()], position=0, total=1)
    assert "Do not mention, restate, or expose your role/persona/profile name" in prompt


def test_social_basic_prompt_carries_the_rule():
    prompt = OS._build_single_agent_system_prompt(_agent(), "basic", [_agent()], social=True)
    assert "Do not mention, restate, or expose your role/persona/profile name" in prompt


def test_nonstream_basic_prompt_carries_the_rule_and_drops_self_intro_example():
    prompt = OS.build_basic_prompt([_agent()])
    assert "Do not mention, restate, or expose your role/persona/profile name" in prompt
    # 자기 역할을 소개하는 예시 문장이 모델에게 '이렇게 쓰라'고 가르치고 있었다.
    assert "저는 실제 활용 사례와 주의점을 추가로 말씀드릴게요" not in prompt


def test_other_modes_keep_their_role_structure():
    """토론/소크라테스/상황극 프롬프트 구조는 건드리지 않는다."""
    for mode in ("debate", "socratic", "simulation"):
        prompt = OS._build_single_agent_system_prompt(_agent(), mode, [_agent()], position=0, total=2)
        assert "Do not mention, restate, or expose your role/persona/profile name" not in prompt
        assert "[모드" in prompt


# ── 출력 가드 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("leaked", [
    "쉬운 풀이 튜터 관점에서, TCP는 연결을 먼저 맺고 데이터를 보냅니다.",
    "튜터 관점에서 보자면 TCP는 연결을 먼저 맺고 데이터를 보냅니다.",
    "저는 쉬운 풀이 튜터 역할로서 TCP는 연결을 먼저 맺고 데이터를 보냅니다.",
    "친절형 입장에서, TCP는 연결을 먼저 맺고 데이터를 보냅니다.",
])
def test_strip_removes_self_role_declaration(leaked):
    out = G.strip_role_meta(leaked, _agent())
    assert "관점에서" not in out and "역할로서" not in out and "입장에서" not in out
    assert "TCP는 연결을 먼저 맺고" in out, out


def test_strip_removes_internal_position_role_names():
    out = G.strip_role_meta("검증자 관점에서, 앞 설명은 흐름 제어를 빠뜨렸습니다.", _agent())
    assert "검증자" not in out
    assert "앞 설명은 흐름 제어를 빠뜨렸습니다." in out


def test_strip_keeps_ordinary_framing_that_is_not_the_agents_identity():
    """'실무 관점에서'처럼 에이전트 정체성과 무관한 서술은 내용이므로 남긴다."""
    text = "실무 관점에서 보면 TCP 재전송은 지연을 만듭니다."
    assert G.strip_role_meta(text, _agent()) == text


def test_strip_does_not_touch_mid_sentence_content():
    text = "TCP는 신뢰성을 우선합니다. 운영 관점에서 재전송 비용을 봐야 합니다."
    assert G.strip_role_meta(text, _agent()) == text


def test_strip_never_empties_the_answer():
    text = "쉬운 풀이 튜터 관점에서"
    assert G.strip_role_meta(text, _agent()).strip() == text


def test_strip_removes_self_introduction_sentence():
    out = G.strip_role_meta("저는 이선배입니다. TCP는 연결 지향 프로토콜입니다.", _agent())
    assert "저는 이선배입니다" not in out
    assert "TCP는 연결 지향 프로토콜입니다." in out


def test_guard_is_basic_only():
    leaked = "쉬운 풀이 튜터 관점에서, 이건 이렇게 봅니다."
    assert OS._basic_answer_guard(leaked, _agent(), "basic") != leaked
    for mode in ("debate", "socratic", "simulation"):
        assert OS._basic_answer_guard(leaked, _agent(), mode) == leaked


def test_identity_sentence_words_are_not_used_as_tokens():
    """프로필 identity 문장의 일반어('정의', '예시', '기준')로 본문을 자르면 안 된다."""
    a = _agent(personality="논리형")   # identity: '정의·기준·예시·반례를 …' 형태의 문장
    for text in ("정의 관점에서 보면 인덱스는 탐색 비용을 줄인다.",
                 "예시 관점에서 설명하면 B-트리가 대표적이다.",
                 "기준 관점에서 나누면 읽기와 쓰기가 갈린다."):
        assert G.strip_role_meta(text, a) == text
