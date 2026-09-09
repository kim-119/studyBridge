"""
DEBATE 모드 실행 엔진 테스트.

LLM은 전부 fake로 주입해 '토론 orchestration이 코드로 실제 일어나는지'만 검증한다.
  - 두 에이전트가 서로 다른 관점을 받는다
  - 반박 프롬프트에 상대의 '실제 발언 원문'이 들어간다
  - 강도(light/normal/deep)가 라운드 수로 반영된다(토큰 길이가 아니라)
  - 사회자/판정 발언이 없다
  - 실패 단계만 재생성된다
"""
import json

import pytest

from app.schemas.multi_chat_schema import AgentProfile, MultiChatRequest
from app.services import debate_engine as DE
from app.services import debate_mode_handler as H


# ── fake LLM ────────────────────────────────────────────────────────────────
A_TERM, B_TERM = "모듈경계유지", "독립배포확장"


class FakeLLM:
    """프롬프트에 요구된 JSON 스키마를 보고 그럴듯한 구조화 응답을 만든다."""

    def __init__(self):
        self.calls = []          # (system, user, max_tokens, temperature)

    def __call__(self, system, user, *, max_tokens, temperature):
        self.calls.append({"system": system, "user": user,
                           "max_tokens": max_tokens, "temperature": temperature})
        if '"perspectives"' in user:
            import re as _re
            m = _re.search(r"관점 (\d+)개", user)
            n = int(m.group(1)) if m else 2
            terms = [A_TERM, B_TERM, "점진전환", "비용전가"]
            labels = ["운영 단순성 우선", "확장 유연성 우선", "전환 속도 우선", "비용 주체 우선"]
            return json.dumps({
                "axis": "운영 단순성과 확장 유연성 중 무엇을 먼저 지킬 것인가",
                "perspectives": [{"label": labels[i], "stance": f"{terms[i]}로 얻는 편익을 우선한다."}
                                 for i in range(n)],
            }, ensure_ascii=False)
        if '"axis"' in user:
            return json.dumps({
                "axis": "운영 단순성과 확장 유연성 중 무엇을 먼저 지킬 것인가",
                "a": {"label": "운영 단순성 우선", "stance": f"{A_TERM}로 복잡도를 억제하는 편익을 우선한다."},
                "b": {"label": "확장 유연성 우선", "stance": f"{B_TERM}로 얻는 확장성을 우선한다."},
            }, ensure_ascii=False)
        if '"agree"' in user:
            return json.dumps({"agree": True, "corrections": [],
                               "reason": "조건이 명시되어 있고 내 예외가 반영되었다."}, ensure_ascii=False)
        if '"conclusion"' in user:
            head = user.split("[상대 관점]")[0]
            term = A_TERM if A_TERM in head else B_TERM
            return json.dumps({
                "conclusion": f"{term} 관점에서 이 선택이 더 타당하다.",
                "reasons": [f"{term} 때문에 초기 비용이 낮다", f"{term} 덕분에 회수 가능성이 높다"],
                "explanation": f"{term} 는 실제 운영에서 병목을 줄인다. " * 3,
            }, ensure_ascii=False)
        if '"targetClaim"' in user:
            # 상대 발언 원문 블록에서 실제 용어를 뽑아 지목한다(strawman 아님).
            opp_block = user.split("실제로 한 발언 원문")[1] if "실제로 한 발언 원문" in user else user
            term = A_TERM if A_TERM in opp_block else B_TERM
            import re as _re
            m = _re.search(r"이번은 (\d+)차 반박이다", user)
            nth = int(m.group(1)) if m else 1
            return json.dumps({
                "targetClaim": f"{term} 때문에 초기 비용이 낮다는 주장",
                "acknowledgedPoint": f"{term} 의 이점 자체는 인정한다.",
                "counterArgument": f"그러나 {term} 는 조건이 바뀌면 비용이 역전된다({nth}번째 논점).",
                "evidenceOrReasoning": f"{term} 가 성립하려면 전제가 필요한데 그 전제가 흔히 깨진다({nth}).",
            }, ensure_ascii=False)
        if '"acknowledgedFromOpponent"' in user:
            mine = A_TERM if A_TERM in user.split("[상대 관점]")[0] else B_TERM
            return json.dumps({
                "acknowledgedFromOpponent": f"{mine} 관점에서도 상대의 전제 지적은 타당하다.",
                "exceptions": [f"{mine} 가 통하지 않는 조직 규모", f"{mine} 의 전제가 깨지는 요구 변화"],
                "flipConditions": [f"{mine} 의 전제가 무너지면 결론이 달라진다"],
                "revisedConclusion": f"{mine} 는 전제가 유지되는 동안에만 유효하다.",
            }, ensure_ascii=False)
        if '"criteria"' in user:
            return json.dumps({"criteria": ["조직 성숙도", "확장 요구의 구체성"]}, ensure_ascii=False)
        if '"decision"' in user:
            return json.dumps({
                "decision": "지금 단계에서는 단순한 구조로 시작하고 병목이 확인된 영역만 분리하라.",
                "conditions": ["조직 규모가 아직 작을 것", "확장 요구가 특정 영역에 몰려 있을 것"],
                "reason": "양측 반박을 모두 통과한 기준은 조직 성숙도였다.",
                "recommendation": "경계를 먼저 정리하고 측정 후 단계적으로 분리하라.",
            }, ensure_ascii=False)
        return "{}"


