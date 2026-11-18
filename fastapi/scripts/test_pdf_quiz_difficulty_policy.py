"""
PDF 퀴즈 난이도 정책 검증 (스펙 [6]).

확인 항목:
 1. requestedDifficulty=normal → appliedDifficulty=normal
 2. requestedDifficulty=hard   → appliedDifficulty=hard
 3. "세부 핵심 내용" 포함 문제 reject
 4. "..." 포함 문제 reject
 5. LLM 실패를 강제(_no_llm)해도 deterministic PDF generator가 요청 난이도/개수를 채움
 6. PDF 텍스트가 없을 때만 PDF_TEXT_INSUFFICIENT
 7. 난이도 mismatch를 이유로 basic fallback이 발생하지 않음
 8. 응답 meta에 BASIC / DEFAULT / difficulty downgraded 값이 없음

실행: cd ~/capstoneLLM/fastapi && .venv/bin/python -m scripts.test_pdf_quiz_difficulty_policy
"""
import json

from app.services.pdf_quiz_service import (
    generate_pdf_quiz,
    validate_quiz_difficulty,
    _BANNED_QUESTION_SUBSTR,
    SOURCE_MODE,
)

PDF_TEXT = (
    "안드로이드 네트워크 통신은 Retrofit과 OkHttp를 사용해 구현한다. "
    "Retrofit은 REST API 호출을 인터페이스로 선언하고 JSON 직렬화를 자동으로 처리한다. "
    "ViewModel은 UI 상태를 보관하고 Repository를 통해 데이터 소스에 접근한다. "
    "MVVM 아키텍처에서 Repository는 네트워크와 로컬 캐시를 추상화해 ViewModel의 책임을 줄인다. "
    "데이터 직렬화와 예외 처리, 통신 계층 분리는 유지보수와 테스트 가능성을 높이는 핵심 설계 원칙이다. "
    "OkHttp 인터셉터는 공통 헤더와 로깅을 한 곳에서 처리하도록 흐름을 구성한다."
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def check(name, cond, extra=""):
    results.append(cond)
    print(f"[{PASS if cond else FAIL}] {name}" + (f"  ({extra})" if extra else ""))


def base_req(diff, count):
    return {
        "material_id": "mat-1",
        "material_title": "안드로이드 네트워크 통신",
        "difficulty": diff,
        "count": count,
        "document_text": PDF_TEXT,
        "keywords": ["Retrofit", "OkHttp", "ViewModel", "Repository", "MVVM"],
        "_no_llm": True,  # LLM 실패 강제 → deterministic 경로 검증
    }


def no_bad_meta(r):
    blob = json.dumps(r, ensure_ascii=False).upper()
    return not any(tok in blob for tok in ("DIFFICULTY DOWNGRADED", "DOWNGRADE")) and \
        r.get("difficulty_applied") not in ("BASIC", "DEFAULT") and \
        (r.get("source") or "").upper() not in ("BASIC", "DEFAULT")


# 1 & 5 & 7 & 8: normal, deterministic, count 충족
r = generate_pdf_quiz(base_req("normal", 6))
check("normal: success", r.get("success") is True)
check("normal: appliedDifficulty == normal (no downgrade)", r.get("difficulty_applied") == "normal",
      f"applied={r.get('difficulty_applied')}")
check("normal: generatedCount == requestedCount(6)", len(r.get("questions", [])) == 6,
      f"got={len(r.get('questions', []))}")
check("normal: source == DETERMINISTIC_PDF (no LLM)", r.get("source") == "DETERMINISTIC_PDF",
      f"source={r.get('source')}")
check("normal: fallback_used == False", r.get("fallback_used") is False)
check("normal: validated", (r.get("validation") or {}).get("passed") is True)
check("normal: no BASIC/DEFAULT/downgraded meta", no_bad_meta(r))

# 2: hard
r = generate_pdf_quiz(base_req("hard", 5))
check("hard: success", r.get("success") is True)
check("hard: appliedDifficulty == hard", r.get("difficulty_applied") == "hard",
      f"applied={r.get('difficulty_applied')}")
check("hard: generatedCount == 5", len(r.get("questions", [])) == 5)
check("hard: no BASIC/DEFAULT/downgraded meta", no_bad_meta(r))

# 3: "세부 핵심 내용" reject
bad = {
    "source_mode": SOURCE_MODE, "document_type": "GENERAL",
    "provider_policy": {"qwen_ratio": 0.8, "openai_ratio": 0.2, "wikipedia_ratio": 0.0},
    "questions": [{
        "question": "세부 핵심 내용에 대한 설명으로 가장 적절한 것은?",
        "choices": ["A", "B", "C", "D"], "correct_answer": "A",
        "explanation": "x", "source_trace": {"source_type": "PDF_BASED", "concepts": ["x"]},
    }],
}
v = validate_quiz_difficulty(bad, "normal")
check('validator rejects "세부 핵심 내용"', v["passed"] is False, v["reason"])

# 4: "..." reject
bad2 = json.loads(json.dumps(bad))
bad2["questions"][0]["question"] = "Retrofit의 역할은 ... 무엇인가?"
v = validate_quiz_difficulty(bad2, "normal")
check('validator rejects "..."', v["passed"] is False, v["reason"])

# banned 토큰 전부 reject되는지
for tok in _BANNED_QUESTION_SUBSTR:
    b = json.loads(json.dumps(bad))
    b["questions"][0]["question"] = f"Retrofit {tok} 설명"
    v = validate_quiz_difficulty(b, "normal")
    check(f'banned 토큰 reject: "{tok}"', v["passed"] is False)

# 6: PDF 텍스트 없음 → PDF_TEXT_INSUFFICIENT (속이지 않고 명확 실패)
r = generate_pdf_quiz({"material_id": "m", "difficulty": "normal", "count": 5,
                       "document_text": "", "_no_llm": True})
check("empty PDF → PDF_TEXT_INSUFFICIENT", r.get("error_code") == "PDF_TEXT_INSUFFICIENT",
      f"code={r.get('error_code')}")
check("empty PDF → success False", r.get("success") is False)

# 6b: 너무 짧은 PDF → PDF_TEXT_INSUFFICIENT
r = generate_pdf_quiz({"material_id": "m", "difficulty": "hard", "count": 5,
                       "document_text": "짧은 텍스트.", "_no_llm": True})
check("짧은 PDF → PDF_TEXT_INSUFFICIENT", r.get("error_code") == "PDF_TEXT_INSUFFICIENT",
      f"code={r.get('error_code')}")

print("\n" + ("=" * 50))
ok = sum(1 for x in results if x)
print(f"결과: {ok}/{len(results)} PASS")
raise SystemExit(0 if ok == len(results) else 1)
