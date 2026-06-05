#!/usr/bin/env python3
"""
학습 시간 예측 스모크 테스트 (FastAPI 단독).

실행 방법:
  cd fastapi
  python scripts/smoke_test_prediction.py
"""
import json
import os
import sys
import urllib.request
import urllib.error

BASE_URL = os.environ.get("FASTAPI_URL", "http://localhost:8000")
API_KEY = os.environ.get("AI_SERVER_API_KEY", "")


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
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()}
    except Exception as e:
        return 0, {"error": str(e)}


def _get(path: str) -> tuple[int, dict]:
    req = urllib.request.Request(BASE_URL + path, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()}
    except Exception as e:
        return 0, {"error": str(e)}


def test_prediction_normal():
    """POST /api/ai/predict/study-time — 정상 입력"""
    weekly = [3600.0, 4200.0, 3000.0, 5400.0, 2700.0, 3900.0, 4500.0]
    status, body = _post("/api/ai/predict/study-time", {
        "userId": 1,
        "weeklyStudySeconds": weekly,
    })
    ok = (
        status == 200
        and "predictedStudySeconds" in body
        and "method" in body
        and "confidence" in body
    )
    if ok:
        predicted_min = round(body["predictedStudySeconds"] / 60)
        method = body["method"]
        confidence = body["confidence"]
        print(
            f"  ✓ 예측 성공: 약 {predicted_min}분 예상"
            f"  | 방식: {method}"
            f"  | 신뢰도: {confidence}"
        )
        # 실제 Transformer가 없으면 weighted_average_fallback 이어야 함
        if method == "transformer":
            print("    ℹ️  Transformer 모델로 예측됨 (실제 학습 완료 상태)")
        else:
            print("    ℹ️  가중평균 fallback 사용 (Transformer 미학습 또는 모델 파일 없음)")
    else:
        print(f"  ✗ 예측 실패: status={status}, error={body.get('error') or body.get('detail')}")
    return ok


def test_prediction_confidence_range():
    """POST /api/ai/predict/study-time — confidence 범위 검증 (0~1)"""
    status, body = _post("/api/ai/predict/study-time", {
        "userId": 2,
        "weeklyStudySeconds": [1800.0, 1800.0, 1800.0, 1800.0, 1800.0, 1800.0, 1800.0],
    })
    ok = status == 200
    if ok:
        confidence = body.get("confidence", -1)
        in_range = 0.0 <= confidence <= 1.0
        print(
            f"  {'✓' if in_range else '✗'} confidence 범위 검증: {confidence}"
            f"  ({'범위 내' if in_range else '범위 초과!'})"
        )
        ok = in_range
    else:
        print(f"  ✗ 요청 실패: status={status}")
    return ok


def test_prediction_high_variance():
    """POST /api/ai/predict/study-time — 분산 큰 데이터 (낮은 confidence 기대)"""
    weekly = [0.0, 7200.0, 0.0, 10800.0, 0.0, 14400.0, 0.0]
    status, body = _post("/api/ai/predict/study-time", {
        "userId": 3,
        "weeklyStudySeconds": weekly,
    })
    ok = status == 200
    if ok:
        confidence = body.get("confidence", 1.0)
        # 분산이 매우 크면 신뢰도가 낮아야 함 (0.55 이하 기대)
        expected_low = confidence <= 0.6
        print(
            f"  {'✓' if ok else '✗'} 분산 큰 데이터 예측: confidence={confidence}"
            f"  {'(신뢰도 낮음 정상)' if expected_low else '⚠️  신뢰도가 예상보다 높음'}"
        )
    else:
        print(f"  ✗ 요청 실패: status={status}")
    return ok


def test_prediction_invalid_count():
    """POST /api/ai/predict/study-time — 입력 개수 오류 (400 기대)"""
    status, body = _post("/api/ai/predict/study-time", {
        "userId": 1,
        "weeklyStudySeconds": [3600.0, 4200.0],  # 7개 미만
    })
    ok = status == 400
    print(f"  {'✓' if ok else '✗'} 7개 미만 입력 → 400 expected, got {status}")
    return ok


def test_prediction_negative():
    """POST /api/ai/predict/study-time — 음수 입력 (400 기대)"""
    status, body = _post("/api/ai/predict/study-time", {
        "userId": 1,
        "weeklyStudySeconds": [3600.0, -100.0, 3000.0, 5400.0, 2700.0, 3900.0, 4500.0],
    })
    ok = status == 400
    print(f"  {'✓' if ok else '✗'} 음수 포함 입력 → 400 expected, got {status}")
    return ok


def test_training_status():
    """GET /api/ai/training/status — 파인튜닝 상태 확인"""
    status, body = _get("/api/ai/training/status")
    ok = status == 200
    current = body.get("current_status", "unknown")
    print(f"  {'✓' if ok else '✗'} GET /api/ai/training/status  →  current_status={current}")

    # 실제 학습하지 않았으면 "trained"이면 안 됨
    if current == "trained":
        print("    ⚠️  current_status=trained — 실제 학습 완료 여부를 확인하세요")
    return ok


def main():
    print(f"\n=== StudyBridge 학습 시간 예측 Smoke Test ===")
    print(f"  Target: {BASE_URL}\n")

    tests = [
        ("예측 정상 동작 (method+confidence 포함)", test_prediction_normal),
        ("confidence 범위 검증 (0~1)", test_prediction_confidence_range),
        ("분산 큰 데이터 — 낮은 신뢰도 기대", test_prediction_high_variance),
        ("7개 미만 입력 — 400 반환", test_prediction_invalid_count),
        ("음수 포함 입력 — 400 반환", test_prediction_negative),
        ("파인튜닝 상태 조회", test_training_status),
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
        print(f"  {'✓' if passed else '✗'} {name}")

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()
