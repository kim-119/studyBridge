"""
StudyBridge FastAPI AI 서버 — Spring Boot 계약 API + 확장 API
uvicorn main:app --host 0.0.0.0 --port 8000 으로 실행한다.

Spring Boot 계약 (v0.5):
  GET  /api/health
  POST /api/ai/predict/study-time
  POST /api/ai/quiz/generate
  POST /api/ai/multi-chat

확장 라우터 (v0.6, 선택적 로드):
  /api/rag/*, /api/agent/deep-search,
  /api/training-candidates/*, /api/ai/chat, /api/ai/material/*
"""
# ─────────────────────────────────────────────────────────────────────────────
# 1. imports
# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# 2. 환경변수 & 로거
# ─────────────────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("studybridge.fastapi")

# ─────────────────────────────────────────────────────────────────────────────
# 3. policy 모듈 (agent_quality_policy.py / agent_feedback_policy.py)
#    같은 디렉터리에 있으면 import; 없으면 fallback 동작
# ─────────────────────────────────────────────────────────────────────────────
_POLICY_AVAILABLE = False
try:
    from agent_quality_policy import (         # noqa: F401
        normalize_agent_config,
        build_agent_system_prompt,
        validate_prompt_contains_agent_constraints,
        validate_answer_quality,
        revise_answer_to_match_quality_policy,
    )
    from agent_feedback_policy import (        # noqa: F401
        detect_feedback_intent,
        build_feedback_system_prompt,
        build_feedback_user_prompt,
        revise_feedback_output,
        validate_feedback_output as validate_feedback_policy_output,
    )
    _POLICY_AVAILABLE = True
    logger.info("agent_quality_policy / agent_feedback_policy 로드 완료")
except ImportError as _policy_err:
    logger.warning("policy 모듈 로드 실패 (fallback 동작): %s", _policy_err)

# ─────────────────────────────────────────────────────────────────────────────
# 4. FastAPI 앱 + CORS
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="StudyBridge AI Server",
    description="RAG + Deep Search + 지식수준별 답변 차등화 AI Orchestrator",
    version="0.6.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# 5. 설정 상수 (환경변수 우선, 기본값 후순위)
# ─────────────────────────────────────────────────────────────────────────────

# OpenAI
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_OUTPUT_TOKENS: int = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "2000"))
OPENAI_MAX_INPUT_CHARS: int = int(os.getenv("OPENAI_MAX_INPUT_CHARS", "12000"))

# Ollama — 주력 엔진 (Qwen2.5 14B 양자화 권장, vLLM 사용 안 함)
# 서버컴에서 `ollama list`로 실제 모델명 확인 후 .env 수정
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "45"))

# 외부 서비스
TAVILY_API_KEY: Optional[str] = os.getenv("TAVILY_API_KEY")
AWS_ACCESS_KEY_ID: Optional[str] = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY: Optional[str] = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION: str = os.getenv("AWS_REGION", "ap-northeast-2")
AWS_S3_BUCKET: Optional[str] = os.getenv("AWS_S3_BUCKET")

# 학습 시간 예측
STUDY_TIME_MODEL_PATH: str = os.getenv("STUDY_TIME_MODEL_PATH", "./models/study_time_model")

# 타임아웃
AI_RESPONSE_TIMEOUT_SECONDS: int = int(os.getenv("AI_RESPONSE_TIMEOUT_SECONDS", "120"))
QUIZ_GENERATION_TIMEOUT_SECONDS: int = int(os.getenv("QUIZ_GENERATION_TIMEOUT_SECONDS", "15"))
MULTI_CHAT_TIMEOUT_SECONDS: int = int(os.getenv("MULTI_CHAT_TIMEOUT_SECONDS", "180"))
# 모드별 총 타임아웃 (소크라테스/토론은 단계적 처리로 오래 걸리므로 길게).
AI_DEFAULT_TIMEOUT_SECONDS: int = int(os.getenv("AI_DEFAULT_TIMEOUT_SECONDS", "90"))
AI_SOCRATIC_TIMEOUT_SECONDS: int = int(os.getenv("AI_SOCRATIC_TIMEOUT_SECONDS", "240"))
AI_DEBATE_TIMEOUT_SECONDS: int = int(os.getenv("AI_DEBATE_TIMEOUT_SECONDS", "300"))
AI_MULTI_AGENT_TIMEOUT_SECONDS: int = int(os.getenv("AI_MULTI_AGENT_TIMEOUT_SECONDS", "300"))
AI_VALIDATION_ENABLED: bool = os.getenv("AI_VALIDATION_ENABLED", "false").lower() in ("true", "1", "yes")
AI_VALIDATION_TIMEOUT_SECONDS: int = int(os.getenv("AI_VALIDATION_TIMEOUT_SECONDS", "30"))

# 퀴즈 생성
DEFAULT_QUIZ_COUNT: int = int(os.getenv("DEFAULT_QUIZ_COUNT", "3"))
DEFAULT_QUIZ_TIME_LIMIT_SECONDS: int = int(os.getenv("DEFAULT_QUIZ_TIME_LIMIT_SECONDS", "30"))
QUIZ_OPTIONS_COUNT: int = 4  # 4지선다 고정

# multi-chat
MULTI_CHAT_MAX_ROUNDS: int = int(os.getenv("MULTI_CHAT_MAX_ROUNDS", "3"))
PREVIOUS_ANSWERS_LIMIT: int = int(os.getenv("PREVIOUS_ANSWERS_LIMIT", "20"))
AGENT_ANSWER_MAX_CHARS: int = int(os.getenv("AGENT_ANSWER_MAX_CHARS", "1200"))
# 사용자에게 보이는 실제 답변 길이 제한(문자). 0이면 절단 비활성화(기본).
# 속도/비용 제어는 문자 절단이 아니라 max_tokens/timeout으로 한다.
AI_MAX_RESPONSE_CHARS: int = int(os.getenv("AI_MAX_RESPONSE_CHARS", "0"))
# LLM 생성 토큰 상한 (답변 잘림 방지를 위해 충분히 크게).
AI_ANSWER_MAX_TOKENS: int = int(os.getenv("AI_ANSWER_MAX_TOKENS", "2048"))
# 로그에만 적용되는 미리보기 길이 (실제 응답에는 영향 없음).
AI_LOG_PREVIEW_CHARS: int = int(os.getenv("AI_LOG_PREVIEW_CHARS", "300"))
SYNTHESIS_AGENT_NAME: str = "종합정리봇"
DEFAULT_AGENT_NAME: str = os.getenv("DEFAULT_AGENT_NAME", "스터디봇")

# 가중 평균 예측 가중치 (최근 7일, 최근일수록 높음)
_PREDICT_WEIGHTS: List[float] = [0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.22]

# fallback 문구 상수 (각 endpoint에 복붙하지 않음)
_FALLBACK_LLM_UNAVAILABLE = (
    "현재 AI 서비스에 일시적으로 접근할 수 없습니다. 잠시 후 다시 시도해 주세요."
)
_FALLBACK_TIMEOUT = (
    "AI 응답 시간이 초과되었습니다. 에이전트 수를 줄이거나 잠시 후 다시 시도해 주세요."
)
_FALLBACK_QUIZ_TITLE = "자료 기반 학습 퀴즈 (기본 안내형)"

# ─────────────────────────────────────────────────────────────────────────────
# 6. LLM 클라이언트 초기화
# ─────────────────────────────────────────────────────────────────────────────
openai_client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ─────────────────────────────────────────────────────────────────────────────
# 7. 공통 유틸 함수
# ─────────────────────────────────────────────────────────────────────────────

def trim_prompt(text: str, max_chars: int = OPENAI_MAX_INPUT_CHARS) -> str:
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[안내] 입력이 너무 길어 일부 내용이 잘렸습니다."
    return text


def safe_strip(value: Any, default: str = "", max_len: int = 2000) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return (text[:max_len] if len(text) > max_len else text) or default


