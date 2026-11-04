"""Phase D R1·R5-2 — 비전 판독 관측 근거(vision-observation.v1) 반환과 평가기의 근거·불확실성 검증.

라우터는 mock VLM·mock 답변만 쓴다(GPU·OpenAI 미사용). 평가기 검증은 관측 → response-quality.v1 근거 변환 후 실제 평가.
"""
from __future__ import annotations

import asyncio
import base64
import io
import uuid

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image, ImageDraw

import app.vision.answer as answer_mod
import app.vision.router as vision_router
from app.contracts.response_quality_v1 import QualityInput, is_displayable
from app.quality_gate.evaluator import clear_cache, evaluate
from app.vision.gate import VisionGate
from app.vision.observations import (SCHEMA_VERSION, build_observations, observation_payload, referenced_ids,
                                     to_quality_evidence)
from app.vision.redaction import mask_obj

KEY = "test-internal-key"
AUTH = {"Authorization": f"Bearer {KEY}"}

MASKED = {"screenType": "code", "legible": True,
          "readableText": "def add(a, b):\n    return a - b\nTypeError: unsupported operand",
          "code": [{"language": "python", "content": "def add(a, b):\n    return a - b"}],
          "errors": ["TypeError: unsupported operand type(s)"], "math": [], "charts": [], "visualElements": ["실행 버튼"],
          "questionEvidence": [], "uncertain": ["3번째 줄 변수명 total_sum 으로 보임"], "embeddedInstructions": []}


# ── 관측 목록 ───────────────────────────────────────────────────────────────────
def test_observations_are_masked_ordered_and_classified():
    raw = dict(MASKED, readableText="연락처 test.user@example.com\napi_key=sk-proj-ABCDEFGHIJKLMNOPQRSTUV")
    masked, n = mask_obj(raw)
    obs = build_observations(masked)
    text = " ".join(o["text"] for o in obs)
    assert n >= 2 and "test.user@example.com" not in text and "sk-proj-" not in text
    assert [o["observationId"] for o in obs] == [f"obs-{i}" for i in range(1, len(obs) + 1)]
    assert {o["kind"] for o in obs} >= {"TEXT", "CODE", "ERROR", "VISUAL", "UNCERTAIN"}
    assert [o["confidence"] for o in obs if o["kind"] == "UNCERTAIN"] == ["UNCERTAIN"]
    assert all("bbox" not in o for o in obs)               # VLM 이 좌표를 내지 않는다 — 추측하지 않는다


def test_illegible_screen_marks_everything_uncertain_and_caps_size():
    obs = build_observations(dict(MASKED, legible=False, readableText="\n".join(f"줄 {i} " + "가" * 390 for i in range(60))))
    assert obs and all(o["confidence"] == "UNCERTAIN" for o in obs)
    assert len(obs) <= 24 and sum(len(o["text"]) for o in obs) <= 6000


def test_referenced_ids_are_deterministic():
    obs = build_observations(MASKED)
    ans = "화면의 return a - b 때문에 덧셈이 아니라 뺄셈이 됩니다 [근거:obs-5] [근거:obs-99]"
    ids = referenced_ids(ans, obs)
    assert "obs-5" in ids and "obs-99" not in ids and ids == referenced_ids(ans, obs)


# ── 라우터: 기본 꺼짐 / 켜면 관측 반환 ──────────────────────────────────────────────────
@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("VISION_API_ENABLED", "true")
    monkeypatch.setenv("VISION_BACKEND", "mock")
    monkeypatch.setenv("VISION_MOCK_DELAY_SECONDS", "0.01")
    monkeypatch.setenv("AI_SERVER_API_KEY", KEY)
    monkeypatch.setenv("VISION_ANSWER_PROVIDER", "mock")
    monkeypatch.setenv("VISION_ANSWER_MOCK_DELAY_SECONDS", "0.01")
    monkeypatch.delenv("VISION_RETURN_OBSERVATIONS", raising=False)
    monkeypatch.setattr(vision_router, "gate", VisionGate())
    monkeypatch.setattr(answer_mod, "budget", answer_mod._DailyBudget())
    clear_cache()


