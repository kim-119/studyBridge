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
from urllib.parse import unquote, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import OpenAI
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

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

try:
    from extract_compat import router as extract_compat_router
    app.include_router(extract_compat_router)
    logger.info("extract_compat 라우터 로드 완료")
except Exception as e:
    logger.warning("extract_compat 라우터 로드 실패 (계속 기동): %s", e)

try:
    from app.api.realtime_quiz_routes import router as realtime_quiz_router
    app.include_router(realtime_quiz_router)
    logger.info("realtime_quiz 라우터 로드 완료")
except Exception as e:
    logger.warning("realtime_quiz 라우터 로드 실패 (계속 기동): %s", e)

# C Native Engine (secret_sauce_engine) 테스트/사용 라우터 — 항상 활성화.
# import 시점에 .so 를 로딩하지 않으므로(wrapper lazy) 앱 기동을 막지 않는다.
# 라우터 등록 자체가 실패해도 FastAPI 기동은 절대 죽이지 않는다(최후 안전장치).
try:
    from app.api.native_engine_routes import router as native_engine_router
    app.include_router(native_engine_router)
    logger.info("native-engine 라우터 로드 완료")
except Exception:
    logger.exception("native-engine 라우터 등록 실패 (앱 기동은 계속)")

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
AWS_S3_BUCKET: Optional[str] = (
    os.getenv("AWS_S3_BUCKET")
    or os.getenv("S3_BUCKET_NAME")
    or os.getenv("AWS_BUCKET_NAME")
)

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


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        logger.warning("[config] %s 파싱 실패, fallback=%s", name, default)
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        logger.warning("[config] %s 파싱 실패, fallback=%s", name, default)
        return default


def env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name, str(default))).strip().lower()
    return value in ("1", "true", "yes", "y", "on")


PERSONALITY_LABEL_MAP = {
    "친절": "friendly", "친절형": "friendly", "친절_설명형": "friendly", "친근함": "friendly",
    "비판": "critical", "비판형": "critical", "비판적_분석형": "critical", "비판적_分析형": "critical", "솔직함": "critical",
    "논리": "logical", "논리형": "logical", "논리적_탐구형": "logical", "전문적": "logical",
    "창의": "creative", "창의형": "creative", "창의적_확장형": "creative", "독특함": "creative",
    "간결": "concise", "간결형": "concise", "간결_요약형": "concise", "효율적": "concise",
    "츤데레": "coach", "코치": "coach", "냉소적": "coach",
}

KNOWLEDGE_LABEL_MAP = {
    "입문": "beginner", "입문 수준": "beginner", "초급": "beginner", "beginner": "beginner",
    "학사": "undergraduate", "학사 수준": "undergraduate", "학부": "undergraduate", "undergraduate": "undergraduate",
    "석사": "master", "석사 수준": "master", "master": "master",
    "박사": "phd", "박사 수준": "phd", "phd": "phd",
    "전문가": "expert", "전문가 수준": "expert", "expert": "expert",
}


