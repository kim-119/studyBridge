"""
PDF 메타데이터 노이즈 필터 테스트 (스펙 [6]).

목표: 날짜/연도/교수명/강의자료 표지·footer·header·슬라이드 번호가
학습 주제/할 일/복습질문/산출물로 승격되지 않는지 검증한다.
"""
import json

from app.utils.pdf_noise_filter import (
    clean_topic,
    conceptual_fallback_items,
    detect_repeated_lines,
    filter_keywords,
    find_noise_violations,
    is_metadata_noise,
    is_valid_topic,
    sanitize_text_fields,
)

# 실제 강의자료에서 보고된 메타데이터(매 페이지 반복되는 표지/날짜/교수명)
LECTURE_PAGES = [
    "Modern Android Development 2026\n2026.04 조수연\n08. View Model\nActivity의 생명주기를 설명한다.",
    "Modern Android Development 2026\n2026.04 조수연\n09. Fragment\nFragment의 역할을 설명한다.",
    "Modern Android Development 2026\n2026.04 조수연\n10. Repository",
]


def _blob(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ── 필수 테스트 1: 반복 표지/날짜+이름/슬라이드 번호 처리 ──────────────────────
def test_metadata_lines_not_promoted_to_topics():
    repeated = detect_repeated_lines(LECTURE_PAGES)
    assert any("Modern Android Development" in r for r in repeated)

    # "2026.04 조수연"은 topic/task 로 쓰일 수 없다
    assert is_metadata_noise("2026.04 조수연") is True
    # 반복 course title 도 metadata
    assert is_metadata_noise("Modern Android Development 2026", repeated=repeated) is True
    # 슬라이드 번호 접두어는 떼고 기술 용어는 유지
    assert clean_topic("08. View Model") == "View Model"
    assert is_valid_topic("08. View Model") is True


# ── 필수 테스트 2: 내용 부족 시 개념형 fallback ───────────────────────────────
def test_conceptual_fallback_for_android():
    items = conceptual_fallback_items("안드로이드 이해")
    joined = " ".join(items)
    assert "Activity" in joined
    assert "Fragment" in joined
    assert "ViewModel" in joined
    # 메타데이터(날짜/연도/교수명)가 fallback 에 들어가지 않는다
    assert "2026" not in joined
    assert "조수연" not in joined


def test_conceptual_fallback_generic_topic():
    items = conceptual_fallback_items("자료구조")
    assert items, "fallback 이 비어 있으면 안 됨"
    assert all("2026" not in it and "조수연" not in it for it in items)
    assert any("자료구조" in it for it in items)


# ── 필수 테스트 3: 날짜+이름 제거, 기술 용어 보존 ─────────────────────────────
def test_strip_metadata_keep_concept():
    assert clean_topic("2026.04 조수연 Activity 생명주기") == "Activity 생명주기"
    # 기술 용어(성씨로 시작하는 단어 포함)는 절대 손상되지 않는다
    for term in ("정규화", "조건문", "함수형 프로그래밍", "ViewModel이 필요한 이유"):
        assert clean_topic(term) == term
        assert is_valid_topic(term) is True


# ── 필수 테스트 4: 결과 JSON 전체에 메타데이터 phrase 부재 ────────────────────
def test_sanitized_roadmap_has_no_metadata():
    repeated = detect_repeated_lines(LECTURE_PAGES)
    raw_roadmap = {
        "title": "Modern Android Development 2026",
        "weeks": [
            {
                "week": 1,
                "title": "2026.04 조수연 예외 처리 전략",
                "goal": "2026.04 조수연에서 발생 가능한 예외와 장애 상황을 이해한다.",
                "tasks": [
                    "2026.04 조수연 비교 표 작성",
                    "Modern Android Development 2026 책임 분리 설계",
                    "Activity 생명주기 정리",
                ],
                "keyConcepts": ["조수연", "2026", "ViewModel"],
            }
        ],
    }
    cleaned = sanitize_text_fields(raw_roadmap, repeated=repeated, title="안드로이드 이해")
    blob = _blob(cleaned)

    for banned in ("조수연", "2026.04", "Modern Android Development 2026"):
        assert banned not in blob, f"금지 문구 잔존: {banned}"

    # 기술 개념은 살아남는다
    assert "Activity" in blob or "ViewModel" in blob
    # topic/task 류 필드에 노이즈 위반이 남지 않는다
    assert find_noise_violations(cleaned, repeated=repeated) == []


def test_empty_tasks_filled_with_concepts():
    # 전부 메타데이터인 tasks 가 정제로 비면 개념형 fallback 으로 채워진다
    obj = {"tasks": ["2026", "조수연", "2026.04"]}
    cleaned = sanitize_text_fields(obj, repeated=["조수연"], title="안드로이드 이해")
    assert cleaned["tasks"], "tasks 가 비면 안 됨(개념형 fallback 필요)"
    assert all("2026" not in t and "조수연" not in t for t in cleaned["tasks"])


def test_filter_keywords_removes_metadata_keeps_tech():
    raw = ["2026", "2026.04", "조수연", "교수명", "Activity", "ViewModel", "정규화"]
    kept = filter_keywords(raw, repeated=["조수연"])
    assert "Activity" in kept
    assert "ViewModel" in kept
    assert "정규화" in kept
    assert "조수연" not in kept
    assert "2026" not in kept
    assert "교수명" not in kept