# 에이전트가 천편일률적으로 시작하는 상투적 도입부 (성격이 죽는 GPT 문체)
_FORBIDDEN_OPENINGS = (
    "안녕하세요", "좋은 질문입니다", "좋은 질문이에요", "궁금하신가요",
    "다음과 같이 설명할 수 있습니다", "핵심 개념은 다음과 같습니다",
    "이 과정은 매우 중요합니다", "요약하자면",
)
_TRAILING_FILLER = (
    "더 궁금한 점이 있으면 질문해주세요", "더 궁금한 점이 있으면 언제든 질문해주세요",
    "도움이 되었길 바랍니다",
)


def strip_generic_phrases(text: str) -> str:
    """상투적 도입부/맺음말을 제거해 성격이 드러나는 답변을 보존한다 (내용은 자르지 않음)."""
    if not text:
        return text
    stripped = text.lstrip()
    # 첫 문장이 금지 도입부로 시작하면 그 문장만 제거
    for opener in _FORBIDDEN_OPENINGS:
        if stripped.startswith(opener):
            # 첫 문장 끝(마침표/줄바꿈)까지 제거
            m = re.search(r"[.!?\n]", stripped)
            stripped = stripped[m.end():].lstrip() if m else ""
            break
    # 상투적 맺음말 제거
    for tail in _TRAILING_FILLER:
        idx = stripped.rfind(tail)
        if idx != -1 and idx >= len(stripped) - len(tail) - 3:
            stripped = stripped[:idx].rstrip()
    return stripped or text  # 전부 비면 원문 유지(빈 답변 방지)


def clean_ai_answer(text: str) -> str:
    """마크다운 제거, 과도한 개행 정리, 상투적 도입부 제거."""
    if not text:
        return ""
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"(?m)^\s*#{2,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*```[a-zA-Z0-9_-]*\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = strip_generic_phrases(text)
    return text.strip()


def preview_text(text: str, limit: int = AI_LOG_PREVIEW_CHARS) -> str:
    """로그 출력 전용 미리보기. 실제 API 응답에는 절대 사용하지 않는다."""
    if not text:
        return ""
    return text[:limit] + ("..." if len(text) > limit else "")


def safe_trim_answer(text: str, max_chars: int) -> str:
    """
    긴 답변을 문장 끝/줄바꿈/공백 경계에서 안전하게 자른다.
    answer[:max_chars] 같은 단순 절단은 문장 중간에서 잘려 broken answer를 만들 수 있으므로 사용하지 않는다.
    max_chars<=0이면 절단을 비활성화하고 원문 전체를 반환한다(사용자 답변 보존).
    """
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    min_cut = int(max_chars * 0.5)

    # 1. 한국어/영어 문장 종결 지점 (마침표/물음표/느낌표 + 공백 또는 끝)
    sentence_end = -1
    for match in re.finditer(r"[.!?][\"')\]]?(?=\s|$)", truncated):
        if match.end() >= min_cut:
            sentence_end = match.end()
    if sentence_end > 0:
        return truncated[:sentence_end].rstrip()

    # 2. 줄바꿈 경계
    newline_cut = truncated.rfind("\n")
    if newline_cut >= min_cut:
        return truncated[:newline_cut].rstrip()

    # 3. 공백 경계 (단어 중간 절단 방지)
    space_cut = truncated.rfind(" ")
    if space_cut >= min_cut:
        return truncated[:space_cut].rstrip()

    return truncated.rstrip()


def sanitize_answer_for_spring(answer: str) -> str:
    """
    Spring DTO 반환 전 정리. 사용자에게 보이는 답변은 임의 절단하지 않는다.
    AI_MAX_RESPONSE_CHARS>0으로 명시 설정한 경우에만 safe_trim_answer로 안전 절단한다.
    """
    text = clean_ai_answer(answer)
    return safe_trim_answer(text, AI_MAX_RESPONSE_CHARS)


def _to_agent_dict(agent: Any) -> Dict[str, Any]:
    """AgentProfile Pydantic 모델 또는 dict를 plain dict로 변환."""
    if hasattr(agent, "model_dump"):
        return agent.model_dump()
    if hasattr(agent, "dict"):
        return agent.dict()
    return agent if isinstance(agent, dict) else {}


# ─────────────────────────────────────────────────────────────────────────────
# 8. LLM 호출 함수 (Ollama 우선 → OpenAI fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _call_ollama(
    system: str, user: str, max_tokens: int = 600, temperature: float = 0.5
) -> Optional[str]:
    """Ollama /api/chat 호출. 서버 불응 시 None 반환."""
    try:
        probe = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if probe.status_code != 200:
            return None
    except Exception:
        return None

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        logger.warning("Ollama 호출 실패: %s", e)
        return None


def _call_openai(
    system: str, user: str, max_tokens: int = 800, temperature: float = 0.5
) -> Optional[str]:
    """OpenAI Chat Completions API 호출. 실패 시 None 반환."""
    if not openai_client:
        return None
    try:
        resp = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": trim_prompt(system)},
                {"role": "user", "content": trim_prompt(user)},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("OpenAI 호출 실패: %s", e)
        return None


def _call_llm(
    system: str, user: str, max_tokens: int = 600, temperature: float = 0.5
) -> str:
    """Ollama 우선, 실패 시 OpenAI, 둘 다 실패 시 fallback 문구."""
    result = _call_ollama(system, user, max_tokens, temperature)
    if result and result.strip():
        return result.strip()
    result = _call_openai(system, user, max_tokens, temperature)
    if result and result.strip():
        return result.strip()
    return _FALLBACK_LLM_UNAVAILABLE


# ─────────────────────────────────────────────────────────────────────────────
# 9. 학습 시간 예측 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
_tf_model = None
_tf_available: bool = False
_tf_load_attempted: bool = False


def _weighted_average_predict(weekly_seconds: List[float]) -> float:
    """7일 가중 평균 예측 (TF 모델 없을 때 fallback)."""
    return round(sum(w * v for w, v in zip(_PREDICT_WEIGHTS, weekly_seconds)), 1)


def _get_or_load_tf_model() -> bool:
    """TensorFlow 모델 로드 시도. 이미 시도했으면 캐시된 결과 반환."""
    global _tf_model, _tf_available, _tf_load_attempted
    if _tf_load_attempted:
        return _tf_available
    _tf_load_attempted = True
    try:
        import tensorflow as tf  # noqa: F401
        if os.path.exists(STUDY_TIME_MODEL_PATH):
            _tf_model = tf.saved_model.load(STUDY_TIME_MODEL_PATH)
            _tf_available = True
            logger.info("TF 모델 로드 완료: %s", STUDY_TIME_MODEL_PATH)
        else:
            logger.warning("TF 모델 파일 없음: %s. 가중 평균 fallback 사용.", STUDY_TIME_MODEL_PATH)
    except ImportError:
        logger.info("TensorFlow 없음. 가중 평균 fallback 사용.")
    except Exception as e:
        logger.warning("TF 모델 로드 실패: %s. 가중 평균 fallback 사용.", e)
    return _tf_available


def predict_study_time(weekly_seconds: List[float]) -> float:
    """TF 모델 예측 → 실패 시 가중 평균 fallback."""
    if _get_or_load_tf_model() and _tf_model is not None:
        try:
            import numpy as np
            arr = np.array([weekly_seconds], dtype=np.float32)
            return float(_tf_model(arr).numpy()[0][0])
        except Exception as e:
            logger.error("TF 예측 실패, fallback 사용: %s", e)
    return _weighted_average_predict(weekly_seconds)


# ─────────────────────────────────────────────────────────────────────────────
# 10. 퀴즈 생성 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
_QUIZ_SYSTEM_PROMPT_TMPL = (
    "너는 대학교 강의 자료 기반 객관식 퀴즈 출제 전문가다.\n"
    "반드시 4지선다 객관식 문제 {count}개를 만든다.\n"
    "정답은 0-indexed(0~3)로 반환한다.\n"
    "반드시 아래 JSON 배열 형식으로만 응답한다. 다른 텍스트 없이 JSON만 출력한다:\n"
    '[{{"question":"...", "options":["...","...","...","..."], '
    '"correctAnswer":0, "timeLimitSeconds":30}}]'
)

