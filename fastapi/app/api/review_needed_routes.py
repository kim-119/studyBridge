"""
오답노트 '복습 필요' AI 분석 — 단일 오답노트에 대해 부족 개념 진단 텍스트 1개를 생성.

EC2(Spring)가 오답노트 목록/상세의 '복습 필요' 화면에서 호출한다. 자료보관함/폴더/DB는
Spring 책임이며, 본 엔드포인트는 전달받은 텍스트만 분석한다(reviewNoteId 소유권 검증 없음).

  POST /api/ai/review-needed → { reviewNoteId, reviewNeededText }

기존 /api/ai/review/* , /api/ai/review-note/* 계약과 별개의 신규 additive 경로.
materialId/folderId/parentFolderId 등 부가 필드가 같이 와도 무시한다(extra=ignore).
LLM 실패/timeout/빈응답은 성공 응답(200) + fallback 텍스트로 반환한다(발표 안정성).
"""
import asyncio
import logging
import os
import re
from typing import Any, List, Optional

from fastapi import APIRouter, Body
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Review Needed AI"])

REVIEW_NEEDED_TIMEOUT = int(os.getenv("AI_REVIEW_NEEDED_TIMEOUT_SECONDS", "60"))

# 출력 길이 정책: 500자 내외. 크게 넘으면 문장 단위로 축약.
_SOFT_LIMIT = 500
_HARD_LIMIT = 560

# 첫 문장 고정 형식: "{개념}에 대한 개념이 부족하여 복습이 필요합니다."
_FIRST_SENTENCE_SUFFIX = "에 대한 개념이 부족하여 복습이 필요합니다."
_FIRST_SENTENCE_RE = re.compile(r"^\s*\S.{0,40}?에 대한 개념이 부족하여 복습이 필요합니다\.")

# 프롬프트 폭주 방지용 입력 컷
_MAX_QUESTION = 1200
_MAX_EXPLANATION = 1500
_MAX_FIELD = 400

# 개념 추출 시 제외할 일반어/불용어
_STOPWORDS = {
    "개념", "문제", "보기", "정답", "오답", "해설", "복습", "필요", "내용", "다음",
    "경우", "사용", "처리", "설명", "이유", "방법", "과목", "자료", "노트",
    "무엇", "어떤", "위해", "있다", "한다", "된다", "이다", "그리고", "하지만",
}

_FALLBACK_TEXT = (
    "문제의 핵심 개념을 정확히 식별하기 어려워 기본 개념 복습이 필요합니다. "
    "원본 자료와 기존 해설을 다시 확인한 뒤, 정답과 오답 선택지를 비교하면서 왜 해당 "
    "선택지가 틀렸는지 정리해 보세요. 특히 문제에서 요구한 조건, 용어 정의, 적용 순서를 "
    "다시 확인하면 같은 유형의 실수를 줄일 수 있습니다."
)

# 한글 2자 이상 또는 영문 식별자 토큰
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+|[가-힣]{2,}")


class ReviewNeededRequest(BaseModel):
    # materialId/folderId/parentFolderId 등 Spring DTO 부가 필드는 무시(보안 모델 전역설정 변경 아님)
    model_config = ConfigDict(extra="ignore")

    reviewNoteId: Optional[int] = None
    subject: Optional[str] = ""
    materialTitle: Optional[str] = ""
    # 기존 단일 문제 계약(하위 호환). 재풀이 정보가 없다.
    question: str = ""
    choices: Optional[Any] = None  # list 또는 string 모두 허용
    correctAnswer: Optional[str] = ""
    userAnswer: Optional[str] = ""
    explanation: Optional[str] = ""
    difficulty: Optional[str] = ""
    # 권장 계약: 문제별 최초 결과 + 재풀이 1회 결과.
    #   questions[]: {question, choices, correctAnswer, explanation, concept,
    #                 firstAnswer, firstCorrect, retryAnswer, retryCorrect}
    #   (다시풀기는 문제당 1회다. retry 횟수/힌트 관련 필드는 존재하지 않는다.)
    questions: Optional[List[Any]] = None


def _choices_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())[:_MAX_FIELD]
    return str(value).strip()[:_MAX_FIELD]


_WRAPPING_QUOTES = ('"', "'", "“", "”", "‘", "’")


def _unquote_first_sentence(text: str) -> str:
    """프롬프트 예시를 그대로 따라 첫 문장을 따옴표로 감싸는 출력을 정리한다."""
    body = (text or "").strip()
    if body[:1] in _WRAPPING_QUOTES:
        closing = next((i for i, ch in enumerate(body[1:], start=1) if ch in _WRAPPING_QUOTES), -1)
        if closing > 0:
            body = (body[1:closing] + body[closing + 1:]).strip()
    return body


