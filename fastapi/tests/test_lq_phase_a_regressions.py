"""Phase A(2026-11-04) 재감사에서 재현된 결함의 회귀 테스트. 각 테스트는 수정 전 코드(HEAD 80179777)에서 실패했다.

출처: 독립 보안 재감사 15건 + 외부 전송/RAG 범위 추적 + 경로 매트릭스 + 실패 테스트 원인 분석.
"""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts.response_quality_v1 import SCHEMA_VERSION, QualityInput, QualityStatus, is_displayable
from app.quality_gate import checks as C
from app.quality_gate import evaluator as E
from tests.lq_helpers import ADMIN_TOKEN, INTERNAL_KEY, PK, REVIEWER_TOKEN, admin_headers, make_sample, service_headers


def run(c):
    return asyncio.run(c)


def q(task, out, ev=None, cons=None, req="질문", kind="text"):
    return QualityInput.model_validate({"schemaVersion": SCHEMA_VERSION, "requestId": "req-phasea-0001", "taskType": task,
                                        "outputKind": kind, "originalRequest": req, "proposedOutput": out,
                                        "groundingEvidence": ev or [], "constraints": cons if cons is not None else {}})


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    E.clear_cache()
    monkeypatch.setenv("AI_SERVER_API_KEY", INTERNAL_KEY)
    monkeypatch.setenv("TRAINING_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("TRAINING_REVIEWER_TOKEN", REVIEWER_TOKEN)
    monkeypatch.setenv("AI_AUDIT_LOG_PATH", str(tmp_path / "audit" / "a.jsonl"))
    monkeypatch.setenv("AI_TRAINING_DATASET_DIR", str(tmp_path / "ds"))
    monkeypatch.delenv("AI_QUALITY_JUDGE", raising=False)


# ── 1. ReDoS / CPU 상한 ──────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "원주율은 약 3.14159265358979323846264338327950 입니다",            # 예전: 20초+ (지수 백트래킹)
    "30! = 265252859812191058636308480000000 의 자릿수를 세면" + "1" * 40,
    "1 " * 30000,
])
def test_math_equation_regex_is_linear(text):
    t = time.time()
    C.check_math(text, None)
    assert time.time() - t < 0.5


@pytest.mark.parametrize("text", ["a" * 60000, "+82" * 20000, "1-" * 30000, "eyJ-" * 15000, "서울 " * 20000])
def test_pii_scan_is_linear_on_adversarial_input(text):
    from app.utils.pii_filter import scan_pii
    t = time.time()
    scan_pii(text)
    assert time.time() - t < 0.5


def test_contradiction_checks_are_bounded():
    out = "\n".join(f"TCP 연결 {i} 은 세 단계로 수립되지 않는다" for i in range(3000))
    ev = ["\n".join(f"TCP 연결 {i} 은 세 단계로 수립된다" for i in range(3000))] * 4
    t = time.time()
    C.internal_contradictions(out)
    C.negation_contradictions(out, ev)
    assert time.time() - t < 3.0


def test_evaluate_returns_quickly_and_does_not_stall_loop():
    t = time.time()
    o = run(E.evaluate(q("MATH_SOLUTION", "원주율은 약 3.14159265358979323846264338 입니다", req="원주율 값"), timeout_s=1.0))
    assert time.time() - t < 1.0 and not is_displayable(o, o.requestId)


# ── 2. 품질 게이트 우회 ──────────────────────────────────────────────────────
@pytest.mark.parametrize("task,out", [
    ("GENERAL_EXPLANATION", "태양이 지구 주위를 돈다는 사실을 모르는 사람은 없습니다."),
    ("STUDYMATE_BASIC", "물은 얼음보다 차가운 상태에서 끓는다는 것을 모르는 학생이 많아요."),
])
def test_disclosure_token_inside_assertion_is_not_a_disclosure(task, out):
    assert not C.is_no_claim_disclosure(out)
    o = run(E.evaluate(q(task, out)))
    assert not is_displayable(o, o.requestId)


@pytest.mark.parametrize("out", [
    "제공된 자료에서 확인되지 않아 정확한 답을 드리기 어렵습니다. 강의 자료를 선택해 주세요.",
    "자료에서 해당 내용을 확인할 수 없습니다. 관련 자료를 업로드해 주세요.",
    "정확히는 모르겠어요. 질문을 조금 더 구체적으로 알려 주세요.",
])
def test_honest_disclosures_still_pass(out):
    assert C.is_no_claim_disclosure(out)


