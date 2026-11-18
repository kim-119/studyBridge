"""Token budget allocator: 필수 섹션(시스템/페르소나/질문)은 절대 잘리지 않고, 이력→grounding 순으로 줄인다."""
from app.studymate import prompt_compiler as PC
from app.studymate import token_budget as TB


def _long_turns(n):
    return [f"- 사용자: 이전 질문 {i} " + "혼잡 윈도우 ssthresh 재전송 타이머 설명 요청 " * 30 for i in range(n)]


def test_required_sections_survive_overflow():
    ci = PC.CompileInput(mode="basic", role="core", persona="critical", level="phd", agent_name="이교수",
                         question="TCP 혼잡제어를 설명해줘", recent_turns=_long_turns(40),
                         grounding_items=["(wiki) " + "근거 문장 " * 400] * 3, num_ctx=8192, output_reserve=1400)
    c = PC.compile_prompt(ci)
    for block in ("[MODE:", "[PERSONALITY: 비판형]", "[KNOWLEDGE LEVEL: 박사]", "[FINAL BEHAVIOR REMINDER]",
                  "[현재 질문]", "TCP 혼잡제어를 설명해줘", "[안전 정책]"):
        assert block in (c.system + c.user), block
    assert c.estimated_tokens <= c.max_input_tokens + TB.TEMPLATE_OVERHEAD
    assert any(d.startswith("recent_context") for d in c.dropped_sections)


def test_history_dropped_before_grounding():
    ci = PC.CompileInput(mode="basic", role="core", persona="logical", level="master", agent_name="x",
                         question="B-트리", recent_turns=_long_turns(12),
                         grounding_items=["(wiki) B-트리 설명 " * 50], num_ctx=4096, output_reserve=1200)
    c = PC.compile_prompt(ci)
    drops = c.dropped_sections
    if any(d.startswith("grounding") for d in drops):
        first_g = next(i for i, d in enumerate(drops) if d.startswith("grounding"))
        assert all(d.startswith("recent_context") or d.startswith("rolling_summary") for d in drops[:first_g])


def test_real_tokenizer_counts_korean_densely():
    n = TB.count_tokens("TCP 혼잡제어는 슬로우스타트, 혼잡회피, 빠른재전송, 빠른회복 4단계로 구성된다. " * 10)
    assert n > 250


def test_default_num_ctx_is_not_4096():
    from app.studymate import model_router
    assert model_router.num_ctx() >= 8192
