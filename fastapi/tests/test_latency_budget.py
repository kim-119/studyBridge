import time

from app.studymate import budget as B
from app.schemas.multi_chat_schema import MultiChatRequest
from app.studymate.basic_pipeline import run_basic_turn
from app.studymate.runtime_context import new_runtime
from tests.studymate_fakes import AGENTS3, FakeOllama, install


def test_stage_minimums_gate():
    b = B.TurnBudget(kind="basic_multi", total_s=10.0)
    assert b.allows("judge") and not b.allows("regenerate") and "regenerate" in b.skipped


def test_budget_exhausted_emits_turn_timeout_without_inference(monkeypatch):
    fake = install(monkeypatch, FakeOllama())
    req = MultiChatRequest(message="캐시", agents=AGENTS3, mode="basic")
    rt = new_runtime()
    rt.budget = B.TurnBudget(kind="basic_multi", total_s=5.0)
    ev = list(run_basic_turn(req, req.agents, current_message="캐시", social=False, rt=rt))
    errs = [e["data"] for e in ev if e["event"] == "agent_error"]
    assert len(errs) == 3 and all(e["code"] == "TURN_TIMEOUT" for e in errs)
    assert fake.count("render") == 0
    ac = ev[-1]["data"]
    assert ac["type"] == "all_complete" and ac["status"] == "FAILED" and ac["degraded"] is True


def test_default_budgets_are_configured():
    for k in ("basic_single", "basic_multi", "socratic", "simulation", "debate"):
        assert B.budget_seconds(k) > 0


def test_repair_skipped_when_soft_target_would_be_exceeded(monkeypatch):
    """soft 목표를 넘길 repair 는 시작하지 않고 PARTIAL + trace 사유로 남긴다(하드 예산은 충분해도)."""
    import time as _t
    from app.studymate.agent_executor import RenderSpec, execute
    from app.studymate.cancellation import CancelToken
    from app.studymate.profile_contract import canonicalize_agent
    from tests.studymate_fakes import FakeOllama, install
    monkeypatch.setenv("STUDYMATE_JUDGE", "off")
    miss = ("'캐시면 무조건 빨라진다'는 전제를 먼저 봐야 한다. 한계는 메모리 비용과 일관성 관리 부담이다. "
            "개선 방향은 실제 조회 패턴을 측정한 뒤 적용하는 것이다. 정의는 자주 쓰는 데이터를 앞단에 두는 저장소다.")

    def slow(req):
        _t.sleep(0.6)
        return miss
    fake = install(monkeypatch, FakeOllama(render=slow))
    a = canonicalize_agent({"agentId": 1, "name": "이교수", "personality": "critical", "knowledgeLevel": "bachelor"}, 0)
    spec = RenderSpec(agent=a, mode="basic", role="solo", question="캐시", turn_id="t", request_id="r", repair_allowance_s=1.0)
    out = execute(spec, cancel=CancelToken(), budget=B.TurnBudget.for_kind("basic_single"))
    assert fake.count("repair") == 0 and out.status == "SUCCESS" and out.quality_status == "PARTIAL"
    assert "repair_skipped_soft_budget" in out.trace.rubric["judgeNotes"]