def _agents(n=2):
    return [
        AgentProfile(agentId=f"a{i}", id=f"a{i}", name=f"교수{i}", agentSlot=i,
                     personality="논리", knowledgeLevel="학사")
        for i in range(1, n + 1)
    ]


def _req(message="모놀리식과 마이크로서비스 중 대규모 서비스에 더 좋은 선택은?", strength="normal", n=2):
    return MultiChatRequest(message=message, mode="debate", learningMode="debate",
                            debateStrength=strength,
                            agents=[a.model_dump() for a in _agents(n)])


# ── 강도 → 라운드 수 ────────────────────────────────────────────────────────
def test_strength_maps_to_rebuttal_rounds_not_tokens():
    assert DE.rebuttal_rounds("light") == 1
    assert DE.rebuttal_rounds("normal") == 2
    assert DE.rebuttal_rounds("deep") == 3


def test_resolve_strength_sources():
    assert DE.resolve_strength(_req(strength="deep")) == "deep"
    assert DE.resolve_strength(MultiChatRequest(message="x", mode="debate")) == "normal"
    assert DE.resolve_strength(
        MultiChatRequest(message="x", mode="debate", debateConfig={"debateDepth": "light"})) == "light"


@pytest.mark.parametrize("strength,rounds", [("light", 1), ("normal", 2), ("deep", 3)])
def test_rebuttal_round_count_matches_strength(strength, rounds):
    llm = FakeLLM()
    t = DE.run_debate(_req(strength=strength), _agents(), llm=llm)
    assert len(t.rebuttals["A"]) == rounds
    assert len(t.rebuttals["B"]) == rounds
    rebuttal_speeches = [s for s in t.speeches if s.speech_type == "REBUTTAL"]
    assert len(rebuttal_speeches) == rounds * 2


def test_strength_does_not_change_token_budget():
    """강도 차이를 max_tokens 로 처리하면 안 된다."""
    budgets = set()
    for strength in ("light", "normal", "deep"):
        llm = FakeLLM()
        DE.run_debate(_req(strength=strength), _agents(), llm=llm)
        budgets.update(c["max_tokens"] for c in llm.calls)
    assert budgets == {DE.CONTENT_MAX_TOKENS}


# ── 관점 배정 ────────────────────────────────────────────────────────────────
def test_positions_are_opposed_and_assigned_to_two_agents():
    llm = FakeLLM()
    t = DE.run_debate(_req(), _agents(), llm=llm)
    assert len(t.positions) == 2
    a, b = t.positions
    assert a.label != b.label
    assert a.stance != b.stance
    assert {a.agent_id, b.agent_id} == {"a1", "a2"}


def test_topic_is_user_message_verbatim_without_topic_generation():
    msg = "RAG 시스템에서 Vector DB를 반드시 별도로 사용해야 하는가?"
    llm = FakeLLM()
    t = DE.run_debate(_req(message=msg), _agents(), llm=llm)
    assert t.topic == msg
    # 논제 후보 생성(TOPIC_SELECTION)을 호출하지 않는다.
    assert all("논제 후보" not in c["user"] for c in llm.calls)


