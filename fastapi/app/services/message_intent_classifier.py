"""
메시지 의도 분류기.

사용자가 선택한 지식수준을 "학습 개념 질문"에는 그대로 적용하고,
단순 인사/감사/잡담에는 과도한 전공 설명을 붙이지 않도록 판별한다.

규칙 기반 + 선택적 GPT 보조 분류 구조.
GPT 호출은 비용/속도 문제로 기본 비활성화.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ── 일상 대화 패턴 (정규식) ────────────────────────────────────────────────
_CASUAL_PATTERNS = re.compile(
    r"^("
    r"안녕|하이|헬로|반가워|반갑습니다|반갑네요"
    r"|고마워|감사|감사합니다|고맙습니다|수고"
    r"|잘자|잘 자|굿나잇|잘가|바이|bye"
    r"|ㅇㅋ|오케이|오케|알겠어|알겠습니다|네|응|그래|좋아"
    r"|ㅋㅋ+|ㅎㅎ+|ㅠㅠ+|ㄷㄷ+|ㅂㅂ|ㅎ+|ㄴ+"
    r"|테스트|test|ping|hello|hi"
    r"|너\s*(누구야?|뭐야?|이름\s*뭐야?)"
    r"|지금\s*(돼|돼?|가능해?)"
    r"|뭐\s*(해|하고\s*있어)\s*\??"
    r"|심심해|졸려|배고파|피곤해"
    r")\s*[?!~ㅋㅎ]*$",
    re.IGNORECASE,
)

# ── 불만 / 버그 리포트 패턴 (최우선 매칭) ──────────────────────────────────
_COMPLAINT_PATTERNS = re.compile(
    r"(이상해|안돼|안 돼|오류|버그|에러|고장|뭐라는|짜증|어이없|화나|답답|불편|동작안|실행안)",
    re.IGNORECASE,
)

# 학습/개념 관련 키워드 (단 하나라도 있으면 learning_question)
_LEARNING_KEYWORDS = re.compile(
    r"(뭐야|뭐죠|무엇|무엇인가|설명|이란|란\s*무엇|개념|정의|원리|구조|차이|비교|"
    r"작동|동작|방법|어떻게|왜|이유|장단점|예시|특징|역할|사용|적용|구현|코드|"
    r"알고리즘|자료구조|데이터베이스|운영체제|네트워크|스프링|spring|java|python|"
    r"딥러닝|머신러닝|인공지능|ai|ml|수학|물리|화학|생물|역사|경제|철학|법|"
    r"함수|클래스|객체|상속|다형성|인터페이스|추상|패턴|아키텍처|"
    r"gradient|matrix|vector|tensor|미분|적분|행렬|벡터|확률|통계|"
    r"jwt|api|rest|http|sql|nosql|cache|thread|process|memory|"
    r"대입|학습|공부|시험|과목|전공|강의|교재)",
    re.IGNORECASE,
)

_CASUAL_EFFECTIVE_LEVEL = "일상대화"


@dataclass
class MessageIntentResult:
    intent: str                      # "learning_question" | "casual_greeting" | ...
    is_casual_message: bool
    requested_knowledge_level: str
    effective_knowledge_level: str
    reason: str


def classify_message_intent(
    message: str,
    requested_knowledge_level: str = "학사",
) -> MessageIntentResult:
    """
    메시지를 분석하여 학습 질문인지 일상 대화인지 판별한다.

    Args:
        message:                  사용자 입력 문자열
        requested_knowledge_level: 사용자가 선택한 지식수준

    Returns:
        MessageIntentResult — intent, effective_knowledge_level 포함
    """
    stripped = message.strip()

    # 1) 일상 대화 패턴 매칭 (길이 30자 이하 제한 — 짧은 잡담에만 적용)
    if len(stripped) <= 30 and _CASUAL_PATTERNS.match(stripped):
        return MessageIntentResult(
            intent="casual_greeting",
            is_casual_message=True,
            requested_knowledge_level=requested_knowledge_level,
            effective_knowledge_level=_CASUAL_EFFECTIVE_LEVEL,
            reason="단순 인사/감사/잡담이므로 지식수준 프롬프트를 과도하게 적용하지 않음",
        )

    # 1-2) 불만 / 버그 제보 / 감정 표현 매칭 (학습 키워드보다 우선 처리)
    if _COMPLAINT_PATTERNS.search(stripped):
        return MessageIntentResult(
            intent="complaint",
            is_casual_message=True,  # 티키타카/RAG 스킵
            requested_knowledge_level=requested_knowledge_level,
            effective_knowledge_level=_CASUAL_EFFECTIVE_LEVEL,
            reason="불만/오류 제보이므로 티키타카 및 무거운 분석을 건너뜀",
        )

    # 2) 학습 키워드 포함 → 무조건 learning_question
    if _LEARNING_KEYWORDS.search(stripped):
        return MessageIntentResult(
            intent="learning_question",
            is_casual_message=False,
            requested_knowledge_level=requested_knowledge_level,
            effective_knowledge_level=requested_knowledge_level,
            reason="학습/개념 키워드가 포함되어 선택한 지식수준을 그대로 적용",
        )

    # 3) 매우 짧고 특수문자/숫자만 있는 경우 (확인 메시지 등)
    if len(stripped) <= 5 and not any(c.isalpha() for c in stripped):
        return MessageIntentResult(
            intent="casual_message",
            is_casual_message=True,
            requested_knowledge_level=requested_knowledge_level,
            effective_knowledge_level=_CASUAL_EFFECTIVE_LEVEL,
            reason="의미 없는 짧은 입력으로 판단",
        )

    # 4) 기본값 — learning_question으로 처리 (오분류 방지)
    return MessageIntentResult(
        intent="learning_question",
        is_casual_message=False,
        requested_knowledge_level=requested_knowledge_level,
        effective_knowledge_level=requested_knowledge_level,
        reason="분류 불명확 — 사용자가 선택한 지식수준을 우선 적용",
    )
