"""
C Native Engine (secret_sauce_engine) 안전 이식 스모크 테스트.

검증 목표:
  - native_scheduler / native_textprep / native_engine_routes import 가능.
  - import 시점에 .so 를 로딩하지 않는다(lazy) → FastAPI 기동을 막지 않는다.
  - health/optimize/textprep public 계약(스키마/키) 유지.
  - .so 부재/로드 실패 시에도 예외 없이 python-fallback 으로 동작(startup 안전).
  - 라우터가 /api/native-engine/* 3개 경로를 노출하고 200 으로 응답.

운영 코드(.so, secret_sauce_engine, main.py)는 건드리지 않고 계약만 확인한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── import / lazy 보장 ────────────────────────────────────────────────
def test_modules_import_without_loading_so():
    """import 만으로 .so 가 로딩되면 안 된다(lazy). import 자체가 예외 없이 성공."""
    import app.services.native_scheduler as ns
    import app.services.native_textprep as nt
    import app.api.native_engine_routes as nr

    # 싱글턴이 아직 생성되지 않았거나, 생성됐어도 로딩을 시도하지 않은 상태여야 한다.
    assert ns._SERVICE is None or ns._SERVICE._load_tried is False
    assert nt._SERVICE is None or nt._SERVICE._load_tried is False
    assert nr.router.prefix == "/api/native-engine"


# ── health 계약 ───────────────────────────────────────────────────────
def test_scheduler_health_contract():
    from app.services.native_scheduler import scheduler_health

    h = scheduler_health()
    assert set(h) >= {"available", "engine", "libraryPath"}
    assert h["engine"] in {"c-native", "python-fallback"}
    # 절대경로 노출 금지(상대경로만).
    assert not Path(h["libraryPath"]).is_absolute()


def test_textprep_health_contract():
    from app.services.native_textprep import textprep_health

    h = textprep_health()
    assert set(h) >= {"available", "engine", "libraryPath"}
    assert h["engine"] in {"c-native", "python-fallback"}
    assert not Path(h["libraryPath"]).is_absolute()


# ── optimize_schedule 계약 ────────────────────────────────────────────
def test_optimize_schedule_contract():
    from app.services.native_scheduler import optimize_schedule

    res = optimize_schedule({
        "daily_minutes": 180,
        "days": 3,
        "subjects": [
            {"name": "수학", "topics": ["미적분"], "priority": 5, "weakness": 4, "exam_weight": 5},
            {"name": "영어", "topics": ["문법"], "priority": 3, "weakness": 2, "exam_weight": 3},
        ],
    })
    assert res["engine"] in {"c-native", "python-fallback"}
    assert len(res["days"]) == 3
    assert res["total_minutes"] > 0
    for day in res["days"]:
        assert day["totalMinutes"] == sum(t["minutes"] for t in day["tasks"])


# ── textprep 계약 ─────────────────────────────────────────────────────
def test_preprocess_and_chunk_contract():
    from app.services.native_textprep import preprocess_and_chunk

    res = preprocess_and_chunk("페이지 1\n\n  실제   내용입니다.  반복   공백.\n12\n끝.", 200, 40)
    assert res["engine"] in {"c-native", "python-fallback"}
    assert isinstance(res.get("chunks"), list)


# ── .so 부재 시 fallback (startup/runtime 안전성 핵심) ─────────────────
def test_scheduler_fallback_when_so_missing(monkeypatch):
    """`.so` 가 없거나 깨져도 예외 없이 python-fallback 으로 동작해야 한다."""
    import app.services.native_scheduler as ns

    monkeypatch.setattr(ns, "_LIB_PATH", Path("/nonexistent/libscheduler.so"))
    svc = ns.NativeSchedulerService()  # 모듈 싱글턴과 분리된 새 인스턴스
    h = svc.health()
    assert h["available"] is False
    assert h["engine"] == "python-fallback"

    res = svc.optimize_schedule({
        "daily_minutes": 120, "days": 2,
        "subjects": [{"name": "x", "topics": ["t"], "priority": 3, "weakness": 3, "exam_weight": 3}],
    })
    assert res["engine"] == "python-fallback"
    assert res["fallback"] is True
    assert res["total_minutes"] > 0


def test_textprep_fallback_when_so_missing(monkeypatch):
    import app.services.native_textprep as nt

    monkeypatch.setattr(nt, "_LIB_PATH", Path("/nonexistent/libtextprep.so"))
    svc = nt.NativeTextPrepService()
    h = svc.health()
    assert h["available"] is False
    assert h["engine"] == "python-fallback"

    res = svc.preprocess_and_chunk("hello   world\n\n실제 내용.", 200, 20)
    assert res["engine"] == "python-fallback"
    assert isinstance(res.get("chunks"), list)


# ── 라우터 endpoint 계약 (full app 미로딩, 최소 mount) ─────────────────
@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.api.native_engine_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_router_exposes_three_paths(client):
    from app.api.native_engine_routes import router

    paths = {r.path for r in router.routes}
    assert paths == {
        "/api/native-engine/health",
        "/api/native-engine/schedule",
        "/api/native-engine/textprep",
    }


def test_endpoint_health_200(client):
    r = client.get("/api/native-engine/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["scheduler"]["engine"] in {"c-native", "python-fallback"}
    assert body["textprep"]["engine"] in {"c-native", "python-fallback"}


def test_endpoint_schedule_200(client):
    r = client.post("/api/native-engine/schedule", json={
        "daily_minutes": 180, "days": 2,
        "subjects": [{"name": "수학", "topics": ["미적분"], "priority": 5, "weakness": 4, "exam_weight": 5}],
    })
    assert r.status_code == 200
    assert len(r.json()["days"]) == 2


def test_endpoint_schedule_validation_422(client):
    # daily_minutes < 30 → pydantic 검증 실패(500 아님).
    r = client.post("/api/native-engine/schedule", json={
        "daily_minutes": 10, "days": 2,
        "subjects": [{"name": "x", "priority": 3, "weakness": 3, "exam_weight": 3}],
    })
    assert r.status_code == 422


def test_endpoint_textprep_200(client):
    r = client.post("/api/native-engine/textprep", json={"text": "hello world 내용.", "chunk_size": 200, "overlap": 20})
    assert r.status_code == 200
    assert isinstance(r.json().get("chunks"), list)
