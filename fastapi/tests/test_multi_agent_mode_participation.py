"""
멀티에이전트 모드 참여 계약 테스트 (debate / socratic / simulation).

이 파일이 지키는 계약은 하나다.
  선택된 에이전트는 모두 실제로 호출되고, 그 결과가 모두 SSE 로 나간다.

  DEBATE      선택 N명 전원이 입론/반박/예외 정리에 참여하고, 최종 결론은 특정 에이전트
              소유가 아니라 합의(초안 → 상호 검토 → 수정) 결과다. 한 명이 발언을 만들지
              못하면 남은 사람으로 성공 처리하지 않고 DEBATE_AGENT_FAILURE 를 낸다.
  SOCRATIC    한 사이클에서 선택된 에이전트 전원이 서로 다른 기능적 역할로 발화한다.
              한 문장짜리 빈약한 응답을 계약으로 막는다.
  SIMULATION  1턴부터 상황 설명문이 아니라 등장인물의 실제 대사가 나가고, 3역할이 모두
              발화한 뒤 사용자 답변을 기다린다.
"""
import json

import pytest

from app.schemas.multi_chat_schema import MultiChatRequest
from app.services import debate_engine as DE
from app.services import debate_mode_handler as DH
from app.services import learning_session as LS
from app.services import simulation_mode_handler as SIMH
from app.services import simulation_session_engine as SIME
from app.services import socratic_mode_handler as SOCH
from app.services import socratic_multi_agent as SMA


@pytest.fixture(autouse=True)
def _clean():
    LS.clear_all()
    yield
    LS.clear_all()


def _agents(n):
    names = ["김교수", "이선배", "박튜터", "최연구원"]
    return [{"agentId": 10 + i, "id": 10 + i, "name": names[i % len(names)],
             "personality": "논리형", "knowledgeLevel": "박사"} for i in range(n)]


def _answers(events):
    return [e["data"] for e in events if e["event"] == "agent_answer"]


def _starts(events):
    return [e["data"] for e in events if e["event"] == "agent_start"]


def _complete(events):
    for e in events:
        if e["event"] == "all_complete":
            return e["data"]
    return None


def _error(events):
    for e in events:
        if e["event"] == "error":
            return e["data"]
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEBATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DebateLLM:
    """토론 계약을 지키는 fake. agree 로 합의 라운드 분기를 제어한다."""

    def __init__(self, agree=True, fail_opening_for=None, raise_on=None):
        self.agree = agree
        self.fail_opening_for = fail_opening_for  # 결론이 빈 입론을 낼 관점 label 조각
        self.raise_on = raise_on
        self.calls = []

    def __call__(self, system, user, *, max_tokens, temperature):
        self.calls.append(user)
        if self.raise_on and self.raise_on in user:
            raise RuntimeError("ollama_down")
        if '"perspectives"' in user:
            import re
            m = re.search(r"관점 (\d+)개", user)
            n = int(m.group(1)) if m else 2
            stances = ["배포 독립성을 먼저 지킨다고 본다. 경계가 맞으면 격리 이득이 크다.",
                       "운영 단순성을 먼저 지킨다고 본다. 분산 비용이 이득을 잠식한다.",
                       "조직 규모 적합성을 먼저 본다. 인력이 없으면 어떤 설계도 무너진다.",
                       "비용 부담 주체를 먼저 본다. 운영팀이 감당 못하면 무의미하다."]
            return json.dumps({"axis": "무엇을 먼저 지킬 것인가",
                               "perspectives": [{"label": f"관점{i + 1}", "stance": stances[i % 4]}
                                                for i in range(n)]}, ensure_ascii=False)
        if '"reasons"' in user and '"explanation"' in user:
            if self.fail_opening_for and self.fail_opening_for in user:
                return json.dumps({"conclusion": "", "reasons": [], "explanation": ""}, ensure_ascii=False)
            return json.dumps({
                "conclusion": "대규모에서도 보편적 우위는 없고 조건부다",
                "reasons": ["분산 트랜잭션 비용이 크다", "관측성 없이는 장애 격리가 환상이다"],
                "explanation": "경계를 잘못 그으면 네트워크 호출이 늘어 장애가 전파된다. "
                               "관측성 없이는 원인 추적이 불가능하다. 조직 규모가 작으면 부담이 이득을 넘는다.",
            }, ensure_ascii=False)
        if '"counterArgument"' in user:
            return json.dumps({
                "targetClaim": "분산 트랜잭션 비용이 크다는 주장",
                "acknowledgedPoint": "비용이 존재한다는 점은 인정한다",
                "counterArgument": "사가 패턴으로 분산 트랜잭션을 회피하면 그것은 설계 문제이지 아키텍처 자체의 비용이 아니다",
                "evidenceOrReasoning": "관측성 투자는 모놀리식에서도 동일하게 필요하며 장애 격리 이득이 더 크다",
            }, ensure_ascii=False)
        if '"flipConditions"' in user:
            return json.dumps({
                "acknowledgedFromOpponent": "조직 규모가 작으면 부담이 크다는 점",
                "exceptions": ["팀이 10명 이하일 때", "도메인 경계가 불명확할 때"],
                "flipConditions": ["운영 인력이 전무한 경우"],
                "revisedConclusion": "조건이 충족될 때만 우위가 성립한다",
            }, ensure_ascii=False)
        if '"criteria"' in user:
            return json.dumps({"criteria": ["조직 규모와 운영 역량", "도메인 경계의 명확성"]}, ensure_ascii=False)
        if '"recommendation"' in user:
            return json.dumps({
                "decision": "조직 규모와 도메인 경계가 충족될 때만 분리하라",
                "conditions": ["독립 배포 단위를 감당할 인력이 있을 것", "관측성 도구가 먼저 갖춰질 것"],
                "reason": "두 관점 모두 조건 없이는 우위가 성립하지 않는다는 데 도달했다",
                "recommendation": "관측성을 먼저 갖추고 경계 하나만 분리해 검증하라",
            }, ensure_ascii=False)
        if '"agree"' in user:
            agree = self.agree or ("수정 사항" in user)
            return json.dumps({"agree": agree,
                               "corrections": [] if agree else ["장애 격리 이득을 조건에 명시할 것"],
                               "reason": "조건이 충분히 명시되었는지 확인했다"}, ensure_ascii=False)
        return "{}"


