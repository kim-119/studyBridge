"""ai07↔EC2 차등 계약 케이스 생성기(결정적). 표준 라이브러리만 쓴다.

기본 fixture(유효)에서 한 군데씩 바꾼 변이 입력을 만든다: 타입 강제변환, 끝 개행, 타임존 없는 시각, null/누락,
정수 범위, NaN/Infinity, 뒤따르는 토큰, BOM, 점수 경계(79/80/100/100.5), APPROVED 불변식, 서명 토큰 변조.
출력: app/contracts/fixtures/differential/cases.v1.jsonl (raw JSON 텍스트를 그대로 담는다 — 비표준 JSON 포함).
Java 판정은 run_java_crosscheck.sh 로 얻어 java-verdicts.v1.jsonl 에 기록한다(사람이 기대값을 손으로 쓰지 않는다).
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
FX = ROOT / "app" / "contracts" / "fixtures"
OUT = FX / "differential" / "cases.v1.jsonl"

MISSING = object()


def load(rel):
    return json.loads((FX / rel).read_text(encoding="utf-8"))


def mutate(base, path, value):
    d = copy.deepcopy(base)
    cur = d
    for p in path[:-1]:
        cur = cur[p]
    if value is MISSING:
        cur.pop(path[-1], None)
    else:
        cur[path[-1]] = value
    return d


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


cases = []


def add(cid, model, raw=None, *, raw_b64=None, **extra):
    c = {"id": cid, "model": model}
    if raw_b64 is not None:
        c["rawBase64"] = raw_b64
    else:
        c["raw"] = raw
    c.update(extra)
    cases.append(c)


def field_cases(prefix, model, base, path, values):
    for name, v in values:
        add(f"{prefix}.{'.'.join(map(str, path))}.{name}", model, dump(mutate(base, path, v)))


# ── 공통 값 묶음 ───────────────────────────────────────────────────────────────
DT_VARIANTS = [
    ("z", "2026-11-01T09:00:00Z"), ("lower_z", "2026-11-01t09:00:00z"), ("offset_colon", "2026-11-01T18:00:00+09:00"),
    ("offset_seconds", "2026-11-01T18:00:00+09:00:00"), ("offset_nocolon", "2026-11-01T18:00:00+0900"),
    ("offset_hh", "2026-11-01T18:00:00+09"), ("utc_plus0000", "2026-11-01T09:00:00+0000"), ("utc_plus00", "2026-11-01T09:00:00+00"),
    ("minus0000", "2026-11-01T09:00:00-00:00"), ("naive", "2026-11-01T09:00:00"), ("date_only", "2026-11-01"),
    ("space_sep", "2026-11-01 09:00:00Z"), ("no_seconds", "2026-11-01T09:00Z"), ("frac3", "2026-11-01T09:00:00.123Z"),
    ("frac6", "2026-11-01T09:00:00.123456Z"), ("frac9", "2026-11-01T09:00:00.123456789Z"), ("frac10", "2026-11-01T09:00:00.1234567891Z"),
    ("epoch_string", "1793750400"), ("epoch_int", 1793750400), ("epoch_float", 1793750400.5), ("empty", ""),
    ("trailing_newline", "2026-11-01T09:00:00Z\n"), ("leading_space", " 2026-11-01T09:00:00Z"), ("hour24", "2026-11-01T24:00:00Z"),
    ("feb30", "2026-02-30T09:00:00Z"), ("leap_second", "2026-12-31T23:59:60Z"), ("year5", "+12026-11-01T09:00:00Z"),
    ("week_date", "2026-W44-7T09:00:00Z"), ("ordinal", "2026-305T09:00:00Z"), ("null", None), ("bool", True), ("object", {}),
    ("zone_id", "2026-11-01T09:00:00Z[UTC]"), ("offset_1800", "2026-11-01T09:00:00+18:00"), ("offset_1900", "2026-11-01T09:00:00+19:00"),
    ("comma_frac", "2026-11-01T09:00:00,5Z"), ("digit_frac_only", "2026-11-01T09:00:00.Z"),
]
ID_VARIANTS = [
    ("ok", "req-ok-000001"), ("trailing_newline", "req-ok-000001\n"), ("trailing_crlf", "req-ok-000001\r\n"),
    ("leading_newline", "\nreq-ok-000001"), ("space", "req ok 000001"), ("unicode", "req-é-000001"), ("fullwidth", "ｒｅｑ-000001"),
    ("len_7", "abcdefg"), ("len_8", "abcdefgh"), ("len_128", "a" * 128), ("len_129", "a" * 129), ("empty", ""),
    ("int", 12345678), ("float", 12345678.0), ("bool", True), ("null", None), ("array", ["req-ok-000001"]), ("object", {"a": 1}),
]
INT_VARIANTS = [("int", 42), ("string", "42"), ("float_integral", 42.0), ("float", 42.5), ("exp", 4.2e1), ("bool_true", True),
                ("zero", 0), ("negative", -1), ("null", None), ("int32_max", 2147483647), ("int32_over", 2147483648),
                ("int64_max", 9223372036854775807), ("int64_over", 9223372036854775808), ("array", [42]), ("object", {})]
BOOL_VARIANTS = [("true", True), ("false", False), ("string_true", "true"), ("int1", 1), ("int0", 0), ("null", None),
                 ("string_yes", "yes"), ("float1", 1.0), ("array", [True])]
STR_VARIANTS = [("int", 5), ("float", 5.5), ("bool", True), ("null", None), ("array", ["x"]), ("object", {"x": 1}), ("empty", "")]
FLOAT_VARIANTS = [("int", 1), ("float", 0.5), ("string", "0.5"), ("bool", True), ("null", None), ("neg", -0.5), ("big", 1e308)]


def gen_learning_context():
    base = load("learning-context.v1/valid_pdf_and_history.json")
    minimal = load("learning-context.v1/valid_minimal.json")
    add("lc.base", "lc", dump(base))
    add("lc.minimal", "lc", dump(minimal))
    field_cases("lc", "lc", base, ["requestId"], ID_VARIANTS + [("len_1", "a")])
    field_cases("lc", "lc", base, ["documentId"], [("trailing_newline", "doc-a1\n"), ("int", 7), ("null", None), ("missing", MISSING)])
    field_cases("lc", "lc", base, ["pseudonymousUserKey"], [("digits", "1234567890123456"), ("trailing_newline", "pk_7f3a9c2e1b4d6a8f\n"),
                                                           ("len_15", "pk_7f3a9c2e1b4d"), ("int", 1234567890123456), ("null", None),
                                                           ("email", "user@example.com")])
    field_cases("lc", "lc", base, ["materialId"], INT_VARIANTS + [("missing", MISSING)])
    field_cases("lc", "lc", base, ["tokenBudget"], [("int", 512), ("string", "512"), ("float", 512.0), ("lo", 255), ("hi", 32769), ("null", None)])
    field_cases("lc", "lc", base, ["currentQuestion"], STR_VARIANTS + [("len_4000", "가" * 4000), ("len_4001", "가" * 4001),
                                                                      ("emoji_4000", "😀" * 4000), ("emoji_4001", "😀" * 4001)])
    field_cases("lc", "lc", base, ["contextItems"], [("null", None), ("empty", []), ("missing", MISSING), ("null_element", [None]),
                                                    ("object", {})])
    field_cases("lc", "lc", base, ["usedSources"], [("null", None), ("unknown", ["ctx-999"]), ("int_element", [1]), ("null_element", [None]),
                                                   ("string", "ctx-001")])
    item = ["contextItems", 0]
    for name, v in DT_VARIANTS:
        add(f"lc.contextItems.0.createdAt.{name}", "lc", dump(mutate(base, item + ["createdAt"], v)))
    field_cases("lc", "lc", base, item + ["page"], INT_VARIANTS)
    field_cases("lc", "lc", base, item + ["id"], [("trailing_newline", "ctx-001\n"), ("int", 1), ("null", None)])
    field_cases("lc", "lc", base, item + ["chunkId"], [("trailing_newline", "m42-c7\n"), ("int", 7), ("null", None)])
    field_cases("lc", "lc", base, item + ["sourceId"], [("trailing_newline", "material:42\n"), ("int", 42)])
    field_cases("lc", "lc", base, item + ["content"], STR_VARIANTS)
    field_cases("lc", "lc", base, item + ["kind"], [("upper", "PDF_CHUNK"), ("int", 0), ("unknown", "video")])
    field_cases("lc", "lc", base, item + ["trustLevel"], [("lower", "source_primary"), ("null", None), ("int", 3)])
    field_cases("lc", "lc", base, item + ["qualityStatus"], [("null", None), ("int", 1), ("len_33", "Q" * 33)])
    field_cases("lc", "lc", base, ["contextItems", 2, "role"], [("system", "system"), ("upper", "USER"), ("int", 1), ("null", None),
                                                                ("assistant", "assistant")])
    prov = item + ["provenance"]
    field_cases("lc", "lc", base, prov + ["retrievalScore"], FLOAT_VARIANTS + [("over", 1.5)])
    field_cases("lc", "lc", base, prov + ["notes"], [("null", None), ("null_element", [None]), ("int_element", [1]), ("nine", ["n"] * 9)])
    field_cases("lc", "lc", base, prov + ["origin"], [("null", None), ("int", 1)])
    field_cases("lc", "lc", base, prov, [("null", None), ("unknown_field", {"origin": "pgvector", "x": 1})])
    # 원시 JSON 수준
    raw = dump(base)
    add("lc.raw.trailing_object", "lc", raw + "{}")
    add("lc.raw.trailing_garbage", "lc", raw + "x")
    add("lc.raw.trailing_whitespace", "lc", raw + " \n\t")
    add("lc.raw.nan_score", "lc", raw.replace('"retrievalScore":0.81', '"retrievalScore":NaN'))
    add("lc.raw.infinity_score", "lc", raw.replace('"retrievalScore":0.81', '"retrievalScore":Infinity'))
    add("lc.raw.leading_zero", "lc", raw.replace('"materialId":42', '"materialId":042'))
    add("lc.raw.duplicate_key_last_valid", "lc", raw.replace('"materialId":42', '"materialId":"x","materialId":42'))
    add("lc.raw.duplicate_key_last_invalid", "lc", raw.replace('"materialId":42', '"materialId":42,"materialId":"x"'))
    add("lc.raw.bom", "lc", raw_b64=base64.b64encode(b"\xef\xbb\xbf" + raw.encode()).decode())
    add("lc.raw.invalid_utf8", "lc", raw_b64=base64.b64encode(raw.encode().replace(b"TCP", b"\xff\xfeP", 1)).decode())
    add("lc.raw.array_top", "lc", "[" + raw + "]")
    add("lc.raw.empty", "lc", "")
    add("lc.raw.null", "lc", "null")
    add("lc.raw.comment", "lc", raw[:-1] + "/*c*/}")
    add("lc.raw.single_quote", "lc", raw.replace('"materialId":42', "'materialId':42"))
    add("lc.raw.lone_surrogate", "lc", raw.replace("3-way handshake 단계는?", "\\ud800"))
    add("lc.raw.paired_surrogate_escape", "lc", raw.replace("3-way handshake 단계는?", "\\ud83d\\ude00"))
    add("lc.raw.duplicate_key_both_valid", "lc", raw.replace('"materialId":42', '"materialId":41,"materialId":42'))
    add("lc.raw.duplicate_key_nested_both_valid", "lc", raw.replace('"origin":"pgvector"', '"origin":"a","origin":"pgvector"'))
    add("lc.raw.deep_nesting", "lc", raw[:-1] + ',"x":' + "[" * 2000 + "]" * 2000 + "}")
    for name, v in [("plus_year4", "+2026-11-01T09:00:00Z"), ("epoch_year5138", "99999999999"), ("epoch_year10000", 253402300800),
                    ("epoch_negative", -1), ("epoch_dot_only", "."), ("epoch_frac_only", ".5"), ("epoch_trailing_dot", "5."),
                    ("epoch_neg_string", "-5"), ("epoch_int64_over", "9223372036854775808"), ("year0000", "0000-01-01T00:00:00Z"),
                    ("tab_trim", "\t2026-11-01T09:00:00Z\t"), ("nbsp_trim", "\u00a02026-11-01T09:00:00Z")]:
        add(f"lc.contextItems.0.createdAt.{name}", "lc", dump(mutate(base, ["contextItems", 0, "createdAt"], v)))


def gen_training_sample():
    base = load("training-sample.v1/valid_pdf_qa_candidate.json")
    fb = load("training-sample.v1/valid_same_qa_negative_feedback.json")
    add("ts.base", "ts", dump(base))
    add("ts.feedback_base", "ts", dump(fb))
    field_cases("ts", "ts", base, ["eventId"], ID_VARIANTS)
    field_cases("ts", "ts", base, ["deletionTrackingId"], [("trailing_newline", base["deletionTrackingId"] + "\n"), ("int", 12345678), ("null", None)])
    field_cases("ts", "ts", base, ["pseudonymousUserKey"], [("digits", "1234567890123456"), ("trailing_newline", base["pseudonymousUserKey"] + "\n"),
                                                           ("int", 1234567890123456)])
    for name, v in DT_VARIANTS:
        add(f"ts.createdAt.{name}", "ts", dump(mutate(base, ["createdAt"], v)))
    for fld in (["consentTimestamp"], ["trainingEligibility", "decidedAt"]):
        for name, v in [("naive", "2026-11-01T09:00:00"), ("z", "2026-11-01T09:00:00Z"), ("null", None), ("epoch_int", 1793750400)]:
            add(f"ts.{'.'.join(fld)}.{name}", "ts", dump(mutate(base, fld, v)))
    field_cases("ts", "ts", base, ["question"], STR_VARIANTS + [("spaces", "   "), ("len_4000", "q" * 4000), ("len_4001", "q" * 4001)])
    field_cases("ts", "ts", base, ["contentHash"], [("upper", base["contentHash"].upper()), ("trailing_newline", base["contentHash"] + "\n"),
                                                   ("null", None), ("int", 1)])
    field_cases("ts", "ts", base, ["trainingEligibility", "consentGranted"], BOOL_VARIANTS)
    field_cases("ts", "ts", base, ["trainingEligibility", "consentWithdrawn"], [("null", None), ("missing", MISSING), ("string", "false"), ("int", 0)])
    field_cases("ts", "ts", base, ["trainingEligibility", "consentScope"], [("null", None), ("null_element", [None]), ("int_element", [1]),
                                                                           ("nine", ["s"] * 9), ("string", "MODEL_TRAINING")])
    field_cases("ts", "ts", base, ["evidence"], [("null", None), ("missing", MISSING), ("null_element", [None])])
    field_cases("ts", "ts", base, ["evidence", 0, "materialId"], INT_VARIANTS)
    field_cases("ts", "ts", base, ["evidence", 0, "page"], [("string", "3"), ("float", 3.0), ("zero", 0), ("int32_over", 2147483648)])
    field_cases("ts", "ts", base, ["qualityLabel"], [("null", None), ("missing", MISSING), ("lower", "unlabeled"), ("unknown", "GOOD")])
    field_cases("ts", "ts", base, ["sourceKind"], [("lower", "pdf_qa"), ("null", None), ("int", 0)])
    field_cases("ts", "ts", base, ["rightsStatus"], [("null", None), ("unknown", "OK")])
    field_cases("ts", "ts", base, ["modelName"], [("null", None), ("int", 1), ("len_65", "m" * 65)])
    field_cases("ts", "ts", base, ["unknownTop"], [("added", 1)])
    field_cases("ts", "ts", fb, ["feedback", "score"], [("int1", 1), ("string", "1"), ("float", 1.0), ("bool", True), ("two", 2), ("null", None)])
    field_cases("ts", "ts", fb, ["feedback", "history"], [("null", None), ("null_element", [None]), ("string_element", ["1"]),
                                                         ("float_element", [1.0]), ("int32_over", [2147483648]), ("big_len", [0] * 65)])
    for name, v in [("naive", "2026-11-01T09:00:00"), ("null", None)]:
        add(f"ts.feedback.updatedAt.{name}", "ts", dump(mutate(fb, ["feedback", "updatedAt"], v)))
    field_cases("ts", "ts", base, ["verification"], [("null", None), ("method_missing", {}), ("ok", {"method": "HUMAN_REVIEW"}),
                                                    ("naive_at", {"method": "HUMAN_REVIEW", "verifiedAt": "2026-11-01T09:00:00"})])
    raw = dump(base)
    add("ts.raw.trailing_object", "ts", raw + "{}")
    add("ts.raw.bom", "ts", raw_b64=base64.b64encode(b"\xef\xbb\xbf" + raw.encode()).decode())


def gen_quality():
    inp = load("response-quality.v1/input_pdf_summary_faithful.json")
    out = load("response-quality.v1/output_approved_shape.json")
    add("rqi.base", "rqi", dump(inp))
    field_cases("rqi", "rqi", inp, ["requestId"], ID_VARIANTS)
    field_cases("rqi", "rqi", inp, ["proposedOutput"], [("missing", MISSING), ("null", None), ("object", {"a": 1}), ("int", 1),
                                                       ("len_60000", "x" * 60000), ("len_60001", "x" * 60001),
                                                       ("obj_near_limit", {"k": "x" * 59990}), ("obj_over_limit", {"k": "x" * 59995})])
    field_cases("rqi", "rqi", inp, ["attemptIndex"], [("null", None), ("missing", MISSING), ("string", "0"), ("three", 3), ("float", 0.0)])
    field_cases("rqi", "rqi", inp, ["groundingEvidence"], [("null", None), ("missing", MISSING), ("null_element", [None]), ("thirty_three", [{"sourceType": "X"}] * 33)])
    field_cases("rqi", "rqi", inp, ["groundingEvidence", 0, "materialId"], [("string", "42"), ("float", 42.0), ("zero", 0)])
    field_cases("rqi", "rqi", inp, ["groundingEvidence", 0, "page"], [("string", "12"), ("zero", 0), ("int32_over", 2147483648)])
    field_cases("rqi", "rqi", inp, ["groundingEvidence", 0, "documentId"], [("int", 1), ("long", "d" * 500)])
    field_cases("rqi", "rqi", inp, ["constraints"], [("null", None), ("missing", MISSING), ("unknown", {"foo": 1}),
                                                    ("require_citations_null", {"requireCitations": None}),
                                                    ("allow_pii_string", {"allowPiiEcho": "false"}),
                                                    ("allowed_ids_null_element", {"allowedMaterialIds": [None]}),
                                                    ("allowed_ids_string", {"allowedMaterialIds": ["42"]}),
                                                    ("max_daily_zero", {"maxDailyHours": 0}), ("max_daily_int", {"maxDailyHours": 8}),
                                                    ("max_daily_string", {"maxDailyHours": "8"}), ("qcount_51", {"expectedQuestionCount": 51}),
                                                    ("qcount_float", {"expectedQuestionCount": 5.0}), ("participants_null_el", {"participants": [None]}),
                                                    ("prereq_int_el", {"knownPrerequisites": [1]})])
    field_cases("rqi", "rqi", inp, ["taskType"], [("unknown", "OTHER"), ("lower", "pdf_summary"), ("null", None)])
    field_cases("rqi", "rqi", inp, ["outputKind"], [("upper", "TEXT"), ("null", None)])
    field_cases("rqi", "rqi", inp, ["schemaVersion"], [("v2", "response-quality.v2"), ("null", None), ("missing", MISSING)])
    field_cases("rqi", "rqi", inp, ["originalRequest"], [("null", None), ("int", 1), ("len_8001", "q" * 8001)])

    rid = out["requestId"]
    add("rqo.base", "rqo", dump(out), expectedRequestId=rid)
    for name, s in [("79", 79), ("79_99", 79.99), ("80", 80), ("80_0", 80.0), ("100", 100), ("100_0", 100.0), ("100_5", 100.5),
                    ("101", 101), ("neg", -1), ("null", None), ("string", "92"), ("bool", True), ("huge", 1e308)]:
        add(f"rqo.approved.score.{name}", "rqo", dump(mutate(out, ["score"], s)), expectedRequestId=rid)
        add(f"rqo.rejected.score.{name}", "rqo", dump(mutate(mutate(out, ["qualityStatus"], "REJECTED"), ["score"], s)),
            expectedRequestId=rid)
    raw = dump(out)
    for name, tok in [("nan", "NaN"), ("inf", "Infinity"), ("neg_inf", "-Infinity"), ("exp_overflow", "1e400")]:
        add(f"rqo.raw.score.{name}", "rqo", raw.replace('"score":92.0', f'"score":{tok}'), expectedRequestId=rid)
    for fld, vals in [
        ("hardFail", [("true", True), ("null", None), ("string", "false"), ("int0", 0)]),
        ("success", [("false", False), ("null", None), ("string", "true")]),
        ("verified", [("false", False), ("null", None), ("int1", 1)]),
        ("minimumScore", [("null", None), ("missing", MISSING), ("79", 79), ("81", 81), ("string", "80"), ("float", 80.0)]),
        ("mandatoryValidatorsPassed", [("true", True), ("false", False), ("null", None), ("string", "true"), ("int1", 1)]),
        ("schemaVersion", [("missing", MISSING), ("null", None), ("v2", "response-quality.v2")]),
        ("requestId", [("missing", MISSING), ("null", None), ("trailing_newline", rid + "\n"), ("other", "req-rq-0002"), ("int", 1),
                       ("short", "r1")]),
        ("evaluatorVersion", [("missing", MISSING), ("null", None), ("int", 1)]),
        ("taskType", [("null", None), ("unknown", "X")]),
        ("qualityStatus", [("null", None), ("lower", "approved"), ("rejected", "REJECTED"), ("validation_error", "VALIDATION_ERROR"),
                           ("pending", "PENDING")]),
        ("violations", [("null", None), ("missing", MISSING), ("hard", [{"code": "X", "severity": "HARD", "reason": "r"}]),
                        ("major", [{"code": "X", "severity": "MAJOR", "reason": "r"}]), ("null_element", [None]),
                        ("missing_reason", [{"code": "X", "severity": "MINOR"}]),
                        ("reason_300", [{"code": "X", "severity": "MINOR", "reason": "r" * 300}]),
                        ("reason_301", [{"code": "X", "severity": "MINOR", "reason": "r" * 301}]),
                        ("unknown_severity", [{"code": "X", "severity": "FATAL", "reason": "r"}]),
                        ("extra_field", [{"code": "X", "severity": "MINOR", "reason": "r", "x": 1}])]),
        ("dimensions", [("null", None), ("missing", MISSING), ("null_element", [None]), ("empty_obj", [{}]),
                        ("null_fields", [{"name": None, "score": None, "maxScore": None, "method": None}]),
                        ("string_score", [{"name": "a", "score": "1", "maxScore": 1, "method": "m"}]),
                        ("extra_field", [{"name": "a", "x": 1}])]),
        ("regenerationHints", [("null_element", [None]), ("int_element", [1]), ("strings", ["a"])]),
        ("latencyMs", [("null", None), ("missing", MISSING), ("string", "3"), ("float", 3.0), ("int32_over", 2147483648), ("neg", -1)]),
        ("modelDigest", [("long", "d" * 500), ("int", 1), ("null", None)]),
        ("unknownTop", [("added", 1)]),
    ]:
        field_cases("rqo", "rqo", out, [fld], vals)
        for c in cases[-len(vals):]:
            c["expectedRequestId"] = rid
    # 승인 불가 상태(REJECTED/VALIDATION_ERROR)에서의 비정상 조합은 구조상 VALID 여야 한다(노출만 거부).
    add("rqo.rejected.hardfail_with_high_score", "rqo", dump(mutate(mutate(out, ["qualityStatus"], "REJECTED"), ["hardFail"], True)),
        expectedRequestId=rid)
    add("rqo.validation_error.success_false", "rqo",
        dump(mutate(mutate(mutate(out, ["qualityStatus"], "VALIDATION_ERROR"), ["success"], False), ["score"], None)), expectedRequestId=rid)
    add("rqo.expected_rid_mismatch", "rqo", dump(out), expectedRequestId="req-rq-9999")
    add("rqo.expected_rid_null", "rqo", dump(out))
    add("rqo.raw.trailing_object", "rqo", raw + "{}", expectedRequestId=rid)
    add("rqo.raw.rejected_score_overflow", "rqo", raw.replace('"score":92.0', '"score":1e400').replace('"APPROVED"', '"REJECTED"'),
        expectedRequestId=rid)
    add("rqo.approved.minimum_null_displayable", "rqo", dump(mutate(out, ["minimumScore"], None)), expectedRequestId=rid)
    add("rqo.approved.mvp_false_80", "rqo", dump(mutate(mutate(out, ["score"], 80), ["mandatoryValidatorsPassed"], False)),
        expectedRequestId=rid)
    add("rqo.approved.minor_violation_ok", "rqo",
        dump(mutate(out, ["violations"], [{"code": "X", "severity": "MINOR", "reason": "r"}])), expectedRequestId=rid)


def _b64e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def gen_signing():
    vec = json.loads((FX / "signing-vectors.v1.json").read_text(encoding="utf-8"))
    keys = vec["keys"]
    now = 1793750410
    sk, ck, bk = keys["AI_SCOPE_SIGNING_KEY"], keys["AI_TRAINING_CONSENT_SIGNING_KEY"], keys["AI_TRAINING_SAMPLE_SIGNING_KEY"]

    def tok(key, payload_json: str, sig_override=None):
        p = _b64e(payload_json.encode())
        sig = _b64e(hmac.new(key.encode(), p.encode(), hashlib.sha256).digest())
        return f"{p}.{sig_override or sig}"

    def cj(obj):
        return json.dumps(obj, separators=(",", ":"), sort_keys=True)

    scope = {"v": 1, "typ": "ai-scope", "sub": "pk_unit_user_000001", "materialIds": [7, 42], "documentIds": ["doc-a1"],
             "iat": now - 10, "exp": now + 110, "rid": "req-unit-000001"}
    consent = {"v": 1, "typ": "training-consent", "sub": "pk_unit_user_000001", "cv": "tc-2026-11", "ct": "2026-11-01T09:00:00Z",
               "scope": ["MODEL_TRAINING"], "rights": {"42": "THIRD_PARTY_UNVERIFIED"}, "dtid": "dt-unit-000001",
               "rid": "evt-unit-000001", "iat": now - 10, "exp": now + 110}
    rid_s, rid_c, sub = scope["rid"], consent["rid"], scope["sub"]

    def scope_case(name, payload, *, rid=rid_s, s=None, key=sk, raw_json=None, token=None):
        t = token if token is not None else tok(key, raw_json if raw_json is not None else cj(payload))
        add(f"sig.scope.{name}", "sig-scope", None, key=sk, token=t, requestId=rid, sub=s, now=now)
        cases[-1].pop("raw")

    def consent_case(name, payload, *, rid=rid_c, s=None, key=ck, raw_json=None, token=None):
        t = token if token is not None else tok(key, raw_json if raw_json is not None else cj(payload))
        add(f"sig.consent.{name}", "sig-consent", None, key=ck, token=t, requestId=rid, sub=s, now=now)
        cases[-1].pop("raw")

    scope_case("ok", scope)
    scope_case("ok_with_sub", scope, s=sub)
    scope_case("sub_mismatch", scope, s="pk_someone_else_0001")
    scope_case("rid_null", scope, rid=None)
    scope_case("rid_mismatch", scope, rid="req-unit-000002")
    scope_case("typ_consent", {**scope, "typ": "training-consent"})
    scope_case("typ_missing", {k: v for k, v in scope.items() if k != "typ"})
    scope_case("v_true", {**scope, "v": True})
    scope_case("v_float", {**scope, "v": 1.0})
    scope_case("v_string", {**scope, "v": "1"})
    scope_case("v_2", {**scope, "v": 2})
    scope_case("iat_string", {**scope, "iat": str(scope["iat"])})
    scope_case("iat_float", {**scope, "iat": float(scope["iat"])})
    scope_case("iat_bool", {**scope, "iat": True})
    scope_case("expired", {**scope, "exp": now - 1})
    scope_case("ttl_601", {**scope, "exp": scope["iat"] + 601})
    scope_case("iat_future_31", {**scope, "iat": now + 31, "exp": now + 100})
    scope_case("iat_gt_exp", {**scope, "iat": now + 5, "exp": now + 1})
    scope_case("material_string", {**scope, "materialIds": ["7"]})
    scope_case("material_float", {**scope, "materialIds": [7.0]})
    scope_case("material_bool", {**scope, "materialIds": [True]})
    scope_case("material_null_el", {**scope, "materialIds": [None]})
    scope_case("material_scalar", {**scope, "materialIds": 7})
    scope_case("material_missing", {k: v for k, v in scope.items() if k != "materialIds"})
    scope_case("document_int", {**scope, "documentIds": [5]})
    scope_case("rid_int", {**scope, "rid": 12345678}, rid="12345678")
    scope_case("payload_array", None, raw_json="[1,2]")
    scope_case("payload_not_json", None, raw_json="not-json")
    scope_case("bad_signature", scope, key="x" * 40)
    scope_case("no_dot", None, token="abc")
    scope_case("two_dots", None, token="a.b.c")
    scope_case("null_token", None, token="")

    consent_case("ok", consent)
    consent_case("ok_with_sub", consent, s=sub)
    consent_case("sub_mismatch", consent, s="pk_someone_else_0001")
    consent_case("rid_expected_null", consent, rid=None)
    consent_case("rid_mismatch", consent, rid="evt-unit-000002")
    consent_case("rid_missing", {k: v for k, v in consent.items() if k != "rid"})
    consent_case("rid_blank", {**consent, "rid": "   "})
    consent_case("rid_empty", {**consent, "rid": ""})
    consent_case("typ_scope", {**consent, "typ": "ai-scope"})
    consent_case("typ_missing", {k: v for k, v in consent.items() if k != "typ"})
    consent_case("typ_scope_and_expired", {**consent, "typ": "ai-scope", "exp": now - 1})
    consent_case("v_true", {**consent, "v": True})
    consent_case("v_2", {**consent, "v": 2})
    consent_case("expired", {**consent, "exp": now - 1})
    consent_case("iat_string", {**consent, "iat": str(consent["iat"])})
    consent_case("sub_missing", {k: v for k, v in consent.items() if k != "sub"})
    consent_case("dtid_missing", {k: v for k, v in consent.items() if k != "dtid"})
    consent_case("bad_signature", consent, key="y" * 40)
    consent_case("payload_not_object", None, raw_json='"str"')

    body = json.dumps({"eventId": "evt-unit-000001", "q": "한글"}, ensure_ascii=False).encode()
    b64 = base64.b64encode(body).decode()

    def sig(ts):
        return "v1=" + hmac.new(bk.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()

    def body_case(name, signature, ts):
        add(f"sig.body.{name}", "sig-body", None, key=bk, bodyBase64=b64, signature=signature, timestamp=ts, now=now)
        cases[-1].pop("raw")

    body_case("ok", sig(now), str(now))
    body_case("ts_padded_space", sig(now), f" {now} ")
    body_case("ts_blank", sig(now), "   ")
    body_case("sig_blank", "  ", str(now))
    body_case("ts_missing", sig(now), None)
    body_case("ts_13_digits", sig(now), "1" * 13)
    body_case("ts_arabic_indic_digits", sig(now), str(now).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")))
    body_case("ts_negative", sig(now), "-1")
    body_case("ts_plus", sig(now), "+" + str(now))
    body_case("ts_skew_301", sig(now - 301), str(now - 301))
    body_case("ts_skew_300", sig(now - 300), str(now - 300))
    body_case("sig_upper_hex", sig(now).upper().replace("V1=", "v1="), str(now))
    body_case("sig_wrong", "v1=" + "0" * 64, str(now))
    body_case("ts_leading_zero", sig(now), "0" + str(now))


def main():
    gen_learning_context()
    gen_training_sample()
    gen_quality()
    gen_signing()
    ids = [c["id"] for c in cases]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise SystemExit(f"duplicate case ids: {sorted(dup)[:5]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"cases={len(cases)} -> {OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
