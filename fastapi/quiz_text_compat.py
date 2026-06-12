"""
StudyBridge 텍스트 기반 퀴즈 생성 호환 모듈.

Spring이 PDF/자료 본문을 추출해 그대로 넘겨주는 케이스를 안정적으로 처리한다.
기존 S3/PDF 기반 /api/ai/quiz/generate (main.py) 와 응답 계약이 다르며,
이 모듈은 다음 단순 계약을 반환한다:

    {
      "success": true,
      "materialId": 12,
      "quiz": [{"question": "...", "options": ["A","B","C","D"], "answer": "A", "explanation": "..."}],
      "error": null
    }

하드코딩 금지: 모델/온도/토큰/타임아웃/기본개수는 .env에서 읽는다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

logger = logging.getLogger("studybridge.quiz")

router = APIRouter(tags=["Quiz Generation (text)"])

# ─────────────────────────────────────────────────────────────────────────────
# 설정 (.env)
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
QUIZ_MODEL: str = os.getenv("QUIZ_MODEL", os.getenv("OLLAMA_MODEL", "qwen3:14b"))
QUIZ_TEMPERATURE: float = float(os.getenv("QUIZ_TEMPERATURE", "0.2"))
QUIZ_MAX_TOKENS: int = int(os.getenv("QUIZ_MAX_TOKENS", "2048"))
QUIZ_DEFAULT_COUNT: int = int(os.getenv("QUIZ_DEFAULT_COUNT", "5"))
QUIZ_TIMEOUT_SECONDS: int = int(os.getenv("QUIZ_TIMEOUT_SECONDS", "90"))
QUIZ_MIN_TEXT_CHARS: int = int(os.getenv("QUIZ_MIN_TEXT_CHARS", "100"))
QUIZ_MAX_COUNT: int = int(os.getenv("QUIZ_MAX_COUNT", "20"))
# LLM에 넘길 본문 최대 길이 (과도한 토큰 방지)
QUIZ_MAX_CONTEXT_CHARS: int = int(os.getenv("QUIZ_MAX_CONTEXT_CHARS", "12000"))

DEFAULT_DIFFICULTY: str = os.getenv("QUIZ_DEFAULT_DIFFICULTY", "중")
DEFAULT_QUESTION_TYPE: str = os.getenv("QUIZ_DEFAULT_QUESTION_TYPE", "multiple_choice")


# ─────────────────────────────────────────────────────────────────────────────
# 요청 모델
# ─────────────────────────────────────────────────────────────────────────────
class QuizTextRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    materialId: Optional[int] = Field(
        None, validation_alias=AliasChoices("materialId", "material_id")
    )
    title: Optional[str] = Field(
        None, validation_alias=AliasChoices("title", "name", "sourceName")
    )
    text: str = Field("", validation_alias=AliasChoices("text", "content", "body"))
    difficulty: str = Field(DEFAULT_DIFFICULTY)
    count: Optional[int] = Field(None)
    questionType: str = Field(
        DEFAULT_QUESTION_TYPE,
        validation_alias=AliasChoices("questionType", "question_type"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 정규화 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def clamp_count(count: Optional[int]) -> int:
    try:
        c = int(count) if count is not None else QUIZ_DEFAULT_COUNT
    except (TypeError, ValueError):
        c = QUIZ_DEFAULT_COUNT
    return max(1, min(c, QUIZ_MAX_COUNT))


def _normalize_question_type(question_type: str) -> str:
    qt = str(question_type or "").strip().lower()
    if qt in {"short_answer", "주관식", "서술형", "단답"}:
        return "short_answer"
    if qt in {"true_false", "ox", "참거짓"}:
        return "true_false"
    return "multiple_choice"


_LETTER_INDEX = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}


def _resolve_answer(raw_answer: Any, options: List[str]) -> str:
    """answer 가 인덱스/알파벳/보기텍스트 어떤 형태로 와도 보기 텍스트로 정규화."""
    if raw_answer is None:
        return ""
    # 정수 인덱스
    if isinstance(raw_answer, int) and 0 <= raw_answer < len(options):
        return options[raw_answer]
    s = str(raw_answer).strip()
    if not s:
        return ""
    # 숫자 인덱스 (0/1 기반 모두 허용)
    if s.isdigit():
        idx = int(s)
        if 0 <= idx < len(options):
            return options[idx]
        if 1 <= idx <= len(options):
            return options[idx - 1]
    # 알파벳 (A/B/C/D)
    low = s.lower()
    if low in _LETTER_INDEX and _LETTER_INDEX[low] < len(options):
        return options[_LETTER_INDEX[low]]
    # 보기 텍스트 직접 매칭
    for opt in options:
        if str(opt).strip() == s:
            return opt
    # 그대로 반환 (단답형 등)
    return s


def _normalize_item(item: Dict[str, Any], question_type: str) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    question = str(item.get("question") or item.get("문제") or "").strip()
    if not question:
        return None

    raw_options = item.get("options") or item.get("choices") or item.get("보기") or []
    options = [str(o).strip() for o in raw_options if str(o).strip()] if isinstance(raw_options, list) else []

    raw_answer = item.get("answer")
    if raw_answer is None:
        raw_answer = item.get("correctAnswer", item.get("정답"))
    answer = _resolve_answer(raw_answer, options)

    explanation = str(item.get("explanation") or item.get("해설") or "").strip()

    qt = _normalize_question_type(question_type)
    if qt == "multiple_choice":
        # 보기가 부족하면 객관식으로 성립하지 않음
        if len(options) < 2 or not answer:
            return None
    else:
        # 단답/서술형은 보기 없이도 허용하되 정답은 필요
        if not answer:
            return None

    return {
        "question": question,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }


def _strip_fences(text: str) -> str:
    """```json ... ``` 코드펜스 및 앞뒤 잡설 제거 1차 정제."""
    if not text:
        return ""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", t)
    if m:
        return m.group(1).strip()
    return t


def parse_quiz_payload(llm_output: str) -> Optional[List[Dict[str, Any]]]:
    """LLM 출력에서 퀴즈 배열을 복구. 실패 시 None."""
    if not llm_output or not llm_output.strip():
        return None

    # 1) 공용 파서 우선 (코드펜스/dict 래핑 처리)
    try:
        from app.utils.json_parser import safe_parse_quiz_json

        parsed = safe_parse_quiz_json(llm_output)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # 2) 자체 복구: 펜스 제거 후 배열/객체 추출
    cleaned = _strip_fences(llm_output)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = None
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = cleaned.find(start_char)
            end = cleaned.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                try:
                    data = json.loads(cleaned[start:end + 1])
                    break
                except json.JSONDecodeError:
                    continue

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("quiz", "questions", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LLM 호출
# ─────────────────────────────────────────────────────────────────────────────
def _build_messages(text: str, title: str, count: int, difficulty: str, question_type: str) -> Tuple[str, str]:
    qt = _normalize_question_type(question_type)
    if qt == "multiple_choice":
        type_rule = (
            "각 문항은 4지선다 객관식이다. options 에는 보기 4개를 넣고, "
            "answer 에는 정답 보기의 텍스트(보기와 정확히 동일한 문자열)를 넣는다."
        )
    elif qt == "true_false":
        type_rule = "각 문항은 O/X 문제다. options 는 [\"O\", \"X\"], answer 는 \"O\" 또는 \"X\"."
    else:
        type_rule = "각 문항은 단답형이다. options 는 빈 배열 [], answer 에는 정답 텍스트를 넣는다."

    system = (
        "너는 학습 자료 기반 문제 출제 엔진이다.\n"
        "반드시 제공된 자료 본문 안의 내용만 근거로 문제를 만든다.\n"
        "자료에 없는 외부 지식, 일반상식, 공부법으로 문제를 만들지 않는다.\n"
        f"{type_rule}\n"
        "각 문항에는 explanation(해설)을 반드시 포함한다.\n"
        "출력은 오직 JSON 배열만 반환한다. 코드블록, 설명, 머리말, 꼬리말을 절대 포함하지 않는다.\n"
        "JSON 형식: [{\"question\": \"\", \"options\": [\"\"], \"answer\": \"\", \"explanation\": \"\"}]"
    )
    user = (
        f"자료 제목: {title or '제목 없음'}\n"
        f"난이도: {difficulty}\n"
        f"문항 수: {count}\n\n"
        f"자료 본문:\n{text}\n\n"
        f"위 자료 본문만 근거로 {count}개의 문제를 JSON 배열로 출제하라. JSON 외 텍스트 금지."
    )
    return system, user


def _call_quiz_llm(system: str, user: str, request_id: str) -> str:
    """Ollama(QUIZ_MODEL) 우선, 실패 시 main._call_openai fallback."""
    # 1) Ollama
    try:
        probe = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if probe.status_code == 200:
            payload = {
                "model": QUIZ_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {
                    "temperature": QUIZ_TEMPERATURE,
                    "num_predict": QUIZ_MAX_TOKENS,
                },
            }
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                timeout=QUIZ_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "") or ""
            if content.strip():
                return content
    except Exception as e:
        logger.warning("quiz.generate.llm.ollama_failed %s %s", request_id, type(e).__name__)

    # 2) OpenAI fallback (main.py 재사용)
    try:
        from main import _call_openai

        content = _call_openai(
            system, user, max_tokens=QUIZ_MAX_TOKENS, temperature=QUIZ_TEMPERATURE
        )
        if content and content.strip():
            return content
    except Exception as e:
        logger.warning("quiz.generate.llm.openai_failed %s %s", request_id, type(e).__name__)

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 핵심 생성 함수
# ─────────────────────────────────────────────────────────────────────────────
def generate_quiz_from_text(
    text: str,
    title: Optional[str] = None,
    difficulty: str = DEFAULT_DIFFICULTY,
    count: Optional[int] = None,
    question_type: str = DEFAULT_QUESTION_TYPE,
    material_id: Optional[int] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """텍스트 본문 기반 퀴즈 생성. 항상 계약 dict 반환(예외를 던지지 않음)."""
    request_id = request_id or uuid.uuid4().hex[:8]
    text = (text or "").strip()
    difficulty = (difficulty or DEFAULT_DIFFICULTY).strip() or DEFAULT_DIFFICULTY
    count = clamp_count(count)
    question_type = question_type or DEFAULT_QUESTION_TYPE

    logger.info(
        "quiz.generate.start %s materialId=%s text_length=%s count=%s difficulty=%s",
        request_id, material_id, len(text), count, difficulty,
    )

    # 입력 검증
    if len(text) < QUIZ_MIN_TEXT_CHARS:
        logger.warning("quiz.generate.empty_text %s materialId=%s", request_id, material_id)
        return _fail(
            material_id,
            "EMPTY_MATERIAL_TEXT",
            "퀴즈 생성에 사용할 자료 본문이 비어 있거나 너무 짧습니다.",
        )

    context = text[:QUIZ_MAX_CONTEXT_CHARS]
    system, user = _build_messages(context, title or "", count, difficulty, question_type)

    started = time.monotonic()
    try:
        raw = _call_quiz_llm(system, user, request_id)
    except Exception as e:  # 방어적: 어떤 예외도 계약으로 변환
        logger.exception("quiz.generate.error %s %s", request_id, repr(e))
        return _fail(material_id, "LLM_CALL_FAILED", "LLM 호출 중 오류가 발생했습니다.")
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if not raw or not raw.strip():
        logger.warning("quiz.generate.parse_failed %s raw_prefix=<empty> elapsed_ms=%s", request_id, elapsed_ms)
        return _fail(material_id, "LLM_EMPTY_RESPONSE", "LLM이 빈 응답을 반환했습니다.")

    items = parse_quiz_payload(raw)
    if items is None:
        logger.warning(
            "quiz.generate.parse_failed %s raw_prefix=%s elapsed_ms=%s",
            request_id, repr(raw[:300]), elapsed_ms,
        )
        return _fail(material_id, "QUIZ_PARSE_FAILED", "LLM 응답을 JSON으로 파싱하지 못했습니다.")

    quiz: List[Dict[str, Any]] = []
    for item in items:
        normalized = _normalize_item(item, question_type)
        if normalized:
            quiz.append(normalized)
        if len(quiz) >= count:
            break

    if not quiz:
        logger.warning(
            "quiz.generate.parse_failed %s raw_prefix=%s elapsed_ms=%s reason=no_valid_items",
            request_id, repr(raw[:300]), elapsed_ms,
        )
        return _fail(material_id, "QUIZ_NO_VALID_ITEMS", "생성된 문항 중 유효한 문항이 없습니다.")

    logger.info(
        "quiz.generate.llm.success %s quiz_count=%s elapsed_ms=%s",
        request_id, len(quiz), elapsed_ms,
    )
    return {
        "success": True,
        "materialId": material_id,
        "quiz": quiz,
        "error": None,
    }


def _fail(material_id: Optional[int], code: str, message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "materialId": material_id,
        "quiz": [],
        "error": {"code": code, "message": message},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 라우터
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/api/quiz/generate")
async def quiz_generate_text(request: QuizTextRequest):
    """텍스트 본문 기반 퀴즈 생성 (Spring 호환 단순 계약)."""
    import asyncio

    request_id = uuid.uuid4().hex[:8]
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                generate_quiz_from_text,
                text=request.text,
                title=request.title,
                difficulty=request.difficulty,
                count=request.count,
                question_type=request.questionType,
                material_id=request.materialId,
                request_id=request_id,
            ),
            timeout=QUIZ_TIMEOUT_SECONDS + 10,
        )
    except asyncio.TimeoutError:
        logger.warning("quiz.generate.error %s timeout", request_id)
        result = _fail(request.materialId, "QUIZ_GENERATE_TIMEOUT", "퀴즈 생성 요청이 시간 초과되었습니다.")
    except Exception as e:
        logger.exception("quiz.generate.error %s %s", request_id, repr(e))
        result = _fail(request.materialId, "QUIZ_GENERATE_FAILED", "퀴즈 생성 중 서버 오류가 발생했습니다.")

    status_code = 200 if result.get("success") else 422
    return JSONResponse(content=result, status_code=status_code)