def test_quiz_wrong_answer_key_with_restated_explanation_is_rejected():
    ev = [{"sourceType": "PDF_ORIGINAL", "materialId": 7, "page": 1, "chunkId": "m7-c0",
           "text": "이진 탐색은 정렬된 배열에서 탐색 범위를 절반씩 줄이는 알고리즘이다. 무작위 배열에는 적용하기 어렵다."}]

    def quiz(idx):
        return {"questions": [{"question": "이진 탐색은 어떤 배열에서 쓰는가?", "options": ["정렬된 배열", "무작위 배열", "연결 리스트", "해시 테이블"],
                               "answerIndex": idx, "explanation": "이진 탐색은 정렬된 배열에서 탐색 범위를 절반씩 줄이는 알고리즘이다."}]}
    ok = run(E.evaluate(q("PDF_QUIZ", quiz(0), ev, {"allowedMaterialIds": [7], "expectedQuestionCount": 1}, kind="quiz_json")))
    bad = run(E.evaluate(q("PDF_QUIZ", quiz(1), ev, {"allowedMaterialIds": [7], "expectedQuestionCount": 1}, kind="quiz_json")))
    assert is_displayable(ok, ok.requestId) and not is_displayable(bad, bad.requestId)
    assert "QUIZ_ANSWER_EXPLANATION_MISMATCH" in {v.code for v in bad.violations}


def test_quarantine_level_pii_is_not_shown():
    o = run(E.evaluate(q("GENERAL_EXPLANATION", "1조 담당자는 학번: 20231234 이고 주소는 서울 강남구 테헤란로 123 입니다.",
                         req="1조 담당자 알려줘")))
    assert not is_displayable(o, o.requestId) and "PII_LEAK" in {v.code for v in o.violations}


def test_learning_loop_system_scalar_is_evaluated(monkeypatch):
    from app.api.learning_loop_routes import _visible_strings
    vis = _visible_strings({"difficulty": "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX123", "answerIndex": 2,
                            "recommendedReviewDate": "2026-11-07", "warnings": ["시스템 경고"]}, [])
    assert vis == ["sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX123"]
    assert _visible_strings({"difficulty": "medium"}, []) == []


# ── 3. PII 규칙 사례(합성) ────────────────────────────────────────────────────
PII_POS = ["연락처는 010-2345-6789 입니다", "+82 10-2345-6789", "사무실 02-123-4567", "메일 hong.gildong@example.com 로",
           "주민번호 900101-1234567", "카드 4111 1111 1111 1111", "국민은행 123456-01-234567", "계좌번호 110-123-456789",
           "학번 20231234", "학번: 2023-12345", "김민수 학생이 질문했다", "이름: 홍길동", "서울특별시 강남구 테헤란로 123",
           "경기도 성남시 분당구 정자일로 95", "여권번호 M12345678", "면허번호 11-12-345678-90", "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX123",
           "Authorization: Bearer abcdefghijklmnop1234567890", "password=hunter2!x", "postgresql://admin:pa55word@db.internal/app",
           "http://10.0.3.7:8000/api/ai/chat", "hong＠example.com", "010​2345​6789", "900101­1234567"]
PII_NEG = ["모든 학생이 3-way handshake 를 배운다", "TCP 포트 8080 과 443 을 연다", "2026년 11월 4일 중간고사",
           "파이썬 버전 3.12.1 을 설치", "이순신 장군의 업적을 정리", "ISBN 978-89-123-4567-8 교재", "좌표 (37.5665, 126.9780)",
           "sha256 해시 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
           "UUID 예시 123e4567-e89b-12d3-a456-426614174000", "로컬에서 http://localhost:8000/docs 를 연다",
           "학생 30명 중 12명 합격", "git 커밋 13dae5e4ddf76d040e978c1a4fc29e6ece53f0e2", "비밀번호는 해시해서 저장한다",
           "홍길동전은 허균이 썼다", "선생님이 설명한 내용", "교수님 강의 3주차"]


@pytest.mark.parametrize("text", PII_POS)
def test_pii_positive_cases_detected(text):
    from app.utils.pii_filter import mask_pii, scan_pii
    assert not scan_pii(text).clean
    masked = mask_pii(text)
    assert not scan_pii(masked).clean or "[" in masked      # 탐지된 값은 정규화 뷰 위에서 마스킹된다


@pytest.mark.parametrize("text", PII_NEG)
def test_pii_negative_cases_clean(text):
    from app.utils.pii_filter import scan_pii
    assert scan_pii(text).clean, scan_pii(text).categories


