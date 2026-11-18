"""
PDF 기반 퀴즈 생성 검증 (deterministic 경로 — LLM 없이 동작 보장).
실행: cd fastapi && python scripts/test_pdf_quiz.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import pdf_quiz_service as pq

# LLM/Wikipedia 호출 차단 → 순수 deterministic + provider_policy 검증
pq._llm_generate = lambda *a, **k: []
pq.fetch_wikipedia_context = lambda concepts: ("", False)

from app.services.pdf_quiz_service import generate_pdf_quiz, validate_quiz_difficulty

PDF_TEXT = (
    "MVVM 아키텍처에서 ViewModel은 UI 상태를 보관하고 View와 분리된다. "
    "Repository는 데이터 소스를 추상화하여 네트워크와 로컬 캐시를 관리한다. "
    "Retrofit2는 REST API 호출을 담당하는 라이브러리다. "
    "ViewModel과 Repository를 분리하면 책임 분리와 테스트 가능성이 높아진다."
)

SYLLABUS_TEXT = (
    "강의계획서\n"
    "교과목명: 모바일 프로그래밍\n"
    "담당교수: 홍길동\n"
    "교수 연구실: 공학관 401호\n"
    "이메일: hong@univ.ac.kr\n"
    "상담시간: 화 14:00-16:00\n"
    "평가비율: 중간 30% 기말 40% 출석 10% 과제 20%\n"
    "주차별 강의계획\n"
    "1주차: 강의 개요와 안드로이드 개발 환경\n"
    "2주차: Kotlin 기초 문법\n"
    "3주차: 액티비티와 생명주기\n"
    "4주차: 레이아웃과 뷰\n"
    "10주차: MVVM 아키텍처\n"
    "12주차: Retrofit2 네트워크 통신\n"
    "15주차: 기말 프로젝트 발표\n"
)

results = []


def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {extra}")
    results.append(bool(cond))
    return cond


def show(res):
    print(f"        document_type={res.get('document_type')} source_mode={res.get('source_mode')} "
          f"provider_policy={res.get('provider_policy')}")
    for q in res.get("questions", [])[:1]:
        print(f"        Q: {q['question']}")
        print(f"        choices={q['choices']}")
        print(f"        source_trace={q['source_trace']}")


def run_general(diff_label, diff_key):
    res = generate_pdf_quiz({
        "material_id": 57, "material_title": "11.MVVM-2", "difficulty": diff_label,
        "count": 3, "document_text": PDF_TEXT,
        "core_content_text": "ViewModel과 Repository의 책임 분리", "keywords": ["ViewModel", "Repository", "Retrofit2"],
    })
    show(res)
    pol = res.get("provider_policy", {})
    ok = res.get("success") and res["source_mode"] == "PDF_BASED"
    ok = ok and all(q["source_trace"]["source_type"] == "PDF_BASED" for q in res["questions"])
    ok = ok and res["validation"]["passed"]
    check(f"general {diff_key} 생성/PDF_BASED/validation", ok, f"reason={res.get('validation', {}).get('reason')}")
    return res, pol


print("==== 일반 강의자료 PDF ====")
_, p_easy = run_general("쉬움", "easy")
check("easy provider Qwen3B 100%", p_easy.get("qwen_ratio") == 1.0 and p_easy.get("openai_ratio") == 0.0)

_, p_norm = run_general("보통", "normal")
check("normal provider Qwen 0.8 + OpenAI 0.2",
      p_norm.get("qwen_ratio") == 0.8 and p_norm.get("openai_ratio") == 0.2)

res_hard, p_hard = run_general("어려움", "hard")
check("hard provider Qwen 0.5 + (OpenAI+Wiki)=0.5",
      p_hard.get("qwen_ratio") == 0.5 and round(p_hard.get("openai_ratio", 0) + p_hard.get("wikipedia_ratio", 0), 3) == 0.5)
check("hard Wikipedia 실패 fallback wikipedia_used=false", p_hard.get("wikipedia_used") is False)
check("hard 단순 '무엇인가요?' 아님(시나리오형)",
      all("무엇인가요?" not in q["question"] or len(q["question"]) >= 80 for q in res_hard["questions"]))

print("\n==== 로드맵 context 없이도 생성 가능 / ROADMAP_ONLY 불필요 ====")
res_noroadmap = generate_pdf_quiz({
    "material_title": "12.Retrofit", "difficulty": "easy", "count": 2,
    "summary": "Retrofit2는 REST API 호출 라이브러리이며 인터페이스 기반으로 동작한다.",
})
check("로드맵 context 없이 PDF 기반 생성 성공", res_noroadmap.get("success") and res_noroadmap["source_mode"] == "PDF_BASED")

print("\n==== PDF context 없음 → PDF_CONTEXT_REQUIRED ====")
res_empty = generate_pdf_quiz({"material_title": "제목만 있음", "difficulty": "hard", "count": 3})
check("title만 있으면 PDF_CONTEXT_REQUIRED", res_empty.get("error_code") == "PDF_CONTEXT_REQUIRED" and res_empty.get("success") is False)

print("\n==== 강의계획서(SYLLABUS) ====")
for diff_label, diff_key in [("쉬움", "easy"), ("보통", "normal"), ("어려움", "hard")]:
    res = generate_pdf_quiz({
        "material_id": 99, "material_title": "모바일프로그래밍 강의계획서",
        "difficulty": diff_label, "count": 3, "document_text": SYLLABUS_TEXT,
    })
    show(res)
    is_syll = res.get("document_type") in ("SYLLABUS", "LECTURE_PLAN")
    check(f"syllabus {diff_key} document_type=SYLLABUS", is_syll, f"({res.get('document_type')})")
    pol = res.get("provider_policy", {})
    check(f"syllabus {diff_key} Qwen3B 100%",
          pol.get("qwen_ratio") == 1.0 and pol.get("openai_ratio") == 0.0 and pol.get("wikipedia_ratio") == 0.0)
    check(f"syllabus {diff_key} source_trace=PDF_BASED_SYLLABUS",
          all(q["source_trace"]["source_type"] == "PDF_BASED_SYLLABUS" for q in res["questions"]))
    # 교수/행정정보 암기형 문제 없어야 함
    admin_free = not any(pq.is_admin_question(q["question"]) for q in res["questions"])
    check(f"syllabus {diff_key} 교수/행정정보 문제 없음", admin_free)
    check(f"syllabus {diff_key} validation passed", res["validation"]["passed"],
          f"reason={res['validation']['reason']}")
    # 주차별 내용 기반 문제가 생성되는지(주차 표기 포함)
    has_week = any("주차" in q["question"] or "흐름" in q["question"] for q in res["questions"])
    check(f"syllabus {diff_key} 주차/흐름 기반 문제 생성", has_week)

print("\n==== 강의계획서 주차별 내용 없음 → SYLLABUS_WEEKLY_CONTENT_REQUIRED ====")
res_nw = generate_pdf_quiz({
    "material_title": "강의계획서", "difficulty": "easy", "count": 3,
    "document_text": "강의계획서\n담당교수: 홍길동\n교수 연구실: 401호\n이메일: a@b.com\n평가비율: 중간 30%",
})
check("주차별 내용 없는 강의계획서 → SYLLABUS_WEEKLY_CONTENT_REQUIRED",
      res_nw.get("error_code") == "SYLLABUS_WEEKLY_CONTENT_REQUIRED")

print("\n==== SUMMARY ====")
passed = sum(1 for r in results if r)
print(f"{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