# ── 6단 논법 2~6단계 ─────────────────────────────────────────────────────────
def test_openings_contain_conclusion_reasons_explanation():
    t = DE.run_debate(_req(), _agents(), llm=FakeLLM())
    for slot in ("A", "B"):
        arg = t.openings[slot]
        assert arg.conclusion
        assert len(arg.reasons) >= 2
        assert len(arg.explanation) >= 30
        assert DE.validate_initial_argument(arg) == []


def test_exception_stage_exists_for_both_agents():
    t = DE.run_debate(_req(), _agents(), llm=FakeLLM())
    for slot in ("A", "B"):
        note = t.exceptions[slot]
        assert len(note.exceptions) >= 2
        assert note.revised_conclusion
    assert len([s for s in t.speeches if s.speech_type == "EXCEPTION"]) == 2


def test_light_has_no_separate_revision_deep_has_convergence():
    light = DE.run_debate(_req(strength="light"), _agents(), llm=FakeLLM())
    assert [s for s in light.speeches if s.speech_type == "REVISION"] == []
    assert light.convergence == []

    deep = DE.run_debate(_req(strength="deep"), _agents(), llm=FakeLLM())
    assert len([s for s in deep.speeches if s.speech_type == "REVISION"]) == 2
    assert len(deep.convergence) >= 2


# ── ★ 상대의 실제 발언을 반박하는가 ──────────────────────────────────────────
def test_rebuttal_prompt_contains_opponent_actual_speech():
    llm = FakeLLM()
    t = DE.run_debate(_req(strength="light"), _agents(), llm=llm)
    opening_b = next(s for s in t.speeches if s.slot == "B" and s.speech_type == "OPENING")
    rebuttal_prompts = [c["user"] for c in llm.calls if '"targetClaim"' in c["user"]]
    # A가 B를 반박할 때 프롬프트에 B의 입론 원문이 들어 있어야 한다.
    assert any(opening_b.text[:60] in p for p in rebuttal_prompts)


def test_rebuttal_targets_opponent_claim():
    t = DE.run_debate(_req(), _agents(), llm=FakeLLM())
    ok, issues = DE.validate_transcript(t)
    assert ok, issues


def test_strawman_rebuttal_is_regenerated():
    """상대가 하지 않은 말을 반박하면 그 단계만 재생성한다."""
    class Strawman(FakeLLM):
        def __init__(self):
            super().__init__()
            self.rebuttal_attempts = 0

        def __call__(self, system, user, *, max_tokens, temperature):
            if '"targetClaim"' in user:
                self.rebuttal_attempts += 1
                if "[재작성 지시" not in user:
                    self.calls.append({"system": system, "user": user,
                                       "max_tokens": max_tokens, "temperature": temperature})
                    return json.dumps({
                        "targetClaim": "완전히 다른 세계의 무관한 문장",
                        "acknowledgedPoint": "없음",
                        "counterArgument": "관련 없는 이야기를 길게 늘어놓는 반박입니다 정말로.",
                        "evidenceOrReasoning": "근거도 무관합니다 정말로 무관합니다.",
                    }, ensure_ascii=False)
            return super().__call__(system, user, max_tokens=max_tokens, temperature=temperature)

    llm = Strawman()
    t = DE.run_debate(_req(strength="light"), _agents(), llm=llm)
    # 반박 2건 × (1차 실패 + 재작성 성공) = 4회 이상 호출
    assert llm.rebuttal_attempts >= 4
    # 재생성은 해당 단계에만 적용된다: 입론은 2회(각 1회)만 생성된다.
    assert len([c for c in llm.calls if '"conclusion"' in c["user"]]) == 2
    ok, issues = DE.validate_transcript(t)
    assert ok, issues


def test_rebuttal_does_not_repeat_previous_round():
    t = DE.run_debate(_req(strength="deep"), _agents(), llm=FakeLLM())
    for slot in ("A", "B"):
        bodies = [r.counter_argument for r in t.rebuttals[slot]]
        assert len(set(bodies)) == len(bodies)


# ── 사회자 없음 / 승패 없음 ──────────────────────────────────────────────────
def test_no_moderator_agent():
    t = DE.run_debate(_req(), _agents(), llm=FakeLLM())
    speakers = {s.agent_id for s in t.speeches}
    # 제3의 '사람'(사회자/심판)은 없다. 합의 결론 카드는 참여자 공동 소유이지 인물이 아니다.
    assert speakers == {"a1", "a2", DE.CONSENSUS_AGENT_ID}
    assert {s.agent_id for s in t.speeches if s.speech_type != "FINAL_CONCLUSION"} == {"a1", "a2"}
    joined = "\n".join(s.text for s in t.speeches)
    for banned in ("사회자", "중재자", "심판", "판정단"):
        assert banned not in joined


