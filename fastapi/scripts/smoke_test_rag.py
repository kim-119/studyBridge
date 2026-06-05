#!/usr/bin/env python3
"""
RAG 파이프라인 스모크 테스트 (FastAPI 단독).

실행 전 FastAPI 서버 + pgvector DB가 실행 중이어야 한다.

실행 방법:
  cd fastapi
  python scripts/smoke_test_rag.py

환경변수:
  FASTAPI_URL=http://localhost:8000
  AI_SERVER_API_KEY=your_key
"""
import json
import os
import sys
import urllib.request
import urllib.error

BASE_URL = os.environ.get("FASTAPI_URL", "http://localhost:8000")
API_KEY = os.environ.get("AI_SERVER_API_KEY", "")

_TEST_MATERIAL_ID = 99999   # 테스트용 material_id (실제 데이터와 충돌 방지)
_TEST_TEXT = """
FastAPI는 Python 기반의 현대적인 웹 프레임워크다.
비동기(async/await) 지원, 자동 OpenAPI 문서 생성, Pydantic 데이터 검증이 특징이다.
uvicorn ASGI 서버와 함께 사용하며, 높은 성능과 개발 생산성을 제공한다.
의존성 주입(Dependency Injection) 시스템이 내장되어 있고,
Swagger UI와 ReDoc을 통한 자동 API 문서화가 가능하다.
"""


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _post(path: str, body: dict, timeout: int = 60) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path, data=data, headers=_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()}
    except Exception as e:
        return 0, {"error": str(e)}


def _delete(path: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE_URL + path, headers=_headers(), method="DELETE"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()}
    except Exception as e:
        return 0, {"error": str(e)}


def test_rag_ingest():
    """POST /api/rag/ingest — 문서 청킹 및 pgvector 저장"""
    status, body = _post("/api/rag/ingest", {
        "material_id": _TEST_MATERIAL_ID,
        "document_title": "FastAPI 스모크 테스트 문서",
        "text": _TEST_TEXT,
    }, timeout=90)
    ok = status == 200 and body.get("status") in ("ingested", "success")
    chunk_count = body.get("chunk_count", "알 수 없음")
    print(
        f"  {'✓' if ok else '✗'} POST /api/rag/ingest  →"
        f"  status={status}, chunk_count={chunk_count}"
    )
    if not ok:
        print(f"      오류: {body.get('error') or body.get('detail')}")
    return ok


def test_rag_query():
    """POST /api/rag/query — 유사도 검색 및 similarity score 확인"""
    status, body = _post("/api/rag/query", {
        "material_id": _TEST_MATERIAL_ID,
        "question": "FastAPI의 특징은 무엇인가?",
        "top_k": 3,
    }, timeout=30)
    ok = status == 200 and "chunks" in body
    if ok:
        chunks = body.get("chunks", [])
        print(
            f"  {'✓' if ok else '✗'} POST /api/rag/query  →"
            f"  status={status}, 검색된 청크 수={len(chunks)}"
        )
        for i, c in enumerate(chunks[:3]):
            sim = c.get("similarity", "N/A")
            content_preview = str(c.get("content", ""))[:60]
            print(f"      chunk[{i}] similarity={sim:.3f}: {content_preview}...")
        if not chunks:
            print("      ⚠️  검색 결과 없음 — 자료 ingest 여부 확인 필요")
    else:
        print(f"  ✗ POST /api/rag/query  →  status={status}, error={body.get('error') or body.get('detail')}")
    return ok


def test_rag_query_no_results():
    """POST /api/rag/query — 자료 없을 때 결과 없음 처리 확인"""
    status, body = _post("/api/rag/query", {
        "material_id": 1,  # 존재하지 않는 material
        "question": "이 자료에 없는 내용",
        "top_k": 3,
    }, timeout=30)
    ok = status == 200  # 결과 없어도 200 반환해야 함
    chunks = body.get("chunks", [])
    print(
        f"  {'✓' if ok else '✗'} POST /api/rag/query (존재 없는 자료)  →"
        f"  status={status}, chunks={len(chunks)} (빈 결과 정상)"
    )
    return ok


def test_rag_delete():
    """DELETE /api/rag/materials/{id} — 테스트 데이터 정리"""
    status, body = _delete(f"/api/rag/materials/{_TEST_MATERIAL_ID}")
    ok = status == 200
    deleted = body.get("deleted_count", "알 수 없음")
    print(
        f"  {'✓' if ok else '✗'} DELETE /api/rag/materials/{_TEST_MATERIAL_ID}  →"
        f"  status={status}, deleted_count={deleted}"
    )
    return ok


def main():
    print(f"\n=== StudyBridge RAG Smoke Test ===")
    print(f"  Target: {BASE_URL}")
    print(f"  Test material_id: {_TEST_MATERIAL_ID}\n")
    print("  ⚠️  테스트 완료 후 material_id={} 데이터가 삭제됩니다.\n".format(_TEST_MATERIAL_ID))

    tests = [
        ("RAG ingest (PDF 텍스트 청킹 저장)", test_rag_ingest),
        ("RAG query (유사도 검색 + similarity score)", test_rag_query),
        ("RAG query (결과 없을 때 빈 결과 반환)", test_rag_query_no_results),
        ("RAG delete (테스트 데이터 정리)", test_rag_delete),
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