def _debate_events(n_agents, llm):
    agents = _agents(n_agents)
    req = MultiChatRequest(message="마이크로서비스가 대규모에서 보편적 우위를 갖는가",
                           mode="debate", learningMode="debate", roomId=1, agents=agents)
    return list(DH.run_debate_mode_stream(req, list(req.agents), llm=llm)), agents


def test_debate_uses_every_selected_agent():
    """3명을 선택하면 3명이 모두 입론과 반박을 한다(앞의 2명만 쓰지 않는다)."""
    events, agents = _debate_events(3, DebateLLM())
    selected = {str(a["agentId"]) for a in agents}
    executed = {str(d["agentId"]) for d in _starts(events)}
    emitted = {str(d["agentId"]) for d in _answers(events)}

    assert selected <= executed, f"호출되지 않은 에이전트가 있다: {selected - executed}"
    assert selected <= emitted, f"SSE 로 나가지 않은 에이전트가 있다: {selected - emitted}"

    openings = [d for d in _answers(events) if d["speechType"] == "OPENING"]
    rebuttals = [d for d in _answers(events) if d["speechType"] == "REBUTTAL"]
    assert {str(d["agentId"]) for d in openings} == selected
    assert {str(d["agentId"]) for d in rebuttals} == selected


def test_debate_two_agents_have_full_argument_structure():
    """A 입론 / B 입론 / A 반박 / B 반박 최소 구조가 존재한다."""
    events, agents = _debate_events(2, DebateLLM())
    seq = [(str(d["agentId"]), d["speechType"]) for d in _answers(events)]
    a, b = str(agents[0]["agentId"]), str(agents[1]["agentId"])
    assert (a, "OPENING") in seq and (b, "OPENING") in seq
    assert (a, "REBUTTAL") in seq and (b, "REBUTTAL") in seq
    # 반박은 상대를 겨냥해야 한다.
    for d in _answers(events):
        if d["speechType"] == "REBUTTAL":
            assert d["targetAgentId"] is not None
            assert str(d["targetAgentId"]) != str(d["agentId"])


def test_debate_final_conclusion_is_not_owned_by_one_agent():
    """최종 결론이 특정 에이전트 이름으로 귀속되지 않는다."""
    events, agents = _debate_events(2, DebateLLM())
    finals = [d for d in _answers(events) if d["speechType"] == "FINAL_CONCLUSION"]
    assert len(finals) == 1
    final = finals[0]
    assert final["consensus"] is True
    assert final["debateSlot"] == DE.CONSENSUS_SLOT
    assert str(final["agentId"]) not in {str(a["agentId"]) for a in agents}
    for a in agents:
        assert not str(final["agentName"]).startswith(a["name"])


