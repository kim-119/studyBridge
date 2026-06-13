"""
신규 작업 검증 (ai07 프롬프트 A~L):
  - 핵심/세부 핵심 내용 ONE_CARD_TEXT_BLOCK (한 카드 문자열)
  - 퀴즈 문항 수 5~20 보정
  - easy/normal/hard 20문제 batch 안정 생성 + 중복 제거
  - sanitize_for_site_display 마크다운 제거(번호 목록 보존)

실행: cd fastapi && .venv/bin/python scripts/test_quiz_count_and_sanitize.py
LLM/Wikipedia 호출 없이 deterministic 경로만으로 동작을 보장한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import pdf_quiz_service as pq

# LLM/Wikipedia 차단 → deterministic batch/fallback 만으로 검증
pq._llm_generate = lambda *a, **k: []
pq.fetch_wikipedia_context = lambda concepts: ("", False)

from app.services.pdf_quiz_service import generate_pdf_quiz, normalize_quiz_count
from app.utils.sanitize import sanitize_for_site_display

PDF_TEXT = (
    "MVVM 아키텍처에서 ViewModel은 UI 상태를 보관하고 View와 분리된다. "
    "Repository는 데이터 소스를 추상화하여 네트워크와 로컬 캐시를 관리한다. "
    "Retrofit2는 REST API 호출을 담당하는 라이브러리다. "
    "LiveData는 관찰 가능한 데이터 홀더이며 생명주기를 인식한다. "
    "Coroutine은 비동기 작업을 구조적으로 처리한다. "
    "ViewModel과 Repository를 분리하면 책임 분리와 테스트 가능성이 높아진다."
)

results = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    results.append(bool(cond))
    return cond


def gen(diff_label, count):
    return generate_pdf_quiz({
        "material_id": 1, "material_title": "MVVM", "difficulty": diff_label,
        "count": count, "document_text": PDF_TEXT,
        "core_content_text": "ViewModel과 Repository의 책임 분리",
        "keywords": ["ViewModel", "Repository", "Retrofit2", "LiveData", "Coroutine"],
    })


print("==== E. 문항 수 보정 ====")
check("count 3 → applied 5", gen("쉬움", 3).get("applied_count") == 5)
check("count 10 → applied 10", gen("쉬움", 10).get("applied_count") == 10)
check("count 25 → applied 20", gen("쉬움", 25).get("applied_count") == 20)
check("count 비숫자 → applied 10", normalize_quiz_count("abc") == (10, 10))
check("count 3 requested_count=3 보존", gen("쉬움", 3).get("requested_count") == 3)
r3 = gen("쉬움", 3)
check("min_count=5 / max_count=20 응답 포함",
      r3.get("min_count") == 5 and r3.get("max_count") == 20)


def check_20(diff_label, diff_key):
    res = gen(diff_label, 20)
    qs = res.get("questions", [])
    ok_len = len(qs) == 20
    ok_succ = res.get("success") is True
    ok_valid = res.get("validation", {}).get("passed") is True
    # 중복 제거 확인
    keys = [pq._norm_q(q["question"]) for q in qs]
    ok_dedup = len(set(keys)) == len(keys)
    # 마크다운 없음
    blob = " ".join(q["question"] + " " + " ".join(q["choices"]) + " " + q["explanation"] for q in qs)
    ok_md = not any(m in blob for m in ("**", "###", "```"))
    check(f"{diff_key} 20문제 생성(length=20)", ok_len, f"len={len(qs)}")
    check(f"{diff_key} 20문제 success/validation passed", ok_succ and ok_valid,
          f"reason={res.get('validation', {}).get('reason')}")
    check(f"{diff_key} 20문제 중복 없음", ok_dedup)
    check(f"{diff_key} 20문제 마크다운 없음", ok_md)
    return res


print("\n==== H/I. easy/normal/hard 20문제 안정 생성 ====")
check_20("쉬움", "easy")
check_20("보통", "normal")
res_hard = check_20("어려움", "hard")
check("hard 20문제 QUIZ_VALIDATE_FAILED 로 끝나지 않음",
      res_hard.get("success") is True and res_hard.get("error_code") is None)
check("hard 단순 '무엇인가요?' 금지(시나리오형)",
      all("무엇인가요?" not in q["question"] or len(q["question"]) >= 80 for q in res_hard["questions"]))


print("\n==== K. PDF context 없음 → 실패 응답 + count 포함 ====")
res_empty = generate_pdf_quiz({"material_title": "제목만", "difficulty": "hard", "count": 25})
check("PDF 없으면 PDF_CONTEXT_REQUIRED", res_empty.get("error_code") == "PDF_CONTEXT_REQUIRED")
check("실패 응답에도 applied_count 포함", res_empty.get("applied_count") == 20)


print("\n==== C. sanitize_for_site_display ====")
md_in = "### **1. UI 구성**\n\n* **목적**: 검색 기능을 추가합니다.\n```kotlin\nval x = 1\n```\n<b>강조</b>"
out = sanitize_for_site_display(md_in)
print("        OUT:", repr(out))
check("### 헤더 제거", "###" not in out and "#" not in out.split("\n")[0])
check("** 굵게 제거", "**" not in out)
check("코드펜스 ``` 제거", "```" not in out)
check("HTML 태그 제거", "<b>" not in out and "</b>" not in out)
check("번호 목록(1.) 보존", out.strip().startswith("1. UI 구성"))
check("코드 내부 텍스트 보존", "val x = 1" in out)
check("불릿 항목 내용 보존", "목적: 검색 기능을 추가합니다." in out)


print("\n==== A/B. 핵심/세부 핵심 내용 ONE_CARD_TEXT_BLOCK ====")
from app.services.material_summary_builder import build_structured_summary
import app.services.material_summary_builder as msb
# LLM 차단 → deterministic 보강 경로
msb._llm_attempt = lambda *a, **k: (None, "ollama_qwen")
msb.AI_ENABLE_GPT_FALLBACK = False

DOC = (PDF_TEXT + " ") * 6  # 충분한 분량 확보
summary = build_structured_summary("MVVM 자료", DOC)
cct = summary.get("core_content_text")
dct = summary.get("detailed_content_text")
check("core_content_text 가 문자열 하나", isinstance(cct, str) and "\n" in cct)
check("detailed_content_text 가 문자열 하나", isinstance(dct, str) and "\n" in dct)
check("rendering_policy == ONE_CARD_TEXT_BLOCK",
      summary.get("rendering_policy") == "ONE_CARD_TEXT_BLOCK")
check("core_contents 배열이 비어 카드 여러 개 유도 안 함",
      summary.get("core_contents") == [] and summary.get("detailed_core_contents") == [])
check("core_content_line_count == 줄 수",
      summary.get("core_content_line_count") == len(cct.split("\n")))
check("detailed_content_line_count == 줄 수",
      summary.get("detailed_content_line_count") == len(dct.split("\n")))
check("핵심/세부 텍스트에 마크다운 없음",
      not any(m in (cct + dct) for m in ("**", "###", "```")))
print(f"        core_lines={summary.get('core_content_line_count')} "
      f"detail_lines={summary.get('detailed_content_line_count')}")


print("\n==== SUMMARY ====")
passed = sum(1 for r in results if r)
print(f"{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