def _jpeg():
    img = Image.new("RGB", (640, 360), "white")
    ImageDraw.Draw(img).text((10, 10), "Traceback: ZeroDivisionError", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _body(question="이 화면의 오류 원인은?"):
    return {"requestId": str(uuid.uuid4()), "groupId": 123, "streamId": "con_abc123", "sharerUserId": 10, "askerUserId": 20,
            "question": question, "image": _jpeg(), "mime": "image/jpeg"}


async def _post(b):
    app = FastAPI()
    app.include_router(vision_router.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.post("/api/ai/vision/analyze", json=b, headers=AUTH)


@pytest.mark.anyio
async def test_default_response_has_no_observations():
    r = await _post(_body())
    assert r.status_code == 200 and "observations" not in r.json() and "answerObservationIds" not in r.json()


@pytest.mark.anyio
async def test_flag_on_returns_masked_observations_and_answer_refs(monkeypatch):
    monkeypatch.setenv("VISION_RETURN_OBSERVATIONS", "true")
    r = await _post(_body())
    j = r.json()
    assert r.status_code == 200 and j["observationSchemaVersion"] == SCHEMA_VERSION
    assert j["observations"] and "test.user@example.com" not in str(j["observations"])   # mock 판독의 이메일은 마스킹
    ids = {o["observationId"] for o in j["observations"]}
    assert set(j["answerObservationIds"]) <= ids and j["answerObservationIds"]            # mock 답변은 판독 본문을 인용
    assert j["uncertainObservationIds"] == [] and j["legible"] is True
    # 같은 응답으로 Spring 이 평가기 근거를 만들면 승인 판단이 가능하다(근거 부재 HARD 가 사라짐)
    ev = to_quality_evidence(j["observations"])
    o = await evaluate(QualityInput.model_validate({
        "schemaVersion": "response-quality.v1", "requestId": "vision-e2e-0001", "taskType": "VISION_CAPTION",
        "outputKind": "vision_text", "originalRequest": "이 화면의 오류 원인은?", "proposedOutput": j["answer"],
        "groundingEvidence": ev, "constraints": {}}))
    assert "VISION_NO_OBSERVATION_EVIDENCE" not in {v.code for v in o.violations}


@pytest.mark.anyio
async def test_unreadable_screen_observations_are_uncertain(monkeypatch):
    monkeypatch.setenv("VISION_RETURN_OBSERVATIONS", "true")
    r = await _post(_body("__MOCK_UNREADABLE__ 뭐가 보여?"))
    j = r.json()
    assert j["legible"] is False and all(o["confidence"] == "UNCERTAIN" for o in j["observations"])


# ── 평가기: 근거·불확실성 ─────────────────────────────────────────────────────────────
def _eval(answer, evidence, rid="vision-req-0001"):
    clear_cache()
    return asyncio.run(evaluate(QualityInput.model_validate({
        "schemaVersion": "response-quality.v1", "requestId": rid, "taskType": "VISION_CAPTION", "outputKind": "vision_text",
        "originalRequest": "이 코드 왜 틀려?", "proposedOutput": answer, "groundingEvidence": evidence, "constraints": {}})))


EV = to_quality_evidence(build_observations(MASKED))


def test_hedged_uncertain_reading_is_approved():
    o = _eval("화면의 코드에서 return a - b 로 되어 있어 덧셈 함수가 뺄셈을 합니다. "
              "3번째 줄 변수명은 흐릿해서 total_sum 인지 확실하지 않습니다.", EV)
    assert o.qualityStatus.value == "APPROVED" and is_displayable(o, "vision-req-0001")


def test_asserting_uncertain_reading_as_fact_is_rejected():
    o = _eval("화면의 코드에서 return a - b 로 되어 있어 덧셈 함수가 뺄셈을 합니다. 3번째 줄 변수명은 total_sum 입니다.", EV)
    codes = {v.code for v in o.violations}
    assert o.qualityStatus.value == "REJECTED" and "VISION_UNCERTAIN_ASSERTED" in codes and o.score < 80
    unc = next(d for d in o.dimensions if d.name == "uncertainty_honesty")
    assert unc.score == 0.0


def test_uncertain_reading_confirmed_by_certain_observation_may_be_stated():
    ev = EV + [{"evidenceId": "obs-90", "sourceType": "VISION_OBSERVATION", "text": "변수명 total_sum 으로 보임"}]
    o = _eval("화면의 코드에서 return a - b 로 되어 있어 뺄셈을 합니다. 3번째 줄 변수명 total_sum 입니다.", ev)
    assert "VISION_UNCERTAIN_ASSERTED" not in {v.code for v in o.violations}


def test_fully_legible_screen_does_not_require_hedging():
    ev = [e for e in EV if not e["sourceType"].endswith("_UNCERTAIN")]
    o = _eval("화면의 코드에서 return a - b 로 되어 있어 덧셈 함수가 뺄셈을 합니다.", ev)
    unc = next(d for d in o.dimensions if d.name == "uncertainty_honesty")
    assert o.qualityStatus.value == "APPROVED" and unc.score == 20.0


def test_unknown_observation_citation_and_unsupported_quote_are_hard():
    o = _eval("화면에 [근거:obs-77] \"Segmentation fault\" 가 표시됩니다.", EV)
    codes = {v.code for v in o.violations}
    assert o.hardFail and {"UNVERIFIED_CITATION", "VISION_UNSUPPORTED_OBSERVATION"} <= codes


def test_no_observation_evidence_keeps_existing_hard_rule():
    o = _eval("화면에 보이는 코드는 덧셈 함수입니다.", [])
    assert o.hardFail and "VISION_NO_OBSERVATION_EVIDENCE" in {v.code for v in o.violations}


def test_payload_round_trip_keeps_ids_consistent():
    p = observation_payload(MASKED, "return a - b 때문에 뺄셈")
    ids = [o["observationId"] for o in p["observations"]]
    assert set(p["answerObservationIds"]) <= set(ids) and set(p["uncertainObservationIds"]) <= set(ids)
    assert [e["evidenceId"] for e in to_quality_evidence(p["observations"])] == ids