def test_debate_consensus_requires_review_from_every_other_agent():
    """초안은 한 명이 쓰지만, 나머지 참여자가 모두 검토 발언을 낸다."""
    events, agents = _debate_events(3, DebateLLM())
    drafts = [d for d in _answers(events) if d["speechType"] == "CONSENSUS_DRAFT"]
    reviews = [d for d in _answers(events) if d["speechType"] == "CONSENSUS_REVIEW"]
    assert len(drafts) >= 1
    assert {str(d["agentId"]) for d in reviews} == {str(a["agentId"]) for a in agents[1:]}

    consensus = _complete(events)["debateResult"]["consensus"]
    assert consensus["agreed"] is True
    assert [x["agree"] for x in consensus["agreement"]] == [True, True, True]


def test_debate_disagreement_triggers_revision_round():
    """동의하지 않으면 초안 작성자가 수정본을 다시 내고 재검토를 받는다."""
    events, _ = _debate_events(2, DebateLLM(agree=False))
    drafts = [d for d in _answers(events) if d["speechType"] == "CONSENSUS_DRAFT"]
    reviews = [d for d in _answers(events) if d["speechType"] == "CONSENSUS_REVIEW"]
    assert len(drafts) == 2, "수정 초안이 다시 나오지 않았다"
    assert len(reviews) == 2
    consensus = _complete(events)["debateResult"]["consensus"]
    assert consensus["rounds"] == 2


def test_debate_agent_failure_does_not_fall_back_to_single_agent():
    """한 명이 입론을 만들지 못하면 남은 한 명으로 성공 처리하지 않는다."""
    events, _ = _debate_events(2, DebateLLM(fail_opening_for="관점2"))
    err = _error(events)
    assert err is not None, "실패했는데 오류 이벤트가 없다"
    assert err["code"] == "DEBATE_AGENT_FAILURE"
    assert err["failedStage"] == "OPENING"
    assert _complete(events) is None, "실패한 토론이 성공(all_complete)으로 끝났다"


def test_debate_llm_exception_is_agent_failure_not_silent_success():
    events, _ = _debate_events(2, DebateLLM(raise_on='"counterArgument"'))
    err = _error(events)
    assert err is not None and err["code"] == "DEBATE_AGENT_FAILURE"
    assert err["failedStage"].startswith("REBUTTAL")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOCRATIC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOPIC_SOC = ("@Transactional이 프록시 기반으로 동작한다는 점은 이해했지만, 동일 객체 내부의 "
             "self-invocation에서 트랜잭션 경계가 형성되지 않는 이유를 연결하지 못하고 있다.")


class SocraticLLM:
    def __init__(self):
        self.roles_seen = []

    def __call__(self, system, user, *, max_tokens, temperature):
        if '"expectedIdea"' in user and '"acknowledge"' not in user:
            return json.dumps({"expectedIdea": "프록시 바깥에서 들어온 호출만 어드바이스를 거친다",
                               "answerKeywords": ["프록시 우회"]}, ensure_ascii=False)
        if '"acknowledge"' in user:
            if "개념 유도" in user:
                role = "PROBE"
                ack = "프록시 기반 동작을 이해했다고 말한 부분은 정확하게 짚은 것이다."
                direction = ("이제 호출이 실제로 어떤 경로를 지나 들어오는지, 그 경로 중 어디가 "
                             "빠지는지를 나눠서 살펴보는 것이 좋겠다.")
                q = "그 호출은 어디에서 출발한다고 보나?"
            elif "다른 관점" in user:
                role = "PERSPECTIVE"
                ack = "호출 경로를 나눠 보자는 앞의 제안은 출발점으로 삼을 만하다."
                direction = ("같은 메서드를 바깥의 다른 객체가 부르는 상황을 함께 놓고 비교하면 "
                             "두 경우의 차이가 훨씬 또렷하게 드러난다.")
                q = "다른 빈이 그 메서드를 부르면 결과가 달라질까?"
            else:
                role = "VERIFY"
                ack = "두 호출을 비교해 보자는 제안까지는 논리가 이어진다."
                direction = ("다만 그 비교에서 무엇이 결론을 결정했는지는 아직 말해지지 않았고, "
                             "그 자리에 빠진 전제가 하나 있는지 확인할 필요가 있다.")
                q = "지금 설명에서 근거 없이 넘어간 단계는 어디인가?"
            self.roles_seen.append(role)
            return json.dumps({"acknowledge": ack, "direction": direction, "question": q},
                              ensure_ascii=False)
        return "{}"


