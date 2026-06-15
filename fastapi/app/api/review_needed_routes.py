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
    question: str = ""
    choices: Optional[Any] = None  # list 또는 string 모두 허용
    correctAnswer: Optional[str] = ""
    userAnswer: Optional[str] = ""
    explanation: Optional[str] = ""
    difficulty: Optional[str] = ""


def _choices_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())[:_MAX_FIELD]
    return str(value).strip()[:_MAX_FIELD]


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


def _build_prompt(req: ReviewNeededRequest) -> str:
    return (
        "아래 오답노트 정보를 바탕으로 학습자가 어떤 개념이 부족해서 복습이 필요한지 "
        "한국어로 500자 내외로 설명하라.\n\n"
        "반드시 첫 문장은 다음 형식을 따른다.\n"
        '"{구체 개념명}에 대한 개념이 부족하여 복습이 필요합니다."\n\n'
        "작성 규칙:\n"
        "1. {구체 개념명}은 과목명 전체가 아니라 문제에서 드러난 세부 개념으로 작성한다.\n"
        "2. 사용자를 비난하지 않는다.\n"
        "3. 정답만 반복하지 않는다.\n"
        "4. 오답 원인, 부족 개념, 복습 순서를 포함한다.\n"
        "5. 500자 내외로 작성한다.\n"
        "6. 불필요한 인사말, 제목, 마크다운은 쓰지 않는다.\n"
        "7. 문제 정보가 부족하면 '핵심 개념 식별이 제한적'이라고 솔직히 표현하되, "
        "그래도 복습 방향을 제시한다.\n\n"
        "[오답노트 정보]\n"
        f"과목명: {(req.subject or '')[:_MAX_FIELD]}\n"
        f"원본 자료명: {(req.materialTitle or '')[:_MAX_FIELD]}\n"
        f"문제: {(req.question or '')[:_MAX_QUESTION]}\n"
        f"보기: {_choices_text(req.choices)}\n"
        f"정답: {(req.correctAnswer or '')[:_MAX_FIELD]}\n"
        f"사용자 오답: {(req.userAnswer or '')[:_MAX_FIELD]}\n"
        f"기존 해설: {(req.explanation or '')[:_MAX_EXPLANATION]}\n"
        f"난이도: {(req.difficulty or '')[:_MAX_FIELD]}\n"
    )


_SYSTEM = "너는 대학생 학습자의 오답노트를 분석하는 학습 코치다."


def _generate_sync(req: ReviewNeededRequest) -> str:
    """Ollama(Qwen) 우선, 실패 시 OpenAI 보강, 둘 다 실패 시 fallback."""
    from app.services.ai_pipeline import openai_refine, qwen_draft

    prompt = _build_prompt(req)
    raw = qwen_draft(_SYSTEM, prompt, max_tokens=700)
    if not (raw and raw.strip()):
        raw = openai_refine(_SYSTEM, prompt, max_tokens=700)
    if not (raw and raw.strip()):
        return _FALLBACK_TEXT

    cleaned = _strip_markdown(raw)
    if not cleaned:
        return _FALLBACK_TEXT
    cleaned = _enforce_first_sentence(cleaned, req)
    cleaned = _shorten(cleaned)
    return cleaned or _FALLBACK_TEXT


@router.post("/api/ai/review-needed", summary="오답노트 '복습 필요' 부족 개념 분석")
async def review_needed(req: ReviewNeededRequest = Body(...)):
    # 입력이 거의 비어도 fallback으로 200 성공 응답을 보장(발표 안정성).
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_generate_sync, req), timeout=REVIEW_NEEDED_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.info("review-needed timeout reviewNoteId=%s → fallback", req.reviewNoteId)
        text = _FALLBACK_TEXT
    except Exception as e:  # noqa: BLE001
        logger.warning("review-needed 실패 reviewNoteId=%s: %s → fallback", req.reviewNoteId, e)
        text = _FALLBACK_TEXT

    return {"reviewNoteId": req.reviewNoteId, "reviewNeededText": text}