# ── 4. 서명/범위 ──────────────────────────────────────────────────────────────
def test_scope_and_consent_tokens_are_not_interchangeable(monkeypatch):
    from app.contracts import signing as S
    monkeypatch.setenv("AI_SCOPE_SIGNING_KEY", "s" * 40)
    monkeypatch.setenv("AI_TRAINING_CONSENT_SIGNING_KEY", "s" * 40)           # 운영자가 같은 키를 재사용
    with pytest.raises(S.SignatureError) as e:
        S.issue_consent_token(PK, consent_version="v", consent_timestamp="t", scope=["MODEL_TRAINING"], rights={},
                              deletion_tracking_id="del-00000001", request_id="req-x-000001")
    assert e.value.code == "SIGNING_KEY_REUSED"
    monkeypatch.setenv("AI_TRAINING_CONSENT_SIGNING_KEY", "c" * 40)
    monkeypatch.setenv("AI_SCOPE_SIGNING_KEY", INTERNAL_KEY)                   # Bearer 키 재사용도 거부
    with pytest.raises(S.SignatureError):
        S.issue_scope_token(PK, [1], [], request_id="req-x-000001")


def test_scope_token_requires_typ_and_request_binding(monkeypatch):
    import base64
    import hashlib
    import hmac
    from app.contracts import signing as S
    monkeypatch.setenv("AI_SCOPE_SIGNING_KEY", "s" * 40)
    tok = S.issue_scope_token(PK, [42], [], request_id="req-bound-0001")
    assert S.verify_request_scope(tok, "req-bound-0001").allows_material(42)
    for rid in (None, "req-other-0001"):
        with pytest.raises(S.SignatureError):
            S.verify_request_scope(tok, rid)
    now = int(time.time())
    p = S._b64e(json.dumps({"v": 1, "sub": PK, "materialIds": [42], "iat": now, "exp": now + 60, "rid": "r"}).encode())
    untyped = p + "." + S._b64e(hmac.new(b"s" * 40, p.encode(), hashlib.sha256).digest())
    with pytest.raises(S.SignatureError) as e:
        S.verify_scope_token(untyped)
    assert e.value.code == "SCOPE_TOKEN_TYPE_INVALID"
    del base64


def test_body_signature_timestamp_overflow_is_401_not_500(monkeypatch):
    from app.contracts import signing as S
    monkeypatch.setenv("AI_TRAINING_SAMPLE_SIGNING_KEY", "t" * 40)
    with pytest.raises(S.SignatureError) as e:
        S.verify_body(b"{}", "v1=00", "9" * 401)
    assert e.value.code == "SIGNATURE_TIMESTAMP_INVALID"


def test_grounded_query_binds_scope_to_request_and_limits_body(monkeypatch):
    from app.api import rag_grounded_routes as R
    from app.contracts.signing import issue_scope_token
    monkeypatch.setenv("AI_SCOPE_SIGNING_KEY", "s" * 40)
    seen = []
    monkeypatch.setattr("app.services.rag_pipeline_service.grounded_rag_query",
                        lambda q, mid, doc, **k: seen.append(mid) or {"success": True, "answer": "x", "usedContext": {}})
    app = FastAPI()
    app.include_router(R.router)
    c = TestClient(app)
    tok = issue_scope_token(PK, [42], [], request_id="req-grounded-01")
    h = {"Authorization": f"Bearer {INTERNAL_KEY}", "X-AI-Scope": tok}
    body = {"question": "TCP?", "materialId": 42}
    assert c.post("/api/ai/rag/grounded-query", json=body, headers=h).status_code == 403
    assert c.post("/api/ai/rag/grounded-query", json=body, headers={**h, "X-Request-Id": "req-grounded-02"}).status_code == 403
    assert c.post("/api/ai/rag/grounded-query", json=body, headers={**h, "X-Request-Id": "req-grounded-01"}).status_code == 200
    assert seen == [42]
    big = {"question": "x" * (200 * 1024), "materialId": 42}
    assert c.post("/api/ai/rag/grounded-query", json=big, headers={**h, "X-Request-Id": "req-grounded-01"}).status_code == 413


def test_pgvector_search_without_material_is_refused():
    from app.services import pdf_rag_service, pgvector_service
    assert pgvector_service.search_similar_chunks([0.0] * 8, None) == []
    assert pgvector_service.search_candidate_chunks([0.0] * 8, None) == []
    assert pdf_rag_service.search_pdf_context("다른 사용자 자료가 섞이면 안 된다", None) == []


