"""
계획 분석 엔진 단위 테스트 (스펙 [10]).

pytest 설치 시: cd ~/capstoneLLM/fastapi && .venv/bin/python -m pytest tests/test_plan_analysis.py -q
미설치 시(plain): cd ~/capstoneLLM/fastapi && .venv/bin/python -m tests.test_plan_analysis
"""
from app.services import plan_analysis_service as P

CODE_TOKEN = "com.example.coroutinepractice.data.dto"
SAMPLE = (f"{CODE_TOKEN} 패키지 추가 로직을 단위 테스트하기 쉽게 "
          "의존성을 분리하고 테스트 케이스 3개를 설계한다.")


def _all_items(text):
    items = []
    for s in P.split_sentences(P.normalize_text(text)):
        items.extend(P.extract_action_items(s))
    return items


# 1. 코드 토큰(패키지명) 보호 — 온점으로 분해되지 않음
def test_package_token_protected():
    items = _all_items(SAMPLE)
    joined = " | ".join(items)
    assert CODE_TOKEN in joined, f"패키지 토큰 보존 실패: {items}"
    # com / example / dto 가 단독 토큰으로 쪼개지지 않음
    for frag in ("com", "example", "dto"):
        assert frag not in [i.strip().lower() for i in items], f"{frag} 단독 분해됨"
    # 토큰 내부에 공백이 끼지 않음
    assert "data. dto" not in joined and "com. example" not in joined


# 2. 파일명 보호
def test_filename_protected():
    for name in ("build.gradle.kts", "MainActivity.kt"):
        prot, mp = P.protect_tokens(f"{name} 파일을 수정한다.")
        assert name in mp.values(), f"{name} 미보호"
        sents = P.split_sentences(f"{name} 파일을 수정한다.")
        assert any(name in s for s in sents), f"{name} 분해됨: {sents}"


# 3. URL / email 보호
def test_url_email_protected():
    text = "https://example.com/path 문서를 보고 test@example.com 으로 보낸다."
    sents = P.split_sentences(text)
    joined = " ".join(sents)
    assert "https://example.com/path" in joined
    assert "test@example.com" in joined
    # 도메인/URL 내부 온점이 문장 경계로 쓰이지 않음(한 문장 안에 둘 다 존재)
    assert any("https://example.com/path" in s and "test@example.com" in s for s in sents)


# 4. 숫자/version 보호
def test_decimal_version_protected():
    text = "버전 v2.0 으로 올리고 임계값 1.5 로 설정한다."
    sents = P.split_sentences(text)
    joined = " ".join(sents)
    assert "v2.0" in joined and "1.5" in joined
    # 1.5 가 "1" "5" 로 분해되지 않음
    assert len(sents) == 1, f"버전/소수점이 문장 경계로 잘림: {sents}"


# 5. PDF 줄바꿈 복원
def test_linebreak_repair():
    norm = P.normalize_text("단위 테스트하\n기 쉽게")
    assert norm == "단위 테스트하기 쉽게", repr(norm)
    # 코드 토큰 줄바꿈 복원
    norm2 = P.normalize_text("com.example.coroutinepractice.data\n.dto 패키지")
    assert "com.example.coroutinepractice.data.dto" in norm2, repr(norm2)


# 6. action item extraction
def test_action_item_extraction():
    items = _all_items(SAMPLE)
    blob = " || ".join(items)
    assert "패키지 추가" in blob, blob
    assert "의존성" in blob and "분리" in blob, blob
    assert "테스트 케이스" in blob and "설계" in blob, blob
    # 명확히 3개의 행동 단위로 분해
    assert len(items) == 3, f"기대 3개, 실제 {len(items)}: {items}"


# 7. 일반(추상) 항목 reject
def test_generic_items_rejected():
    for bad in ("핵심 내용 정리", "세부 내용 학습", "자료를 이해한다", "열심히 복습한다"):
        assert P._is_generic_item(bad), f"일반 항목 미차단: {bad}"
    # validator: 일반 항목만 있으면 reject
    only_generic = [{"text": "핵심 내용 정리", "sourceText": "원문"}]
    assert P.validate_items(only_generic)["passed"] is False
    # 코드 토큰 파편 단독 항목 reject
    broken = [{"text": "dto", "sourceText": "원문"}]
    assert P.validate_items(broken)["passed"] is False


# 8. 추천: completed/hidden 제외, 미완료 기반 생성
def test_recommendation_filters():
    items = [
        {"text": "com.example.coroutinepractice.data.dto 패키지 추가", "completed": True,
         "hidden": False, "sourceText": "x", "sourceType": "PDF", "pageNumber": 1,
         "chunkIndex": 0, "sentenceIndex": 0},
        {"text": "의존성을 분리한다", "completed": False, "hidden": True, "sourceText": "x",
         "sourceType": "PDF", "pageNumber": 1, "chunkIndex": 0, "sentenceIndex": 1},
        {"text": "테스트 케이스 3개를 설계한다", "completed": False, "hidden": False,
         "sourceText": "x", "sourceType": "PDF", "pageNumber": 1, "chunkIndex": 0,
         "sentenceIndex": 2},
    ]
    recs = P.build_recommendations(items)
    assert recs, "추천이 비어 있음"
    blob = " ".join(recs)
    # completed/hidden 항목은 추천에서 제외
    assert "패키지 추가" not in blob
    assert "의존성을 분리" not in blob
    # 미완료 항목 기반 추천
    assert "테스트 케이스 3개를 설계" in blob
    # 일반 조언 금지
    for bad in ("열심히", "꾸준히", "자료를 읽", "중요 개념을 다시"):
        assert bad not in blob


# 9. (추가) 전체 analyze_plan 계약 — 빈 텍스트/정상
def test_analyze_contract():
    empty = P.analyze_plan({"sourceTexts": [], "_no_llm": True})
    assert empty.get("code") == "PLAN_ANALYSIS_TEXT_EMPTY"

    r = P.analyze_plan({
        "requestId": "t1", "materialId": 601, "_no_llm": True,
        "sourceTexts": [{"sourceType": "PDF", "pageNumber": 1, "text": SAMPLE}],
    })
    assert "items" in r and len(r["items"]) >= 3, r
    assert r["meta"]["mode"] == "DETERMINISTIC_ONLY"
    assert r["meta"]["chunkCount"] >= 1
    assert r["meta"]["sentenceCount"] >= 1
    assert r["meta"]["itemCount"] == len(r["items"])
    assert any(CODE_TOKEN in it["text"] for it in r["items"])
    # 모든 item 에 sourceText 존재
    assert all(it["sourceText"] for it in r["items"])


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] {t.__name__}: {e}")
    print(f"\n결과: {passed}/{len(tests)} PASS")
    raise SystemExit(0 if passed == len(tests) else 1)