def test_final_conclusion_is_single_answer_not_a_winner():
    t = DE.run_debate(_req(), _agents(), llm=FakeLLM())
    assert t.final is not None
    assert DE.validate_final(t.final) == []
    final_speech = next(s for s in t.speeches if s.speech_type == "FINAL_CONCLUSION")
    # 최종 결론은 특정 에이전트 소유가 아니다(합의 결과).
    assert final_speech.slot == DE.CONSENSUS_SLOT
    assert final_speech.agent_id == DE.CONSENSUS_AGENT_ID
    assert "승" not in t.final.decision


def test_winner_declaration_is_rejected_by_validator():
    bad = DE.FinalConclusion(decision="Agent A 승리로 판정한다. 이것이 결론이다.",
                             conditions=["조건 하나가 여기에 있다"],
                             reason="A의 근거가 더 강했기 때문이다.",
                             recommendation="A의 방식을 따르라.")
    assert "winner_declaration" in DE.validate_final(bad)


# ── 사용자가 입장을 먼저 말해도 반대 관점이 검토된다 ─────────────────────────
def test_user_stated_stance_still_gets_opposing_position():
    msg = "나는 마이크로서비스가 더 좋다고 생각한다. 독립 배포가 가능하기 때문이다."
    t = DE.run_debate(_req(message=msg), _agents(), llm=FakeLLM())
    assert t.positions[0].label != t.positions[1].label
    assert t.openings["A"].conclusion and t.openings["B"].conclusion
    assert len(t.rebuttals["A"]) >= 1 and len(t.rebuttals["B"]) >= 1


# ── 단일 에이전트 방에서도 2인 토론 ──────────────────────────────────────────
def test_single_agent_room_gets_two_debaters():
    a, b = DE.select_debate_agents(_agents(1))
    assert a is not b
    assert DE._agent_id(a) != DE._agent_id(b)


# ── 구조 검증기 ──────────────────────────────────────────────────────────────
def test_validate_transcript_detects_missing_pieces():
    t = DE.DebateTranscript(topic="", strength="light")
    ok, issues = DE.validate_transcript(t)
    assert not ok
    assert "topic_missing" in issues
    assert "positions_missing" in issues
    assert "final_conclusion_missing" in issues


def test_references_opponent_rejects_unrelated_text():
    assert DE.references_opponent("모듈경계유지 비용이 낮다", "모듈경계유지 덕분에 비용이 낮다")
    assert not DE.references_opponent("전혀 무관한 주제의 문장", "모듈경계유지 덕분에 비용이 낮다")


def test_parse_json_object_tolerates_fences_and_prose():
    raw = '설명 텍스트\n```json\n{"decision":"x","conditions":["y"]}\n```'
    assert DE.parse_json_object(raw)["decision"] == "x"


# ── SSE 스트림 계약 ─────────────────────────────────────────────────────────
def _events(strength="light", n=2, message=None):
    req = _req(strength=strength, n=n) if message is None else _req(message=message, strength=strength, n=n)
    return list(H.run_debate_mode_stream(req, _agents(n), llm=FakeLLM()))


def test_stream_emits_turn_start_answers_and_all_complete():
    events = _events()
    names = [e["event"] for e in events]
    assert names[0] == "turn_start"
    assert names[-1] == "all_complete"
    assert names.count("all_complete") == 1
    answers = [e for e in events if e["event"] == "agent_answer"]
    # light: 입론2 + 반박2 + 예외2 + 합의 초안1 + 검토1 + 최종1 = 9
    assert len(answers) == 9
    types = [e["data"]["speechType"] for e in answers]
    assert types.count("CONSENSUS_DRAFT") == 1 and types.count("CONSENSUS_REVIEW") == 1
    assert all(e["data"]["answer"].strip() for e in answers)


def test_stream_marks_rebuttal_target_and_unique_stage_types():
    events = _events(strength="normal")
    answers = [e["data"] for e in events if e["event"] == "agent_answer"]
    rebuttals = [a for a in answers if a["speechType"] == "REBUTTAL"]
    assert rebuttals and all(a["targetAgentName"] for a in rebuttals)
    # 라운드마다 stageType 이 달라야 SSE dedup(fingerprint)에 걸리지 않는다.
    assert {a["stageType"] for a in rebuttals} == {"DEBATE_REBUTTAL_R1", "DEBATE_REBUTTAL_R2"}