def _socratic_events(n_agents, llm, message=TOPIC_SOC, state=None, room=2):
    agents = _agents(n_agents)
    req = MultiChatRequest(message=message, mode="socratic", learningMode="socratic",
                           roomId=room, socraticState=state, agents=agents)
    return list(SOCH.run_socratic_mode_stream(req, list(req.agents), llm=llm)), agents


def test_socratic_every_selected_agent_speaks_in_one_cycle():
    events, agents = _socratic_events(3, SocraticLLM())
    answers = _answers(events)
    assert len(answers) == 3, "설정한 에이전트 수만큼 발화하지 않았다"
    assert {str(d["agentId"]) for d in answers} == {str(a["agentId"]) for a in agents}
    assert [d["socraticRole"] for d in answers] == [SMA.PROBE, SMA.PERSPECTIVE, SMA.VERIFY]


def test_socratic_answers_are_not_one_liners():
    """맥락 인정 + 사고 방향 + 질문 1개 계약이 빈약한 응답을 막는다."""
    events, _ = _socratic_events(3, SocraticLLM())
    for d in _answers(events):
        assert len(d["answer"]) >= SMA.MIN_TURN_CHARS, f"너무 짧다: {d['answer']}"
        assert d["answer"].count("?") == 1, f"질문이 1개가 아니다: {d['answer']}"
        assert d["question"], "질문 필드가 비었다"


def test_socratic_second_cycle_also_uses_all_agents():
    """첫 사이클 이후에도 1번 에이전트만 계속 쓰면 FAIL 이다."""
    llm = SocraticLLM()
    events, agents = _socratic_events(3, llm)
    state = _complete(events)["socraticState"]
    events2, _ = _socratic_events(3, llm, message="같은 객체 안에서 호출하니까 프록시를 안 거칩니다",
                                  state=state)
    answers2 = _answers(events2)
    assert len(answers2) == 3
    assert {str(d["agentId"]) for d in answers2} == {str(a["agentId"]) for a in agents}


def test_socratic_does_not_reveal_answer_first():
    events, _ = _socratic_events(3, SocraticLLM())
    complete = _complete(events)
    assert all(step["directAnswerSuppressed"] for step in complete["socraticSteps"])


def test_socratic_roles_are_assigned_to_all_agents():
    roles = SMA.assign_roles(_agents(4))
    assert len(roles) == 4, "선택된 에이전트를 잘라내면 안 된다"
    assert [r for _, r in roles] == [SMA.PROBE, SMA.PERSPECTIVE, SMA.VERIFY, SMA.PROBE]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SIMULATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOPIC_SIM = ("캡스톤 최종 발표에서 Spring Boot와 FastAPI를 분리한 아키텍처의 타당성과 "
             "그로 인해 발생하는 부분 장애 문제를 방어해야 하는 상황이다.")