# ── 5. 외부 전송(learning-loop) ───────────────────────────────────────────────
def test_learning_loop_uses_local_llm_only_by_default(monkeypatch):
    from app.services import ai_pipeline, learning_loop_service as svc, llm_engine_router as L
    monkeypatch.delenv("AI_LEARNING_LOOP_EXTERNAL_LLM_ENABLED", raising=False)
    calls = []
    monkeypatch.setattr(ai_pipeline, "openai_refine", lambda *a, **k: calls.append("openai") or None)
    monkeypatch.setattr(ai_pipeline, "qwen_draft", lambda *a, **k: '{"ok": true}')
    assert svc._llm_struct(draft_system="s", draft_user="u", validator=lambda d: d.get("ok")) == {"ok": True}
    monkeypatch.setattr(L, "_try_ollama", lambda *a, **k: "[Ollama 실패]")
    monkeypatch.setattr(L, "_try_openai", lambda *a, **k: calls.append("openai-fallback") or "외부 답")
    assert svc._llm_text("s", "u") is None
    assert calls == []
    monkeypatch.setenv("AI_LEARNING_LOOP_EXTERNAL_LLM_ENABLED", "true")
    assert svc._llm_text("s", "u") == "외부 답" and calls == ["openai-fallback"]


# ── 6. 학습 후보 파이프라인 ───────────────────────────────────────────────────
def _client():
    from app.api.training_candidate_routes import ADMIN_RATE, REVOCATION_RATE, SERVICE_RATE, router
    for b in (ADMIN_RATE, REVOCATION_RATE, SERVICE_RATE):
        b.reset()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _repo():
    from app.training_pipeline.repository import InMemoryTrainingRepository, set_repository
    r = InMemoryTrainingRepository()
    set_repository(r)
    return r


def test_pii_correction_on_eligible_candidate_quarantines_and_invalidates(monkeypatch):
    monkeypatch.setenv("AI_TRAINING_COLLECTION_ENABLED", "true")
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline.records import ManifestRecord, ModelCandidateRecord, utcnow
    repo, c = _repo(), _client()
    cid = run(cs.collect_sample(repo, make_sample(1))).candidate_id
    assert c.post("/api/training-candidates/approve", json={"candidate_uuid": cid}, headers=admin_headers()).json()["state"] == "TRAIN_ELIGIBLE"
    rec = run(repo.get(cid))
    run(repo.save_manifest(ManifestRecord("train_v20261104_001_deadbeef", "ACTIVE", "0" * 64, [rec.content_hash], utcnow())))
    run(repo.register_model_candidate(ModelCandidateRecord("adp-1", "train_v20261104_001_deadbeef", "Qwen/Qwen3-14B",
                                                           "REGISTERED", "cand-001", [])))
    r = c.post("/api/training-candidates/correction", headers=service_headers(),
               json={"candidateId": cid, "correctedAnswer": "정답은 hong@example.com 으로 문의"})
    assert r.status_code == 200 and run(repo.get(cid)).state.value == "QUARANTINED"
    assert run(repo.get_manifest("train_v20261104_001_deadbeef")).status == "INVALIDATED"
    assert [m.status for m in run(repo.models_for_dataset("train_v20261104_001_deadbeef"))] == ["RETIREMENT_REQUIRED"]


def test_reject_on_revoked_or_rejected_candidate_is_not_500():
    from app.training_pipeline import candidate_service as cs
    repo, c = _repo(), _client()
    cid = run(cs.collect_sample(repo, make_sample(2))).candidate_id
    run(cs.withdraw_consent(repo, PK, actor=cs.Actor("svc", "service")))
    r = c.post("/api/training-candidates/reject", json={"candidate_uuid": cid}, headers=admin_headers())
    assert r.status_code == 200 and r.json()["status"] == "NOT_ALLOWED"
    cid2 = run(cs.collect_sample(repo, make_sample(3, user="pk_otheruser_000001"))).candidate_id
    for _ in range(2):                                   # 재시도 멱등
        r = c.post("/api/training-candidates/reject", json={"candidate_uuid": cid2}, headers=admin_headers())
        assert r.status_code == 200 and r.json()["status"] == "REJECTED"