_FALLBACK_QUESTIONS_DATA: List[Dict[str, Any]] = [
    {
        "question": "다음 중 효과적인 학습 방법으로 알려진 것은?",
        "options": [
            "한 번에 몰아서 공부하기",
            "분산 학습(Spaced Repetition) 활용하기",
            "밑줄만 긋고 다시 보지 않기",
            "소리만 듣고 노트 필기 안 하기",
        ],
        "correctAnswer": 1,
        "timeLimitSeconds": 30,
    },
    {
        "question": "학습 내용을 장기 기억으로 전환하는 데 가장 효과적인 방법은?",
        "options": [
            "한 번 읽고 넘어가기",
            "형광펜으로 중요 부분만 표시하기",
            "자신이 배운 내용을 직접 설명해보기 (인출 연습)",
            "공부 후 바로 자기",
        ],
        "correctAnswer": 2,
        "timeLimitSeconds": 30,
    },
    {
        "question": "집중력을 높이기 위한 포모도로 기법에서 기본 집중 시간은?",
        "options": ["10분", "25분", "45분", "60분"],
        "correctAnswer": 1,
        "timeLimitSeconds": 30,
    },
]


def build_fallback_quiz(file_name: str = "", reason: str = "") -> Dict[str, Any]:
    """S3/LLM/PDF 실패 시 기본 안내형 퀴즈 반환."""
    if reason:
        logger.warning("퀴즈 fallback: file=%s reason=%s", file_name, reason)
    return {"quizTitle": _FALLBACK_QUIZ_TITLE, "questions": _FALLBACK_QUESTIONS_DATA}


def _load_pdf_from_s3(s3_key: str) -> bytes:
    import boto3  # 선택적 의존성 — 설치 없으면 ImportError
    s3 = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )
    obj = s3.get_object(Bucket=AWS_S3_BUCKET, Key=s3_key)
    return obj["Body"].read()


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    import fitz  # PyMuPDF
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _parse_quiz_json(llm_output: str) -> List[Dict[str, Any]]:
    """LLM 출력에서 JSON 배열을 파싱하고 유효한 문항만 반환."""
    match = re.search(r"\[.*?\]", llm_output.strip(), re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group())
    except json.JSONDecodeError:
        return []

    validated: List[Dict[str, Any]] = []
    for item in items[:5]:
        options = item.get("options", [])
        correct = int(item.get("correctAnswer", 0))
        if len(options) != QUIZ_OPTIONS_COUNT or not (0 <= correct <= 3):
            continue
        validated.append({
            "question": safe_strip(item.get("question"), "문제를 불러올 수 없습니다."),
            "options": [safe_strip(o) for o in options],
            "correctAnswer": correct,
            "timeLimitSeconds": int(item.get("timeLimitSeconds", DEFAULT_QUIZ_TIME_LIMIT_SECONDS)),
        })
    return validated