class SimulationLLM:
    def __init__(self, choice_count=3):
        self.choice_count = choice_count

    def __call__(self, system, user, *, max_tokens, temperature):
        n = self.choice_count
        if '"sceneBrief"' in user:
            return json.dumps({
                "sceneBrief": "캡스톤 최종 발표장, 심사위원 셋이 앞에 앉아 있다.",
                "userRole": "발표자", "goal": "아키텍처 분리 근거를 방어한다",
                "speakerRole": "교수",
                "line": "Spring Boot 하나로도 HTTP API를 만들 수 있는데 왜 굳이 FastAPI 서버를 "
                        "따로 분리했습니까? 단순히 파이썬 라이브러리가 편해서였던 건 아닙니까?",
                "choices": [{"label": f"선택 {i + 1}"} for i in range(n)],
            }, ensure_ascii=False)
        if '"focusPoints"' in user:
            return json.dumps({"focusPoints": ["분리 결정의 기준", "부분 장애 대응책"],
                               "line": "근거부터 말하고 대안 비교로 이어가세요."}, ensure_ascii=False)
        if '"speakerRole"' in user:
            return json.dumps({"speakerRole": "심사위원",
                               "line": "두 서버 사이에 네트워크 호출이 하나 더 생기면 타임아웃과 부분 장애가 "
                                       "따라옵니다. 그 비용을 감수할 설계상 이점이 무엇입니까?"}, ensure_ascii=False)
        if '"reaction"' in user:
            return json.dumps({
                "reaction": "교수가 메모하다 고개를 든다.",
                "targetPart": "모델 서빙을 파이썬에서 한다고 말한 부분",
                "line": "모델 서빙을 파이썬에서 한다고 하셨는데, 그 서버가 죽으면 사용자 요청은 어떻게 됩니까?",
                "choices": [{"label": f"다음 {i + 1}"} for i in range(n)],
            }, ensure_ascii=False)
        if '"targetPoint"' in user:
            return json.dumps({"targetPoint": "재시도로 막는다고 한 부분",
                               "line": "재시도로 막는다고 하셨는데 모델 추론은 수 초가 걸립니다. "
                                       "재시도가 오히려 큐를 무너뜨리지 않겠습니까?"}, ensure_ascii=False)
        if '"strengths"' in user:
            return json.dumps({"strengths": ["분리 이유를 먼저 말했다"],
                               "weaknesses": ["장애 시 폴백이 빠졌다"],
                               "improvement": "타임아웃 값과 폴백 경로를 한 줄로 덧붙이세요."}, ensure_ascii=False)
        return "{}"


def _sim_events(llm, message=TOPIC_SIM, state=None, config=None, room=3, n_agents=3):
    agents = _agents(n_agents)
    req = MultiChatRequest(message=message, mode="simulation", learningMode="simulation",
                           roomId=room, simulationState=state,
                           simulationConfig=config or {"choiceCount": 3}, agents=agents)
    return list(SIMH.run_simulation_mode_stream(req, list(req.agents), llm=llm)), agents


def test_simulation_first_turn_is_dialogue_not_briefing():
    """1턴이 상황 설명문 한 장으로 끝나지 않고 등장인물의 대사로 시작한다."""
    events, _ = _sim_events(SimulationLLM())
    answers = _answers(events)
    host = answers[0]
    assert host["simulationRole"] == SIME.HOST
    assert '"' in host["answer"], "등장인물의 대사가 없다"
    assert host["answer"].rstrip().endswith('"'), "대사로 끝나지 않고 안내문으로 끝났다"
    # 예전 실패 형태(설명문 블록)를 그대로 되풀이하지 않는다.
    assert "당신의 역할:" not in host["answer"]
    assert "목표:" not in host["answer"]


def test_simulation_first_turn_uses_all_three_roles():
    events, agents = _sim_events(SimulationLLM())
    answers = _answers(events)
    assert [d["simulationRole"] for d in answers] == [SIME.HOST, SIME.CHALLENGER, SIME.COACH]
    assert {str(d["agentId"]) for d in answers} == {str(a["agentId"]) for a in agents}


def test_simulation_does_not_answer_for_the_user():
    """1턴은 질문까지만 하고 사용자 답변을 기다린다."""
    events, _ = _sim_events(SimulationLLM())
    complete = _complete(events)
    assert complete["turnIndex"] == 1
    host, challenger = _answers(events)[0], _answers(events)[1]
    assert "?" in host["answer"] and "?" in challenger["answer"]


def test_simulation_second_turn_follows_up_on_user_answer():
    llm = SimulationLLM()
    events, _ = _sim_events(llm)
    state = _complete(events)["simulationState"]
    events2, _ = _sim_events(llm, message="모델 서빙을 파이썬에서 하고 장애 시 재시도로 막습니다",
                             state=state)
    answers2 = _answers(events2)
    assert [d["simulationRole"] for d in answers2] == [SIME.HOST, SIME.CHALLENGER, SIME.COACH]
    assert "모델 서빙" in answers2[0]["answer"], "꼬리질문이 사용자 답변을 집지 않았다"
    assert "재시도" in answers2[1]["answer"], "검증자가 사용자 답변을 공격하지 않았다"
    assert "보완할 점" in answers2[2]["answer"], "코치 피드백이 없다"
    assert _complete(events2)["simulationValidation"]["passed"] is True