def test_deletion_purges_exported_files(tmp_path):
    from app.training_pipeline import candidate_service as cs
    from app.training_pipeline import export_service as ex
    repo = _repo()
    rv = cs.Actor("rev-1", "training_reviewer", "req-rev-0001")
    ids = []
    for i in range(3):
        r = run(cs.collect_sample(repo, make_sample(i)))
        run(cs.review(repo, r.candidate_id, decision="VERIFY", actor=rv))
        ids.append(r.candidate_id)
    exp = run(ex.export_dataset(repo, actor="a", request_id="req-exp-0001"))
    victim = run(repo.get(ids[0]))
    files = list((tmp_path / "ds" / exp.dataset_id).glob("*.jsonl"))
    assert files and any(victim.question in f.read_text(encoding="utf-8") for f in files)
    res = run(cs.delete_by_tracking_id(repo, victim.deletion_tracking_id, actor=cs.Actor("svc", "service")))
    assert res.purged_datasets == [exp.dataset_id] and not (tmp_path / "ds" / exp.dataset_id).exists()
    m = run(repo.get_manifest(exp.dataset_id))
    assert m.status == "INVALIDATED" and "FILES_PURGED" in m.invalidated_reasons
    again = run(cs.delete_by_tracking_id(repo, victim.deletion_tracking_id, actor=cs.Actor("svc", "service")))
    assert again.status == "DELETED"                     # 재시도 멱등(이미 파기)


def test_negative_feedback_is_sticky_against_late_positive():
    from app.training_pipeline import candidate_service as cs
    repo = _repo()
    svc = cs.Actor("svc", "service")
    rv = cs.Actor("rev", "training_reviewer", "req-r-000001")
    cid = run(cs.collect_sample(repo, make_sample(4))).candidate_id
    run(cs.review(repo, cid, decision="VERIFY", actor=rv, use="reviewer", reviewer_answer="검수자가 다시 쓴 정답 문장이다."))
    assert run(cs.record_feedback(repo, cid, -1, actor=svc)).state == "NEEDS_REVIEW"     # 별도 타깃 → 재검수
    late = make_sample(4, feedback=1).model_copy(update={"eventId": "evt-late-pos-0001"})
    late.feedback.updatedAt = datetime.now(timezone.utc) - timedelta(minutes=3)
    run(cs.collect_sample(repo, late))
    r = run(cs.review(repo, cid, decision="VERIFY", actor=rv, use="candidate"))          # 싫어요 받은 원 AI 답변
    assert r.state != "TRAIN_ELIGIBLE" and "NEGATIVE_FEEDBACK" in r.reasons


def test_duplicate_event_replay_applies_once():
    from app.training_pipeline import candidate_service as cs
    repo = _repo()
    cid = run(cs.collect_sample(repo, make_sample(5))).candidate_id
    dup = make_sample(5, feedback=1).model_copy(update={"eventId": "evt-dup-replay-01"})
    # Phase B3: 재전송 판정은 DB 원장(run_once) — 프로세스 메모리 캐시가 아니다.
    statuses = [run(cs.run_once(repo, event_id=dup.eventId, message_type="SAMPLE", body_sha256="d" * 64,
                                work=lambda: cs.collect_sample(repo, dup)))[1].status for _ in range(3)]
    assert statuses == ["DUPLICATE", "IDEMPOTENT_REPLAY", "IDEMPOTENT_REPLAY"]
    assert run(repo.get(cid)).feedback_history == [1]


def test_admin_operation_refused_when_audit_cannot_be_written(monkeypatch, tmp_path):
    (tmp_path / "blocker").write_text("x")
    monkeypatch.setenv("AI_AUDIT_LOG_PATH", str(tmp_path / "blocker" / "a.jsonl"))     # 상위가 파일 → 쓰기 불가
    _repo()
    r = _client().post("/api/training-candidates/export-jsonl", json={}, headers=admin_headers())
    assert r.status_code == 503 and r.json()["detail"]["errorCode"] == "AUDIT_UNAVAILABLE"
    assert not (tmp_path / "ds").exists() or not list((tmp_path / "ds").glob("train_v*"))


def test_identifier_with_trailing_newline_is_rejected():
    from pydantic import ValidationError

    from app.contracts.training_sample_v1 import TrainingSampleV1
    s = make_sample(6).model_dump(mode="json")
    s["deletionTrackingId"] = "del-abcdef-0006\n"
    with pytest.raises(ValidationError):
        TrainingSampleV1.model_validate(s)