def generate_quiz_from_pdf(material_id: int, s3_key: str, file_name: str) -> Dict[str, Any]:
    """S3 → PDF 추출 → LLM 퀴즈 생성. 각 단계 실패 시 fallback 반환."""
    try:
        pdf_bytes = _load_pdf_from_s3(s3_key)
    except Exception as e:
        return build_fallback_quiz(file_name, f"S3 로드 실패: {e}")

    try:
        pdf_text = _extract_pdf_text(pdf_bytes)
        if len(pdf_text.strip()) < 100:
            return build_fallback_quiz(file_name, "PDF 텍스트 부족")
    except Exception as e:
        return build_fallback_quiz(file_name, f"PDF 추출 실패: {e}")

    system = _QUIZ_SYSTEM_PROMPT_TMPL.format(count=DEFAULT_QUIZ_COUNT)
    user = (
        f"## 자료명\n{file_name}\n\n"
        f"## 자료 내용\n{pdf_text[:2500]}\n\n"
        f"위 자료를 기반으로 객관식 퀴즈 {DEFAULT_QUIZ_COUNT}개를 JSON 배열 형식으로 출제하라."
    )
    # OpenAI 우선, Ollama fallback
    llm_output = _call_openai(system, user, max_tokens=1200, temperature=0.3)
    if not llm_output:
        llm_output = _call_ollama(system, user, max_tokens=1200, temperature=0.3)
    if not llm_output:
        return build_fallback_quiz(file_name, "LLM 응답 없음")

    questions = _parse_quiz_json(llm_output)
    if not questions:
        return build_fallback_quiz(file_name, "JSON 파싱 실패")

    return {
        "quizTitle": f"[{file_name}] 자료 기반 학습 퀴즈",
        "questions": questions,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11. multi-chat 프롬프트 빌더
# ─────────────────────────────────────────────────────────────────────────────

# 로컬 personality → agent_quality_policy 호환 매핑
_PERSONALITY_COMPAT: Dict[str, str] = {
    "친절_설명형": "친근함",
    "비판적_분析형": "솔직함",
    "논리적_탐구형": "전문적",
    "창의적_확장형": "독특함",
    "간결_요약형": "효율적",
    "冷소적": "냉소적",
}


def _normalize_agent_for_policy(agent_dict: Dict[str, Any]) -> Dict[str, Any]:
    """로컬 personality 값을 agent_quality_policy 호환 값으로 매핑."""
    d = dict(agent_dict)
    personality = d.get("personality") or ""
    d["personality"] = _PERSONALITY_COMPAT.get(personality, personality)
    d.setdefault("tone", d["personality"])
    return d


_LEARNING_MODES = ("basic", "socratic", "debate")


def normalize_learning_mode(value: Optional[str]) -> str:
    """프론트에서 전달한 learningMode를 basic/socratic/debate로 정규화한다."""
    v = str(value or "basic").strip().lower()
    return v if v in _LEARNING_MODES else "basic"


def resolve_multi_chat_timeout(mode: Optional[str], learning_mode: str) -> int:
    """
    mode/learning_mode 기준으로 multi-chat 총 타임아웃(초)을 결정한다.
    소크라테스/토론/멀티에이전트는 단계적 검토로 오래 걸리므로 길게 허용한다.
    Spring 측 대기시간보다 약간 짧거나 같게 두어 FastAPI가 우아한 fallback을 반환할 수 있게 한다.
    """
    m = str(mode or "").strip().lower()
    if learning_mode == "socratic" or "socratic" in m:
        return AI_SOCRATIC_TIMEOUT_SECONDS
    if learning_mode == "debate" or "debate" in m:
        return AI_DEBATE_TIMEOUT_SECONDS
    if "multi_agent" in m or "multi-agent" in m:
        return AI_MULTI_AGENT_TIMEOUT_SECONDS
    return max(AI_DEFAULT_TIMEOUT_SECONDS, MULTI_CHAT_TIMEOUT_SECONDS)


def build_learning_mode_instruction(learning_mode: str, knowledge_level: str) -> str:
    """학습 진행 모드(소크라테스/토론)에 따른 추가 답변 지침을 생성한다."""
    if learning_mode == "socratic":
        return (
            "[학습 진행 방식: 소크라테스 모드]\n"
            "정답을 곧바로 길게 설명하지 말고 다음 순서를 따라 답하라.\n"
            "1) 사용자가 현재 어디까지 이해하고 있는지 짧게 확인한다.\n"
            "2) 사용자의 사고를 유도하는 핵심 질문을 1~2개 제시한다.\n"
            "3) 막히지 않도록 가벼운 힌트를 함께 제공한다.\n"
            "4) 사용자가 답하면 다음 단계로 자연스럽게 이어가겠다는 태도로 마무리한다.\n"
            f"질문과 힌트의 난이도는 학습자의 지식수준('{knowledge_level}')에 맞춘다 — "
            "입문 수준이면 쉬운 질문 위주로, 학사 수준이면 개념 간 관계를 묻는 질문 위주로, "
            "박사/전문가 수준이면 원리·한계·반례를 묻는 질문 위주로 구성한다. "
            "사용자를 몰아붙이지 말고 학습자 수준에 맞춰 친절하게 유도한다."
        )
    if learning_mode == "debate":
        return (
            "[학습 진행 방식: 토론 모드]\n"
            "다른 에이전트들과 같은 결론을 그대로 반복하지 말고, 너만의 관점과 근거를 제시하라. "
            "단정적으로 결론짓기보다 '~라고 볼 수 있다', '다른 관점에서는' 같은 표현으로 "
            "다른 시각이 있을 수 있음을 인정하는 태도로 답하라."
        )
    return ""


# 성격(personality) → PersonaDNA: voice / signature_move / forbidden 을 한 블록으로 강제.
# 라벨이 아니라 '사고방식'으로 작동하도록 system prompt에 직접 주입한다.
_PERSONA_DNA: Dict[str, str] = {
    "친근함": (
        "[PersonaDNA: 친근한 설명형]\n"
        "- voice: 따뜻하지만 가볍지 않게. 상대를 어린아이 취급하지 않는다.\n"
        "- signature_move: 생활 속 비유 1개 + '한마디로 말하면' 식 짧은 정리.\n"
        "- forbidden: 과장된 상담사 말투, 모든 내용을 번호 목록으로만 나열."
    ),
    "솔직함": (
        "[PersonaDNA: 비판적 분석형 — 츤데레 코치]\n"
        "- voice: 살짝 까칠하지만 도와주려는 태도. 두루뭉술함을 싫어한다.\n"
        "- signature_move: 흔한 오개념 1개를 반드시 교정 + 마지막에 짧은 코칭 한 줄.\n"
        "- forbidden: 인신공격, 과도한 비난, 친절형처럼 둥글둥글한 말투."
    ),
    "전문적": (
        "[PersonaDNA: 논리적 분석형]\n"
        "- voice: 차분하고 명확. 잡담 없이 구조부터 잡고 용어를 정확히 쓴다.\n"
        "- signature_move: '조건 → 과정 → 결과' 구조 + 마지막에 핵심 변수/주의점.\n"
        "- forbidden: 감성적 문장 남발, 비유 중심 설명, 장황한 서론."
    ),
    "독특함": (
        "[PersonaDNA: 창의적 비유형]\n"
        "- voice: 시각적이고 기억에 남는 문장. 개념을 하나의 장면처럼 보여준다.\n"
        "- signature_move: 강한 은유 1개로 시작 → 개념 매핑 → 기억용 한 줄.\n"
        "- forbidden: 비유만 있고 정확한 설명이 없는 답변, 시처럼 과한 꾸밈, 교과서 목차식."
    ),
    "효율적": (
        "[PersonaDNA: 간결 핵심형]\n"
        "- voice: 짧고 단단하게. 불필요한 말은 버리고 핵심만 찍는다.\n"
        "- signature_move: 결론부터 → 이유 3개 이하 → 예시 1개 → 암기 포인트.\n"
        "- forbidden: 긴 서론, 과한 비유, 5개 이상 목록 남발."
    ),
    "냉소적": (
        "[PersonaDNA: 냉소적 현실형]\n"
        "- voice: 건조하고 현실적. 환상을 걷어내고 실제로 중요한 것만 말한다.\n"
        "- signature_move: 흔한 착각을 짚고, 실제로 쓰이는 부분만 콕 집는다.\n"
        "- forbidden: 응원성 멘트, 인신공격, 핵심 없는 비꼬기."
    ),
}

_UNIVERSAL_STYLE_RULES = (
    "[공통 답변 규칙]\n"
    "- 첫 문장부터 너의 성격이 드러나야 한다. 상투적 인사말로 시작하지 마라.\n"
    "- 모든 답변을 '핵심 개념 / 원리 / 단계' 구조로 쓰지 마라.\n"
    "- 답변 안에 기억 장치 최소 1개(비유, 반례, 짧은 공식, 한 줄 문장, 실생활 장면, 비교 구조)를 넣어라.\n"
    "- 비유는 개념의 보조 도구일 뿐 개념 자체를 대체하면 안 되고, 사실을 꾸며내지 마라.\n"
    "- 금지 표현: '안녕하세요', '좋은 질문입니다', '궁금하신가요', '다음과 같이 설명할 수 있습니다', "
    "'핵심 개념은 다음과 같습니다', '요약하자면', '더 궁금한 점이 있으면 질문해주세요'."
)


def build_persona_dna_block(agent_dict: Dict[str, Any]) -> str:
    """성격 라벨을 PersonaDNA(사고방식)로 변환한 system prompt 블록."""
    personality = _PERSONALITY_COMPAT.get(
        agent_dict.get("personality") or "", agent_dict.get("personality") or ""
    )
    dna = _PERSONA_DNA.get(personality, "")
    return "\n\n".join(p for p in (dna, _UNIVERSAL_STYLE_RULES) if p)


def build_multi_agent_system_prompt(agent: Any, context: str = "", learning_mode: str = "basic") -> str:
    """
    agent_quality_policy.build_agent_system_prompt 우선 사용.
    실패 시 직접 빌드한다. learning_mode에 따라 소크라테스/토론 지침을 덧붙인다.
    """
    agent_dict = _normalize_agent_for_policy(_to_agent_dict(agent))
    knowledge_level = agent_dict.get("knowledgeLevel") or "학사 수준"
    mode_instruction = build_learning_mode_instruction(learning_mode, knowledge_level)
    persona_dna = build_persona_dna_block(agent_dict)

    if _POLICY_AVAILABLE:
        try:
            normalized = normalize_agent_config(agent_dict, user_message="")
            base_prompt = build_agent_system_prompt(normalized)
            parts = [base_prompt, persona_dna]
            if mode_instruction:
                parts.append(mode_instruction)
            if context:
                parts.append(context)
            return "\n\n".join(p for p in parts if p)
        except Exception as e:
            logger.debug("policy prompt 빌드 실패, fallback 사용: %s", e)

    # fallback 직접 빌드
    name = agent_dict.get("name", DEFAULT_AGENT_NAME)
    level = agent_dict.get("knowledgeLevel") or "학사"
    personality = agent_dict.get("personality") or "친근함"
    parts = [
        f"너는 StudyBridge AI 에이전트 '{name}'이다.",
        f"지식 수준: {level} / 성격: {personality}",
        "반드시 한국어로 답변한다.",
        "학습에 도움이 되는 실질적인 내용을 제공한다.",
        persona_dna,
    ]
    if mode_instruction:
        parts.append(f"\n{mode_instruction}")
    if context:
        parts.append(f"\n{context}")
    return "\n".join(p for p in parts if p)


def build_context_from_previous_answers(
    previous_answers: List[Any], max_items: int = PREVIOUS_ANSWERS_LIMIT
) -> str:
    """이전 답변 최근 N개를 컨텍스트 문자열로 변환."""
    if not previous_answers:
        return ""
    recent = previous_answers[-max_items:]
    lines = ["[이전 대화 맥락]"]
    for item in recent:
        name = getattr(item, "agentName", None) or (item.get("agentName", "") if isinstance(item, dict) else "")
        ans = getattr(item, "answer", None) or (item.get("answer", "") if isinstance(item, dict) else "")
        role = getattr(item, "role", None) or "ASSISTANT"
        if ans.strip():
            lines.append(f"[{role}] {name}: {ans.strip()[:300]}")
    return "\n".join(lines)


# 에이전트별로 서로 다른 '설명 렌즈'를 강제해 천편일률적 교과서 구조를 깬다.
_STYLE_SEEDS = (
    "생활 속 장면과 비유로 직관부터 잡아라.",
    "흔히 빠지는 오개념을 먼저 잡아내고 교정하라.",
    "조건 → 과정 → 결과의 인과 구조로 분석하라.",
    "강한 은유 이미지로 시작해 실제 개념과 연결하라.",
    "결론부터 말하고 핵심 이유만 압축하라.",
    "변수·조건·한계와 실제 적용 관점까지 짚어라.",
    "반례와 예외 상황을 중심으로 설명하라.",
    "시험/실전에서 바로 쓰는 포인트 중심으로 정리하라.",
)


def build_agent_turn_instruction(agent_index: int, total_agents: int) -> str:
    """
    에이전트마다 서로 다른 설명 렌즈(style seed)를 배정한다.
    모든 에이전트가 '핵심 개념/원리/요약'을 반복하던 구조를 제거하고,
    각자 다른 관점으로 같은 지식을 설명하도록 유도한다.
    """
    if total_agents <= 1:
        return ""
    seed = _STYLE_SEEDS[agent_index % len(_STYLE_SEEDS)]
    return (
        f"[너만의 설명 렌즈] {seed}\n"
        "다른 에이전트와 같은 첫 문장, 같은 목차 구조, 같은 비유를 절대 반복하지 마라. "
        "이미 나온 설명을 복사하거나 재배열하지 말고, 너의 성격에 맞는 다른 관점으로 설명하라."
    )


def select_agents_for_response(
    agents: List[Any], target_id: Optional[int]
) -> List[Any]:
    """targetAgentId 필터링. 매칭 없으면 전체 반환."""
    if target_id is None:
        return agents
    filtered = [
        a for a in agents
        if getattr(a, "agentId", None) == target_id or getattr(a, "id", None) == target_id
    ]
    if not filtered:
        logger.warning("targetAgentId=%s 매칭 없음. 전체 에이전트 사용.", target_id)
        return agents
    return filtered


def generate_single_agent_response(
    agent: Any,
    message: str,
    context: str,
    agent_index: int,
    total_agents: int,
    learning_mode: str = "basic",
) -> str:
    """단일 에이전트 답변 생성 (Ollama 우선 → OpenAI fallback)."""
    system_prompt = build_multi_agent_system_prompt(agent, context, learning_mode)
    turn_instr = build_agent_turn_instruction(agent_index, total_agents)

    user_parts: List[str] = []
    if turn_instr:
        user_parts.append(f"[이번 역할] {turn_instr}")
    user_parts.append(f"[사용자 메시지] {message}")
    user_prompt = "\n".join(user_parts)

    raw = _call_llm(system_prompt, user_prompt, max_tokens=AI_ANSWER_MAX_TOKENS)
    return clean_ai_answer(raw)


def build_final_synthesis_answer(
    answers: List[Dict[str, str]], message: str
) -> str:
    """showFinalSynthesis=True일 때 종합 답변 생성."""
    existing = "\n".join(
        f"[{a['agentName']}] {a['answer'][:200]}" for a in answers
    )
    system = (
        "너는 여러 에이전트의 답변을 종합하는 정리 전문가다. "
        "각 에이전트의 핵심 포인트를 통합하여 최종 결론을 한국어로 명확하게 제시하라. "
        "중복 내용은 제거하고 핵심만 압축하라."
    )
    user = (
        f"[사용자 질문] {message}\n\n"
        f"[에이전트 답변들]\n{existing}\n\n"
        "위 내용을 종합하여 최종 정리를 제공하라."
    )
    return clean_ai_answer(_call_llm(system, user, max_tokens=AI_ANSWER_MAX_TOKENS))


# ─────────────────────────────────────────────────────────────────────────────
# 12. 검증 래퍼 (agent_quality_policy 재사용)
# ─────────────────────────────────────────────────────────────────────────────

def is_broken_answer(text: str) -> bool:
    """revise 결과가 비정상인지 판단한다. True면 원본 답변을 유지해야 한다."""
    if not text or len(text.strip()) < 80:
        return True
    stripped = text.strip()
    if stripped.count("(") > stripped.count(")"):
        return True
    if stripped.count("[") > stripped.count("]"):
        return True
    if stripped.count("{") > stripped.count("}"):
        return True
    broken_endings = (
        "그리고", "하지만", "즉", "예를 들어",
        "객체", "메서드", "클래스", "(", "[", "{", ",", ":", "-",
    )
    if stripped.endswith(broken_endings):
        return True
    return False


def should_use_internal_collaboration(mode: str) -> bool:
    """mode 값이 명시적 협업 모드일 때만 True. parallel/None 등은 False."""
    return mode in ("internal_collaboration", "collaboration", "natural_collaboration")


def validate_and_revise_agent_answer(
    answer: str,
    agent_payload: Dict[str, Any],
    user_message: str,
    response_mode: str = "general",
) -> Tuple[str, Dict[str, Any]]:
    """
    1. normalize_agent_config
    2. validate_prompt_contains_agent_constraints (로그만)
    3. validate_answer_quality
    4. 실패 시 revise_answer_to_match_quality_policy
    5. 재생성 실패 시 원문 반환

    반환: (최종 답변, 검증 메타데이터)
    메타데이터는 로그용 — Spring 응답에 노출하지 않는다.
    """
    if not _POLICY_AVAILABLE or not AI_VALIDATION_ENABLED:
        reason = "policy_unavailable" if not _POLICY_AVAILABLE else "validation_disabled"
        return answer, {"skipped": True, "reason": reason}

    try:
        agent_config = normalize_agent_config(
            _normalize_agent_for_policy(agent_payload), user_message=user_message
        )
    except Exception as e:
        logger.warning("normalize_agent_config 실패: %s", e)
        return answer, {"error": str(e)}

    # prompt 제약 경고 (로그만)
    try:
        prompt_text = build_agent_system_prompt(agent_config)
        warnings = validate_prompt_contains_agent_constraints(prompt_text, agent_config)
        if warnings:
            logger.debug("prompt 제약 경고: %s", warnings)
    except Exception:
        warnings = []

    # 품질 검증
    try:
        validation = validate_answer_quality(answer, agent_config, user_message)
    except Exception as e:
        logger.warning("validate_answer_quality 실패: %s", e)
        return answer, {"error": str(e)}

    meta: Dict[str, Any] = {
        "passed": validation.get("passed", True),
        "score": validation.get("score", 0.0),
        "issues": validation.get("issues", []),
        "prompt_warnings": warnings,
    }

    if validation.get("passed", True):
        return answer, meta

    # 품질 미달 → revise 시도 (원본 보존 원칙)
    logger.info(
        "답변 품질 미달 → revise 시도 score=%.2f issues=%s",
        validation.get("score", 0), validation.get("issues", []),
    )
    original_answer = answer
    try:
        revised = revise_answer_to_match_quality_policy(
            answer=answer,
            agent_config=agent_config,
            validation_result=validation,
            user_message=user_message,
            openai_client=openai_client,
            model=OPENAI_MODEL,
        )
        cleaned_revised = clean_ai_answer(revised) if revised else ""
        if cleaned_revised and not is_broken_answer(cleaned_revised):
            meta["revised"] = True
            return cleaned_revised, meta
        logger.warning("revise 결과 비정상; 원본 답변 유지")
        meta["revised"] = False
        return original_answer, meta
    except Exception as e:
        logger.warning("revise_answer 실패; 원본 답변 유지: %s", e)
        meta["revised"] = False
        return original_answer, meta


def build_fallback_agent_answer(agent_name: str, reason: str = "") -> str:
    if reason:
        logger.warning("에이전트 fallback: agent=%s reason=%s", agent_name, reason)
    return _FALLBACK_LLM_UNAVAILABLE


def build_fallback_multi_chat_response(mode: str, agent_name: str, reason: str = "") -> Dict[str, Any]:
    if reason:
        logger.warning("multi-chat fallback: reason=%s", reason)
    return {
        "mode": mode,
        "answers": [{"agentName": agent_name, "answer": _FALLBACK_LLM_UNAVAILABLE}],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 13. Pydantic 스키마 (Spring 계약 필드명 camelCase 유지)
# ─────────────────────────────────────────────────────────────────────────────

class StudyTimePredictRequest(BaseModel):
    userId: int = Field(..., description="사용자 ID")
    weeklyStudySeconds: List[float] = Field(..., description="최근 7일 학습 시간 (초 단위)")


class StudyTimePredictResponse(BaseModel):
    predictedStudySeconds: float


class QuizGenerateRequest(BaseModel):
    materialId: int = Field(..., description="자료 ID")
    s3Key: str = Field(..., description="S3 오브젝트 키")
    fileName: str = Field(..., description="원본 파일명")


class QuizQuestion(BaseModel):
    question: str
    options: List[str] = Field(..., min_length=4, max_length=4)
    correctAnswer: int = Field(..., ge=0, le=3)
    timeLimitSeconds: int = Field(DEFAULT_QUIZ_TIME_LIMIT_SECONDS)


class QuizGenerateResponse(BaseModel):
    quizTitle: str
    questions: List[QuizQuestion]


class PreviousAnswer(BaseModel):
    agentName: str
    answer: str
    role: str = "ASSISTANT"
    agentId: Optional[int] = None


class AgentProfile(BaseModel):
    id: Optional[int] = None
    agentId: Optional[int] = None
    name: str
    role: Optional[str] = None
    personality: Optional[str] = None
    personalityStrength: Optional[str] = None
    style: Optional[str] = None
    tone: Optional[str] = None
    knowledgeLevel: Optional[str] = None
    customInstruction: Optional[str] = None


class MultiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="사용자 메시지")
    mode: str = Field("multi_agent_discussion")
    # 학습 진행 방식: basic(기본 채팅) / socratic(소크라테스) / debate(토론). mode와 별개 필드.
    learningMode: Optional[str] = Field("basic")
    rounds: int = Field(3, ge=1, le=5)
    showFinalSynthesis: bool = Field(True)
    targetAgentId: Optional[int] = None
    previousAnswers: List[PreviousAnswer] = Field(default_factory=list)
    agents: List[AgentProfile] = Field(default_factory=list)


class AgentAnswer(BaseModel):
    agentName: str
    answer: str


class InitialAnswerStep(BaseModel):
    """1차: 에이전트가 독립적으로 생성한 최초 답변 (safe trim 적용 후 안정된 텍스트)."""
    agentName: str
    answer: str


class ValidatedAnswerStep(BaseModel):
    """2차: 품질 검증/revise 결과. 검증 비활성화 시 원본 답변 + 안내 issue를 담는다."""
    agentName: str
    answer: str
    score: Optional[float] = None
    issues: List[str] = Field(default_factory=list)
    revised: bool = False


class PeerFeedbackStep(BaseModel):
    """3차: 에이전트 간 상호 피드백 (토론 모드 등에서만 생성)."""
    fromAgent: str
    toAgent: str
    feedback: str


class ProcessSteps(BaseModel):
    """1차/2차/3차 생성 과정 — 선택 필드. 없으면 프론트는 '과정 데이터 없음'으로 처리한다."""
    initialAnswers: List[InitialAnswerStep] = Field(default_factory=list)
    validatedAnswers: List[ValidatedAnswerStep] = Field(default_factory=list)
    peerFeedback: List[PeerFeedbackStep] = Field(default_factory=list)


class MultiChatResponse(BaseModel):
    mode: str
    answers: List[AgentAnswer]
    # 선택 필드 — 1차/2차/3차 생성 과정. 기존 answers 계약은 그대로 유지한다.
    processSteps: Optional[ProcessSteps] = None


# ─────────────────────────────────────────────────────────────────────────────
# 14. 동기 실행 함수 (asyncio.to_thread에서 호출)
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_AGENT_PROFILE = AgentProfile(
    id=0, agentId=0, name=DEFAULT_AGENT_NAME, role="학습 도우미",
    personality="친절_설명형", personalityStrength="moderate", knowledgeLevel="학사",
)


# ─────────────────────────────────────────────────────────────────────────────
# 14-A. 병렬 에이전트 실행 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _get_agent_name(agent: Any) -> str:
    if hasattr(agent, "name"):
        return agent.name or "에이전트"
    if isinstance(agent, dict):
        return (
            agent.get("name")
            or agent.get("agentName")
            or agent.get("displayName")
            or "에이전트"
        )
    return "에이전트"


def _make_agent_timeout_answer(agent_name: str) -> AgentAnswer:
    return AgentAnswer(
        agentName=agent_name,
        answer=f"{agent_name} 응답 생성이 지연되었습니다. 잠시 후 다시 시도해 주세요.",
    )


def _make_agent_error_answer(agent_name: str) -> AgentAnswer:
    return AgentAnswer(
        agentName=agent_name,
        answer=f"{agent_name} 응답 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
    )


def _build_validated_step(agent_name: str, final_answer: str, meta: Dict[str, Any]) -> ValidatedAnswerStep:
    """validate_and_revise_agent_answer의 메타데이터를 2차 검증 표시용 데이터로 변환한다."""
    if meta.get("skipped"):
        if meta.get("reason") == "validation_disabled":
            issue = "현재 시연 안정성을 위해 품질 검증은 비활성화되어 원본 답변을 유지했습니다."
        else:
            issue = "검증 모듈을 사용할 수 없어 원본 답변을 유지했습니다."
        return ValidatedAnswerStep(agentName=agent_name, answer=final_answer, score=None, issues=[issue], revised=False)

    if meta.get("error"):
        return ValidatedAnswerStep(
            agentName=agent_name, answer=final_answer, score=None,
            issues=["검증 중 오류가 발생하여 원본 답변을 유지했습니다."], revised=False,
        )

    score = meta.get("score")
    issues = [str(i) for i in (meta.get("issues") or [])][:5]
    return ValidatedAnswerStep(
        agentName=agent_name,
        answer=final_answer,
        score=float(score) if isinstance(score, (int, float)) else None,
        issues=issues,
        revised=bool(meta.get("revised", False)),
    )


def _make_agent_run_timeout_result(agent_name: str) -> Dict[str, Any]:
    answer = _make_agent_timeout_answer(agent_name)
    return {
        "agentName": agent_name,
        "initialAnswer": answer.answer,
        "finalAnswer": answer,
        "validatedStep": ValidatedAnswerStep(
            agentName=agent_name, answer=answer.answer, score=None,
            issues=["응답 생성이 지연되어 검증을 진행하지 못했습니다."], revised=False,
        ),
    }


def _make_agent_run_error_result(agent_name: str) -> Dict[str, Any]:
    answer = _make_agent_error_answer(agent_name)
    return {
        "agentName": agent_name,
        "initialAnswer": answer.answer,
        "finalAnswer": answer,
        "validatedStep": ValidatedAnswerStep(
            agentName=agent_name, answer=answer.answer, score=None,
            issues=["답변 생성 중 오류가 발생하여 검증을 진행하지 못했습니다."], revised=False,
        ),
    }


def _run_single_agent_sync(
    agent: AgentProfile,
    message: str,
    context: str,
    agent_index: int,
    total_agents: int,
    learning_mode: str = "basic",
) -> Dict[str, Any]:
    """
    ThreadPoolExecutor에서 호출되는 단일 에이전트 동기 실행.
    1차(원본)/2차(검증) 데이터를 함께 수집해 반환한다 (processSteps 구성용).
    """
    agent_name = _get_agent_name(agent)
    try:
        raw = generate_single_agent_response(
            agent=agent,
            message=message,
            context=context,
            agent_index=agent_index,
            total_agents=total_agents,
            learning_mode=learning_mode,
        )
        initial_answer = sanitize_answer_for_spring(raw)

        # validate_and_revise_agent_answer 내부에서 AI_VALIDATION_ENABLED 체크
        final_text, meta = validate_and_revise_agent_answer(
            answer=raw,
            agent_payload=_to_agent_dict(agent),
            user_message=message,
            response_mode="general",
        )
        logger.debug(
            "single_agent done agent=%s passed=%s score=%s validation_enabled=%s",
            agent_name, meta.get("passed"), meta.get("score"), AI_VALIDATION_ENABLED,
        )
        final_answer_text = sanitize_answer_for_spring(final_text)
        return {
            "agentName": agent_name,
            "initialAnswer": initial_answer,
            "finalAnswer": AgentAnswer(agentName=agent_name, answer=final_answer_text),
            "validatedStep": _build_validated_step(agent_name, final_answer_text, meta),
        }
    except Exception as e:
        logger.error("에이전트 '%s' 답변 실패: %s", agent_name, e)
        return _make_agent_run_error_result(agent_name)


def generate_peer_feedback_for_debate(
    agents: List[AgentProfile],
    final_answers: List[AgentAnswer],
    message: str,
) -> List[PeerFeedbackStep]:
    """
    토론 모드 3차: 에이전트들이 순환 구조(0→1, 1→2, ... n-1→0)로 서로의 답변에
    짧은 보완/비판 피드백을 제시한다. 내부 프롬프트 전문은 노출하지 않는다.
    """
    total = len(agents)
    if total < 2:
        return []

    answer_by_name = {a.agentName: a.answer for a in final_answers}
    feedback_steps: List[PeerFeedbackStep] = []

    for i in range(total):
        from_name = _get_agent_name(agents[i])
        to_name = _get_agent_name(agents[(i + 1) % total])
        to_answer_excerpt = answer_by_name.get(to_name, "")[:250]

        system = (
            f"너는 StudyBridge AI 에이전트 '{from_name}'이다. "
            f"같은 질문에 대한 동료 에이전트 '{to_name}'의 답변을 검토하고, "
            "짧게 보완하거나 비판할 점, 혹은 동의하는 부분을 한국어 3~4문장으로 제시하라. "
            "인신공격이나 무관한 화제는 피하고, 학습에 도움이 되는 건설적인 피드백만 작성하라."
        )
        user = (
            f"[원래 질문] {message}\n\n"
            f"[{to_name}의 답변]\n{to_answer_excerpt}\n\n"
            "위 답변에 대한 너의 피드백을 작성하라."
        )
        try:
            raw_feedback = clean_ai_answer(_call_llm(system, user, max_tokens=800))
        except Exception as e:
            logger.warning("peer feedback 생성 실패 from=%s to=%s: %s", from_name, to_name, e)
            raw_feedback = ""

        if not raw_feedback.strip():
            raw_feedback = f"{to_name}의 답변에 대한 추가 의견을 정리하지 못했습니다."

        feedback_steps.append(PeerFeedbackStep(
            fromAgent=from_name,
            toAgent=to_name,
            feedback=safe_trim_answer(raw_feedback, AI_MAX_RESPONSE_CHARS),
        ))

    return feedback_steps


def _run_agents_parallel(
    agents: List[AgentProfile],
    message: str,
    context: str,
    timeout_seconds: int,
    learning_mode: str = "basic",
) -> Tuple[List[AgentAnswer], ProcessSteps]:
    """
    병렬 에이전트 실행.
    - 항상 len(agents) 개수만큼 answers 반환
    - timeout된 에이전트만 개별 fallback (agentName 유지)
    - 성공한 에이전트 답변은 절대 버리지 않음
    - 1차(initialAnswers)/2차(validatedAnswers)/3차(peerFeedback) 데이터를 함께 수집한다
    """
    start_time = time.monotonic()
    total = len(agents)
    results_by_name: Dict[str, Dict[str, Any]] = {}
    max_workers = min(total, 5)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_agent: Dict[Any, AgentProfile] = {
            executor.submit(
                _run_single_agent_sync,
                agent,
                message,
                context,
                idx,
                total,
                learning_mode,
            ): agent
            for idx, agent in enumerate(agents)
        }

        try:
            for future in as_completed(future_to_agent, timeout=timeout_seconds):
                agent = future_to_agent[future]
                agent_name = _get_agent_name(agent)
                try:
                    result = future.result(timeout=5)
                    results_by_name[agent_name] = result
                except Exception:
                    logger.exception(
                        "parallel agent answer exception agent=%s", agent_name
                    )
                    results_by_name[agent_name] = _make_agent_run_error_result(agent_name)

        except FuturesTimeoutError:
            elapsed = time.monotonic() - start_time
            completed_count = len(results_by_name)
            timeout_names = [
                _get_agent_name(ag)
                for f, ag in future_to_agent.items()
                if not f.done()
            ]
            logger.warning(
                "parallel multi-chat timeout; "
                "mode=parallel requested_agent_count=%d completed_agent_count=%d "
                "timeout_agent_names=%s elapsed_seconds=%.1f validation_enabled=%s",
                total, completed_count, timeout_names, elapsed, AI_VALIDATION_ENABLED,
            )

        # 미완료 future 정리 및 timeout fallback 세팅
        for future, agent in future_to_agent.items():
            agent_name = _get_agent_name(agent)
            if not future.done():
                future.cancel()
                results_by_name.setdefault(
                    agent_name,
                    _make_agent_run_timeout_result(agent_name),
                )

    # 요청 agents 순서대로 재정렬 (항상 len(agents) 반환 보장)
    ordered_results: List[Dict[str, Any]] = []
    final_answers: List[AgentAnswer] = []
    for agent in agents:
        agent_name = _get_agent_name(agent)
        result = results_by_name.get(agent_name) or _make_agent_run_timeout_result(agent_name)
        ordered_results.append(result)
        final_answers.append(result["finalAnswer"])

    process_steps = ProcessSteps(
        initialAnswers=[
            InitialAnswerStep(agentName=r["agentName"], answer=r["initialAnswer"])
            for r in ordered_results
        ],
        validatedAnswers=[r["validatedStep"] for r in ordered_results],
        peerFeedback=(
            generate_peer_feedback_for_debate(agents, final_answers, message)
            if learning_mode == "debate"
            else []
        ),
    )

    return final_answers, process_steps


def _run_multi_chat_sync(
    active_agents: List[AgentProfile],
    message: str,
    context: str,
    rounds: int,
    show_synthesis: bool,
    learning_mode: str = "basic",
) -> List[AgentAnswer]:
    """동기 multi-chat 실행 — asyncio.to_thread 전용."""
    answers: List[AgentAnswer] = []
    total = len(active_agents)

    for round_idx in range(rounds):
        if round_idx > 0 and total <= 1:
            break
        for agent_idx, agent in enumerate(active_agents):
            try:
                raw = generate_single_agent_response(
                    agent=agent,
                    message=message,
                    context=context,
                    agent_index=agent_idx,
                    total_agents=total,
                    learning_mode=learning_mode,
                )
                # agent_quality_policy 검증 & 보정
                final_text, meta = validate_and_revise_agent_answer(
                    answer=raw,
                    agent_payload=_to_agent_dict(agent),
                    user_message=message,
                    response_mode="general",
                )
                logger.debug("agent=%s passed=%s score=%s", agent.name, meta.get("passed"), meta.get("score"))
                answers.append(AgentAnswer(
                    agentName=agent.name,
                    answer=sanitize_answer_for_spring(final_text),
                ))
            except Exception as e:
                logger.error("에이전트 '%s' 답변 실패: %s", agent.name, e)
                answers.append(AgentAnswer(
                    agentName=agent.name,
                    answer="일시적인 오류로 답변을 생성할 수 없습니다.",
                ))
        if round_idx == 0 and total <= 1:
            break

    if not answers:
        answers.append(AgentAnswer(agentName="시스템", answer=_FALLBACK_LLM_UNAVAILABLE))

    if show_synthesis and len(answers) > 1:
        try:
            synth = build_final_synthesis_answer(
                answers=[{"agentName": a.agentName, "answer": a.answer} for a in answers],
                message=message,
            )
            answers.append(AgentAnswer(
                agentName=SYNTHESIS_AGENT_NAME,
                answer=sanitize_answer_for_spring(synth),
            ))
        except Exception as e:
            logger.warning("종합 답변 생성 실패 (건너뜀): %s", e)

    return answers


# ─────────────────────────────────────────────────────────────────────────────
# 15. Spring 계약 API endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_root():
    """루트 헬스 체크 (uvicorn 직접 실행 확인용)."""
    return {"status": "ok", "service": "StudyBridge AI Server", "version": "0.6.0"}


@app.get("/api/health", tags=["Health"])
async def health_check():
    """
    Spring Boot 계약 헬스 체크.
    key 값 노출 없이 설정 여부만 boolean으로 반환한다.
    """
    return {
        "status": "ok",
        "service": "studybridge-fastapi",
        "openaiConfigured": bool(OPENAI_API_KEY),
        "ollamaConfigured": bool(OLLAMA_BASE_URL),
        "tavilyConfigured": bool(TAVILY_API_KEY),
        "awsConfigured": bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET),
    }


