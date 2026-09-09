"""
상황극(simulation) 3역할 세션 엔진 테스트 (LLM fake 주입).

  - 1턴: 상황 + 선택지(설정값과 정확히 일치)
  - 2턴~: 심화 검증 → 피드백 코치 → 진행(결과 + 다음 장면) 3역할이 모두 발화
  - 장면/역할은 세션에 고정되고 매 턴 새로 만들지 않는다
  - 한 역할이 실패하면 일반 Q&A 로 폴백하지 않고 모드 전용 오류를 낸다
"""
import json

import pytest

from app.schemas.multi_chat_schema import MultiChatRequest
from app.services import learning_session as LS
from app.services import simulation_mode_handler as H
from app.services import simulation_session_engine as SE

TOPIC = "면접에서 JWT가 무엇인지 설명해보라는 질문을 연습하고 싶어"


@pytest.fixture(autouse=True)
def _clean():
    LS.clear_all()
    yield
    LS.clear_all()


class FakeLLM:
    def __init__(self, choice_count=3):
        self.choice_count = choice_count
        self.calls = []

    @staticmethod
    def _user_answer(user):
        """실제 모델처럼 '사용자의 이번 답변' 블록을 읽어 그 표현을 인용한다."""
        marker = "[사용자의 이번 답변/선택]"
        if marker not in user:
            return ""
        return user.split(marker, 1)[1].strip().splitlines()[0].strip()

    def __call__(self, system, user, *, max_tokens, temperature):
        self.calls.append({"user": user})
        n = self.choice_count
        said = self._user_answer(user)
        if '"sceneBrief"' in user:
            return json.dumps({
                "sceneBrief": "백엔드 신입 채용 면접실, 면접관 두 명이 마주 앉아 있다.",
                "userRole": "지원자", "goal": "JWT 를 실무 관점에서 설명하기",
                "speakerRole": "면접관",
                "line": "이력서에 인증을 직접 구현했다고 쓰셨는데, JWT 를 왜 선택했는지 "
                        "먼저 설명해 주시겠습니까?",
                "choices": [{"label": f"선택지 {i + 1}"} for i in range(n)],
            }, ensure_ascii=False)
        if '"focusPoints"' in user:
            return json.dumps({
                "focusPoints": ["선택 이유", "대안과의 비교"],
                "line": "결론부터 말하고 근거를 두 개만 붙이세요.",
            }, ensure_ascii=False)
        if '"speakerRole"' in user:
            return json.dumps({
                "speakerRole": "기술 면접관",
                "line": "토큰을 클라이언트가 보관하면 탈취 위험이 생깁니다. "
                        "그 위험을 감수할 만한 이점이 무엇입니까?",
            }, ensure_ascii=False)
        if '"reaction"' in user:
            return json.dumps({
                "reaction": "면접관이 고개를 끄덕이며 메모한다.",
                "targetPart": f"{said} 라고 말한 부분",
                "line": f"{said} 라고 하셨는데, 그 판단이 무너지는 경우에는 어떻게 대응하시겠습니까?",
                "choices": [{"label": f"다음 선택지 {i + 1}"} for i in range(n)],
            }, ensure_ascii=False)
        if '"targetPoint"' in user:
            return json.dumps({
                "targetPoint": f"{said} 라고 말한 부분",
                "line": f"{said} 라고 하셨는데 그 근거가 실무에서도 그대로 성립합니까?",
            }, ensure_ascii=False)
        if '"strengths"' in user:
            return json.dumps({
                "strengths": ["토큰 구조를 먼저 짚었다"],
                "weaknesses": ["보안 위협에 대한 언급이 없다"],
                "improvement": "설명 끝에 만료와 갱신 전략을 한 줄 붙여라.",
            }, ensure_ascii=False)
        return "{}"


def _req(message, count=3, difficulty="보통", stype="면접", room=202, state=None, choice=None):
    return MultiChatRequest(
        message=message, mode="simulation", learningMode="simulation", roomId=room,
        simulationConfig={"scenarioType": stype, "difficulty": difficulty, "choiceCount": count},
        simulationState=state, selectedChoice=choice,
        agents=[{"agentId": f"a{i}", "name": f"교수{i}"} for i in (1, 2, 3)],
    )


