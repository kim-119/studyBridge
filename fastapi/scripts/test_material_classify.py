"""
업로드 자료 유형 자동 판별 rule-based 검증 (LLM 없이 동작 보장).
실행: cd fastapi && python scripts/test_material_classify.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# LLM 호출을 막아 순수 rule-based 경로만 검증 (Ollama/OpenAI 미기동 환경 대비)
from app.api import material_classify_routes as mc

mc._qwen_classify = lambda req: None
mc._openai_refine = lambda req, candidate: None

from app.api.material_classify_routes import (
    ClassifyRequest, MaterialMetadata, _classify_sync, validate_material_classification,
)


def run(name, req, expected_type, *, expect_mismatch=None, expect_msg_contains=None):
    res = _classify_sync(req)
    ok = res["recommended_type"] == expected_type
    assert validate_material_classification(res), f"[{name}] 검증 실패: {res}"
    if expect_mismatch is not None:
        ok = ok and (res["is_mismatch"] == expect_mismatch)
    if expect_msg_contains is not None:
        ok = ok and (expect_msg_contains in res["user_message"])
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: recommended={res['recommended_type']} "
          f"selected={res['selected_type']} mismatch={res['is_mismatch']} "
          f"conf={res['confidence']}")
    print(f"        user_message: {res['user_message']}")
    print(f"        capability_hint: {res['capability_hint']}")
    if not ok:
        print(f"        FULL: {res}")
    return ok


def main():
    results = []

    # H-1. 공부 플래너 PDF (사용자는 STUDY_PDF 선택) → PLANNER, mismatch
    planner = ClassifyRequest(
        file_name="7.pdf", mime_type="application/pdf", selected_type="STUDY_PDF",
        extracted_text="날짜 2026-06-13 과목명 수학 학습 유형 개념 우선순위 상 "
                       "목표 학습 시간 3시간 시간표 09:00-10:00 세부 학습/메모 미적분 복습 체크박스",
        page_count=1, preview_text="공부 플래너", metadata=MaterialMetadata(title="6월 공부 플래너"),
    )
    results.append(run("H-1 공부 플래너 PDF", planner, "PLANNER",
                       expect_mismatch=True, expect_msg_contains="알맞은 곳에 넣으세요"))

    # H-2. 강의자료 PDF → STUDY_PDF
    lecture = ClassifyRequest(
        file_name="lecture_ch3.pdf", mime_type="application/pdf", selected_type="STUDY_PDF",
        extracted_text="3장 목차 개념 설명 아키텍처 API 사용법 코드 예제 이론 강의자료 슬라이드",
        page_count=42, metadata=MaterialMetadata(title="운영체제 강의자료"),
    )
    results.append(run("H-2 강의자료 PDF", lecture, "STUDY_PDF", expect_mismatch=False))

    # H-3. 오답노트 PDF → WRONG_NOTE
    wrong = ClassifyRequest(
        file_name="wrong_note.pdf", mime_type="application/pdf", selected_type="STUDY_PDF",
        extracted_text="오답노트 문제 번호 3 틀린 문제 내가 고른 답 2번 정답 4번 해설 다시 풀기 유사문제 복습",
        page_count=5, metadata=MaterialMetadata(title="수학 오답노트"),
    )
    results.append(run("H-3 오답노트 PDF", wrong, "WRONG_NOTE",
                       expect_mismatch=True, expect_msg_contains="오답노트"))

    # H-4. 학습일지 문서 → STUDY_LOG
    log = ClassifyRequest(
        file_name="diary.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        selected_type="STUDY_LOG",
        extracted_text="오늘 공부한 내용 회고 배운 점 느낀 점 다음 목표 학습 소감 학습 시간 기록 2시간",
        page_count=1, metadata=MaterialMetadata(title="6월 학습일지"),
    )
    results.append(run("H-4 학습일지 문서", log, "STUDY_LOG", expect_mismatch=False))

    # C. 텍스트 없는 플래너 PDF (extracted 비어있고 파일명/OCR 단서만) → PLANNER (not UNKNOWN/STUDY_PDF)
    empty_planner = ClassifyRequest(
        file_name="공부플래너_양식.pdf", mime_type="application/pdf", selected_type="STUDY_PDF",
        extracted_text="", ocr_text="시간표 목표 학습 시간 우선순위", page_count=1,
        metadata=MaterialMetadata(title="플래너"),
    )
    results.append(run("C 텍스트없는 플래너 PDF", empty_planner, "PLANNER", expect_mismatch=True))

    # UNKNOWN. 텍스트/OCR/단서 모두 없음
    unknown = ClassifyRequest(
        file_name="scan001.pdf", mime_type="application/pdf", selected_type="STUDY_PDF",
        extracted_text="", ocr_text="", page_count=1, metadata=MaterialMetadata(title=""),
    )
    results.append(run("UNKNOWN 단서없음", unknown, "UNKNOWN",
                       expect_msg_contains="확실히 판단하기 어렵습니다"))

    print("\n==== SUMMARY ====")
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