def test_stream_all_complete_carries_debate_result_and_validation():
    events = _events()
    data = events[-1]["data"]
    assert data["mode"] == "debate"
    assert data["suppressAgentFill"] is True
    assert data["debateResult"]["decision"]
    assert data["debateValidation"]["passed"], data["debateValidation"]["issues"]
    assert len(data["debatePositions"]) == 2
    assert data["debateStrength"] == "light"
    assert data["rebuttalRounds"] == 1


def test_stream_with_three_selected_agents_uses_all_three():
    """선택된 3명이 모두 토론에 참여한다(앞의 2명만 쓰면 나머지가 화면에서 사라진다)."""
    events = _events(n=3)
    answers = [e["data"] for e in events if e["event"] == "agent_answer"]
    debaters = {a["agentId"] for a in answers if a["speechType"] != "FINAL_CONCLUSION"}
    assert debaters == {"a1", "a2", "a3"}
    openings = {a["agentId"] for a in answers if a["speechType"] == "OPENING"}
    rebuttals = {a["agentId"] for a in answers if a["speechType"] == "REBUTTAL"}
    assert openings == rebuttals == {"a1", "a2", "a3"}


def test_sync_handler_returns_answers_and_messages():
    result = H.run_debate_mode_sync(_req(strength="light"), _agents(), llm=FakeLLM())
    assert result["success"] is True
    assert result["mode"] == "debate"
    assert len(result["answers"]) == len(result["messages"]) == 9
    assert result["debateResult"]["recommendation"]
    assert result["question"]


def test_exception_step_excludes_opponent_exception_from_context():
    """상대의 '예외 정리'는 컨텍스트로 넘기지 않는다(그대로 베끼는 것 방지)."""
    llm = FakeLLM()
    t = DE.run_debate(_req(strength="light"), _agents(), llm=llm)
    exception_prompts = [c["user"] for c in llm.calls if '"acknowledgedFromOpponent"' in c["user"]]
    a_exception = next(s for s in t.speeches if s.slot == "A" and s.speech_type == "EXCEPTION")
    # B의 예외 프롬프트에 A의 예외 정리 본문이 들어가면 안 된다.
    assert all("예외 정리]" not in p for p in exception_prompts)
    assert all(a_exception.text[:50] not in p for p in exception_prompts)
    assert t.exceptions["A"].exceptions != t.exceptions["B"].exceptions


def test_exception_copied_from_opponent_is_regenerated():
    class Copycat(FakeLLM):
        def __init__(self):
            super().__init__()
            self.exception_attempts = 0

        def __call__(self, system, user, *, max_tokens, temperature):
            if '"acknowledgedFromOpponent"' in user:
                self.exception_attempts += 1
                if "[재작성 지시" not in user:
                    return json.dumps({
                        "acknowledgedFromOpponent": "동일한 문장",
                        "exceptions": ["완전히 동일한 예외 하나", "완전히 동일한 예외 둘"],
                        "flipConditions": ["동일한 조건"],
                        "revisedConclusion": "완전히 동일한 수정 결론이다.",
                    }, ensure_ascii=False)
            return super().__call__(system, user, max_tokens=max_tokens, temperature=temperature)

    llm = Copycat()
    DE.run_debate(_req(strength="light"), _agents(), llm=llm)
    # A는 1회, B는 복사 판정으로 재생성 → 총 3회 이상
    assert llm.exception_attempts >= 3


def test_is_copy_of_detects_duplicate_exception():
    a = DE.ExceptionNote(exceptions=["같은 예외 문장 하나"], revised_conclusion="같은 결론")
    b = DE.ExceptionNote(exceptions=["같은 예외 문장 하나"], revised_conclusion="같은 결론")
    assert DE._is_copy_of(a, b)
    c = DE.ExceptionNote(exceptions=["전혀 다른 예외 문장"], revised_conclusion="다른 결론이다")
    assert not DE._is_copy_of(a, c)