@app.post(
    "/api/ai/predict/study-time",
    response_model=StudyTimePredictResponse,
    tags=["Study Time Prediction"],
)
async def predict_study_time_endpoint(request: StudyTimePredictRequest):
    """
    최근 7일 학습 시간 기반 예측.
    TF 모델 없으면 가중 평균 fallback.
    weeklyStudySeconds 길이 != 7 또는 음수 → 400.
    """
    if len(request.weeklyStudySeconds) != 7:
        raise HTTPException(status_code=400, detail="weeklyStudySeconds는 정확히 7개여야 합니다.")
    if any(v < 0 for v in request.weeklyStudySeconds):
        raise HTTPException(status_code=400, detail="weeklyStudySeconds 값은 음수일 수 없습니다.")
    try:
        predicted = await asyncio.wait_for(
            asyncio.to_thread(predict_study_time, list(request.weeklyStudySeconds)),
            timeout=AI_RESPONSE_TIMEOUT_SECONDS,
        )
        return StudyTimePredictResponse(predictedStudySeconds=predicted)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="학습 시간 예측 요청이 시간 초과되었습니다.")
    except Exception as e:
        logger.error("학습 시간 예측 오류: %s", e)
        raise HTTPException(status_code=500, detail="학습 시간 예측 중 서버 오류가 발생했습니다.")


