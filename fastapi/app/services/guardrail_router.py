"""
Structured LLM Guardrail Router (멀티에이전트 채팅 입력 라우터).

목적:
  사용자 입력을 generation pipeline 실행 전에 route enum으로 분류하여
  인사/자기소개/잡담/욕설/불명확 입력이 학습 답변·검증·피어피드백 pipeline을
  타지 않도록 hard stop을 강제한다.

설계 원칙:
  - 특정 문자열 하나만 if로 막지 않는다. lexical + 구조 패턴으로 일반화한다.
  - LLM 호출 없이 동작하는 lightweight deterministic guard (hot path 지연 0).
    애매하면 LEARNING_QUESTION으로 안전 분류한다(오분류 시에도 학습 답변 제공).
  - sanitize_user_visible_text로 내부 evaluator 문구/raw markdown 누출을 차단한다.

이 모듈은 응답 schema를 바꾸지 않는다. 호출 측에서 route 결과를 사용해
직접 응답(direct reply)을 만들거나, 내부 phase 노출 여부를 결정한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ── Route enum (문자열 상수) ────────────────────────────────────────────────
GREETING = "GREETING"
SELF_INTRO = "SELF_INTRO"
SMALL_TALK = "SMALL_TALK"
ABUSE = "ABUSE"
UNCLEAR = "UNCLEAR"
LEARNING_QUESTION = "LEARNING_QUESTION"
FEEDBACK_REQUEST = "FEEDBACK_REQUEST"
DEBATE_REQUEST = "DEBATE_REQUEST"
QUIZ_REQUEST = "QUIZ_REQUEST"
ROADMAP_REQUEST = "ROADMAP_REQUEST"

# generation/validation/peer feedback을 호출하면 안 되는 route (hard stop 대상)
DIRECT_REPLY_ROUTES = frozenset({GREETING, SELF_INTRO, SMALL_TALK, ABUSE, UNCLEAR})


@dataclass
class RouteResult:
    route: str
    visibleMode: str           # basic | feedback | debate | quiz | roadmap | direct
    directReply: Optional[str]  # DIRECT_REPLY_ROUTES면 즉시 반환할 안전 응답
    reason: str
    matched: List[str] = field(default_factory=list)

    @property
    def is_hard_stop(self) -> bool:
        return self.route in DIRECT_REPLY_ROUTES


# ── 정규화 ────────────────────────────────────────────────────────────────
def _normalize(text: str) -> str:
    """공백/반복문자 정규화 — 욕설 우회(ㅅ ㅂ, 시이발 등)를 일부 흡수한다."""
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", "", t)               # 모든 공백 제거 (ㅅ ㅂ -> ㅅㅂ)
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)    # 3회 이상 반복 -> 2회 (시이이발 -> 시이발 근사)
    return t


# ── 욕설/공격성 lexicon (일반화: root 토큰 + 자음 패턴) ──────────────────────
# 단일 문자열 매칭이 아니라 어근 집합. 정규화 후 substring 검사.
_ABUSE_ROOTS = (
    "씨발", "시발", "씨바", "시바", "씨팔", "쌍놈", "쌍년", "개새", "개색", "개세",
    "새끼", "병신", "븅신", "지랄", "ㅈㄹ", "ㅄ", "ㅂㅅ", "ㅅㅂ", "ㅆㅂ", "ㅗ",
    "엿먹", "꺼져", "닥쳐", "좆", "좇", "fuck", "shit", "bitch", "asshole",
    "느금", "니애미", "니미", "창녀", "걸레년", "미친놈", "미친년", "또라이",
    "찐따", "한남", "한녀", "джи",
)
# 모욕 결합 패턴 (지능/외모 비하 등) — '바보/멍청이' 단독은 학습어와 충돌하므로 공격 대상어와 결합 시만
_ABUSE_INSULT_PATTERN = re.compile(
    r"(너|니|당신|넌|네가|니가).{0,4}(바보|멍청|등신|쓰레기|찌질|역겹|꺼져|닥쳐)"
)


def _is_abuse(message: str, norm: str) -> Optional[List[str]]:
    hits = [r for r in _ABUSE_ROOTS if r in norm]
    if hits:
        return hits
    if _ABUSE_INSULT_PATTERN.search(message):
        return ["insult_pattern"]
    return None


# ── 인사 / 자기소개 / 잡담 ──────────────────────────────────────────────────
_GREETING_RE = re.compile(
    r"^("
    r"안녕|안뇽|하이|하잉|헬로|hello|hi|hey|반가|반갑|좋은\s*(아침|오후|저녁)|ㅎㅇ|ㅎ2"
    r")",
    re.IGNORECASE,
)
_SELF_INTRO_RE = re.compile(
    r"(나는?|난|내\s*이름은?|저는?|제\s*이름은?)\s*[가-힣a-zA-Z]{1,12}\s*(이?야|이?에요|입니다|이라고\s*해|라고\s*해)"
)
_SELF_INTRO_NAME_RE = re.compile(
    r"(?:나는?|난|내\s*이름은?|저는?|제\s*이름은?)\s*([가-힣]{2,4}?)이?\s*(?:야|에요|예요|입니다|이라고|라고)"
)
_SMALL_TALK_RE = re.compile(
    r"^("
    r"고마워|감사|고맙|수고|잘자|잘\s*자|굿나잇|잘가|바이|bye|ㅂㅂ"
    r"|ㅇㅋ|오케이?|오케|알겠|네|넵|응|그래|좋아|ㅋㅋ|ㅎㅎ|ㅠㅠ"
    r"|심심|졸려|배고파|피곤|뭐해|뭐\s*하|밥\s*먹었"
    r")",
    re.IGNORECASE,
)

# ── 명시적 요청 키워드 ──────────────────────────────────────────────────────
_FEEDBACK_RE = re.compile(
    r"(평가\s*해|평가해줘|피드백|첨삭|검토\s*해|리뷰\s*해|봐\s*줘|점수\s*매|고쳐\s*줘|"
    r"어때\?|개선\s*점|보완\s*점|잘\s*했는지)"
)
_DEBATE_RE = re.compile(
    r"(토론|찬반|찬성과\s*반대|반론|반박|비교\s*해|비교해줘|대립|논쟁|debate)"
)
_QUIZ_RE = re.compile(
    r"(퀴즈|문제\s*내|문제\s*만들|문제\s*출제|시험\s*문제|quiz|객관식|문제\s*풀)"
)
_ROADMAP_RE = re.compile(
    r"(로드맵|학습\s*계획|학습계획|공부\s*계획|커리큘럼|학습\s*순서|roadmap|학습\s*로드)"
)

# 학습/개념 키워드 (message_intent_classifier와 정합)
_LEARNING_RE = re.compile(
    r"(뭐야|뭐죠|무엇|설명|이란|개념|정의|원리|구조|차이|작동|동작|방법|어떻게|왜|이유|"
    r"장단점|예시|특징|역할|사용|적용|구현|코드|예제|보여\s*줘|알려\s*줘|공부|배우|학습|"
    r"알고리즘|자료구조|데이터베이스|운영체제|네트워크|스프링|spring|java|python|자바|"
    r"객체|상속|다형성|인터페이스|추상|클래스|함수|oop|sql|api|http|전제|한계|반례)",
    re.IGNORECASE,
)


def classify_route(
    message: str,
    mode: Optional[str] = None,
    learning_mode: Optional[str] = None,
) -> RouteResult:
    """
    사용자 입력을 route enum으로 분류한다. (deterministic, LLM 미호출)

    우선순위:
      1) ABUSE (안전 최우선 — 어떤 모드에서도 hard stop)
      2) 명시적 모드(debate/quiz/roadmap)가 선택되어 있으면 해당 request route
      3) 인사/자기소개/잡담
      4) 명시적 요청 키워드(feedback/debate/quiz/roadmap)
      5) 학습 키워드 → LEARNING_QUESTION
      6) UNCLEAR (매우 짧거나 의미 불명확)
      7) 기본 LEARNING_QUESTION (오분류 안전판)
    """
    raw = (message or "").strip()
    norm = _normalize(raw)
    lm = (learning_mode or "").strip().lower()
    md = (mode or "").strip().lower()

    # 1) 욕설/공격성 — 최우선 hard stop
    abuse_hits = _is_abuse(raw, norm)
    if abuse_hits:
        return RouteResult(
            route=ABUSE,
            visibleMode="direct",
            directReply=_DIRECT_REPLIES[ABUSE],
            reason="욕설/공격성 표현 감지 — 안전 응답으로 hard stop",
            matched=abuse_hits,
        )

    # 2) 사용자가 명시적으로 토론/상황극/소크라테스 모드를 선택한 경우는 그 파이프라인을 존중한다.
    #    (욕설은 위에서 이미 hard stop. 이 모드들에서는 '나는 학생이야' 같은 역할 설정 문구가
    #     자기소개로 오분류되어 direct_reply로 빠지는 것을 막는다.)
    explicit_debate = lm in {"debate", "토론"} or md in {"debate", "토론"}
    if explicit_debate and raw:
        return RouteResult(DEBATE_REQUEST, "debate", None,
                           "명시적 토론 모드", ["mode=debate"])
    _sim_aliases = {"simulation", "situation", "roleplay", "sim", "상황극", "시뮬레이션"}
    explicit_simulation = lm in _sim_aliases or md in _sim_aliases
    if explicit_simulation and raw:
        return RouteResult(LEARNING_QUESTION, "basic", None,
                           "명시적 상황극 모드", ["mode=simulation"])
    explicit_socratic = lm in {"socratic", "소크라테스"} or md in {"socratic", "소크라테스"}
    if explicit_socratic and raw:
        return RouteResult(LEARNING_QUESTION, "basic", None,
                           "명시적 소크라테스 모드", ["mode=socratic"])

    # 3) 인사 / 자기소개 / 잡담 (짧은 입력 위주)
    if _SELF_INTRO_RE.search(raw) and not _LEARNING_RE.search(raw):
        return RouteResult(SELF_INTRO, "direct", _self_intro_reply(raw),
                           "자기소개 감지", ["self_intro"])
    if len(raw) <= 40 and _GREETING_RE.match(raw) and not _LEARNING_RE.search(raw):
        return RouteResult(GREETING, "direct", _DIRECT_REPLIES[GREETING],
                           "인사 감지", ["greeting"])
    if len(raw) <= 30 and _SMALL_TALK_RE.match(raw) and not _LEARNING_RE.search(raw):
        return RouteResult(SMALL_TALK, "direct", _DIRECT_REPLIES[SMALL_TALK],
                           "잡담 감지", ["small_talk"])

    # 4) 명시적 요청 키워드
    if _FEEDBACK_RE.search(raw):
        return RouteResult(FEEDBACK_REQUEST, "feedback", None,
                           "평가/피드백 요청", ["feedback"])
    if _DEBATE_RE.search(raw):
        return RouteResult(DEBATE_REQUEST, "debate", None,
                           "토론/비교/반론 요청", ["debate_kw"])
    if _QUIZ_RE.search(raw):
        return RouteResult(QUIZ_REQUEST, "quiz", None,
                           "퀴즈/문제 요청", ["quiz_kw"])
    if _ROADMAP_RE.search(raw):
        return RouteResult(ROADMAP_REQUEST, "roadmap", None,
                           "로드맵/학습계획 요청", ["roadmap_kw"])

    # 5) 학습 키워드
    if _LEARNING_RE.search(raw):
        return RouteResult(LEARNING_QUESTION, "basic", None,
                           "학습/개념 키워드", ["learning_kw"])

    # 6) UNCLEAR — 너무 짧거나 의미 없는 입력
    if len(raw) <= 4 or (len(raw) <= 8 and not any(c.isalpha() or "가" <= c <= "힣" for c in raw)):
        return RouteResult(UNCLEAR, "direct", _DIRECT_REPLIES[UNCLEAR],
                           "불명확/너무 짧은 입력", ["too_short"])

    # 7) 기본 — 학습 질문으로 안전 분류 (억지 답변 방지 위해 길이 매우 짧으면 UNCLEAR)
    if len(raw) <= 10:
        return RouteResult(UNCLEAR, "direct", _DIRECT_REPLIES[UNCLEAR],
                           "분류 불명확 + 짧은 입력", ["fallback_short"])
    return RouteResult(LEARNING_QUESTION, "basic", None,
                       "분류 불명확 — 학습 질문으로 안전 처리", ["fallback_learning"])


# ── 직접 응답 템플릿 (markdown 없음, 1~2문장) ──────────────────────────────
_DIRECT_REPLIES: Dict[str, str] = {
    GREETING: "안녕하세요! 반가워요. 오늘은 어떤 걸 같이 공부해볼까요?",
    SMALL_TALK: "네, 편하게 이야기해요. 공부하다 궁금한 게 생기면 언제든 물어봐 주세요.",
    ABUSE: "그런 표현은 도와주기 어렵습니다. 공부 관련 질문으로 다시 말해 주세요.",
    UNCLEAR: "질문을 조금만 더 구체적으로 말해 주실래요? 어떤 개념이 궁금한지 알려주면 도와드릴게요.",
}


def _self_intro_reply(message: str) -> str:
    m = _SELF_INTRO_NAME_RE.search(message)
    if m:
        name = m.group(1)
        return f"안녕하세요 {name}님, 반가워요! 오늘은 어떤 걸 같이 공부해볼까요?"
    return "반가워요! 소개 고마워요. 오늘은 어떤 걸 같이 공부해볼까요?"


def direct_reply_for(route: str, message: str = "") -> str:
    if route == SELF_INTRO:
        return _self_intro_reply(message)
    return _DIRECT_REPLIES.get(route, _DIRECT_REPLIES[UNCLEAR])


# ── 사용자 노출 텍스트 sanitize ────────────────────────────────────────────
# 내부 evaluator/단계 문구 — 사용자 visible 답변에 절대 노출 금지.
_INTERNAL_MARKERS = (
    "검증 결과", "보완점", "수정 제안", "근거 확인", "2차 생성", "1차 생성", "3차 생성",
    "2차 검증", "내부 검증", "ROUTE_DECISION", "INTERNAL_VALIDATION", "PEER_FEEDBACK",
    "RAW_MODEL_OUTPUT", "peer feedback", "상호 피드백 결과",
)
_INTERNAL_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*\s*)?(?:" +
    r"검증\s*결과|보완점|수정\s*제안|근거\s*확인|2차\s*생성(?:\s*내용)?|1차\s*생성|3차\s*생성|"
    r"2차\s*검증|내부\s*검증|상호\s*피드백|ROUTE_DECISION|INTERNAL_VALIDATION|PEER_FEEDBACK"
    r")\b.*$",
    re.IGNORECASE,
)
# markdown 제거용 (direct reply 전용)
_MD_BOLD_RE = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
_MD_CODEFENCE_RE = re.compile(r"```[a-zA-Z]*")
_MD_INLINE_CODE_RE = re.compile(r"`([^`]*)`")


# 성격/스타일 검증 점수 디버그 문구 (LLM 본문에 새어나올 경우를 위한 방어).
# '보완 필요' 같은 일반 학습 피드백은 보존하고, 성격/스타일/검증/score와 함께
# 등장하는 진단 문구만 제거한다.
_PERSONALITY_DEBUG_RES = (
    re.compile(r"성격\s*검증\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:보완\s*필요)?", re.IGNORECASE),
    re.compile(r"(?:스타일|style)\s*검증\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:보완\s*필요)?", re.IGNORECASE),
    re.compile(r"personality\s*(?:validation|score)\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:needs\s*improvement)?", re.IGNORECASE),
    re.compile(r"style\s*(?:validation|score)\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:needs\s*improvement)?", re.IGNORECASE),
    re.compile(r"(?:validation|quality)\s*score\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:needs\s*improvement)?", re.IGNORECASE),
)


def strip_personality_debug_text(text: str) -> str:
    """성격/스타일 검증 점수 디버그 문구를 본문에서 제거한다(일반 피드백은 보존)."""
    if not text:
        return text or ""
    cleaned = text
    for rx in _PERSONALITY_DEBUG_RES:
        cleaned = rx.sub("", cleaned)
    # 제거로 생긴 빈 괄호/잉여 공백 정리
    cleaned = re.sub(r"\(\s*\)|\[\s*\]", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned


def strip_internal_markers(text: str) -> str:
    """학습 답변에서 내부 evaluator 헤더/라벨 라인을 제거한다(코드블록/본문은 보존)."""
    if not text:
        return text
    out = []
    for line in text.splitlines():
        if _INTERNAL_LINE_RE.match(line):
            continue
        out.append(line)
    return strip_personality_debug_text("\n".join(out)).strip()


def has_internal_leak(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(m.lower() in low for m in _INTERNAL_MARKERS)


def sanitize_user_visible_text(text: str, allow_markdown: bool = True) -> str:
    """
    사용자에게 보이는 텍스트를 정리한다.
      - allow_markdown=False (direct reply): **, ###, ```, ` 제거 + 내부 문구 제거.
      - allow_markdown=True  (학습 답변):  코드블록/일반 markdown은 유지하되
        내부 evaluator 헤더 라인만 제거한다.
    """
    if not text:
        return text or ""
    cleaned = strip_internal_markers(text)
    if not allow_markdown:
        cleaned = _MD_CODEFENCE_RE.sub("", cleaned)
        cleaned = _MD_HEADING_RE.sub("", cleaned)
        cleaned = re.sub(r"#{1,6}\s*", "", cleaned)  # 인라인 # 시퀀스까지 제거
        cleaned = _MD_BOLD_RE.sub(r"\1", cleaned)
        cleaned = _MD_INLINE_CODE_RE.sub(r"\1", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{2,}", "\n", cleaned).strip()
    return cleaned


def internal_phases_visible_default() -> bool:
    """기본 채팅에서 내부 검증/피어피드백 단계를 사용자 UI에 스트리밍할지 여부.

    기본 false: LEARNING_QUESTION 기본 모드에서는 내부 단계를 노출하지 않는다.
    FEEDBACK_REQUEST일 때만 호출 측에서 명시적으로 True를 전달한다.
    환경변수 AI_STREAM_INTERNAL_PHASES_VISIBLE=true로 운영 override 가능.
    """
    import os
    return (os.getenv("AI_STREAM_INTERNAL_PHASES_VISIBLE", "false").strip().lower()
            in {"1", "true", "yes", "on"})