def _strip_markdown(text: str) -> str:
    """마크다운 제목/코드블록/강조 제거 + 공백 정리."""
    if not text:
        return ""
    # 코드블록 펜스 제거
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = text.replace("```", " ")
    out_lines: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        # 마크다운 제목줄(#...) 통째 제거
        if s.startswith("#"):
            continue
        out_lines.append(line)
    text = "\n".join(out_lines)
    # 인라인 강조/백틱 제거
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"(?<!\d)\*(?!\d)", "", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    # 공백 정규화
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", " ", text)
    text = text.replace("\n", " ")
    return text.strip()


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?。])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _shorten(text: str) -> str:
    """500자 내외로 자연스러운 문장 단위 축약."""
    if len(text) <= _HARD_LIMIT:
        return text
    acc = ""
    for sent in _sentences(text):
        if not acc:
            acc = sent
            continue
        if len(acc) + 1 + len(sent) > _SOFT_LIMIT:
            break
        acc = f"{acc} {sent}"
    if not acc:  # 한 문장이 통째로 길 때
        acc = text[:_SOFT_LIMIT].rstrip()
    return acc.strip()


def _extract_concept(req: ReviewNeededRequest) -> str:
    """과목명 전체가 아닌, 문제/해설에서 드러난 세부 개념 후보를 추출."""
    subject_tokens = set(_TOKEN_RE.findall(req.subject or ""))
    # 해설을 우선(구체적 개념이 많음), 다음 문제
    pool = f"{req.explanation or ''} {req.question or ''}"
    freq: dict = {}
    for tok in _TOKEN_RE.findall(pool):
        if tok in _STOPWORDS or tok in subject_tokens:
            continue
        if len(tok) < 2:
            continue
        freq[tok] = freq.get(tok, 0) + 1
    if freq:
        ranked = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))
        top = [w for w, _ in ranked[:2]]
        return " ".join(top)
    # 후보가 없으면 과목명 → 그래도 없으면 일반어
    subj = (req.subject or "").strip()
    return subj or "핵심 개념"


def _first_concept_in(text: str) -> Optional[str]:
    m = _FIRST_SENTENCE_RE.match(text)
    if not m:
        return None
    head = m.group(0)
    return head[: head.index(_FIRST_SENTENCE_SUFFIX)].strip() or None


def _enforce_first_sentence(text: str, req: ReviewNeededRequest) -> str:
    """첫 문장이 고정 형식이 아니면 보정. 형식이지만 개념이 과목명처럼 넓으면 구체화 시도."""
    concept = _first_concept_in(text)
    if concept is None:
        fixed_head = f"{_extract_concept(req)}{_FIRST_SENTENCE_SUFFIX}"
        body = text.strip()
        return f"{fixed_head} {body}".strip() if body else fixed_head
    # 첫 문장 개념이 과목명과 동일하게 넓은 경우 → 더 구체적 개념으로 치환 시도
    subject = (req.subject or "").strip()
    if subject and concept == subject:
        specific = _extract_concept(req)
        if specific and specific != subject:
            text = text.replace(
                f"{concept}{_FIRST_SENTENCE_SUFFIX}",
                f"{specific}{_FIRST_SENTENCE_SUFFIX}",
                1,
            )
    return text


def _payload(req: ReviewNeededRequest) -> dict:
    return req.model_dump()


def _decision(req: ReviewNeededRequest):
    from app.services import review_needed_analyzer as RA
    questions = RA.parse_questions(_payload(req))
    return RA.decide(questions, req.subject or "")


_SYSTEM_FALLBACK = "너는 대학생 학습자의 오답노트를 분석하는 학습 코치다."