@app.post(
    "/api/ai/quiz/generate",
    response_model=QuizGenerateResponse,
    tags=["Quiz Generation"],
)
async def generate_quiz_endpoint(request: QuizGenerateRequest):
    """
    S3 PDF 기반 4지선다 퀴즈 생성.
    S3/PDF/LLM 실패 시 fallback quiz 반환 (구조 유지).
    """
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                generate_quiz_from_pdf,
                material_id=request.materialId,
                s3_key=request.s3Key,
                file_name=request.fileName,
            ),
            timeout=QUIZ_GENERATION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = build_fallback_quiz(request.fileName, "timeout")
    except Exception as e:
        logger.error("퀴즈 생성 오류: %s", e)
        result = build_fallback_quiz(request.fileName, str(e))

    return QuizGenerateResponse(
        quizTitle=result["quizTitle"],
        questions=[QuizQuestion(**q) for q in result["questions"]],
    )


@app.post(
    "/api/ai/multi-chat",
    response_model=MultiChatResponse,
    tags=["Multi Agent Chat"],
)
async def multi_chat_endpoint(request: MultiChatRequest):
    """
    멀티 에이전트 응답 — 동기 JSON 반환 (SSE는 Spring Boot 담당).

    모드 라우팅:
      - internal_collaboration / collaboration / natural_collaboration
          → 순차 협업 (_run_multi_chat_sync)
      - 그 외 (parallel / multi / None / "" / multi_agent_discussion 등)
          → 병렬 개별 답변 (_run_agents_parallel)
            항상 요청 agents 수만큼 answers 반환 보장.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message는 비워둘 수 없습니다.")

    agents = request.agents if request.agents else [_DEFAULT_AGENT_PROFILE]
    active_agents = select_agents_for_response(agents, request.targetAgentId)
    context = build_context_from_previous_answers(request.previousAnswers)
    rounds = min(request.rounds, MULTI_CHAT_MAX_ROUNDS)
    learning_mode = normalize_learning_mode(request.learningMode)
    effective_timeout = resolve_multi_chat_timeout(request.mode, learning_mode)

    if should_use_internal_collaboration(request.mode):
        # 협업 모드: 순차 실행 (기존 로직 유지)
        try:
            raw_answers = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_multi_chat_sync,
                    active_agents, request.message, context, rounds, request.showFinalSynthesis, learning_mode,
                ),
                timeout=effective_timeout,
            )
            return MultiChatResponse(mode=request.mode, answers=raw_answers)
        except asyncio.TimeoutError:
            logger.warning(
                "multi-chat 협업 타임아웃 mode=%s requested_agent_count=%d "
                "elapsed_seconds=%d validation_enabled=%s",
                request.mode, len(active_agents),
                effective_timeout, AI_VALIDATION_ENABLED,
            )
            return MultiChatResponse(
                mode=request.mode,
                answers=[
                    AgentAnswer(agentName=a.name, answer=_FALLBACK_TIMEOUT)
                    for a in active_agents
                ],
            )
        except Exception as e:
            logger.error("multi-chat 협업 오류: %s", e)
            return MultiChatResponse(
                mode=request.mode,
                answers=[
                    AgentAnswer(agentName=a.name, answer=_FALLBACK_LLM_UNAVAILABLE)
                    for a in active_agents
                ],
            )
    else:
        # 병렬 모드: 에이전트별 개별 timeout 처리, 항상 agents 수만큼 반환
        # _run_agents_parallel이 내부에서 per-agent fallback을 보장하므로
        # 외부 asyncio.wait_for로 전체를 "시스템 1개"로 축소하지 않는다.
        try:
            raw_answers, process_steps = await asyncio.to_thread(
                _run_agents_parallel,
                active_agents,
                request.message,
                context,
                effective_timeout,
                learning_mode,
            )
            logger.info(
                "parallel multi-chat 완료 mode=%s learningMode=%s requested_agent_count=%d "
                "returned_count=%d validation_enabled=%s",
                request.mode, learning_mode, len(active_agents), len(raw_answers), AI_VALIDATION_ENABLED,
            )
            return MultiChatResponse(mode=request.mode, answers=raw_answers, processSteps=process_steps)
        except Exception as e:
            logger.error(
                "parallel multi-chat 예외 mode=%s requested_agent_count=%d "
                "validation_enabled=%s error=%s",
                request.mode, len(active_agents), AI_VALIDATION_ENABLED, e,
            )
            # 예외 시에도 agents 수만큼 fallback 반환
            return MultiChatResponse(
                mode=request.mode,
                answers=[_make_agent_error_answer(a.name) for a in active_agents],
            )


# ─────────────────────────────────────────────────────────────────────────────
# 16. v0.6 확장 라우터 (app/ 구조 선택적 로드)
#     deep_search, rag, training, agent_chat 고유 엔드포인트 유지
# ─────────────────────────────────────────────────────────────────────────────
try:
    from app.api.rag_routes import router as _rag_legacy_router, spring_rag_router as _spring_rag_router
    from app.api.deep_search_routes import router as _deep_search_router
    from app.api.training_candidate_routes import router as _training_router
    from app.routers.agent_chat_router import router as _agent_chat_router
    from app.api.roadmap_routes import router as _roadmap_router
    from app.api.material_legacy_routes import router as _material_legacy_router

    app.include_router(_spring_rag_router)      # /api/rag/ingest, /api/rag/query, DELETE /api/rag/materials/{id}
    app.include_router(_rag_legacy_router)      # /api/materials/{id}/rag/* (하위 호환)
    app.include_router(_deep_search_router)     # /api/agent/deep-search
    app.include_router(_training_router)        # /api/training-candidates/stats, /export-jsonl
    app.include_router(_agent_chat_router)      # /api/ai/chat, /api/ai/material/*
    app.include_router(_roadmap_router)         # POST /api/materials/{id}/ai/roadmap
    app.include_router(_material_legacy_router) # POST /api/ai/summary|quiz|question|roadmap|feedback (자료보관함 라이브)

    logger.info("v0.6 확장 라우터 로드 완료 (로드맵 + 자료보관함 라이브 포함)")
except Exception as _ext_err:
    logger.warning("v0.6 확장 라우터 로드 실패 (Spring 계약 API는 정상 동작): %s", _ext_err)


# ─────────────────────────────────────────────────────────────────────────────
# 직접 실행 (개발용)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