def test_transcript_payload_keeps_frontend_debate_stage_fields():
    """기존 프론트 토론 렌더러가 읽는 필드(stageTitle/side/content)를 유지한다."""
    t = DE.run_debate(_req(strength="light"), _agents(), llm=FakeLLM())
    payload = DE.transcript_payload(t)
    stages = payload["debateStages"]
    assert len(stages) == len(t.speeches)
    for st in stages:
        assert st["stageTitle"] and st["content"] and st["stageType"]
        assert st["side"] in ("PRO", "CON", "NEUTRAL")
        assert st["agentIndex"] in (0, 1, 2)
    assert stages[-1]["side"] == "NEUTRAL"          # 최종 결론 카드
    assert payload["debateResult"]["decision"]


def test_untargeted_claims_filters_already_rebutted():
    cands = ["모듈경계유지 때문에 초기 비용이 낮다", "완전히 다른 두 번째 주장이다"]
    assert DE.untargeted_claims(cands, ["모듈경계유지 때문에 초기 비용이 낮다"]) == ["완전히 다른 두 번째 주장이다"]
    assert len(DE.untargeted_claims(cands, [])) == 2


def test_later_rounds_receive_untargeted_claim_candidates():
    """2차 이후 반박 프롬프트에는 '아직 반박하지 않은 상대 주장' 후보가 실려야 한다."""
    llm = FakeLLM()
    DE.run_debate(_req(strength="deep"), _agents(), llm=llm)
    rebuttal_prompts = [c["user"] for c in llm.calls if '"targetClaim"' in c["user"]]
    later = [p for p in rebuttal_prompts if "이번은 2차 반박이다" in p or "이번은 3차 반박이다" in p]
    assert later
    assert all("아직 네가 반박하지 않은 상대 주장" in p for p in later)
    assert all("상대의 직전 발언" in p for p in later)


def test_reused_counter_argument_is_regenerated():
    """지목 대상만 바꾸고 반박 본문을 재사용하면 재생성한다."""
    class Recycler(FakeLLM):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def __call__(self, system, user, *, max_tokens, temperature):
            if '"targetClaim"' in user:
                self.attempts += 1
                if "[재작성 지시" not in user:
                    opp = user.split("실제로 한 발언 원문")[1]
                    term = A_TERM if A_TERM in opp else B_TERM
                    return json.dumps({
                        "targetClaim": f"{term} 관련 주장 {self.attempts}",
                        "acknowledgedPoint": "인정",
                        "counterArgument": f"{term} 는 조건이 바뀌면 비용이 역전된다는 완전히 동일한 본문.",
                        "evidenceOrReasoning": f"{term} 전제가 깨지는 경우가 흔하다는 동일한 근거.",
                    }, ensure_ascii=False)
            return super().__call__(system, user, max_tokens=max_tokens, temperature=temperature)

    llm = Recycler()
    DE.run_debate(_req(strength="normal"), _agents(), llm=llm)
    # 2라운드 × 2명 = 4건 중 2라운드는 본문 재사용으로 재생성이 걸린다.
    assert llm.attempts > 4


def test_resolve_strength_from_dict_config():
    """비스트림 경로(main.MultiChatRequest)는 debateConfig 를 dict 로 갖는다."""
    class _Req:
        debateStrength = None
        debateConfig = {"debateDepth": "deep"}
    assert DE.resolve_strength(_Req()) == "deep"


def test_persona_filler_is_stripped_from_debate_fields():
    """성격(친근한) 렌더러가 붙이는 격려 문구가 논거 본문에 남지 않는다."""
    raw = ("모놀리식은 트랜잭션 관리가 단순하다. 아주 좋은 질문이에요! 조금만 더 힘내봐요!")
    assert DE._s(raw) == "모놀리식은 트랜잭션 관리가 단순하다."


def test_acknowledged_point_made_of_filler_only_becomes_empty():
    """'인정할 부분'이 격려 문구뿐이면 인정 항목 자체를 비운다(상대 주장을 인정한 게 아니다)."""
    reb = DE.Rebuttal(target_claim="마이크로서비스가 더 낫다",
                      acknowledged_point=DE._s("아주 좋은 질문이에요!"),
                      counter_argument="운영 복잡도가 함께 증가한다",
                      evidence_or_reasoning="서비스 디스커버리와 분산 추적이 필요하다")
    pos = DE.DebatePosition(slot="A", label="모놀리식 지지", stance="모놀리식",
                            agent_id="1", agent_name="김교수")
    rendered = DE.render_rebuttal(reb, pos, "이교수")
    assert "인정할 부분" not in rendered
    assert "좋은 질문" not in rendered
