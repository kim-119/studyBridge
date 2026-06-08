"""
질문 유형 분류기.
초기 버전은 규칙 기반(키워드 매칭)으로 구현한다.
추후 LLM 기반 분류로 교체 가능한 구조로 설계한다.
"""


# PDF/문서 관련 키워드
_PDF_KEYWORDS = [
    "pdf", "자료", "문서", "강의자료", "업로드",
    "이 파일", "이 자료", "첨부", "파일에서", "자료에서",
]

# 최신 정보 관련 키워드
_TAVILY_KEYWORDS = [
    "최신", "요즘", "최근", "현재", "2025", "2026",
    "트렌드", "동향", "뉴스", "업데이트", "지금",
]

# 개념/정의 관련 키워드
_WIKIPEDIA_KEYWORDS = [
    "개념", "정의", "뜻", "무엇", "뭐야", "설명",
    "이란", "이란?", "란?", "란 무엇", "란?", "란 ",
    "알려줘", "가르쳐", "소개",
]


def classify_question(question: str) -> dict:
    """
    사용자 질문을 분석하여 어떤 자료원을 사용할지 결정한다.

    Args:
        question: 사용자 질문 문자열

    Returns:
        {
            "use_pdf": bool,
            "use_tavily": bool,
            "use_wikipedia": bool,
            "reason": str
        }
    """
    q_lower = question.lower()

    use_pdf = any(kw in q_lower for kw in _PDF_KEYWORDS)
    use_tavily = any(kw in q_lower for kw in _TAVILY_KEYWORDS)
    use_wikipedia = any(kw in q_lower for kw in _WIKIPEDIA_KEYWORDS)

    # 아무 조건도 해당하지 않으면 기본으로 Wikipedia 사용
    if not use_pdf and not use_tavily and not use_wikipedia:
        use_wikipedia = True

    # 분류 이유 구성
    reasons = []
    if use_pdf:
        reasons.append("PDF 자료 기반 질문")
    if use_tavily:
        reasons.append("최신 정보 필요")
    if use_wikipedia:
        reasons.append("개념 설명 필요")

    reason = " + ".join(reasons) if reasons else "기본 Wikipedia 검색"

    return {
        "use_pdf": use_pdf,
        "use_tavily": use_tavily,
        "use_wikipedia": use_wikipedia,
        "reason": reason,
    }
