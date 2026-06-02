"""
환경변수 중앙 관리 모듈.
os.getenv를 각 파일에서 직접 호출하지 않도록 이 모듈에서 통합 관리한다.
"""
import os
from dotenv import load_dotenv

# .env 파일 로드 (없어도 오류 발생 안 함)
load_dotenv()

# ----- Qwen2.5 vLLM 서버 -----
QWEN_BASE_URL: str = os.getenv("QWEN_BASE_URL", "http://localhost:8001/v1")
QWEN_MODEL_NAME: str = os.getenv("QWEN_MODEL_NAME", "Qwen/Qwen2.5-14B-Instruct")
QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "EMPTY")

# ----- Tavily 검색 -----
TAVILY_API_KEY: str | None = os.getenv("TAVILY_API_KEY")

# ----- OpenAI (추후 ChatGPT 교차 검증용) -----
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

# ----- Wikipedia -----
WIKI_LANGUAGE: str = os.getenv("WIKI_LANGUAGE", "ko")
WIKI_USER_AGENT: str = os.getenv("WIKI_USER_AGENT", "StudyBridge-Capstone/1.0")

# ----- 검색 기본값 -----
DEFAULT_SEARCH_DEPTH: str = os.getenv("DEFAULT_SEARCH_DEPTH", "basic")
DEFAULT_MAX_RESULTS: int = int(os.getenv("DEFAULT_MAX_RESULTS", "5"))

# ----- PostgreSQL + pgvector (AI RAG 전용 DB) -----
VECTOR_DATABASE_URL: str | None = os.getenv("VECTOR_DATABASE_URL")

# ----- 임베딩 모델 -----
EMBEDDING_MODEL_NAME: str = os.getenv(
    "EMBEDDING_MODEL_NAME", "intfloat/multilingual-e5-base"
)
EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "768"))

# ----- RAG 파라미터 -----
RAG_CHUNK_SIZE: int   = int(os.getenv("RAG_CHUNK_SIZE",   "800"))
RAG_CHUNK_OVERLAP: int = int(os.getenv("RAG_CHUNK_OVERLAP", "120"))
RAG_TOP_K: int        = int(os.getenv("RAG_TOP_K",        "5"))
RAG_MIN_SCORE: float  = float(os.getenv("RAG_MIN_SCORE",  "0.30"))

# ----- 내부 API 인증 (Spring Boot ↔ FastAPI) -----
AI_SERVER_API_KEY: str | None = os.getenv("AI_SERVER_API_KEY")

# ----- GPT 모델 설정 (자료보관함 AI + 검증) -----
GPT_MODEL_MATERIAL: str = os.getenv("GPT_MODEL_MATERIAL", "gpt-4o-mini")
GPT_MODEL_VERIFIER: str = os.getenv("GPT_MODEL_VERIFIER", "gpt-4o-mini")

# ----- 에이전트 채팅 기본값 -----
DEFAULT_KNOWLEDGE_LEVEL: str = os.getenv("DEFAULT_KNOWLEDGE_LEVEL", "학사")
DEFAULT_PERSONALITY: str     = os.getenv("DEFAULT_PERSONALITY", "친절_설명형")
DEFAULT_AGENT_NAME: str      = os.getenv("DEFAULT_AGENT_NAME", "자바도우미")

# ----- 티키타카 설정 -----
TIKI_TAKA_MAX_ROUND: int        = int(os.getenv("TIKI_TAKA_MAX_ROUND", "2"))
TIKI_TAKA_MAX_TOKENS: int       = int(os.getenv("TIKI_TAKA_MAX_TOKENS", "400"))

# ----- 검증 작업 보관 최대 수 (메모리 보호) -----
VALIDATION_JOB_MAX: int = int(os.getenv("VALIDATION_JOB_MAX", "200"))

# ----- AI 전용 DB (기존 capstone DB와 분리) -----
# 기존 DB: DB_HOST=db, DB_NAME=capstone (Spring Boot 전용)
# AI DB: AI_DATABASE_URL → ai-db (FastAPI AI 서버 전용)
AI_DATABASE_URL: str | None = os.getenv(
    "AI_DATABASE_URL",
    os.getenv("VECTOR_DATABASE_URL"),  # 하위 호환: VECTOR_DATABASE_URL도 허용
)

# ----- Redis -----
REDIS_URL: str | None = os.getenv("REDIS_URL")

# ----- Ollama (로컬 LLM 서버) -----
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str    = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT: int  = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))

# ----- OpenAI 임베딩 -----
OPENAI_MODEL: str           = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_EMBEDDING_DIM: int   = int(os.getenv("OPENAI_EMBEDDING_DIM", "1536"))

# ----- 학습 후보 자동 판정 기준 -----
TRAINING_AUTO_APPROVE_SCORE: int = int(os.getenv("TRAINING_AUTO_APPROVE_SCORE", "90"))
TRAINING_HOLDOUT_SCORE: int      = int(os.getenv("TRAINING_HOLDOUT_SCORE", "70"))

# ----- 환경 구분 -----
APP_ENV: str  = os.getenv("APP_ENV", "local")
APP_NAME: str = os.getenv("APP_NAME", "StudyBridge AI Server")
API_PREFIX: str = os.getenv("API_PREFIX", "/api")