def test_simulation_session_is_not_restarted_every_turn():
    llm = SimulationLLM()
    events, _ = _sim_events(llm)
    complete = _complete(events)
    events2, _ = _sim_events(llm, message="모델 서빙을 파이썬에서 하고 장애 시 재시도로 막습니다",
                             state=complete["simulationState"])
    complete2 = _complete(events2)
    assert complete2["sessionId"] == complete["sessionId"]
    assert complete2["turnIndex"] == 2
    # 같은 장면을 이어간다 — 첫 장면 소개를 다시 하지 않는다.
    assert "심사위원 셋이 앞에 앉아" not in _answers(events2)[0]["answer"]


@pytest.mark.parametrize("count", [2, 3, 4])
def test_simulation_choice_count_is_exact(count):
    events, _ = _sim_events(SimulationLLM(choice_count=count),
                            config={"choiceCount": count}, room=300 + count)
    complete = _complete(events)
    assert len(complete["choices"]) == count


def test_simulation_free_response_setting_adds_no_choices():
    """면접/발표처럼 자유 답변이 자연스러운 설정이면 선택지를 억지로 붙이지 않는다."""
    events, _ = _sim_events(SimulationLLM(choice_count=0),
                            config={"choiceCount": 3, "interactionStyle": "free_response"},
                            room=311)
    assert _complete(events)["choices"] == []


def test_simulation_include_choices_false_is_respected():
    events, _ = _sim_events(SimulationLLM(choice_count=0),
                            config={"choiceCount": 3, "includeChoices": False}, room=312)
    assert _complete(events)["choices"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 계측
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_dispatcher_logs_selected_executed_emitted(caplog, monkeypatch):
    from app.services import learning_mode_dispatcher as D

    def fake_handler(request, agents):
        yield {"event": "agent_start", "data": {"agentId": 10}}
        yield {"event": "agent_answer", "data": {"agentId": 10}}
        yield {"event": "all_complete", "data": {}}

    monkeypatch.setattr(D, "_handler", lambda mode: (fake_handler, "fake"))
    req = MultiChatRequest(message="토론해보자 마이크로서비스 분리 기준이 무엇인가",
                           mode="debate", learningMode="debate", roomId=9, agents=_agents(2))
    with caplog.at_level("INFO"):
        list(D.run_learning_mode_stream(req, list(req.agents), "debate"))
    audit = [r.getMessage() for r in caplog.records if "[MODE-AUDIT]" in str(r.msg)]
    assert audit, "MODE-AUDIT 로그가 없다"
    line = audit[0]
    assert "expected_agent_count=2" in line
    assert "emitted_agent_count=1" in line
    assert "result=FAIL" in line, "선택 2명인데 1명만 나갔으면 FAIL 로 표시돼야 한다"


def test_debate_topic_ignores_injected_memory_block():
    """앞단에서 주입된 [이전 대화 기억] 블록이 이번 토론의 안건이 되면 안 된다."""
    from app.services import memory_recall_service as MR

    current = "지금 물어보는 것은 캐시 무효화 전략이 정당한가이다"
    injected = (f"[이전 대화 기억]\n- 사용자: 완전히 다른 옛날 질문\n\n"
                f"{MR._MEMORY_BLOCK_CURRENT_MARKER}\n{current}")
    req = MultiChatRequest(message=injected, mode="debate", learningMode="debate",
                           roomId=77, agents=_agents(2))
    assert DE.extract_topic(req) == current


def test_socratic_rejects_agent_that_repeats_the_previous_speaker():
    """세 명이 같은 말을 조금씩 바꿔 세 번 하면 계약 위반으로 잡는다."""
    first = SMA.AgentSpeech(role=SMA.PROBE, agent_id=1, agent_name="김교수", agent_index=1,
                            text="", acknowledge="프록시 기반 동작을 이해했다고 말한 부분은 정확하다.",
                            direction="이제 호출 경로가 어디서 끊기는지 나눠서 살펴보자.",
                            question="그 호출은 어디에서 출발하나?")
    copycat = SMA.AgentSpeech(role=SMA.PERSPECTIVE, agent_id=2, agent_name="이선배", agent_index=2,
                              text="", acknowledge=first.acknowledge,
                              direction=first.direction,
                              question="그 호출은 어디에서 시작되나?")
    copycat.text = SMA._render(copycat.acknowledge, copycat.direction, copycat.question)
    issues = SMA.validate_speech(copycat, expected_idea="", known_text="",
                                 keywords=None, used_questions=[first.question], peers=[first])
    assert "question_repeated" in issues or "repeats_peer_body" in issues