def test_pdf_task_with_pasted_or_derived_context_is_not_rights_verified(monkeypatch):
    from app.contracts.response_quality_v1 import QualityOutput, TaskType
    from app.contracts.signing import ConsentClaim
    from app.training_pipeline import collection_hook as ch
    monkeypatch.setenv("AI_TRAINING_COLLECTION_ENABLED", "true")
    qo = QualityOutput(schemaVersion="response-quality.v1", requestId="req-col-000002", taskType="PDF_SUMMARY", success=True, verified=True,
                       qualityStatus="APPROVED", score=90.0, hardFail=False, evaluatorVersion="rqg-1.0.0")
    c = ConsentClaim(sub=PK, consent_version="v", consent_timestamp="2026-10-30T00:00:00Z", scope=frozenset({"MODEL_TRAINING"}),
                     rights={"42": "USER_OWNED_VERIFIED"}, deletion_tracking_id="del-00000002", request_id="req-col-000002")
    pdf = {"sourceType": "PDF_ORIGINAL", "materialId": 42, "page": 1, "chunkId": "m42-c0", "text": "원문"}
    pasted = {"sourceType": "USER_PROVIDED_TEXT", "evidenceId": "sourceText", "text": "붙여넣은 제3자 글"}
    ev = ch.ResponseCollectionEvent(request_id="req-col-000002", task_type=TaskType.PDF_SUMMARY, question="q", output="a",
                                    evidence=[pdf, pasted], quality=qo, consent=c, derived_context_used=False)
    assert ch.submit(ev) == "SKIPPED_RIGHTS_UNVERIFIED"


def test_repository_db_errors_and_bad_ids_have_stable_contract(monkeypatch):
    from app.training_pipeline.repository import PostgresTrainingRepository, RepositoryUnavailable, set_repository
    repo = PostgresTrainingRepository("postgresql://none:none@127.0.0.1:9/none")
    assert run(repo.get("not-a-uuid")) is None
    set_repository(repo)
    # Phase B3: 철회는 서명된 training-control.v1 만 받는다 → 서명이 맞아야 저장소 단계까지 가서 503 이 된다.
    import time as _t
    from datetime import datetime as _dt, timezone as _tz
    from app.contracts import signing as _S
    monkeypatch.setenv("AI_TRAINING_SAMPLE_SIGNING_KEY", "s" * 40)
    body = json.dumps({"schemaVersion": "training-control.v1", "typ": "training-control",
                       "messageType": "CONSENT_WITHDRAWAL", "eventId": "rv-dberr-000001",
                       "issuedAt": _dt.now(_tz.utc).isoformat(), "pseudonymousUserKey": PK,
                       "scope": ["MODEL_TRAINING"]}).encode()
    ts = int(_t.time())
    h = {**service_headers(), "Content-Type": "application/json", "X-Request-Id": "rv-dberr-000001",
         "X-AI-Contract-Timestamp": str(ts), "X-AI-Contract-Signature": _S.sign_body_with_key(b"s" * 40, body, ts)}
    r = _client().post("/api/training-candidates/consent-withdrawal", headers=h, content=body)
    assert r.status_code == 503 and r.json()["errorCode"] == "TRAINING_REPOSITORY_UNAVAILABLE"
    del RepositoryUnavailable


# ── 7. 기존 라이브 버그(별도 이슈, 영역 관련) ──────────────────────────────────
def test_tasks_fetch_stream_without_feature_does_not_crash(monkeypatch):
    import app.services.ai_fetch_stream_service as svc
    monkeypatch.setattr(svc, "stream_ollama", lambda *a, **k: iter(["답변 조각"]))
    lines = [json.loads(b) for b in b"".join(svc.tasks_stream({"message": "오늘 공부 계획 세워줘"})).decode().splitlines() if b.strip()]
    assert lines[0]["type"] == "status" and lines[0]["requestedFeature"] == "generic" and lines[-1]["type"] == "done"


def test_polite_negation_contradicting_source_is_rejected():
    """gold 시드 smoke 가 찾은 기존 결함: '아닙니다/아닌/아님' 은 부정 정규식에 걸리지 않아 원문 모순이 승인됐다."""
    tcp = [{"sourceType": "PDF_ORIGINAL", "materialId": 42, "page": 3, "chunkId": "m42-c7", "text": "TCP 는 연결 지향 프로토콜이다."}]
    for out in ("TCP 는 연결 지향 프로토콜이 아닙니다.", "TCP 는 연결 지향 프로토콜이 아님.", "TCP 는 연결 지향이 아닌 프로토콜이다."):
        E.clear_cache()
        o = run(E.evaluate(q("PDF_QA", out, tcp, {"allowedMaterialIds": [42]}, "TCP 는 어떤 프로토콜?")))
        assert not is_displayable(o, o.requestId), out
