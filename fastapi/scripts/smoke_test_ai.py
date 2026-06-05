#!/usr/bin/env python3
"""
AI 기능 스모크 테스트 (FastAPI 단독).

실행 전 FastAPI 서버가 localhost:8000 에서 실행 중이어야 한다.

실행 방법:
  cd fastapi
  python scripts/smoke_test_ai.py

환경변수 FASTAPI_URL 로 서버 주소 변경 가능:
  FASTAPI_URL=http://ai.example.com python scripts/smoke_test_ai.py
"""
import json
import os
import sys
import urllib.request
import urllib.error

BASE_URL = os.environ.get("FASTAPI_URL", "http://localhost:8000")
API_KEY = os.environ.get("AI_SERVER_API_KEY", "")

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
SKIP = "\033[93m[SKIP]\033[0m"


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _post(path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path, data=data, headers=_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()}
    except Exception as e:
        return 0, {"error": str(e)}


def _get(path: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE_URL + path, headers=_headers(), method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()}
    except Exception as e:
        return 0, {"error": str(e)}


def test_health():
    """GET /api/health"""
    status, body = _get("/api/health")
    ok = status == 200 and body.get("status") == "ok"
    print(f"  {'✓' if ok else '✗'} GET /api/health  →  status={status}, body.status={body.get('status')}")
    return ok


def test_ai_health():
    """GET /api/ai/health — 상세 연결 검증"""
    status, body = _get("/api/ai/health")
    ok = status == 200 and "checks" in body
    print(f"  {'✓' if ok else '✗'} GET /api/ai/health  →  status={status}, overall={body.get('status')}")
    if ok:
        for k, v in body.get("checks", {}).items():
            print(f"      {k}: {v}")
    return ok


def test_training_status():
    """GET /api/ai/training/status"""
    status, body = _get("/api/ai/training/status")
    ok = status == 200 and "current_status" in body
    current = body.get("current_status", "unknown")
    # 절대 "trained"(완료)라고 과장되면 안 됨 — 실제로 학습을 하지 않은 경우
    print(f"  {'✓' if ok else '✗'} GET /api/ai/training/status  →  status={status}, current={current}")
    return ok


def test_study_time_prediction():
    """POST /api/ai/predict/study-time"""
    status, body = _post("/api/ai/predict/study-time", {
        "userId": 1,
        "weeklyStudySeconds": [3600, 4200, 3000, 5400, 2700, 3900, 4500],
    })
    ok = (
        status == 200
        and "predictedStudySeconds" in body
        and "method" in body
        and "confidence" in body
    )
    print(
        f"  {'✓' if ok else '✗'} POST /api/ai/predict/study-time  →"
        f"  status={status}, method={body.get('method')}, "
        f"confidence={body.get('confidence')}, "
        f"predictedSec={body.get('predictedStudySeconds')}"
    )
    return ok


def test_study_time_prediction_invalid():
    """POST /api/ai/predict/study-time — 잘못된 입력 (400 기대)"""
    # 7개 미만 → 400
    status, body = _post("/api/ai/predict/study-time", {
        "userId": 1,
        "weeklyStudySeconds": [3600, 4200],
    })
    ok = status == 400
    print(f"  {'✓' if ok else '✗'} POST /api/ai/predict/study-time (6개만) → 400 expected, got {status}")
    return ok


def test_ai_chat_learning_question():
    """POST /api/ai/chat — 학습 질문 (effective_knowledge_level 유지 확인)"""
    status, body = _post("/api/ai/chat", {
        "question": "스프링이 뭐야?",
        "knowledge_level": "박사",
        "personality": "친절_설명형",
        "use_gpt_validation": False,
    })
    ok = status == 200 and "answer" in body
    if ok:
        # 박사 수준인데 너무 짧은 답변이면 경고
        answer_len = len(body.get("answer", ""))
        level = body.get("knowledge_level", "")
        effective = body.get("effective_knowledge_level", "알 수 없음")
        short = answer_len < 100
        print(
            f"  {'✓' if ok else '✗'} POST /api/ai/chat (learning, 박사)  →"
            f"  status={status}, effective_level={effective}, answer_len={answer_len}"
            + ("  ⚠️  답변이 매우 짧습니다 (박사 수준 부적합 가능)" if short else "")
        )
    else:
        print(f"  ✗ POST /api/ai/chat (learning)  →  status={status}, error={body.get('error') or body.get('detail')}")
    return ok


def test_ai_chat_casual():
    """POST /api/ai/chat — 일상 대화 (effective_knowledge_level = 일상대화 확인)"""
    status, body = _post("/api/ai/chat", {
        "question": "안녕",
        "knowledge_level": "박사",
        "personality": "친절_설명형",
        "use_gpt_validation": False,
    })
    ok = status == 200 and "answer" in body
    if ok:
        effective = body.get("effective_knowledge_level", "알 수 없음")
        intent = body.get("intent", "알 수 없음")
        answer_len = len(body.get("answer", ""))
        print(
            f"  {'✓' if ok else '✗'} POST /api/ai/chat (casual, 안녕)  →"
            f"  status={status}, effective_level={effective}, intent={intent}, answer_len={answer_len}"
        )
        if effective not in ("일상대화", "casual"):
            print("      ⚠️  단순 인사인데 일상대화로 분류되지 않음")
    else:
        print(f"  ✗ POST /api/ai/chat (casual)  →  status={status}")
    return ok


def main():
    print(f"\n=== StudyBridge AI Smoke Test ===")
    print(f"  Target: {BASE_URL}\n")

    tests = [
        ("health check (env)", test_health),
        ("AI health check (connections)", test_ai_health),
        ("training status", test_training_status),
        ("study time prediction", test_study_time_prediction),
        ("study time prediction (invalid input)", test_study_time_prediction_invalid),
        ("AI chat (learning question)", test_ai_chat_learning_question),
        ("AI chat (casual)", test_ai_chat_casual),
    ]

    results = []
    for name, fn in tests:
        print(f"[{name}]")
        try:
            passed = fn()
        except Exception as e:
            print(f"  ✗ 예외 발생: {e}")
            passed = False
        results.append((name, passed))
        print()

    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    print(f"=== 결과: {passed_count}/{total} 통과 ===")
    for name, passed in results:
        icon = "✓" if passed else "✗"
        print(f"  {icon} {name}")

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()
