"""A1: 기본개념모드 답변 골격(개념→예시→정리) 주입 검증."""
from app.schemas.multi_chat_schema import AgentProfile
from app.services import orchestrator_service as orch


def _agent():
    return AgentProfile(id=1, agentId="a1", name="전문봇", personality="전문적", knowledgeLevel="학사")


def test_basic_system_prompt_has_structure_skeleton():
    sp = orch._build_single_agent_system_prompt(_agent(), "basic", [_agent()], position=0, total=1)
    assert "예시" in sp and "정리" in sp
    assert "골격" in sp


def test_socratic_prompt_does_not_force_explanation_skeleton():
    # 소크라테스는 설명 골격을 강제하지 않는다(모드 형식 우선).
    sp = orch._build_single_agent_system_prompt(_agent(), "socratic", [_agent()], position=0, total=1)
    assert "답변 골격" not in sp
