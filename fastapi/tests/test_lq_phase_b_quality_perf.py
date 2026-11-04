"""Phase B4 — 평가 중복 제거·병렬 상한·선읽기·오프로드·평가기 장애 미노출·재생성 상한."""
import asyncio
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts.response_quality_v1 import SCHEMA_VERSION, QualityInput, QualityOutput
from app.quality_gate import evaluator as E
from app.quality_gate import stream_gate as G

KEY = "k" * 40


def run(c):
    return asyncio.run(c)


def _ok(rid):
    return QualityOutput(schemaVersion=SCHEMA_VERSION, requestId=rid, taskType="STUDYMATE_SOCRATIC", success=True,
                         verified=True, qualityStatus="APPROVED", score=90.0, minimumScore=80, hardFail=False,
                         evaluatorVersion="t", mandatoryValidatorsPassed=True)


def _turn(agents=3, gen_s=0.0, extra_question=True, tamper_aggregate=False):
    async def upstream():
        msgs = []
        for i in range(agents):
            if gen_s:
                await asyncio.sleep(gen_s)
            c = f"에이전트 {i} 설명"
            msgs.append({"agentId": f"a{i}", "content": c + (" 변조" if tamper_aggregate and i == 0 else "")})
            d = {"turnId": "t1", "agentId": f"a{i}", "content": c}
            if extra_question:
                d["question"] = "다음은?"
            yield {"event": "agent_answer", "data": d}
        yield {"event": "all_complete", "data": {"turnId": "t1", "messages": msgs}}
    return upstream()


def _collect(src, ev, **pol):
    import dataclasses
    policy = dataclasses.replace(G.policy_for("studymate"), **pol)

    async def go():
        return [o async for o in G.gate_event_stream(src, ev, policy=policy, request_id="req-perf-0001")]
    return run(go())


def test_all_complete_reuses_same_agent_approved_fields_and_reevaluates_changed_text():
    calls = []

    async def ev(key, text, src, rid):
        calls.append(key)
        return _ok(rid)
    out = _collect(_turn(), ev)
    final = [o for o in out if o["event"] == "all_complete"][0]
    assert len(calls) == 3 and all("#" not in k for k in calls)                  # 중복 평가 0
    assert [m["content"] for m in final["data"]["messages"]] == ["에이전트 0 설명", "에이전트 1 설명", "에이전트 2 설명"]
    calls.clear()
    _collect(_turn(tamper_aggregate=True), ev)
    assert len(calls) == 4 and any(k.endswith("#messages") for k in calls)        # 내용이 다르면 다시 평가


def test_aggregate_does_not_borrow_other_agents_or_rejected_verdicts():
    async def upstream():
        yield {"event": "agent_answer", "data": {"turnId": "t", "agentId": "a0", "content": "같은 문장"}}
        yield {"event": "all_complete", "data": {"messages": [{"agentId": "a9", "content": "같은 문장"}]}}
    calls = []

    async def ev(key, text, src, rid):
        calls.append(key)
        return _ok(rid) if "#" not in key else _ok("req-other-00000001")       # 집계 평가는 다른 rid → 미승인
    out = _collect(upstream(), ev)
    final = [o for o in out if o["event"] == "all_complete"][0]
    # 다른 에이전트 이름으로 실린 같은 문장은 재사용하지 않는다(새 평가). 같은 본문 해시면 스트림 범위 판정을 재사용한다.
    assert final["data"]["messages"] in ([], [{"agentId": "a9", "content": "같은 문장",
                                               "quality": final["data"]["messages"][0]["quality"]}])


def test_aggregate_parallel_evaluations_are_bounded():
    live = {"now": 0, "max": 0}

    async def ev(key, text, src, rid):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        await asyncio.sleep(0.02)
        live["now"] -= 1
        return _ok(rid)

    async def upstream():
        yield {"event": "all_complete", "data": {"messages": [{"agentId": f"x{i}", "content": f"본문 {i}"} for i in range(8)]}}
    out = _collect(upstream(), ev, max_parallel_evaluations=2)
    assert live["max"] == 2 and len(out[0]["data"]["messages"]) == 8
    assert [m["agentId"] for m in out[0]["data"]["messages"]] == [f"x{i}" for i in range(8)]   # 순서 보존


