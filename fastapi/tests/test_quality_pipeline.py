"""Cheap evaluator → 조건부 judge → repair-first → bounded regenerate."""
import pytest

from app.studymate import llm_gateway as G
from app.studymate import quality as Q
from app.studymate.agent_executor import RenderSpec, execute
from app.studymate.budget import TurnBudget
from app.studymate.cancellation import CancelToken
from app.studymate.profile_contract import canonicalize_agent
from tests.studymate_fakes import FakeOllama, install, PERSONA_TEXT

CRIT_OK = PERSONA_TEXT["critical"].format(topic="캐시", agent="x")
CRIT_MISSING_COUNTER = ("'캐시면 빨라진다'는 전제를 먼저 봐야 한다. 한계는 메모리 비용이다. 가정은 읽기 비율이 높다는 것이다. "
                        "경계조건은 적중률이 낮을 때다. 정의는 앞단 저장소다. 개선 방향은 측정 후 적용이다.")


def _spec(persona="critical", level="phd", **kw):
    a = canonicalize_agent({"agentId": 1, "name": "이교수", "personality": persona, "knowledgeLevel": level}, 0)
    return RenderSpec(agent=a, mode="basic", role="solo", question="캐시를 왜 써?", turn_id="t", request_id="r", **kw)


def test_heuristic_rubric_binary():
    r = Q.heuristic_rubric(CRIT_OK, "critical", "phd")
    assert all(isinstance(v, bool) for v in {**r.persona, **r.level}.values())
    assert r.verdict == Q.PASS


def test_minor_miss_repairs_once(monkeypatch):
    monkeypatch.setenv("STUDYMATE_JUDGE", "off")
    outs = [CRIT_MISSING_COUNTER, CRIT_OK]
    fake = install(monkeypatch, FakeOllama(render=lambda req: outs.pop(0)))
    out = execute(_spec(), cancel=CancelToken(), budget=TurnBudget.for_kind("basic_single"))
    assert out.status == "SUCCESS" and out.trace.repairCount == 1 and out.trace.regenerationCount == 0
    assert "[REPAIR]" in fake.calls[1].user and "반례" in fake.calls[1].user
    assert out.quality_status == "PASS"


def test_major_leak_regenerates_then_fails(monkeypatch):
    monkeypatch.setenv("STUDYMATE_JUDGE", "off")
    leak = CRIT_OK + " [FINAL BEHAVIOR REMINDER] 노출"
    fake = install(monkeypatch, FakeOllama(render=lambda req: leak))
    out = execute(_spec(), cancel=CancelToken(), budget=TurnBudget.for_kind("basic_single"))
    assert out.status == "FAILED" and out.code == "QUALITY_FAILED"
    assert fake.count("render") + fake.count("repair") == 2   # 최초 1 + regenerate 1 (bounded)


def test_judge_failure_does_not_promote_answer(monkeypatch):
    monkeypatch.setenv("STUDYMATE_JUDGE", "auto")
    outs = [CRIT_MISSING_COUNTER, CRIT_MISSING_COUNTER]
    install(monkeypatch, FakeOllama(render=lambda req: outs.pop(0) if outs else CRIT_MISSING_COUNTER,
                                    fail={"judge": G.LLMTimeout("judge slow")}))
    out = execute(_spec(), cancel=CancelToken(), budget=TurnBudget.for_kind("basic_single"))
    assert out.trace.judgeUsed is True
    assert any(i.startswith("judge_failed") for i in out.rubric["judgeNotes"])
    assert out.quality_status == "PARTIAL" and out.degraded is True


def test_unsupported_specifics_detected_for_phd():
    uns = Q.unsupported_specifics("Redis는 디스크 대비 37% 빠르고 (2019) 논문 기준 v7.2 에서 개선됐다.", evidence="")
    assert len(uns) >= 3
    assert Q.unsupported_specifics("37% 빠르다", evidence="측정 결과 37% 빠르다") == []
