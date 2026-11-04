"""Phase B1 — 승인 판정의 requestId 바인딩·APPROVED 불변식·필수 검증기 필드(EC2 isDisplayable 과 동일)."""
import asyncio
import json

import pytest
from pydantic import ValidationError

from app.contracts.response_quality_v1 import (QualityInput, QualityOutput, SCHEMA_VERSION, is_displayable,
                                               parse_input_json, parse_output_json)
from app.quality_gate import evaluator as E
from app.quality_gate.stream_gate import gate_event_stream


def run(c):
    return asyncio.run(c)


def _out(**kw):
    base = dict(schemaVersion=SCHEMA_VERSION, requestId="req-bind-000001", taskType="GENERAL_EXPLANATION", success=True,
                verified=True, qualityStatus="APPROVED", score=90.0, minimumScore=80, hardFail=False,
                evaluatorVersion="t", mandatoryValidatorsPassed=True)
    base.update(kw)
    return QualityOutput(**base)


@pytest.mark.parametrize("score,ok", [(79, False), (79.99, False), (80, True), (100, True), (100.5, False)])
def test_score_band_approval(score, ok):
    if ok:
        assert is_displayable(_out(score=score), "req-bind-000001")
    else:
        with pytest.raises(ValidationError):           # APPROVED 인데 범위 밖 = 계약 위반(수신 거부)
            _out(score=score)
        assert not is_displayable(_out(qualityStatus="REJECTED", score=score), "req-bind-000001")


def test_hardfail_95_and_mandatory_false_and_hard_violation_never_approved():
    with pytest.raises(ValidationError):
        _out(score=95.0, hardFail=True)
    with pytest.raises(ValidationError):
        _out(mandatoryValidatorsPassed=False)
    with pytest.raises(ValidationError):
        _out(violations=[{"code": "PII_LEAK", "severity": "HARD", "reason": "r"}])
    assert not is_displayable(_out(qualityStatus="REJECTED", score=95.0, hardFail=True), "req-bind-000001")


def test_request_id_binding_and_schema_version():
    o = _out()
    assert is_displayable(o, "req-bind-000001")
    assert not is_displayable(o, "req-bind-000002") and not is_displayable(o, None) and not is_displayable(None, "x")
    with pytest.raises(ValidationError):
        _out(schemaVersion="response-quality.v2")
    with pytest.raises(ValueError):
        parse_output_json(json.dumps({k: v for k, v in o.model_dump(mode="json").items() if k != "schemaVersion"}))


def test_evaluator_output_carries_required_canonical_fields():
    E.clear_cache()
    inp = QualityInput.model_validate({"schemaVersion": SCHEMA_VERSION, "requestId": "req-bind-eval-01",
                                       "taskType": "GENERAL_EXPLANATION", "outputKind": "text",
                                       "originalRequest": "1+1?", "proposedOutput": ""})
    o = run(E.evaluate(inp))
    d = o.model_dump(mode="json")
    assert d["requestId"] == "req-bind-eval-01" and d["evaluatorVersion"] and d["minimumScore"] == 80
    assert d["schemaVersion"] == SCHEMA_VERSION and d["mandatoryValidatorsPassed"] is False and d["hardFail"] is True
    assert parse_output_json(json.dumps(d)).requestId == "req-bind-eval-01"   # 출력이 canonical 파서를 통과
    assert 0 <= d["latencyMs"] <= 2 ** 31 - 1


def test_evaluator_error_output_is_not_mandatory_passed():
    inp = QualityInput.model_validate({"schemaVersion": SCHEMA_VERSION, "requestId": "req-bind-eval-02",
                                       "taskType": "GENERAL_EXPLANATION", "outputKind": "text",
                                       "originalRequest": "q", "proposedOutput": "a"})
    o = E._error_output(inp, "EVALUATOR_ERROR", 0.0)      # started=0 → latency 상한 고정 확인
    assert o.mandatoryValidatorsPassed is False and o.qualityStatus.value == "VALIDATION_ERROR"
    assert o.latencyMs == 2 ** 31 - 1 and not is_displayable(o, "req-bind-eval-02")


def test_raw_parser_rejects_nan_duplicates_trailing_and_coercion():
    base = {"schemaVersion": SCHEMA_VERSION, "requestId": "req-bind-raw-01", "taskType": "GENERAL_EXPLANATION",
            "outputKind": "text", "originalRequest": "q", "proposedOutput": "a", "attemptIndex": 0}
    raw = json.dumps(base)
    assert parse_input_json(raw).requestId == "req-bind-raw-01"
    for bad in (raw.replace('"attemptIndex": 0', '"attemptIndex": "0"'), raw + "{}", raw.replace('"q"', '"q", "originalRequest": "q"'),
                raw.replace('"attemptIndex": 0', '"attemptIndex": NaN'), raw.replace("req-bind-raw-01", "req-bind-raw-01\\n")):
        with pytest.raises(ValueError):
            parse_input_json(bad)


def test_stream_gate_rejects_verdict_bound_to_another_request():
    async def src():
        yield {"event": "agent_answer", "data": {"agentId": "a", "content": "답변"}}
        yield {"event": "done", "data": {}}

    async def stale(key, text, msg, rid):          # 다른 요청의 승인 판정을 돌려주는 평가기(캐시 오용 등)
        return _out(requestId="req-other-0000001")

    async def fresh(key, text, msg, rid):
        return _out(requestId=rid)

    async def collect(ev):
        return [e async for e in gate_event_stream(src(), ev, request_id="turn-xyz-0001")]
    bad = run(collect(stale))
    assert [e["event"] for e in bad] == ["quality_rejected", "done"] and "답변" not in json.dumps(bad, ensure_ascii=False)
    good = run(collect(fresh))
    assert good[0]["event"] == "agent_answer" and good[0]["data"]["content"] == "답변"