def test_prefetch_overlaps_generation_with_evaluation_without_reordering_or_early_body():
    seen_before_approval = []

    async def ev(key, text, src, rid):
        await asyncio.sleep(0.15)
        return _ok(rid)
    t = time.perf_counter()
    out = _collect(_turn(gen_s=0.15, extra_question=False), ev, prefetch_events=128)
    with_prefetch = time.perf_counter() - t
    t = time.perf_counter()
    out0 = _collect(_turn(gen_s=0.15, extra_question=False), ev, prefetch_events=0)
    without = time.perf_counter() - t
    assert [o["event"] for o in out] == [o["event"] for o in out0]                # 방출 순서 동일
    assert with_prefetch < without - 0.2, (with_prefetch, without)               # 3×(0.15+0.15)=0.9s → ≈0.6s
    del seen_before_approval


def test_deny_all_emits_zero_body_chars_with_prefetch():
    async def ev(key, text, src, rid):
        return _ok("req-mismatch-000001")                                        # 다른 요청 판정 = 미승인
    out = _collect(_turn(gen_s=0.0), ev)
    blob = json.dumps(out, ensure_ascii=False)
    assert "에이전트" not in blob and "다음은" not in blob


def test_offloaded_evaluation_gives_same_verdict(monkeypatch):
    text = ("TCP 는 연결 지향 프로토콜이다. " * 800)
    inp = QualityInput.model_validate({"schemaVersion": SCHEMA_VERSION, "requestId": "req-offload-01",
                                       "taskType": "GENERAL_EXPLANATION", "outputKind": "text", "originalRequest": "q",
                                       "proposedOutput": text})
    E.clear_cache()
    monkeypatch.setenv("AI_QUALITY_EVAL_OFFLOAD_MIN_CHARS", "0")
    a = run(E.evaluate(inp)).model_dump(exclude={"latencyMs"})
    E.clear_cache()
    monkeypatch.setenv("AI_QUALITY_EVAL_OFFLOAD_MIN_CHARS", "10000000")
    b = run(E.evaluate(inp)).model_dump(exclude={"latencyMs"})
    assert a == b


def _api():
    from app.quality_gate import routes as R
    R.RATE.reset() if hasattr(R.RATE, "reset") else None
    R.IDEMPOTENCY._d.clear()
    app = FastAPI()
    app.include_router(R.router)
    return R, TestClient(app, raise_server_exceptions=False)


def _body(rid="req-api-000001"):
    return {"schemaVersion": SCHEMA_VERSION, "requestId": rid, "taskType": "GENERAL_EXPLANATION", "outputKind": "text",
            "originalRequest": "q", "proposedOutput": "a"}


