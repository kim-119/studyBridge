"""
자료보관함 퀴즈/로드맵 streaming 오케스트레이터 검증 (Y 테스트).

LLM/Wikipedia 차단 → deterministic + C/Python fallback 경로만으로 동작 보장.
event contract / 90초 deadline / 난이도 검증 / partial_validated / 84일 구조 / SSE 토큰을 확인한다.

실행: cd fastapi && .venv/bin/python scripts/test_material_stream.py
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import pdf_quiz_service as pq

# LLM/Wikipedia 차단 → 65초 fallback 경로(C→Python)만으로 검증, 단 빠르게.
pq._llm_generate = lambda *a, **k: []
pq.fetch_wikipedia_context = lambda c: ("", False)
# fallback_started 를 즉시 타도록 65초 → 0초로 단축
import app.services.stream_events as se
se.FALLBACK_START_SEC = 0
import app.services.quiz_stream_orchestrator as qso
qso.FALLBACK_START_SEC = 0

from app.services.quiz_stream_orchestrator import quiz_event_stream
from app.services.roadmap_stream_orchestrator import roadmap_event_stream

results = []


def check(name, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    results.append(bool(cond))
    return cond


PDF_TEXT = (
    "MVVM 아키텍처에서 ViewModel은 UI 상태를 보관하고 View와 분리된다. "
    "Repository는 데이터 소스를 추상화하여 네트워크와 로컬 캐시를 관리한다. "
    "Retrofit2는 REST API 호출을 담당하는 라이브러리다. "
    "ViewModel과 Repository를 분리하면 책임 분리와 테스트 가능성이 높아진다."
)


async def collect(gen):
    events = []
    async for ev in gen:
        events.append(ev)
    return events


def quiz_body(diff, count):
    return {"requestId": f"quiz-test-{diff}-{count}", "material_id": 57, "material_title": "MVVM",
            "difficulty": diff, "count": count, "document_text": PDF_TEXT,
            "core_content_text": "ViewModel과 Repository의 책임 분리",
            "keywords": ["ViewModel", "Repository", "Retrofit2", "StateFlow"]}


async def run_quiz(diff, count):
    started = time.monotonic()
    events = await collect(quiz_event_stream(quiz_body(diff, count), f"quiz-{diff}-{count}"))
    elapsed = time.monotonic() - started
    names = [e["event"] for e in events]
    completes = [e for e in events if e["event"] == "complete"]
    partials = [e for e in events if e["event"] == "partial_validated"]
    return events, names, completes, partials, elapsed


async def main():
    print("==== 공통 event contract / 90초 ====")
    events, names, completes, partials, elapsed = await run_quiz("easy", 5)
    check("start 가 첫 event", names[0] == "start")
    check("context_ready 포함", "context_ready" in names)
    check("generation_started 포함", "generation_started" in names)
    check("fallback_started 포함(LLM 차단)", "fallback_started" in names)
    check("complete 로 종료", names[-1] == "complete")
    check("90초 이내 종료", elapsed < 90, f"elapsed={elapsed:.1f}s")
    check("모든 event 에 requestId/type", all(e.get("requestId") and e.get("type") == "quiz" for e in events))
    check("partial_validated 존재", len(partials) >= 1)

    print("\n==== easy 5 / normal 20 / hard 20 ====")
    for diff, cnt, key in [("easy", 5, "easy5"), ("normal", 20, "normal20"), ("어려움", 20, "hard20")]:
        events, names, completes, partials, elapsed = await run_quiz(diff, cnt)
        ok_complete = bool(completes)
        qs = completes[0]["questions"] if completes else []
        applied = pq.normalize_quiz_count(cnt)[1]
        ok_count = len(qs) == applied
        ndiff = pq.normalize_difficulty(diff)
        # 난이도 절대 준수: hard 는 시나리오 신호어 + 길이
        if ndiff == "hard":
            ok_diff = all(len(q["question"]) >= pq.HARD_MIN_LEN
                          and any(s.lower() in q["question"].lower() for s in pq._HARD_SIGNALS)
                          for q in qs)
        else:
            ok_diff = all(len(q.get("choices", [])) == 4 for q in qs)
        # partial_validated 에는 검증 통과 문제만 (choices 4개)
        ok_partial = all(len(pqq.get("choices", [])) == 4
                         for p in partials for pqq in p.get("questions", []))
        ok_md = not any(m in (q["question"] + " " + " ".join(q["choices"]))
                        for q in qs for m in ("**", "###", "```"))
        check(f"{key} complete", ok_complete and elapsed < 90, f"elapsed={elapsed:.1f}s")
        check(f"{key} applied_count={applied} 문항", ok_count, f"len={len(qs)}")
        check(f"{key} 난이도 준수", ok_diff)
        check(f"{key} partial_validated 검증 통과만", ok_partial)
        check(f"{key} 마크다운 없음", ok_md)

    print("\n==== PDF context 없음 → error ====")
    events = await collect(quiz_event_stream({"material_title": "제목만", "difficulty": "hard", "count": 5},
                                             "quiz-empty"))
    err = [e for e in events if e["event"] == "error"]
    check("PDF 없으면 error event", bool(err) and err[0].get("error_code") == "PDF_CONTEXT_REQUIRED")
    check("무한 로딩 아님(error 로 종료)", events[-1]["event"] == "error")

    print("\n==== C fallback validate 통과 후보 ====")
    from app.fallback.c_fallback_runner import run_c_quiz_fallback
    cres = run_c_quiz_fallback("hard", 5, ["ViewModel", "Repository"])
    cqs = cres["questions"]
    # C 후보를 orchestrator gate(_question_difficulty_ok)로 검증
    gate_ok = all(pq._question_difficulty_ok(q, "hard", False) for q in cqs)
    check("C fallback hard 후보가 hard gate 통과", gate_ok)
    check("C fallback candidate_only/type", cres.get("candidate_only") and cres.get("fallback_type") == "C_LOCAL")

    print("\n==== 로드맵 84일 streaming ====")
    rbody = {"requestId": "roadmap-test", "material_id": 57, "material_title": "MVVM",
             "summary": PDF_TEXT, "keywords": ["ViewModel", "Repository"], "_no_llm": True}
    started = time.monotonic()
    revents = await collect(roadmap_event_stream(rbody, "roadmap-1"))
    relapsed = time.monotonic() - started
    rnames = [e["event"] for e in revents]
    rcomplete = [e for e in revents if e["event"] == "complete"]
    check("로드맵 start/generation_started/complete", rnames[0] == "start" and rnames[-1] == "complete")
    check("로드맵 90초 이내", relapsed < 90, f"elapsed={relapsed:.1f}s")
    if rcomplete:
        rm = rcomplete[0]["roadmap"]
        check("total_weeks==12", rm.get("total_weeks") == 12)
        check("days_per_week==7", rm.get("days_per_week") == 7)
        check("total_days==84", rm.get("total_days") == 84)
        check("로드맵 검증 통과", rm.get("validation", {}).get("passed") is True)
    else:
        check("로드맵 complete", False)

    print("\n==== SSE job 토큰 인증 ====")
    from app.api import material_stream_routes as msr
    info = msr._create_job("quiz", quiz_body("easy", 5), "quiz-job-1")
    jid, tok = info["jobId"], info["eventToken"]
    check("jobId/eventToken 발급", bool(jid) and bool(tok))
    ok_resolve = bool(msr._resolve_job(jid, tok, "quiz"))
    check("정상 토큰 resolve", ok_resolve)
    from fastapi import HTTPException
    try:
        msr._resolve_job(jid, "wrong-token", "quiz")
        check("위조 토큰 403", False)
    except HTTPException as e:
        check("위조 토큰 403", e.status_code == 403)
    try:
        msr._resolve_job("no-such-job", tok, "quiz")
        check("없는 job 404", False)
    except HTTPException as e:
        check("없는 job 404", e.status_code == 404)

    print("\n==== SUMMARY ====")
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


asyncio.run(main())