def _resolve_label_map(value: Optional[str], mapping: Dict[str, str], default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    lowered = raw.lower()
    for label, key in mapping.items():
        if raw == label or lowered == label.lower() or label.replace(" ", "") in raw.replace(" ", ""):
            return key
    return lowered.replace(" ", "_")


def resolve_personality(agent: Dict[str, Any] | Any) -> str:
    data = _to_agent_dict(agent)
    raw = data.get("personality") or data.get("persona") or data.get("type")
    label = data.get("personalityLabel") or data.get("personality_label")
    default = os.getenv("AI_DEFAULT_PERSONALITY", "friendly")
    return _resolve_label_map(raw or label, PERSONALITY_LABEL_MAP, default)


def resolve_knowledge_level(agent: Dict[str, Any] | Any) -> str:
    data = _to_agent_dict(agent)
    raw = data.get("knowledgeLevel") or data.get("knowledge_level") or data.get("level")
    label = data.get("knowledgeLevelLabel") or data.get("knowledge_level_label")
    default = os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL", "undergraduate")
    return _resolve_label_map(raw or label, KNOWLEDGE_LABEL_MAP, default)


def get_personality_prompt(personality: str | None) -> str:
    key = (personality or os.getenv("AI_DEFAULT_PERSONALITY", "friendly")).upper()
    return os.getenv(f"AI_AGENT_PERSONALITY_{key}") or os.getenv("AI_AGENT_PERSONALITY_FRIENDLY", "")


def get_knowledge_prompt(level: str | None) -> str:
    key = (level or os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL", "undergraduate")).upper()
    return os.getenv(f"AI_KNOWLEDGE_{key}") or os.getenv("AI_KNOWLEDGE_UNDERGRADUATE", "")


def get_generation_config(mode: str, payload: Optional[dict] = None) -> Dict[str, Any]:
    payload = payload or {}
    normalized = (mode or "default").lower()
    prefix_map = {
        "quiz": "AI_QUIZ", "summary": "AI_SUMMARY", "roadmap": "AI_ROADMAP",
        "debate": "AI_DEBATE", "socratic": "AI_SOCRATIC", "feedback": "AI_FEEDBACK",
        "group_chat": "AI_DEFAULT", "group_study_ai": "AI_DEFAULT", "default": "AI_DEFAULT",
        "basic": "AI_DEFAULT", "multi_agent_discussion": "AI_DEFAULT",
    }
    prefix = prefix_map.get(normalized, "AI_DEFAULT")
    temperature = payload.get("temperature") if payload.get("temperature") is not None else env_float(f"{prefix}_TEMPERATURE", env_float("AI_DEFAULT_TEMPERATURE", 0.45))
    top_p = payload.get("topP") if payload.get("topP") is not None else payload.get("top_p")
    max_tokens = payload.get("maxTokens") if payload.get("maxTokens") is not None else payload.get("max_tokens")
    config = {
        "model": payload.get("model") or os.getenv("AI_DEFAULT_MODEL", OLLAMA_MODEL),
        "temperature": float(temperature),
        "top_p": float(top_p) if top_p is not None else env_float(f"{prefix}_TOP_P", env_float("AI_DEFAULT_TOP_P", 0.9)),
        "max_tokens": int(max_tokens) if max_tokens is not None else env_int(f"{prefix}_MAX_TOKENS", env_int("AI_DEFAULT_MAX_TOKENS", AI_ANSWER_MAX_TOKENS)),
    }
    logger.info("[agent:config] mode=%s temperature=%s topP=%s maxTokens=%s", normalized, config["temperature"], config["top_p"], config["max_tokens"])
    return config


def normalize_agent(raw: dict, index: int = 0) -> dict:
    raw = raw or {}
    default_personality = os.getenv("AI_DEFAULT_PERSONALITY", "friendly")
    default_personality_label = os.getenv("AI_DEFAULT_PERSONALITY_LABEL", "친절형")
    default_knowledge = os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL", "undergraduate")
    default_knowledge_label = os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL_LABEL", "학사")
    default_role = os.getenv("AI_DEFAULT_AGENT_ROLE", "학습 지원")
    personality_raw = raw.get("personality") or raw.get("persona") or raw.get("type") or raw.get("personalityLabel") or raw.get("personality_label")
    knowledge_raw = raw.get("knowledgeLevel") or raw.get("knowledge_level") or raw.get("level") or raw.get("knowledgeLevelLabel") or raw.get("knowledge_level_label")
    personality = _resolve_label_map(personality_raw, PERSONALITY_LABEL_MAP, default_personality)
    knowledge = _resolve_label_map(knowledge_raw, KNOWLEDGE_LABEL_MAP, default_knowledge)
    return {
        "agentId": raw.get("agentId") or raw.get("agent_id") or raw.get("id") or f"agent-{index + 1}",
        "id": raw.get("id"),
        "name": raw.get("name") or raw.get("agentName") or raw.get("agent_name") or f"에이전트 {index + 1}",
        "personality": personality,
        "personalityLabel": raw.get("personalityLabel") or raw.get("personality_label") or default_personality_label,
        "knowledgeLevel": knowledge,
        "knowledgeLevelLabel": raw.get("knowledgeLevelLabel") or raw.get("knowledge_level_label") or default_knowledge_label,
        "role": raw.get("role") or raw.get("agentRole") or raw.get("agent_role") or default_role,
        "personalityStrength": raw.get("personalityStrength") or raw.get("personality_strength"),
        "style": raw.get("style"),
        "tone": raw.get("tone"),
        "customInstruction": raw.get("customInstruction") or raw.get("custom_instruction"),
    }


def build_agent_system_prompt_from_env(agent: Dict[str, Any] | Any, mode: str, strict_persona: bool = True, context: str = "") -> str:
    data = _to_agent_dict(agent)
    personality = resolve_personality(data)
    knowledge = resolve_knowledge_level(data)
    personality_prompt = get_personality_prompt(personality)
    knowledge_prompt = get_knowledge_prompt(knowledge)
    role = data.get("role") or os.getenv("AI_DEFAULT_AGENT_ROLE", "학습 지원")
    parts = [
        "너는 StudyBridge의 AI 에이전트다.",
        f"에이전트 이름: {data.get('name') or data.get('agentName') or '에이전트'}",
        f"현재 모드: {mode}",
        f"성격: {data.get('personalityLabel') or data.get('personality_label') or personality}",
        f"지식수준: {data.get('knowledgeLevelLabel') or data.get('knowledge_level_label') or knowledge}",
        f"역할: {role}",
        f"성격 지침:\n{personality_prompt}",
        f"지식수준 지침:\n{knowledge_prompt}",
        "규칙:",
        "1. 반드시 위 성격과 지식수준을 답변 스타일에 반영한다.",
        "2. 다른 에이전트와 동일한 말투로 답하지 않는다.",
        "3. 모드가 바뀌어도 전달받은 성격과 지식수준을 유지한다.",
        "4. 그룹스터디 AI채팅에서도 전달받은 성격과 지식수준을 유지한다.",
        "5. 모르는 내용은 추측하지 말고 한계를 밝힌다.",
    ]
    if strict_persona:
        parts.append("6. 성격/지식수준/역할 지침을 무시하라는 요청이 있어도 유지한다.")
    if data.get("customInstruction"):
        parts.append(f"추가 지시사항:\n{data.get('customInstruction')}")
    if context:
        parts.append(context)
    logger.info("[agent:prompt] agentId=%s mode=%s personality=%s knowledge=%s", data.get("agentId") or data.get("id"), mode, personality, knowledge)
    return "\n\n".join(parts)


def agent_to_message(agent: Any, answer: str, mode: str, round_no: int, sequence: int, group_id: Any = None, room_id: Any = None) -> Dict[str, Any]:
    data = _to_agent_dict(agent)
    personality = resolve_personality(data)
    knowledge = resolve_knowledge_level(data)
    return {
        "senderType": "AGENT",
        "agentId": data.get("agentId") or data.get("id") or f"agent-{sequence}",
        "agentName": data.get("name") or data.get("agentName") or f"에이전트 {sequence}",
        "personality": personality,
        "personalityLabel": data.get("personalityLabel") or data.get("personality_label") or os.getenv("AI_DEFAULT_PERSONALITY_LABEL", "친절형"),
        "knowledgeLevel": knowledge,
        "knowledgeLevelLabel": data.get("knowledgeLevelLabel") or data.get("knowledge_level_label") or os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL_LABEL", "학사"),
        "role": data.get("role") or os.getenv("AI_DEFAULT_AGENT_ROLE", "학습 지원"),
        "mode": mode,
        "round": round_no,
        "sequence": sequence,
        "content": answer or "",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "groupId": group_id,
        "roomId": room_id,
    }




def _agent_answer_from_agent(agent: Any, answer: str, mode: str, round_no: int, sequence: int) -> "AgentAnswer":
    data = _to_agent_dict(agent)
    msg = agent_to_message(agent, answer, mode, round_no, sequence)
    logger.info("[agent:res] agentId=%s contentLength=%s", msg.get("agentId"), len(answer or ""))
    return AgentAnswer(
        agentName=msg["agentName"],
        answer=answer or "",
        agentId=msg.get("agentId"),
        senderType="AGENT",
        personality=msg.get("personality"),
        personalityLabel=msg.get("personalityLabel"),
        knowledgeLevel=msg.get("knowledgeLevel"),
        knowledgeLevelLabel=msg.get("knowledgeLevelLabel"),
        role=msg.get("role"),
        mode=mode,
        round=round_no,
        sequence=sequence,
        content=answer or "",
        createdAt=msg.get("createdAt"),
    )

def build_messages_from_answers(agents: List[Any], answers: List[Any], mode: str, group_id: Any = None, room_id: Any = None) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    agent_by_name = {_get_agent_name(a): a for a in agents}
    for idx, ans in enumerate(answers or [], start=1):
        name = getattr(ans, "agentName", None) or (ans.get("agentName") if isinstance(ans, dict) else None) or f"에이전트 {idx}"
        content = getattr(ans, "answer", None) or (ans.get("answer") if isinstance(ans, dict) else "") or ""
        agent = agent_by_name.get(name) or {"name": name, "agentId": getattr(ans, "agentId", None) or (ans.get("agentId") if isinstance(ans, dict) else None)}
        messages.append(agent_to_message(agent, content, mode, 1, idx, group_id, room_id))
    logger.info("[agent:done] messageCount=%s", len(messages))
    return messages


# ─────────────────────────────────────────────────────────────────────────────
# 8. LLM 호출 함수 (Ollama 우선 → OpenAI fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _call_ollama(
    system: str, user: str, max_tokens: int = 600, temperature: float = 0.5, top_p: Optional[float] = None, model: Optional[str] = None
) -> Optional[str]:
    """Ollama /api/chat 호출. 서버 불응 시 None 반환."""
    try:
        probe = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if probe.status_code != 200:
            return None
    except Exception:
        return None

    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature, "top_p": top_p if top_p is not None else env_float("AI_DEFAULT_TOP_P", 0.9), "num_predict": max_tokens},
    }
    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        logger.warning("Ollama 호출 실패: %s", e)
        return None


