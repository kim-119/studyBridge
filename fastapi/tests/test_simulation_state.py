from app.services import learning_session as LS
from app.services import simulation_mode_handler as H
from app.services import simulation_session_engine as SE


def test_simulation_state_v2_accumulates_actions_and_consequences():
    s = LS.LearningSession(session_id="sim-1", mode="simulation", topic="장애 대응", state="CHOICE_RESULT", turn_index=1,
                           data={"scenario": "새벽 장애", "userRole": "온콜", "goal": "복구", "prompt": "무엇을 할까?",
                                 "choices": [{"label": "롤백"}, {"label": "재시작"}],
                                 "stateV2": {"userActions": [{"turn": 0, "action": "로그 확인"}], "consequences": []}})
    host = SE.SimSpeech(role=SE.HOST, stage_type="CHOICE_RESULT", stage_title="결과", text="롤백하자 오류율이 떨어졌다",
                        structured={"line": "롤백하자 오류율이 떨어졌다"})
    st = H._simulation_state_v2(s, [host], "롤백", is_new=False)
    assert st["version"] == 2 and st["scenarioState"]["scenario"] == "새벽 장애"
    assert [a["action"] for a in st["userActions"]] == ["로그 확인", "롤백"]
    assert st["consequences"][-1]["result"].startswith("롤백하자")
    assert st["unresolvedEvents"] == ["롤백", "재시작"]


def test_simulation_prompts_receive_persona(monkeypatch):
    from app.schemas.multi_chat_schema import AgentProfile
    seen = {}

    def base(system_prompt, user_prompt, **kw):
        seen["system"] = system_prompt
        return "{}"
    styled = H._styled_llm(base, AgentProfile(agentId=1, name="이교수", personality="냉소적", knowledgeLevel="박사"))
    styled("엔진 시스템", "u", max_tokens=10, temperature=0.1)
    assert "엔진 시스템" in seen["system"] and "[PERSONALITY: 냉소적]" in seen["system"]
    assert "[MODE: 상황극]" in seen["system"] and "[KNOWLEDGE LEVEL: 박사]" in seen["system"]