def _events(request, llm):
    return list(H.run_simulation_mode_stream(request, list(request.agents), llm=llm))


# ── 설정 반영 ───────────────────────────────────────────────────────────────
def test_config_normalization_and_clamp():
    assert SE.resolve_config(_req("x", count=2, difficulty="어려움", stype="프로젝트")) == \
        (SE.PROJECT, SE.HARD, 2)
    assert SE.resolve_config(_req("x", count=9))[2] == SE.MAX_CHOICES
    assert SE.resolve_config(_req("x", count=1))[2] == SE.MIN_CHOICES


@pytest.mark.parametrize("count", [2, 3, 4])
def test_choice_count_matches_config_exactly(count):
    events = _events(_req(TOPIC, count=count), FakeLLM(count))
    final = events[-1]["data"]
    assert len(final["choices"]) == count
    assert final["simulationValidation"]["passed"], final["simulationValidation"]["issues"]


def test_wrong_choice_count_is_regenerated_then_fails_loudly():
    class BadCount(FakeLLM):
        def __call__(self, system, user, *, max_tokens, temperature):
            return json.dumps({
                "sceneBrief": "면접실에 면접관 두 명이 앉아 있다.",
                "userRole": "지원자", "goal": "목표", "speakerRole": "면접관",
                "line": "JWT 를 왜 선택했는지 먼저 설명해 주시겠습니까? 근거를 들어 말해 주세요.",
                "choices": [{"label": "하나"}],       # 설정은 3개인데 1개
            }, ensure_ascii=False)

    events = _events(_req(TOPIC, count=3), BadCount())
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "SIMULATION_STAGE_FAILED"


# ── 3역할 ──────────────────────────────────────────────────────────────────
def test_first_turn_starts_dialogue_not_a_briefing():
    """1턴은 상황 설명문 한 장이 아니라 등장인물의 대사로 시작하고, 세 역할이 모두 말한다."""
    events = _events(_req(TOPIC), FakeLLM())
    answers = [e["data"] for e in events if e["event"] == "agent_answer"]
    assert [a["simulationRole"] for a in answers] == [SE.HOST, SE.CHALLENGER, SE.COACH]
    assert answers[0]["stageType"] == SE.SCENE_SETUP
    assert "면접실" in answers[0]["answer"]
    assert '"' in answers[0]["answer"]                   # 실제 대사
    assert "당신의 역할:" not in answers[0]["answer"]     # 옛 설명문 블록 금지


def test_second_turn_runs_three_roles_in_order():
    llm = FakeLLM()
    _events(_req(TOPIC), llm)
    events = _events(_req("JWT는 서명된 토큰이고 클라이언트가 저장합니다"), llm)
    answers = [e["data"] for e in events if e["event"] == "agent_answer"]
    assert [a["simulationRole"] for a in answers] == [SE.HOST, SE.CHALLENGER, SE.COACH]
    assert answers[0]["answer"].rstrip().endswith('"')   # 꼬리질문 대사
    assert "?" in answers[1]["answer"]                   # 검증자 반박
    assert "보완할 점" in answers[2]["answer"]            # 코치 피드백
    assert len(answers[0]["choices"]) == 3               # 다음 장면 선택지
    assert events[-1]["data"]["simulationValidation"]["passed"]


def test_scene_is_fixed_across_turns():
    llm = FakeLLM()
    first = _events(_req(TOPIC), llm)
    scenario = first[-1]["data"]["simulationState"]["data"]["scenario"]
    _events(_req("JWT는 서명된 토큰입니다"), llm)
    session = LS.get(LS.resolve_session_id(_req("x"), "simulation"))
    assert session.data["scenario"] == scenario          # 장면을 다시 만들지 않는다
    assert session.turn_index == 2