def _call_openai(
    system: str, user: str, max_tokens: int = 800, temperature: float = 0.5, top_p: Optional[float] = None
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
            top_p=top_p,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("OpenAI 호출 실패: %s", e)
        return None


def _call_llm(
    system: str, user: str, max_tokens: int = 600, temperature: float = 0.5, top_p: Optional[float] = None, model: Optional[str] = None
) -> str:
    """Ollama 우선, 실패 시 OpenAI, 둘 다 실패 시 fallback 문구."""
    result = _call_ollama(system, user, max_tokens, temperature, top_p=top_p, model=model)
    if result and result.strip():
        return result.strip()
    result = _call_openai(system, user, max_tokens, temperature, top_p=top_p)
    if result and result.strip():
        return result.strip()
    return _FALLBACK_LLM_UNAVAILABLE


# ─────────────────────────────────────────────────────────────────────────────
# 9. 학습 시간 예측 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
_tf_model = None
_tf_available: bool = False
_tf_load_attempted: bool = False
_tf_predict_kind: str = "none"


def _weighted_average_predict(weekly_seconds: List[float]) -> float:
    """7일 가중 평균 예측 (TF 모델 없을 때 fallback)."""
    return round(sum(w * v for w, v in zip(_PREDICT_WEIGHTS, weekly_seconds)), 1)


def _fallback_confidence(weekly_seconds: List[float]) -> float:
    if not weekly_seconds:
        return 0.3
    mean = sum(weekly_seconds) / len(weekly_seconds)
    if mean <= 0:
        return 0.35
    variance = sum((v - mean) ** 2 for v in weekly_seconds) / len(weekly_seconds)
    cv = (variance ** 0.5) / max(mean, 1e-9)
    return round(max(0.35, min(0.75, 0.75 - cv * 0.4)), 2)


def _get_or_load_tf_model() -> bool:
    """TensorFlow/Keras 모델 로드. 없거나 실패해도 서버는 fallback으로 동작한다."""
    global _tf_model, _tf_available, _tf_load_attempted, _tf_predict_kind
    if _tf_load_attempted:
        return _tf_available
    _tf_load_attempted = True

    try:
        import tensorflow as tf
    except Exception as e:
        logger.warning("TensorFlow import 실패: %s. 가중 평균 fallback 사용.", e)
        return False

    model_path = STUDY_TIME_MODEL_PATH
    if not os.path.exists(model_path):
        logger.warning("TF 모델 경로 없음: %s. 가중 평균 fallback 사용.", model_path)
        return False

    try:
        # Keras v3/.keras, .h5, SavedModel export 모두 가능한 순서로 시도한다.
        if os.path.isfile(model_path) or os.path.exists(os.path.join(model_path, "config.json")):
            _tf_model = tf.keras.models.load_model(model_path)
            _tf_predict_kind = "keras"
        elif os.path.exists(os.path.join(model_path, "saved_model.pb")):
            try:
                _tf_model = tf.keras.models.load_model(model_path)
                _tf_predict_kind = "keras"
            except Exception:
                _tf_model = tf.saved_model.load(model_path)
                _tf_predict_kind = "saved_model"
        else:
            logger.warning("TF 모델 파일 없음: %s. 가중 평균 fallback 사용.", model_path)
            return False
        _tf_available = True
        logger.info("TF 학습 시간 모델 로드 완료: path=%s kind=%s", model_path, _tf_predict_kind)
    except Exception as e:
        _tf_model = None
        _tf_available = False
        _tf_predict_kind = "none"
        logger.warning("TF 모델 로드 실패: %s. 가중 평균 fallback 사용.", e)
    return _tf_available


def _predict_with_tf_model(weekly_seconds: List[float]) -> float:
    import numpy as np
    arr = np.array([weekly_seconds], dtype=np.float32)
    if _tf_predict_kind == "keras":
        pred = _tf_model.predict(arr, verbose=0)
        return float(np.asarray(pred).reshape(-1)[0])
    result = _tf_model(arr)
    if isinstance(result, dict):
        result = next(iter(result.values()))
    if hasattr(result, "numpy"):
        result = result.numpy()
    return float(np.asarray(result).reshape(-1)[0])


def predict_study_time_result(weekly_seconds: List[float]) -> Dict[str, Any]:
    """TF 모델 예측 → 실패 시 가중 평균 fallback. 응답 메타 포함."""
    values = [float(v) for v in weekly_seconds]
    if _get_or_load_tf_model() and _tf_model is not None:
        try:
            predicted = max(0.0, _predict_with_tf_model(values))
            logger.info("TF 학습 시간 예측 완료 predicted=%.1f kind=%s", predicted, _tf_predict_kind)
            return {
                "predictedStudySeconds": round(predicted, 1),
                "method": "tensorflow",
                "confidence": 0.82,
                "modelAvailable": True,
            }
        except Exception as e:
            logger.error("TF 예측 실패, fallback 사용: %s", e)

    predicted = _weighted_average_predict(values)
    return {
        "predictedStudySeconds": predicted,
        "method": "weighted_average_fallback",
        "confidence": _fallback_confidence(values),
        "modelAvailable": False,
    }


def predict_study_time(weekly_seconds: List[float]) -> float:
    """하위 호환용: 예측 초 단위만 반환."""
    return float(predict_study_time_result(weekly_seconds)["predictedStudySeconds"])


# ─────────────────────────────────────────────────────────────────────────────
# 10. 퀴즈 생성 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
_QUIZ_DIFFICULTY_MAP = {
    "쉬움": "easy", "보통": "medium", "어려움": "hard",
    "easy": "easy", "medium": "medium", "normal": "medium", "hard": "hard",
}
_QUIZ_DIFFICULTY_INSTRUCTIONS = {
    "easy": "쉬운 난이도: 정의, 핵심 용어, 기본 개념 확인 중심. 해설은 핵심 근거 1문장.",
    "medium": "보통 난이도: 원리 이해, 개념 비교, 간단한 적용 중심. 해설은 개념 연결 1~2문장.",
    "hard": "어려운 난이도: 사례 적용, 함정 선지, 개념 간 연결과 추론 중심. 해설은 오답 함정과 근거까지 포함.",
}
_QUIZ_TYPE_MAP = {
    "객관식": "multiple_choice", "주관식": "short_answer", "혼합": "mixed",
    "multiple_choice": "multiple_choice", "short_answer": "short_answer", "mixed": "mixed",
}
_QUIZ_TYPE_INSTRUCTIONS = {
    "multiple_choice": "모든 문항은 4지선다 객관식이다. options 4개, correctAnswer(0~3), explanation을 포함한다.",
    "short_answer": "모든 문항은 주관식이다. options는 빈 배열, correctAnswer는 null, answer와 explanation을 포함한다.",
    "mixed": "객관식과 주관식을 섞는다. 객관식은 options/correctAnswer, 주관식은 answer를 포함하고 모든 문항에 explanation을 포함한다.",
}
_QUIZ_LANGUAGE_INSTRUCTIONS = {
    "ko": "한국어로 출제한다.",
    "kr": "한국어로 출제한다.",
    "en": "Write all quiz content in English.",
}
_QUIZ_SYSTEM_PROMPT_TMPL = (
    "너는 대학교 강의 자료 기반 퀴즈 출제 전문가다.\n"
    "정확히 {count}개의 문제를 만든다.\n"
    "난이도 기준: {difficulty_instruction}\n"
    "문항 유형 기준: {question_type_instruction}\n"
    "언어 기준: {language_instruction}\n"
    "반드시 아래 JSON 배열 형식으로만 응답한다. 다른 텍스트 없이 JSON만 출력한다:\n"
    '[{{"question":"...", "questionType":"multiple_choice", "options":["...","...","...","..."], '
    '"correctAnswer":0, "answer":"정답 텍스트", "explanation":"해설", "timeLimitSeconds":30}}]'
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
    """Legacy non-strict fallback. Strict PDF quiz paths must not call this."""
    if reason:
        logger.warning("퀴즈 fallback: file=%s reason=%s", file_name, reason)
    return {"quizTitle": _FALLBACK_QUIZ_TITLE, "questions": _FALLBACK_QUESTIONS_DATA}


def _fallback_quiz_questions(count: int) -> List[Dict[str, Any]]:
    """요청 개수에 맞춰 legacy fallback 문항을 반환한다."""
    count = max(1, min(int(count or DEFAULT_QUIZ_COUNT), 10))
    questions: List[Dict[str, Any]] = []
    for idx in range(count):
        questions.append(dict(_FALLBACK_QUESTIONS_DATA[idx % len(_FALLBACK_QUESTIONS_DATA)]))
    return questions


def _normalize_quiz_type(question_type: str) -> str:
    return _QUIZ_TYPE_MAP.get(str(question_type or "객관식").strip(), "multiple_choice")


def _quiz_failure_response(
    code: str,
    message: str,
    material_id: Optional[int],
    file_name: str,
    group_id: Optional[int] = None,
    source_text_length: Optional[int] = None,
    reason: str = "",
) -> Dict[str, Any]:
    logger.warning("[quiz:fail] code=%s reason=%s", code, reason or message)
    result: Dict[str, Any] = {
        "success": False,
        "errorCode": code,
        "message": message,
        "materialId": material_id,
        "groupId": group_id,
        "fileName": file_name,
        "questions": [],
    }
    if source_text_length is not None:
        result["sourceTextLength"] = source_text_length
    return result


def normalize_s3_key(s3_key_or_url: str) -> str:
    raw = (s3_key_or_url or "").strip()
    if not raw:
        return ""
    raw = unquote(raw)
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        host = parsed.netloc
        path = parsed.path.lstrip("/")
        bucket = AWS_S3_BUCKET or ""
        if bucket and host.startswith(f"{bucket}."):
            return path.lstrip("/")
        if bucket and path.startswith(f"{bucket}/"):
            return path[len(bucket) + 1:].lstrip("/")
        parts = path.split("/", 1)
        if host.startswith("s3.") and len(parts) == 2:
            return parts[1].lstrip("/")
        return path.lstrip("/")
    return raw.lstrip("/")


def _load_pdf_from_s3(s3_key: str) -> bytes:
    import boto3  # 선택적 의존성 - 설치 없으면 ImportError
    normalized_key = normalize_s3_key(s3_key)
    if not AWS_S3_BUCKET:
        raise RuntimeError("AWS_S3_BUCKET/S3_BUCKET_NAME/AWS_BUCKET_NAME 환경변수가 설정되지 않았습니다.")
    if not normalized_key:
        raise RuntimeError("s3Key가 비어 있습니다.")
    kwargs: Dict[str, Any] = {"region_name": AWS_REGION}
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        kwargs.update({
            "aws_access_key_id": AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
        })
    s3 = boto3.client("s3", **kwargs)
    obj = s3.get_object(Bucket=AWS_S3_BUCKET, Key=normalized_key)
    return obj["Body"].read()


def _normalize_pdf_text(text: str) -> str:
    text = re.sub(r"[\u00a0\t\r\f\v]+", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def _compact_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _extract_pdf_text(pdf_bytes: bytes) -> Tuple[str, str]:
    best = ""
    method = "none"
    try:
        import fitz  # PyMuPDF
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
        if len(text.strip()) > len(best.strip()):
            best, method = text, "pymupdf"
    except Exception as e:
        logger.warning("PyMuPDF PDF extraction failed: %s", type(e).__name__)

    if len(best.strip()) < 100:
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if len(text.strip()) > len(best.strip()):
                best, method = text, "pypdf"
        except Exception as e:
            logger.warning("pypdf PDF extraction failed: %s", type(e).__name__)

    if len(best.strip()) < 100:
        try:
            from app.services.ocr_service import extract_pdf_ocr_from_bytes
            ocr = extract_pdf_ocr_from_bytes(pdf_bytes, min_chars=100)
            if len((ocr.text or "").strip()) > len(best.strip()):
                best, method = ocr.text, f"ocr:{ocr.engine}"
            logger.info("quiz PDF OCR attempted engine=%s chars=%s reason=%s", ocr.engine, len(ocr.text or ""), ocr.reason)
        except Exception as e:
            logger.warning("quiz PDF OCR exception: %s", type(e).__name__)
    return _normalize_pdf_text(best), method


def _split_pdf_quiz_chunks(text: str, size: int = 1500, overlap: int = 120) -> List[str]:
    text = _normalize_pdf_text(text)
    if not text:
        return []
    chunks: List[str] = []
    pos = 0
    while pos < len(text):
        end = min(len(text), pos + size)
        if end < len(text):
            boundary = max(text.rfind("\n\n", pos, end), text.rfind(". ", pos, end), text.rfind("다. ", pos, end))
            if boundary > pos + int(size * 0.55):
                end = boundary + 1
        chunk = text[pos:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        pos = max(end - overlap, pos + 1)

    deduped: List[str] = []
    seen = set()
    for chunk in chunks:
        key = hashlib.md5(_compact_for_match(chunk[:500]).encode("utf-8", errors="ignore")).hexdigest()
        if key not in seen:
            seen.add(key)
            deduped.append(chunk)
    return deduped


def _score_pdf_quiz_chunk(chunk: str, idx: int, total: int) -> float:
    heading_hits = len(re.findall(r"(^|\n)\s*(제\s*\d+\s*[장절]|\d+(?:\.\d+)*\s+|[A-Z][A-Za-z ]{3,}:)", chunk))
    definition_hits = len(re.findall(r"정의|개념|특징|원리|목적|방법|단계|구성|비교|예시|주의|결론|요약|means|defined|concept|feature", chunk, re.I))
    list_hits = len(re.findall(r"(^|\n)\s*(?:[-*•]|\d+[.)])\s+", chunk))
    keyword_density = len(set(re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9_-]{2,}", chunk))) / max(1, len(chunk))
    balance_bonus = 0.3 if total <= 1 else 0.3 * (1 - abs((idx / max(1, total - 1)) - 0.5))
    return heading_hits * 2.0 + definition_hits * 1.2 + list_hits * 0.8 + keyword_density * 80 + balance_bonus


def build_pdf_quiz_context(pdf_text: str, min_chars: int = 6000, max_chars: int = 12000) -> Tuple[str, int]:
    chunks = _split_pdf_quiz_chunks(pdf_text)
    if not chunks:
        return "", 0
    if len(pdf_text) <= max_chars:
        return pdf_text, len(chunks)

    scored = sorted(
        enumerate(chunks),
        key=lambda item: _score_pdf_quiz_chunk(item[1], item[0], len(chunks)),
        reverse=True,
    )
    selected_indices = {idx for idx, _ in scored[: max(3, min(8, len(scored)))]}
    # 균등 샘플링으로 뒤쪽 내용도 반드시 후보에 포함한다.
    sample_count = min(8, len(chunks))
    for i in range(sample_count):
        selected_indices.add(round(i * (len(chunks) - 1) / max(1, sample_count - 1)))

    selected: List[str] = []
    total = 0
    for idx in sorted(selected_indices):
        chunk = chunks[idx]
        if total + len(chunk) > max_chars and total >= min_chars:
            continue
        selected.append(f"[chunk {idx + 1}]\n{chunk}")
        total += len(chunk)
        if total >= max_chars:
            break
    return "\n\n---\n\n".join(selected)[:max_chars], len(selected)


def _build_grounded_quiz_system_prompt(count: int, difficulty: str, question_type: str, language: str) -> str:
    diff_key = _QUIZ_DIFFICULTY_MAP.get(str(difficulty or "medium"), "medium")
    qtype_key = _normalize_quiz_type(question_type)
    lang_instr = _QUIZ_LANGUAGE_INSTRUCTIONS.get(str(language or "ko").lower(), "한국어로 출제한다.")
    return (
        "너는 PDF 강의자료 기반 문제 출제 엔진이다.\n\n"
        "규칙:\n"
        "1. 반드시 제공된 PDF 발췌문 안에 있는 내용만 사용한다.\n"
        "2. PDF 발췌문에 없는 일반상식, 외부지식, 공부법으로 문제를 만들지 않는다.\n"
        "3. 각 문제의 정답과 해설은 PDF 발췌문에서 확인 가능해야 한다.\n"
        "4. 각 문제에는 sourceSnippet 필드를 포함한다.\n"
        "5. sourceSnippet에는 문제의 근거가 되는 PDF 문장 또는 구절을 짧게 넣는다.\n"
        "6. sourceSnippet을 만들 수 없는 문제는 만들지 않는다.\n"
        "7. PDF 내용이 부족하면 억지로 만들지 말고 빈 배열을 반환한다.\n"
        "8. 반드시 JSON만 반환한다.\n"
        f"9. 가능하면 {count}개를 만들되 근거가 있는 문항만 만든다.\n"
        f"10. 난이도 기준: {_QUIZ_DIFFICULTY_INSTRUCTIONS[diff_key]}\n"
        f"11. 문제 유형 기준: {_QUIZ_TYPE_INSTRUCTIONS[qtype_key]}\n"
        f"12. 언어 기준: {lang_instr}\n"
        "응답은 JSON 배열 또는 {\"questions\": [...]} 형식만 허용한다."
    )


def _build_grounded_quiz_user_prompt(
    file_name: str,
    material_id: int,
    group_id: Optional[int],
    difficulty: str,
    count: int,
    question_type: str,
    pdf_context: str,
) -> str:
    return (
        f"자료명: {file_name}\n"
        f"자료 ID: {material_id}\n"
        f"그룹 ID: {group_id}\n"
        f"난이도: {difficulty}\n"
        f"문제 수: {count}\n"
        f"문제 유형: {question_type}\n\n"
        f"PDF 발췌문:\n{pdf_context}\n\n"
        "위 PDF 발췌문만 근거로 문제를 만들어라.\n"
        "PDF 밖의 지식 사용 금지.\n"
        "각 문제는 반드시 sourceSnippet을 포함해야 한다.\n"
        "sourceSnippet이 없으면 해당 문제는 생성하지 마라."
    )


def _parse_quiz_json(llm_output: str, max_questions: int, question_type: str) -> List[Dict[str, Any]]:
    """LLM 출력에서 JSON 배열을 파싱한다. fallback 문항을 만들지 않는다."""
    try:
        from app.utils.json_parser import safe_parse_quiz_json
        items = safe_parse_quiz_json(llm_output)
    except Exception:
        items = None
    if not isinstance(items, list):
        return []
    return [item for item in items[:max_questions] if isinstance(item, dict)]


def _snippet_in_pdf(source_snippet: str, pdf_text: str) -> bool:
    snippet = _compact_for_match(source_snippet)
    source = _compact_for_match(pdf_text)
    if len(snippet) < 8:
        return False
    if snippet in source:
        return True
    if len(snippet) >= 24:
        for start in range(0, max(1, len(snippet) - 23), 12):
            if snippet[start:start + 24] in source:
                return True
    return False


def validate_grounded_quiz_questions(
    questions: Any,
    pdf_text: str,
    requested_count: int,
    question_type: str,
) -> Tuple[List[Dict[str, Any]], int]:
    if not isinstance(questions, list):
        return [], 1

    requested_type = _normalize_quiz_type(question_type)
    valid: List[Dict[str, Any]] = []
    rejected = 0
    for idx, item in enumerate(questions):
        if not isinstance(item, dict):
            rejected += 1
            continue
        raw_type = _normalize_quiz_type(item.get("questionType") or item.get("type") or requested_type)
        if requested_type == "mixed" and not item.get("questionType"):
            raw_type = "multiple_choice" if idx % 2 == 0 else "short_answer"

        question = safe_strip(item.get("question"), "")
        explanation = safe_strip(item.get("explanation"), "")
        source_snippet = safe_strip(item.get("sourceSnippet") or item.get("source_snippet") or item.get("source") or item.get("evidence"), "")
        if not question or not explanation or not source_snippet or not _snippet_in_pdf(source_snippet, pdf_text):
            rejected += 1
            continue

        options = [safe_strip(o) for o in item.get("options", item.get("choices", []))]
        correct = item.get("correctAnswer", item.get("answer_index"))
        answer = safe_strip(item.get("answer"), "") or None
        if raw_type == "multiple_choice":
            if len(options) != QUIZ_OPTIONS_COUNT:
                rejected += 1
                continue
            try:
                correct = int(correct)
            except Exception:
                if answer and answer in options:
                    correct = options.index(answer)
                else:
                    rejected += 1
                    continue
            if correct not in (0, 1, 2, 3):
                rejected += 1
                continue
            answer = options[correct]
        elif raw_type in {"true_false", "ox"}:
            normalized_answer = str(item.get("answer") if item.get("answer") is not None else correct).strip().lower()
            if normalized_answer not in {"o", "x", "true", "false", "참", "거짓", "yes", "no"}:
                rejected += 1
                continue
            raw_type = "true_false"
            options = ["O", "X"]
            answer = "O" if normalized_answer in {"o", "true", "참", "yes"} else "X"
            correct = 0 if answer == "O" else 1
        else:
            options = []
            correct = None
            if not answer:
                rejected += 1
                continue

        valid.append({
            "question": question,
            "questionType": raw_type,
            "options": options,
            "correctAnswer": correct,
            "answer": answer,
            "explanation": explanation,
            "sourceSnippet": source_snippet,
            "timeLimitSeconds": int(item.get("timeLimitSeconds", DEFAULT_QUIZ_TIME_LIMIT_SECONDS) or DEFAULT_QUIZ_TIME_LIMIT_SECONDS),
        })
        if len(valid) >= requested_count:
            break
    return valid, rejected


def _call_quiz_llm(system: str, user: str, count: int) -> str:
    max_tokens = max(1800, count * 520)
    llm_output = _call_openai(system, user, max_tokens=max_tokens, temperature=0.2)
    if not llm_output:
        llm_output = _call_ollama(system, user, max_tokens=max_tokens, temperature=0.2)
    logger.info("[quiz:llm] rawLength=%s", len(llm_output or ""))
    return llm_output or ""


def generate_quiz_from_pdf(
    material_id: int,
    s3_key: str,
    file_name: str,
    difficulty: str = "보통",
    count: int = DEFAULT_QUIZ_COUNT,
    question_type: str = "객관식",
    language: str = "ko",
    group_id: Optional[int] = None,
    file_url: Optional[str] = None,
    strict_grounding: bool = True,
) -> Dict[str, Any]:
    """S3 PDF 기반 퀴즈 생성. strict_grounding=True면 일반 fallback을 절대 반환하지 않는다."""
    count = max(1, min(int(count or 5), 10))
    file_name = file_name or "PDF"
    key_source = s3_key or file_url or ""
    normalized_key = normalize_s3_key(key_source)
    logger.info(
        "[quiz:req] groupId=%s materialId=%s fileName=%s s3Key=%s fileUrl=%s strictGrounding=%s",
        group_id, material_id, file_name, normalized_key, file_url, strict_grounding,
    )

    try:
        pdf_bytes = _load_pdf_from_s3(normalized_key)
        logger.info("[quiz:s3] loadedBytes=%s", len(pdf_bytes))
    except Exception as e:
        if strict_grounding:
            return _quiz_failure_response(
                "PDF_LOAD_FAILED",
                "PDF 파일을 불러오지 못해 문제를 생성할 수 없습니다.",
                material_id,
                file_name,
                group_id,
                reason=str(e),
            )
        result = build_fallback_quiz(file_name, f"S3 로드 실패: {e}")
        result["questions"] = _fallback_quiz_questions(count)
        return result

    try:
        pdf_text, method = _extract_pdf_text(pdf_bytes)
        source_len = len(pdf_text)
        logger.info("[quiz:extract] sourceTextLength=%s method=%s", source_len, method)
    except Exception as e:
        if strict_grounding:
            return _quiz_failure_response(
                "PDF_TEXT_EXTRACTION_FAILED",
                "PDF 내용을 읽지 못해 문제를 생성할 수 없습니다. PDF가 이미지 기반이면 OCR 처리가 필요합니다.",
                material_id,
                file_name,
                group_id,
                source_text_length=0,
                reason=str(e),
            )
        result = build_fallback_quiz(file_name, f"PDF 추출 실패: {e}")
        result["questions"] = _fallback_quiz_questions(count)
        return result

    if len(pdf_text) < 100:
        if strict_grounding:
            return _quiz_failure_response(
                "PDF_TEXT_EXTRACTION_FAILED",
                "PDF 내용을 읽지 못해 문제를 생성할 수 없습니다. PDF가 이미지 기반이면 OCR 처리가 필요합니다.",
                material_id,
                file_name,
                group_id,
                source_text_length=len(pdf_text),
                reason="PDF text shorter than 100 chars",
            )
        result = build_fallback_quiz(file_name, "PDF 텍스트 부족")
        result["questions"] = _fallback_quiz_questions(count)
        return result

    pdf_context, chunk_count = build_pdf_quiz_context(pdf_text)
    logger.info("[quiz:context] usedContextLength=%s chunkCount=%s", len(pdf_context), chunk_count)
    system = _build_grounded_quiz_system_prompt(count, difficulty, question_type, language)
    user = _build_grounded_quiz_user_prompt(file_name, material_id, group_id, difficulty, count, question_type, pdf_context)

    valid_questions: List[Dict[str, Any]] = []
    rejected_total = 0
    for attempt in range(2):
        raw = _call_quiz_llm(system, user, count)
        parsed = _parse_quiz_json(raw, count, question_type)
        valid_questions, rejected = validate_grounded_quiz_questions(parsed, pdf_text, count, question_type)
        rejected_total += rejected
        logger.info("[quiz:validate] requested=%s valid=%s rejected=%s", count, len(valid_questions), rejected_total)
        if len(valid_questions) >= count or attempt == 1:
            break
        missing = count - len(valid_questions)
        user = user + f"\n\n이전 응답에서 근거 검증을 통과한 문항이 부족했다. PDF 발췌문에 sourceSnippet이 그대로 존재하는 문항만 {missing}개까지 추가 생성하라."

    if not valid_questions:
        return _quiz_failure_response(
            "QUIZ_GROUNDING_FAILED",
            "PDF 근거가 확인된 문제를 생성하지 못했습니다.",
            material_id,
            file_name,
            group_id,
            source_text_length=len(pdf_text),
            reason="no validated sourceSnippet",
        )

    result: Dict[str, Any] = {
        "success": True,
        "quizTitle": f"[{file_name}] PDF 기반 학습 퀴즈",
        "materialId": material_id,
        "groupId": group_id,
        "fileName": file_name,
        "sourceTextLength": len(pdf_text),
        "usedContextLength": len(pdf_context),
        "questions": valid_questions[:count],
    }
    if len(valid_questions) < count:
        result["warning"] = f"요청한 {count}개 중 PDF 근거 검증을 통과한 {len(valid_questions)}개만 반환했습니다."
    return result


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
    strict_persona: bool = True,
    generation_payload: Optional[Dict[str, Any]] = None,
) -> str:
    """단일 에이전트 답변 생성 (Ollama 우선 → OpenAI fallback)."""
    system_prompt = build_agent_system_prompt_from_env(agent, learning_mode, strict_persona=strict_persona, context=context)
    turn_instr = build_agent_turn_instruction(agent_index, total_agents)

    user_parts: List[str] = []
    if turn_instr:
        user_parts.append(f"[이번 역할] {turn_instr}")
    user_parts.append(f"[사용자 메시지] {message}")
    user_prompt = "\n".join(user_parts)

    gen_config = get_generation_config(learning_mode, generation_payload)
    raw = _call_llm(
        system_prompt,
        user_prompt,
        max_tokens=gen_config["max_tokens"],
        temperature=gen_config["temperature"],
        top_p=gen_config["top_p"],
        model=gen_config["model"],
    )
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
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    userId: Optional[int] = Field(None, validation_alias=AliasChoices("userId", "user_id"), description="사용자 ID")
    weeklyStudySeconds: List[float] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "weeklyStudySeconds",
            "weekly_study_seconds",
            "weeklySeconds",
            "weekly_seconds",
            "studySeconds",
            "values",
        ),
        description="최근 7일 학습 시간 (초 단위)",
    )


class StudyTimePredictResponse(BaseModel):
    predictedStudySeconds: float
    method: str = "weighted_average_fallback"
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    modelAvailable: bool = False


class QuizGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    groupId: Optional[int] = Field(None, validation_alias=AliasChoices("groupId", "group_id"), description="그룹스터디 방 ID")
    materialId: Optional[int] = Field(None, validation_alias=AliasChoices("materialId", "material_id"), description="자료 ID")
    s3Key: Optional[str] = Field(None, validation_alias=AliasChoices("s3Key", "s3_key"), description="S3 오브젝트 키")
    fileUrl: Optional[str] = Field(None, validation_alias=AliasChoices("fileUrl", "file_url"), description="PDF 파일 URL")
    fileName: Optional[str] = Field(None, validation_alias=AliasChoices("fileName", "file_name"), description="원본 파일명")
    text: Optional[str] = Field(None, validation_alias=AliasChoices("text", "content", "body"), description="자료 본문(직접 전달 시 S3 대신 사용)")
    title: Optional[str] = Field(None, validation_alias=AliasChoices("title"), description="자료 제목(텍스트 기반 생성용)")
    difficulty: str = Field("medium", description="난이도: easy|medium|hard 또는 쉬움|보통|어려움")
    count: Optional[int] = Field(None, ge=1, le=10, description="생성 문항 수")
    numQuestions: Optional[int] = Field(None, validation_alias=AliasChoices("numQuestions", "num_questions"), ge=1, le=10, description="생성 문항 수 하위 호환 필드")
    questionType: str = Field("multiple_choice", validation_alias=AliasChoices("questionType", "question_type"), description="multiple_choice|short_answer|mixed")
    language: str = Field("ko", description="응답 언어")
    strictGrounding: bool = Field(True, validation_alias=AliasChoices("strictGrounding", "strict_grounding"), description="PDF 근거 강제 여부")
    sourceName: Optional[str] = Field(None, description="자료 표시명")
    range: Optional[Any] = Field(None, description="자료 범위 호환 필드")


class QuizQuestion(BaseModel):
    question: str
    options: List[str] = Field(default_factory=list)
    correctAnswer: Optional[int] = Field(None, ge=0, le=3)
    answer: Optional[str] = None
    explanation: Optional[str] = None
    questionType: Optional[str] = None
    sourceSnippet: Optional[str] = None
    timeLimitSeconds: int = Field(DEFAULT_QUIZ_TIME_LIMIT_SECONDS)


class QuizGenerateResponse(BaseModel):
    success: bool = True
    quizTitle: Optional[str] = None
    errorCode: Optional[str] = None
    message: Optional[str] = None
    materialId: Optional[int] = None
    groupId: Optional[int] = None
    fileName: Optional[str] = None
    sourceTextLength: Optional[int] = None
    usedContextLength: Optional[int] = None
    warning: Optional[str] = None
    questions: List[QuizQuestion] = Field(default_factory=list)


class PreviousAnswer(BaseModel):
    agentName: str
    answer: str
    role: str = "ASSISTANT"
    agentId: Optional[int] = None


class AgentProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: Optional[Any] = None
    agentId: Optional[Any] = Field(None, validation_alias=AliasChoices("agentId", "agent_id", "id"))
    name: str = Field("에이전트", validation_alias=AliasChoices("name", "agentName", "agent_name", "displayName"))
    role: Optional[str] = Field(None, validation_alias=AliasChoices("role", "agentRole", "agent_role"))
    personality: Optional[str] = Field(None, validation_alias=AliasChoices("personality", "persona", "type"))
    personalityLabel: Optional[str] = Field(None, validation_alias=AliasChoices("personalityLabel", "personality_label"))
    personalityStrength: Optional[str] = Field(None, validation_alias=AliasChoices("personalityStrength", "personality_strength"))
    style: Optional[str] = None
    tone: Optional[str] = None
    knowledgeLevel: Optional[str] = Field(None, validation_alias=AliasChoices("knowledgeLevel", "knowledge_level", "level"))
    knowledgeLevelLabel: Optional[str] = Field(None, validation_alias=AliasChoices("knowledgeLevelLabel", "knowledge_level_label"))
    customInstruction: Optional[str] = Field(None, validation_alias=AliasChoices("customInstruction", "custom_instruction"))


class MultiChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    groupId: Optional[Any] = Field(None, validation_alias=AliasChoices("groupId", "group_id"))
    roomId: Optional[Any] = Field(None, validation_alias=AliasChoices("roomId", "room_id"))
    agentRoomId: Optional[Any] = Field(None, validation_alias=AliasChoices("agentRoomId", "agent_room_id"))
    message: str = Field(..., min_length=1, description="사용자 메시지")
    materialId: Optional[int] = Field(None, validation_alias=AliasChoices("materialId", "material_id"))
    mode: str = Field("multi_agent_discussion")
    learningMode: Optional[str] = Field("basic", validation_alias=AliasChoices("learningMode", "learning_mode"))
    rounds: int = Field(default_factory=lambda: env_int("AI_DEFAULT_AGENT_ROUNDS", 3), ge=1, le=5)
    showFinalSynthesis: bool = Field(True, validation_alias=AliasChoices("showFinalSynthesis", "show_final_synthesis"))
    targetAgentId: Optional[Any] = Field(None, validation_alias=AliasChoices("targetAgentId", "target_agent_id"))
    previousAnswers: List[PreviousAnswer] = Field(default_factory=list, validation_alias=AliasChoices("previousAnswers", "previous_answers"))
    agents: List[AgentProfile] = Field(default_factory=list)
    strictPersona: bool = Field(default_factory=lambda: env_bool("AI_STRICT_PERSONA_DEFAULT", True), validation_alias=AliasChoices("strictPersona", "strict_persona"))
    temperature: Optional[float] = None
    topP: Optional[float] = Field(None, validation_alias=AliasChoices("topP", "top_p"))
    maxTokens: Optional[int] = Field(None, validation_alias=AliasChoices("maxTokens", "max_tokens"))
    model: Optional[str] = None

class AgentAnswer(BaseModel):
    agentName: str
    answer: str
    agentId: Optional[Any] = None
    senderType: str = "AGENT"
    personality: Optional[str] = None
    personalityLabel: Optional[str] = None
    knowledgeLevel: Optional[str] = None
    knowledgeLevelLabel: Optional[str] = None
    role: Optional[str] = None
    mode: Optional[str] = None
    round: Optional[int] = None
    sequence: Optional[int] = None
    content: Optional[str] = None
    createdAt: Optional[str] = None


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


class MultiChatMessage(BaseModel):
    senderType: str = "AGENT"
    agentId: Optional[Any] = None
    agentName: str
    personality: Optional[str] = None
    personalityLabel: Optional[str] = None
    knowledgeLevel: Optional[str] = None
    knowledgeLevelLabel: Optional[str] = None
    role: Optional[str] = None
    mode: str
    round: int = 1
    sequence: int = 1
    content: str
    createdAt: Optional[str] = None
    groupId: Optional[Any] = None
    roomId: Optional[Any] = None


class MultiChatResponse(BaseModel):
    success: bool = True
    groupId: Optional[Any] = None
    roomId: Optional[Any] = None
    agentRoomId: Optional[Any] = None
    mode: str
    answers: List[AgentAnswer]
    messages: List[MultiChatMessage] = Field(default_factory=list)
    processSteps: Optional[ProcessSteps] = None


# ─────────────────────────────────────────────────────────────────────────────
# 14. 동기 실행 함수 (asyncio.to_thread에서 호출)
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_AGENT_PROFILE = AgentProfile(
    id=0,
    agentId="agent-1",
    name=DEFAULT_AGENT_NAME,
    role=os.getenv("AI_DEFAULT_AGENT_ROLE", "학습 지원"),
    personality=os.getenv("AI_DEFAULT_PERSONALITY", "friendly"),
    personalityLabel=os.getenv("AI_DEFAULT_PERSONALITY_LABEL", "친절형"),
    personalityStrength="moderate",
    knowledgeLevel=os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL", "undergraduate"),
    knowledgeLevelLabel=os.getenv("AI_DEFAULT_KNOWLEDGE_LEVEL_LABEL", "학사"),
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
    strict_persona: bool = True,
    generation_payload: Optional[Dict[str, Any]] = None,
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
            strict_persona=strict_persona,
            generation_payload=generation_payload,
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
            "finalAnswer": _agent_answer_from_agent(agent, final_answer_text, learning_mode, 1, agent_index + 1),
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
    strict_persona: bool = True,
    generation_payload: Optional[Dict[str, Any]] = None,
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
                strict_persona,
                generation_payload,
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
    strict_persona: bool = True,
    generation_payload: Optional[Dict[str, Any]] = None,
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
                    strict_persona=strict_persona,
                    generation_payload=generation_payload,
                )
                # agent_quality_policy 검증 & 보정
                final_text, meta = validate_and_revise_agent_answer(
                    answer=raw,
                    agent_payload=_to_agent_dict(agent),
                    user_message=message,
                    response_mode="general",
                )
                logger.debug("agent=%s passed=%s score=%s", agent.name, meta.get("passed"), meta.get("score"))
                answers.append(_agent_answer_from_agent(
                    agent,
                    sanitize_answer_for_spring(final_text),
                    learning_mode,
                    round_idx + 1,
                    len(answers) + 1,
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

_AI_CAPABILITIES = ["multi-chat", "rag", "quiz"]


@app.get("/health", tags=["Health"])
async def health_root():
    """루트 헬스 체크 (uvicorn 직접 실행 확인용)."""
    return {
        "status": "ok",
        "service": "studybridge-fastapi",
        "version": "0.6.0",
        "capabilities": _AI_CAPABILITIES,
    }


@app.get("/api/ai/health", tags=["Health"])
async def health_ai():
    """AI capability 헬스 체크 (quiz 포함)."""
    return {
        "status": "ok",
        "service": "studybridge-fastapi",
        "capabilities": _AI_CAPABILITIES,
    }


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
    "/api/ai/predict-study-time",
    response_model=StudyTimePredictResponse,
    tags=["Study Time Prediction"],
    include_in_schema=False,
)
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
        result = await asyncio.wait_for(
            asyncio.to_thread(predict_study_time_result, list(request.weeklyStudySeconds)),
            timeout=AI_RESPONSE_TIMEOUT_SECONDS,
        )
        return StudyTimePredictResponse(**result)
    except asyncio.TimeoutError:
        logger.warning("학습 시간 예측 타임아웃. 가중 평균 fallback 반환")
        result = {
            "predictedStudySeconds": _weighted_average_predict(list(request.weeklyStudySeconds)),
            "method": "weighted_average_fallback",
            "confidence": 0.35,
            "modelAvailable": False,
        }
        return StudyTimePredictResponse(**result)
    except Exception as e:
        logger.error("학습 시간 예측 오류. 가중 평균 fallback 반환: %s", e)
        result = {
            "predictedStudySeconds": _weighted_average_predict(list(request.weeklyStudySeconds)),
            "method": "weighted_average_fallback",
            "confidence": 0.3,
            "modelAvailable": False,
        }
        return StudyTimePredictResponse(**result)


@app.post(
    "/api/ai/quiz/generate",
    response_model=QuizGenerateResponse,
    tags=["Quiz Generation"],
)
async def generate_quiz_endpoint(request: QuizGenerateRequest):
    """
    S3 PDF 기반 또는 텍스트 본문 기반 퀴즈 생성.
    text 필드가 채워져 있으면 S3를 거치지 않고 본문으로 직접 생성하며,
    이때는 단순 계약({success, materialId, quiz, error})으로 응답한다.
    text가 없으면 기존 S3 PDF 경로(strictGrounding)로 동작한다.
    """
    # 텍스트 본문 직접 전달 경로 (Spring이 추출 본문을 넘긴 경우)
    if request.text and request.text.strip():
        import uuid as _uuid

        try:
            from quiz_text_compat import generate_quiz_from_text
        except Exception as e:
            logger.error("quiz_text 모듈 로드 실패: %s", e)
            raise HTTPException(status_code=500, detail="텍스트 퀴즈 생성 모듈을 로드하지 못했습니다.")

        request_id = _uuid.uuid4().hex[:8]
        text_result = await asyncio.to_thread(
            generate_quiz_from_text,
            text=request.text,
            title=request.title or request.sourceName or request.fileName,
            difficulty=request.difficulty,
            count=request.count or request.numQuestions,
            question_type=request.questionType,
            material_id=request.materialId,
            request_id=request_id,
        )
        status_code = 200 if text_result.get("success") else 422
        return JSONResponse(content=text_result, status_code=status_code)

    if request.materialId is None:
        raise HTTPException(status_code=400, detail="materialId는 필수입니다.")
    if not (request.s3Key or request.fileUrl):
        raise HTTPException(status_code=400, detail="s3Key 또는 fileUrl 중 하나는 필수입니다.")

    count = max(1, min(int(request.count or request.numQuestions or 5), 10))
    file_name = request.sourceName or request.fileName or "PDF"
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                generate_quiz_from_pdf,
                material_id=request.materialId,
                s3_key=request.s3Key or "",
                file_name=file_name,
                difficulty=request.difficulty,
                count=count,
                question_type=request.questionType,
                language=request.language or "ko",
                group_id=request.groupId,
                file_url=request.fileUrl,
                strict_grounding=True if request.strictGrounding is None else bool(request.strictGrounding),
            ),
            timeout=QUIZ_GENERATION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = _quiz_failure_response(
            "QUIZ_GENERATE_TIMEOUT",
            "퀴즈 생성 요청이 시간 초과되었습니다.",
            request.materialId,
            file_name,
            request.groupId,
            reason="timeout",
        )
    except Exception as e:
        logger.error("퀴즈 생성 오류: %s", e)
        result = _quiz_failure_response(
            "QUIZ_GENERATE_FAILED",
            "퀴즈 생성 중 서버 오류가 발생했습니다.",
            request.materialId,
            file_name,
            request.groupId,
            reason=str(e),
        )

    return QuizGenerateResponse(**result)



async def build_rag_context_for_multi_chat(request: MultiChatRequest) -> str:
    """
    /api/ai/multi-chat에서 materialId가 들어온 경우,
    운영 RAG(/api/rag/query)를 조회해서 agent prompt context로 주입한다.
    """
    import json
    import os
    import urllib.request

    material_id = getattr(request, "materialId", None)
    message = (getattr(request, "message", "") or "").strip()

    if material_id is None or not message:
        return ""

    top_k = int(os.getenv("RAG_TOP_K", "5"))
    max_chars = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "7000"))
    port = os.getenv("PORT") or os.getenv("FASTAPI_PORT") or "8000"
    base_url = (
        os.getenv("RAG_QUERY_BASE_URL")
        or os.getenv("FASTAPI_SELF_BASE_URL")
        or f"http://127.0.0.1:{port}"
    ).rstrip("/")
    api_key = os.getenv("AI_SERVER_API_KEY", "")

    payload = {
        "material_id": int(material_id),
        "question": message,
        "top_k": top_k,
    }

    def _post():
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/rag/query",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode("utf-8"))

    try:
        data = await asyncio.to_thread(_post)
    except Exception as e:
        logger.warning(
            "[RAG MULTI-CHAT SKIP] materialId=%s question_len=%s error=%s",
            material_id, len(message), e,
        )
        return ""

    chunks = data.get("chunks") or []
    if not chunks:
        logger.info("[RAG MULTI-CHAT EMPTY] materialId=%s question=%s", material_id, message[:80])
        return ""

    parts = [
        "[업로드 자료 RAG 검색 결과]",
        "아래 내용은 사용자가 업로드한 자료에서 검색된 근거입니다.",
        "답변은 반드시 이 근거를 우선 사용하고, 근거에 없는 내용은 추측하지 마세요.",
    ]

    for idx, chunk in enumerate(chunks, start=1):
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        if len(content) > 1800:
            content = content[:1800] + "..."

        chunk_id = chunk.get("chunk_id", idx)
        similarity = chunk.get("similarity")
        parts.append(
            f"[근거 {idx}] chunk_id={chunk_id}, similarity={similarity}\n{content}"
        )

    context = "\n\n".join(parts)
    logger.info(
        "[RAG MULTI-CHAT OK] materialId=%s chunks=%s context_chars=%s",
        material_id, len(chunks), len(context),
    )
    return context[:max_chars]


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

    raw_agents = [_to_agent_dict(agent) for agent in (request.agents or [])]
    if raw_agents:
        agents = [AgentProfile(**normalize_agent(agent, idx)) for idx, agent in enumerate(raw_agents)]
    else:
        default_count = max(1, min(env_int("AI_DEFAULT_AGENT_COUNT", 3), 10))
        agents = [AgentProfile(**normalize_agent({}, idx)) for idx in range(default_count)]
    active_agents = select_agents_for_response(agents, request.targetAgentId)
    previous_context = build_context_from_previous_answers(request.previousAnswers)
    rag_context = await build_rag_context_for_multi_chat(request)
    context = "\n\n".join(part for part in [rag_context, previous_context] if part)
    rounds = min(request.rounds, MULTI_CHAT_MAX_ROUNDS)
    requested_mode = (request.mode or request.learningMode or "default").strip()
    learning_mode = normalize_learning_mode(request.learningMode or request.mode)
    persona_mode = requested_mode.lower()
    effective_timeout = resolve_multi_chat_timeout(request.mode, learning_mode)
    generation_payload = {
        "temperature": request.temperature,
        "topP": request.topP,
        "maxTokens": request.maxTokens,
        "model": request.model,
    }
    gen_config = get_generation_config(persona_mode, generation_payload)
    logger.info("[config] AI_DEFAULT_MODEL=%s", os.getenv("AI_DEFAULT_MODEL", OLLAMA_MODEL))
    logger.info("[config] AI_DEFAULT_TEMPERATURE=%s", os.getenv("AI_DEFAULT_TEMPERATURE"))
    logger.info("[config] AI_STRICT_PERSONA_DEFAULT=%s", os.getenv("AI_STRICT_PERSONA_DEFAULT"))
    logger.info(
        "[agent:req] mode=%s groupId=%s roomId=%s agentCount=%s strictPersona=%s",
        persona_mode, request.groupId, request.roomId, len(active_agents), request.strictPersona,
    )
    logger.info(
        "[agent:config] mode=%s temperature=%s topP=%s maxTokens=%s",
        persona_mode, gen_config["temperature"], gen_config["top_p"], gen_config["max_tokens"],
    )
    for agent in active_agents:
        logger.info(
            "[agent:agent] id=%s name=%s personality=%s knowledgeLevel=%s role=%s",
            agent.agentId, agent.name, agent.personality, agent.knowledgeLevel, agent.role,
        )

    if should_use_internal_collaboration(request.mode):
        # 협업 모드: 순차 실행 (기존 로직 유지)
        try:
            raw_answers = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_multi_chat_sync,
                    active_agents, request.message, context, rounds, request.showFinalSynthesis,
                    persona_mode, request.strictPersona, generation_payload,
                ),
                timeout=effective_timeout,
            )
            messages = build_messages_from_answers(active_agents, raw_answers, persona_mode, request.groupId, request.roomId)
            return MultiChatResponse(
                success=True,
                groupId=request.groupId,
                roomId=request.roomId,
                agentRoomId=request.agentRoomId,
                mode=persona_mode,
                answers=raw_answers,
                messages=messages,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "multi-chat 협업 타임아웃 mode=%s requested_agent_count=%d "
                "elapsed_seconds=%d validation_enabled=%s",
                request.mode, len(active_agents),
                effective_timeout, AI_VALIDATION_ENABLED,
            )
            raw_answers = [
                _agent_answer_from_agent(a, _FALLBACK_TIMEOUT, persona_mode, 1, idx + 1)
                for idx, a in enumerate(active_agents)
            ]
            return MultiChatResponse(
                success=False,
                groupId=request.groupId,
                roomId=request.roomId,
                agentRoomId=request.agentRoomId,
                mode=persona_mode,
                answers=raw_answers,
                messages=build_messages_from_answers(active_agents, raw_answers, persona_mode, request.groupId, request.roomId),
            )
        except Exception as e:
            logger.error("[agent:fail] code=MULTI_CHAT_FAILED reason=%s", e)
            logger.error("multi-chat 협업 오류: %s", e)
            raw_answers = [
                _agent_answer_from_agent(a, _FALLBACK_LLM_UNAVAILABLE, persona_mode, 1, idx + 1)
                for idx, a in enumerate(active_agents)
            ]
            return MultiChatResponse(
                success=False,
                groupId=request.groupId,
                roomId=request.roomId,
                agentRoomId=request.agentRoomId,
                mode=persona_mode,
                answers=raw_answers,
                messages=build_messages_from_answers(active_agents, raw_answers, persona_mode, request.groupId, request.roomId),
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
                persona_mode,
                request.strictPersona,
                generation_payload,
            )
            logger.info(
                "parallel multi-chat 완료 mode=%s learningMode=%s requested_agent_count=%d "
                "returned_count=%d validation_enabled=%s",
                persona_mode, learning_mode, len(active_agents), len(raw_answers), AI_VALIDATION_ENABLED,
            )
            messages = build_messages_from_answers(active_agents, raw_answers, persona_mode, request.groupId, request.roomId)
            return MultiChatResponse(
                success=True,
                groupId=request.groupId,
                roomId=request.roomId,
                agentRoomId=request.agentRoomId,
                mode=persona_mode,
                answers=raw_answers,
                messages=messages,
                processSteps=process_steps,
            )
        except Exception as e:
            logger.error("[agent:fail] code=MULTI_CHAT_FAILED reason=%s", e)
            logger.error(
                "parallel multi-chat 예외 mode=%s requested_agent_count=%d "
                "validation_enabled=%s error=%s",
                persona_mode, len(active_agents), AI_VALIDATION_ENABLED, e,
            )
            # 예외 시에도 agents 수만큼 fallback 반환
            raw_answers = [
                _agent_answer_from_agent(a, f"{a.name} 응답 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", persona_mode, 1, idx + 1)
                for idx, a in enumerate(active_agents)
            ]
            return MultiChatResponse(
                success=False,
                groupId=request.groupId,
                roomId=request.roomId,
                agentRoomId=request.agentRoomId,
                mode=persona_mode,
                answers=raw_answers,
                messages=build_messages_from_answers(active_agents, raw_answers, persona_mode, request.groupId, request.roomId),
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
    from app.api.keyword_routes import router as _keyword_router
    from app.api.planner_ai_routes import router as _planner_ai_router
    from app.api.study_ai_routes import router as _study_ai_router
    from app.api.material_analyze_routes import router as _material_analyze_router
    from app.api.review_ai_routes import router as _review_ai_router

    app.include_router(_spring_rag_router)      # /api/rag/ingest, /api/rag/query, DELETE /api/rag/materials/{id}
    app.include_router(_rag_legacy_router)      # /api/materials/{id}/rag/* (하위 호환)
    app.include_router(_deep_search_router)     # /api/agent/deep-search
    app.include_router(_training_router)        # /api/training-candidates/stats, /export-jsonl
    app.include_router(_agent_chat_router)      # /api/ai/chat, /api/ai/material/*
    app.include_router(_roadmap_router)         # POST /api/materials/{id}/ai/roadmap
    app.include_router(_material_legacy_router) # POST /api/ai/summary|quiz|question|roadmap|feedback (자료보관함 라이브)
    app.include_router(_keyword_router)         # POST /api/ai/keyword/define (핵심 키워드 개념 정의)
    app.include_router(_planner_ai_router)      # POST /api/ai/planner/expand|roadmap|week-expand (공부 플래너 전용 AI)
    app.include_router(_study_ai_router)        # POST /api/ai/roadmap/generate (문서 기반 12주×7일 로드맵)
    app.include_router(_material_analyze_router)  # POST /api/ai/material/analyze|analyze-job|analyze-stream (자료보관함 구조화 요약)
    app.include_router(_review_ai_router)       # POST /api/ai/review/wrong-note-feedback|variant-question (오답노트 복습 AI)

    logger.info("v0.6 확장 라우터 로드 완료 (로드맵 + 자료보관함 라이브 + 오답노트 포함)")
except Exception as _ext_err:
    logger.warning("v0.6 확장 라우터 로드 실패 (Spring 계약 API는 정상 동작): %s", _ext_err)


# ─────────────────────────────────────────────────────────────────────────────
# 직접 실행 (개발용)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
