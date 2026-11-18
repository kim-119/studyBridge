"""PromptCompiler 구조 전수: 6 persona × 5 knowledge × 4 mode = 120 조합."""
import itertools

import pytest

from app.studymate import prompt_compiler as PC
from app.studymate.knowledge_policy import CONTRACT as KC
from app.studymate.mode_policy import CONTRACT as MC, role_for_position
from app.studymate.persona_policy import STRATEGY
from app.studymate.profile_contract import KNOWLEDGE_KEYS, PERSONALITY_KEYS

MODES = ("basic", "socratic", "debate", "simulation")
COMBOS = list(itertools.product(PERSONALITY_KEYS, KNOWLEDGE_KEYS, MODES))


def test_combo_count():
    assert len(COMBOS) == 120


@pytest.mark.parametrize("persona,level,mode", COMBOS)
def test_compiled_structure(persona, level, mode):
    c = PC.compile_prompt(PC.CompileInput(mode=mode, role="core", persona=persona, level=level, agent_name="교수",
                                          question="질문", num_ctx=8192, output_reserve=1000))
    sysu = c.system + "\n" + c.user
    assert f"[MODE: {MC[mode]['name']}]" in c.system
    assert "[ROLE]" in c.system
    assert f"[KNOWLEDGE LEVEL: {KC[level]['name']}]" in c.system
    assert f"[PERSONALITY: {STRATEGY[persona]['name']}]" in c.system
    assert "[FINAL BEHAVIOR REMINDER]" in c.user
    assert c.user.index("[FINAL BEHAVIOR REMINDER]") < c.user.index("[현재 질문]")
    assert c.system.index("[MODE:") < c.system.index("[KNOWLEDGE LEVEL:") < c.system.index("[PERSONALITY:")
    assert not c.overflow_required
    style = PC.style_directive(persona, level, mode, "debater")
    for tag in ("[MODE:", "[KNOWLEDGE LEVEL:", "[PERSONALITY:", "[FINAL BEHAVIOR REMINDER]"):
        assert tag in style


def test_system_prefix_is_byte_stable_across_questions():
    a = PC.compile_prompt(PC.CompileInput(mode="basic", role="core", persona="critical", level="phd", agent_name="x", question="A"))
    b = PC.compile_prompt(PC.CompileInput(mode="basic", role="core", persona="critical", level="phd", agent_name="x", question="B 다른 질문"))
    assert a.system == b.system and a.system_hash == b.system_hash and a.prompt_hash != b.prompt_hash


def test_mode_changes_protocol_block():
    blocks = {m: PC.mode_block(m) for m in MODES}
    assert len(set(blocks.values())) == 4


def test_role_rotation():
    assert [role_for_position(i, 3) for i in range(3)] == ["core", "challenge", "extend"]
    assert role_for_position(0, 1) == "solo"