def _generate_sync(req: ReviewNeededRequest) -> dict:
    """현재 오답노트 데이터만으로 생성한다(대화 기억/이전 문제 컨텍스트 사용 금지).

    반환: {"text", "reviewNeeded", "cases", "concept", "source"}
    """
    from app.services import review_needed_analyzer as RA
    from app.services.ai_pipeline import openai_refine, qwen_draft

    decision = _decision(req)
    base = {"reviewNeeded": decision.review_needed,
            "cases": decision.cases, "concept": decision.concept}

    # CASE D: 최초 정답만 있으면 AI를 호출하지 않는다(불필요한 호출 금지).
    if not decision.review_needed:
        text = (RA.build_no_review_text(decision) if decision.questions else _FALLBACK_TEXT)
        return {**base, "text": text, "source": "deterministic"}

    prompt = RA.build_prompt(decision, req.subject or "", req.materialTitle or "",
                             req.difficulty or "")
    issues: list = []
    # 검증 실패 시 그 요청만 1회 재생성한다(전체 파이프라인 재실행 아님).
    for attempt in range(2):
        ask = prompt if attempt == 0 else (
            f"{prompt}\n\n[재작성 지시 — 직전 출력이 계약을 어겼다: {', '.join(issues)}]\n"
            "재풀이 결과를 문장 안에 명시하고, 부족한 개념과 복습 순서를 반드시 포함하라.")
        raw = qwen_draft(RA.SYSTEM, ask, max_tokens=700)
        if not (raw and raw.strip()):
            raw = openai_refine(RA.SYSTEM, ask, max_tokens=700)

        cleaned = _strip_markdown(raw or "")
        if not cleaned:
            break
        cleaned = _enforce_first_sentence_v2(_unquote_first_sentence(cleaned), decision)
        cleaned = _shorten(cleaned)
        issues = RA.validate_text(cleaned, decision)
        if not issues:
            return {**base, "text": cleaned, "source": "ai"}
        logger.info("review-needed 생성 검증 실패(attempt=%d) issues=%s", attempt + 1, issues)

    # AI 실패/검증 실패: 현재 문제 데이터 기반 결정론 텍스트(의미 없는 고정 문장 금지)
    return {**base, "text": RA.build_fallback(decision, req.materialTitle or ""),
            "source": "deterministic"}


def _enforce_first_sentence_v2(text: str, decision) -> str:
    """첫 문장 계약({개념}에 대한 개념이 부족하여 복습이 필요합니다.) 유지."""
    from app.services import review_needed_analyzer as RA
    if RA.FIRST_SENTENCE_SUFFIX in text[:120]:
        return text
    concept = decision.concept or "핵심 개념"
    return f"{concept}{RA.FIRST_SENTENCE_SUFFIX} {text.strip()}".strip()


@router.post("/api/ai/review-needed", summary="오답노트 '복습 필요' 부족 개념 분석")
async def review_needed(req: ReviewNeededRequest = Body(...)):
    """최초 풀이 + 재풀이(1회) 결과를 함께 보고 '왜 다시 봐야 하는가'를 생성한다.

    실패/timeout 이어도 200 + 현재 문제 기반 텍스트를 반환한다(빈 영역 금지).
    """
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_generate_sync, req), timeout=REVIEW_NEEDED_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.info("review-needed timeout reviewNoteId=%s → 결정론 폴백", req.reviewNoteId)
        result = _timeout_fallback(req)
    except Exception as e:  # noqa: BLE001
        logger.warning("review-needed 실패 reviewNoteId=%s: %s → 결정론 폴백", req.reviewNoteId, e)
        result = _timeout_fallback(req)

    logger.info("review-needed done reviewNoteId=%s reviewNeeded=%s cases=%s source=%s len=%d",
                req.reviewNoteId, result.get("reviewNeeded"), result.get("cases"),
                result.get("source"), len(result.get("text") or ""))
    return {
        "reviewNoteId": req.reviewNoteId,
        "reviewNeededText": result.get("text") or _FALLBACK_TEXT,
        # additive — 기존 UI 계약(reviewNeededText)은 그대로 두고 진단 필드만 추가한다.
        "reviewNeeded": result.get("reviewNeeded", True),
        "cases": result.get("cases", []),
        "concept": result.get("concept", ""),
        "generatedBy": result.get("source", "deterministic"),
    }


def _timeout_fallback(req: ReviewNeededRequest) -> dict:
    """AI 실패 시에도 현재 문제의 개념/최초·재풀이 결과를 반영한 텍스트를 만든다."""
    from app.services import review_needed_analyzer as RA
    try:
        decision = _decision(req)
        if not decision.questions:
            return {"text": _FALLBACK_TEXT, "reviewNeeded": True, "cases": [],
                    "concept": "", "source": "deterministic"}
        text = (RA.build_no_review_text(decision) if not decision.review_needed
                else RA.build_fallback(decision, req.materialTitle or ""))
        return {"text": text, "reviewNeeded": decision.review_needed,
                "cases": decision.cases, "concept": decision.concept, "source": "deterministic"}
    except Exception:  # pragma: no cover
        return {"text": _FALLBACK_TEXT, "reviewNeeded": True, "cases": [],
                "concept": "", "source": "deterministic"}