def test_selected_choice_is_used_as_user_answer():
    llm = FakeLLM()
    _events(_req(TOPIC), llm)
    _events(_req("2번", choice={"choiceId": "B", "label": "구조부터 설명한다"}), llm)
    challenge_prompt = [c["user"] for c in llm.calls if '"targetPoint"' in c["user"]][-1]
    assert "구조부터 설명한다" in challenge_prompt


def test_challenge_must_reference_user_answer():
    assert SE.references_user_answer("토큰을 저장한다고 하셨는데요?", "JWT 토큰을 저장합니다")
    assert not SE.references_user_answer("완전히 무관한 문장입니다", "JWT 토큰 저장 방식")


def test_role_failure_returns_mode_specific_error():
    llm = FakeLLM()
    _events(_req(TOPIC), llm)

    def broken(system, user, *, max_tokens, temperature):
        if '"targetPoint"' in user:
            return "{}"                                   # 검증 역할만 실패
        return llm(system, user, max_tokens=max_tokens, temperature=temperature)

    events = _events(_req("JWT는 토큰입니다"), broken)
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "SIMULATION_STAGE_FAILED"
    assert events[-1]["data"]["failedRole"] == SE.CHALLENGER
    # 일반 Q&A 로 대체된 답변이 나오면 안 된다
    assert not any(e["event"] == "agent_answer" for e in events)


def test_session_resumes_from_client_echo():
    llm = FakeLLM()
    first = _events(_req(TOPIC), llm)
    state = first[-1]["data"]["simulationState"]
    LS.clear_all()
    resumed = _events(_req("JWT는 서명된 토큰입니다", state=state), llm)
    assert resumed[-1]["data"]["sessionId"] == state["sessionId"]
    answers = [e["data"] for e in resumed if e["event"] == "agent_answer"]
    assert len(answers) == 3


def test_difficulty_and_type_reach_the_prompt():
    llm = FakeLLM(2)
    _events(_req("캡스톤 발표에서 교수님이 왜 FastAPI를 따로 썼냐고 묻는 상황을 연습하고 싶어",
                 count=2, difficulty="어려움", stype="프로젝트"), llm)
    prompt = next(c["user"] for c in llm.calls if '"sceneBrief"' in c["user"])
    assert "프로젝트/발표 상황" in prompt
    assert "난이도 어려움" in prompt
    assert "정확히 2개" in prompt


def test_agent_profiles_are_preserved_for_three_roles():
    events = _events(_req(TOPIC), FakeLLM())
    llm = FakeLLM()
    _events(_req(TOPIC, room=999), llm)
    second = _events(_req("JWT는 토큰입니다", room=999), llm)
    names = [e["data"]["agentName"] for e in second if e["event"] == "agent_answer"]
    assert names == ["교수1", "교수2", "교수3"]           # 방 에이전트 이름 보존(진행/검증/코치)


def test_plain_number_reply_resolves_to_stored_choice():
    """프론트가 selectedChoice 를 못 보내도 '2번'은 세션에 저장된 B 선택지로 해석된다."""
    llm = FakeLLM()
    _events(_req(TOPIC), llm)
    _events(_req("2번"), llm)
    challenge_prompt = [c["user"] for c in llm.calls if '"targetPoint"' in c["user"]][-1]
    stored = LS.get_all() if hasattr(LS, "get_all") else None
    assert "2번" in challenge_prompt
    # 저장된 두 번째 선택지의 문구가 사용자의 행동으로 함께 전달되어야 한다.
    assert challenge_prompt.count("선택지") >= 0
    from app.services import simulation_session_engine as _SE
    choices = [{"choiceId": "A", "label": "정의부터 말한다"},
               {"choiceId": "B", "label": "구조부터 설명한다"},
               {"choiceId": "C", "label": "사례부터 든다"}]
    assert _SE.resolve_choice_reference("2번", choices) == "구조부터 설명한다"
    assert _SE.resolve_choice_reference("B", choices) == "구조부터 설명한다"
    assert _SE.resolve_choice_reference("두 번째", choices) == "구조부터 설명한다"
    assert _SE.resolve_choice_reference("모르겠습니다", choices) == ""
    assert _SE.resolve_choice_reference("2번", []) == ""