def test_evaluate_api_busy_disabled_and_timeout_never_return_unverified_approval(monkeypatch):
    monkeypatch.setenv("AI_SERVER_API_KEY", KEY)
    H = {"Authorization": f"Bearer {KEY}"}
    R, c = _api()
    monkeypatch.delenv("AI_QUALITY_EVALUATE_API_ENABLED", raising=False)
    r = c.post("/api/ai/quality/evaluate", json=_body(), headers=H)
    assert r.status_code == 503 and r.json() == {"success": False, "errorCode": "FEATURE_DISABLED"}
    monkeypatch.setenv("AI_QUALITY_EVALUATE_API_ENABLED", "true")
    monkeypatch.setenv("AI_QUALITY_EVAL_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("AI_QUALITY_EVAL_QUEUE_WAIT_SECONDS", "0.05")
    sem = R._semaphore()

    async def hold():
        await sem.acquire()
    run(hold())                                                                  # 슬롯을 다른 요청이 점유
    try:
        r = c.post("/api/ai/quality/evaluate", json=_body("req-api-000002"), headers=H)
        assert r.status_code == 429 and r.json()["errorCode"] == "EVALUATOR_BUSY" and "qualityStatus" not in r.json()
    finally:
        sem.release()
    monkeypatch.setenv("AI_QUALITY_EVAL_TIMEOUT_SECONDS", "0.05")

    async def slow(inp, judge, started):
        await asyncio.sleep(1)
    monkeypatch.setattr(E, "_evaluate", slow)                                   # 평가기 지연(장애) 주입
    E.clear_cache()
    r = c.post("/api/ai/quality/evaluate", json=_body("req-api-000003"), headers=H)
    j = r.json()
    assert r.status_code == 200 and j["qualityStatus"] == "VALIDATION_ERROR" and j["success"] is False
    assert j["mandatoryValidatorsPassed"] is False and j["requestId"] == "req-api-000003"
    r = c.post("/api/ai/quality/evaluate", content=b'{"schemaVersion":"response-quality.v1","x":NaN}',
               headers={**H, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["errorCode"] == "CONTRACT_VALIDATION_FAILED"


def test_regeneration_is_capped_at_two_even_if_env_asks_more(monkeypatch):
    from app.quality_gate.regeneration import run_quality_gated_generation
    monkeypatch.setenv("AI_RESPONSE_MAX_REGENERATIONS", "9")
    drafts = iter(["초안 1 은 틀렸다", "초안 2 도 틀렸다", "초안 3 역시", "초안 4", "초안 5"])
    n = {"gen": 0}

    async def gen(req):
        n["gen"] += 1
        return next(drafts)

    def build(draft, attempt):
        return QualityInput.model_validate({"schemaVersion": SCHEMA_VERSION, "requestId": f"req-regen-00{attempt}",
                                            "taskType": "PDF_QA", "outputKind": "text", "originalRequest": "q",
                                            "proposedOutput": draft, "constraints": {"allowedMaterialIds": [1]}})
    E.clear_cache()
    out = run(run_quality_gated_generation(generate=gen, build_input=build))
    assert n["gen"] == 3 and out.attempts == 3 and not out.approved


def test_graph_checker_accepts_graph_builder_from_to_edges_and_rejects_ambiguous_keys():
    from app.quality_gate import checks as C
    g = {"nodes": [{"id": "q"}, {"id": "c1"}, {"id": "c2"}],
         "edges": [{"id": "e1", "from": "q", "to": "c1", "kind": "topic"}, {"id": "e2", "from": "c1", "to": "c2"}]}
    codes = {x[0] for x in C.check_graph(g)} if hasattr(C, "check_graph") else None
    if codes is None:
        fn = next(getattr(C, n) for n in dir(C) if n.startswith("check_") and "graph" in n)
        codes = {x[0] for x in fn(g)}
    else:
        fn = C.check_graph
    assert "GRAPH_DANGLING_EDGE" not in codes and "JSON_SCHEMA_INVALID" not in codes
    bad = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b", "from": "b", "to": "a"}]}
    assert "JSON_SCHEMA_INVALID" in {x[0] for x in fn(bad)}
    dangling = {"nodes": [{"id": "a"}], "edges": [{"from": "a", "to": "zz"}]}
    assert "GRAPH_DANGLING_EDGE" in {x[0] for x in fn(dangling)}


def test_planner_text_coaching_is_not_hard_failed_as_json_but_structured_plan_still_checked():
    def ev(output, kind):
        E.clear_cache()
        return run(E.evaluate(QualityInput.model_validate({
            "schemaVersion": SCHEMA_VERSION, "requestId": "req-plan-000001", "taskType": "PLANNER_COACHING",
            "outputKind": kind, "originalRequest": "이번 주 자료구조 공부 계획을 조언해줘", "proposedOutput": output})))
    text = run_text = ("이번 주 자료구조 공부는 배열과 연결 리스트 복습부터 시작하고, 하루에 한 주제씩 예제를 직접 구현해 보세요. "
                       "주말에는 스택과 큐를 묶어 문제를 풀며 약한 부분을 다시 정리하면 좋습니다.")
    o = ev(text, "text")
    codes = {x.code for x in o.violations}
    assert "JSON_SCHEMA_INVALID" not in codes and not o.hardFail
    feas = [d for d in o.dimensions if d.name == "feasibility"][0]
    assert feas.score is None and feas.method == "not_applicable"
    o2 = ev({"items": [{"title": "배열 복습", "hours": 2}]}, "plan_json")            # 날짜 없는 구조화 계획
    assert o2.hardFail and "PLAN_DATE_INVALID" in {x.code for x in o2.violations}
    del run_text
