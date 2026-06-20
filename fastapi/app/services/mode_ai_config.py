"""
Mode-Aware AI Config — 방 모드별 AI 동작 정책 SSOT(Single Source of Truth).

StudyBridge의 각 방 모드(basic/expert/socratic/debate/roleplay/rag/multi_agent/
exam/code_review/research)마다 시스템 프롬프트, 답변 깊이, 전문용어 강도, 도구
사용 정책(OpenAI/Tavily/Wikipedia/RAG), 답변 구조, 검증 단계, 생성 파라미터
(temperature/top_p/max_tokens)를 "코드 한 곳"에서 선언적으로 정의한다.

설계 원칙:
- 모든 수치/플래그는 .env(AI_MODE_*, AI_DEFAULT_*, AI_EXPERT_* 등)로 튜닝 가능하며,
  환경변수가 없으면 본 모듈의 안전한 기본값으로 fallback한다.
- secret(키 값)은 이 모듈에서 읽지 않는다. on/off 플래그와 모델명·수치만 다룬다.
- 알 수 없는 mode는 'basic'으로 fallback하되 로그를 남긴다. 사용자에게 내부 에러를
  노출하지 않는다.
- 이 모듈은 LLM을 호출하지 않는다. 순수 설정/정책 객체만 제공한다(부작용 없음).
- 기존 라우터/스키마/엔진을 강제로 바꾸지 않는다. caller가 필요할 때만 참조한다.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 환경변수 헬퍼 (secret 미취급, 안전한 기본값 fallback)
# ──────────────────────────────────────────────────────────────────────────────
def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v.strip() if v and v.strip() else default


def config_enabled() -> bool:
    """Mode-Aware 정책 전체 on/off. false면 caller는 기존 기본 동작을 유지해야 한다."""
    return _flag("AI_MODE_CONFIG_ENABLED", True)


# ──────────────────────────────────────────────────────────────────────────────
# 전역 기본값 (provider / model / 샘플링) — .env로 덮어쓰기 가능
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_PROVIDER = _str("AI_DEFAULT_PROVIDER", "ollama")
DEFAULT_MODEL = _str("AI_DEFAULT_MODEL", "qwen3:14b")
DEFAULT_TEMPERATURE = _float("AI_DEFAULT_TEMPERATURE", 0.45)
DEFAULT_TOP_P = _float("AI_DEFAULT_TOP_P", 0.85)
DEFAULT_MAX_TOKENS = _int("AI_DEFAULT_MAX_TOKENS", 4096)

EXPERT_PROVIDER = _str("AI_EXPERT_PROVIDER", "openai")
EXPERT_MODEL = _str("AI_EXPERT_MODEL", "gpt-4o-mini")

OLLAMA_ENABLED = _flag("AI_OLLAMA_ENABLED", True)
OPENAI_ENABLED = _flag("AI_OPENAI_ENABLED", True)
TAVILY_ENABLED = _flag("AI_TAVILY_ENABLED", True)
WIKIPEDIA_ENABLED = _flag("AI_WIKIPEDIA_ENABLED", True)
RAG_ENABLED = _flag("AI_RAG_ENABLED", True)
QUALITY_VALIDATION_ENABLED = _flag("AI_QUALITY_VALIDATION_ENABLED", True)

# fallback 정책 (caller가 라우팅 시 참조)
OPENAI_FALLBACK_TO_OLLAMA = _flag("AI_OPENAI_FALLBACK_TO_OLLAMA", True)
SEARCH_FAILURE_ALLOW_MODEL_ONLY = _flag("AI_SEARCH_FAILURE_ALLOW_MODEL_ONLY", True)
RAG_FAILURE_ALLOW_GENERAL_ANSWER = _flag("AI_RAG_FAILURE_ALLOW_GENERAL_ANSWER", True)


# ──────────────────────────────────────────────────────────────────────────────
# 모드 이름 매핑 — 프론트/레거시에서 쓰는 다양한 이름을 표준 mode로 정규화
# ──────────────────────────────────────────────────────────────────────────────
SUPPORTED_MODES = (
    "basic", "expert", "socratic", "debate", "roleplay",
    "rag", "multi_agent", "exam", "code_review", "research",
)

MODE_ALIASES: Dict[str, str] = {
    # basic
    "default_chat": "basic", "default": "basic", "normal": "basic",
    "chat": "basic", "general": "basic", "study_mate": "basic", "studymate": "basic",
    # expert
    "professor": "expert", "expert_mode": "expert", "phd": "expert",
    "academic": "expert", "deep": "expert",
    # socratic
    "socrates": "socratic", "socratic_mode": "socratic", "tutor": "socratic",
    # debate
    "debate_room": "debate", "discussion": "debate", "debate_mode": "debate",
    # roleplay
    "simulation": "roleplay", "interview": "roleplay", "roleplay_mode": "roleplay",
    "counsel": "roleplay", "role_play": "roleplay",
    # rag
    "material_chat": "rag", "document_chat": "rag", "doc": "rag",
    "material": "rag", "rag_mode": "rag",
    # multi_agent
    "group_study": "multi_agent", "multi_chat": "multi_agent", "multichat": "multi_agent",
    "multiagent": "multi_agent", "agents": "multi_agent", "tiki_taka": "multi_agent",
    "multi": "multi_agent",
    # exam
    "quiz_exam": "exam", "quiz": "exam", "exam_mode": "exam", "test": "exam",
    # code_review
    "code": "code_review", "review": "code_review", "code_review_mode": "code_review",
    "coding": "code_review",
    # research
    "deep_search": "research", "deepsearch": "research", "research_mode": "research",
    "investigate": "research", "deep_research": "research",
}


def normalize_mode(mode: Optional[str]) -> str:
    """프론트/레거시 mode 문자열을 표준 mode로 정규화한다. 알 수 없으면 basic."""
    if not mode:
        return "basic"
    key = str(mode).strip().lower().replace("-", "_").replace(" ", "_")
    if key in SUPPORTED_MODES:
        return key
    if key in MODE_ALIASES:
        return MODE_ALIASES[key]
    logger.info("[mode_ai_config] unknown mode=%r → basic 으로 fallback", mode)
    return "basic"


# ──────────────────────────────────────────────────────────────────────────────
# ModeAIConfig
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ModeAIConfig:
    mode: str
    display_name: str
    provider: str                 # 주력 provider: "ollama" | "openai"
    model: str
    temperature: float
    top_p: float
    max_tokens: int

    # 도구/엔진 사용 정책
    use_openai: bool = True
    use_ollama: bool = True
    use_tavily: bool = False
    use_wikipedia: bool = False
    use_rag: bool = False
    use_quality_validator: bool = False
    # 이 모드의 1순위 도구(있으면 질문 신호와 무관하게 강제 활성). "rag" | "tavily" | None
    primary_tool: Optional[str] = None

    # 답변 계약
    require_citations: bool = False
    require_examples: bool = True
    require_multiple_perspectives: bool = False
    require_terminology_explanation: bool = True

    # 답변 구조(섹션 제목 목록)
    answer_sections: List[str] = field(default_factory=list)

    # mode별 시스템 프롬프트(공통 SSOT 헤더 + 모드 역할)
    system_prompt: str = ""

    def resolved_provider(self) -> str:
        """전역 enabled 플래그를 반영해 실제 사용 가능한 provider를 고른다."""
        if self.provider == "openai" and not (self.use_openai and OPENAI_ENABLED):
            return "ollama"
        if self.provider == "ollama" and not (self.use_ollama and OLLAMA_ENABLED):
            return "openai" if OPENAI_ENABLED else "ollama"
        return self.provider

    def as_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────────
# 공통 System Prompt 헤더 (모든 모드 공유 — 학문 분야 무관 전문가 원칙)
# ──────────────────────────────────────────────────────────────────────────────
COMMON_SYSTEM_HEADER = (
    "너는 StudyBridge의 AI 학습메이트다.\n"
    "너는 컴퓨터공학 전용이 아니라 수학·물리·화학·생명과학·공학·심리·철학·경제·경영·"
    "역사·언어·교육·법·정책·예술이론 등 모든 학문 분야에 대해 질문 의도를 분석하고, "
    "해당 분야의 전문용어와 이론체계를 활용해 답한다.\n"
    "전문용어는 회피하지 말고 적극 사용하되, 처음 등장할 때 반드시 쉬운 말로 뜻을 풀어라.\n"
    "단순 요약이 아니라 원리·구조·예시·한계·흔한 오해를 함께 설명한다.\n"
    "사용자가 선택한 방 모드의 역할과 답변 구조를 반드시 따른다.\n"
    "자료(문서) 기반 질문에서는 문서 근거를 우선하고, 문서에 없는 내용은 구분해서 말한다.\n"
    "검색 결과를 그대로 복붙하지 말고, 신뢰 가능한 근거만 합성해 답한다.\n"
    "반드시 한국어로 답한다."
)


def _prompt(role: str) -> str:
    return f"{COMMON_SYSTEM_HEADER}\n\n[현재 방 모드 역할]\n{role.strip()}"


# 모드별 역할/규칙 본문
_BASIC_ROLE = (
    "역할: 친절하고 명확한 학습 도우미.\n"
    "- 과도하게 장황하지 않게, 핵심을 또렷이 전달한다.\n"
    "- 사용자가 모를 만한 단어는 풀어서 설명하고 쉬운 예시를 든다.\n"
    "- 너무 깊게 들어가지 않되 정확해야 한다."
)
_EXPERT_ROLE = (
    "역할: 교수/연구자 수준의 전문가.\n"
    "- 단순 요약 금지. 원리·구조·이론/실무/비판 관점·한계·반론을 포함한다.\n"
    "- 전문용어를 적극 사용하되 각 용어는 '쉬운 말 + 학문적 정의'로 풀어라.\n"
    "  예) 캡슐화(encapsulation): 객체 내부 상태와 불변식을 외부로부터 보호하는 경계 설정.\n"
    "- 모든 학문 분야에서 박사급 깊이를 유지한다."
)
_SOCRATIC_ROLE = (
    "역할: 소크라테스식 튜터.\n"
    "- 처음부터 완성된 정답 장문을 출력하지 않는다.\n"
    "- 사용자의 현재 이해를 확인하고, 핵심 질문 1개와 단계적 힌트로 사고를 유도한다.\n"
    "- 사용자가 막히면 반드시 힌트를 제공한다. 질문만 던지고 방치하지 않는다.\n"
    "- 사용자가 원하면 마지막에 정리/정답 요약을 제공한다."
)
_DEBATE_ROLE = (
    "역할: 균형 잡힌 토론 진행자.\n"
    "- 한쪽만 편들지 않는다. 찬성/반대 주장, 핵심 쟁점, 반론/재반론, 중립 평가를 모두 다룬다.\n"
    "- 논증·전제·결론·반례·인과관계·규범명제·경험명제 등 논리학 용어를 사용하고 짧게 설명한다.\n"
    "- 근거 중심으로 전개하고, 열린 결론 또는 조건부 판단으로 마무리한다."
)
_ROLEPLAY_ROLE = (
    "역할: 상황극/면접/상담/실무 시뮬레이션 진행자.\n"
    "- 사용자가 정한 상황과 역할에 몰입하고 역할을 유지한다(역할 붕괴 금지).\n"
    "- 강의문처럼 길게 설명하지 말고, 실제 대화처럼 한 번에 하나씩 진행한다.\n"
    "- 필요 시 힌트를 주고, 세션 종료 시 학습 관점의 피드백을 제공한다.\n"
    "- 학습 목적을 벗어나지 않는다."
)
_RAG_ROLE = (
    "역할: 문서 근거 기반 답변자(자료보관함/업로드 문서/강의자료).\n"
    "- 제공된 문서 근거를 최우선으로 사용한다. 문서에 없는 내용을 있는 것처럼 말하지 않는다.\n"
    "- 모르는 내용은 모른다고 말하고, 문서 지식과 일반 지식을 명확히 구분한다.\n"
    "- 외부 검색/일반지식으로 보조할 때는 출처를 구분해 표기한다.\n"
    "- 근거 없는 환각을 절대 만들지 않는다."
)
_MULTI_AGENT_ROLE = (
    "역할: 다중 에이전트 종합 진행자.\n"
    "- 친절 설명형/비판 검증형/논리 구조형/창의 확장형/간결 요약형 등 성격이 뚜렷이 다른 "
    "에이전트들의 관점을 종합한다.\n"
    "- 1차 답변 → 상호 검증 → 핵심 충돌 지점 → 최종 종합 → 바로 쓸 요약 순으로 정리한다.\n"
    "- 에이전트 간 차이가 실제로 드러나야 한다(말투/판단기준/강조점)."
)
_EXAM_ROLE = (
    "역할: 시험 코치.\n"
    "- 핵심 개념을 출제 관점으로 정리하고, 암기 포인트와 함정 포인트를 구분한다.\n"
    "- 난이도별(easy: 정의/기초, medium: 개념 적용, hard: 시나리오·예외·비교/분석) 문제를 만든다.\n"
    "- hard는 단순 암기가 아니라 사고형으로 출제한다.\n"
    "- 문제와 함께 정답·해설·오답 포인트를 제공한다."
)
_CODE_REVIEW_ROLE = (
    "역할: 시니어 개발자(코드 리뷰/버그 추적/리팩터링/아키텍처 검토).\n"
    "- 추측보다 근거. 실제 코드 맥락을 기준으로만 판단한다.\n"
    "- 문제 요약 → 원인 후보 → 실제 근거 → 수정 방향 → 변경안 → 부작용 → 검증 명령어 → 롤백 순.\n"
    "- 변경 범위를 최소화하고, 컴파일/런타임/보안/성능/유지보수 위험을 지적한다.\n"
    "- 대규모 리팩터링·무관한 변경·비밀값 출력 금지."
)
_RESEARCH_ROLE = (
    "역할: 연구조교(딥서치/자료조사/보고서 보완/최신 동향).\n"
    "- 출처 기반으로 주장과 근거를 분리하고 최신성을 확인한다.\n"
    "- 조사 질문 재정의 → 핵심 결론 → 근거 요약 → 관점 비교 → 적용 가능성 → 한계 → "
    "보고서에 넣을 문장 → 추가 조사 필요점 순으로 정리한다.\n"
    "- 서로 다른 관점을 비교하고, 불확실한 부분은 단정하지 않는다."
)


# ──────────────────────────────────────────────────────────────────────────────
# 모드별 설정 빌더 (수치는 AI_MODE_<MODE>_* 환경변수로 덮어쓰기 가능)
# ──────────────────────────────────────────────────────────────────────────────
def _mt(mode_key: str, default: int) -> int:
    return _int(f"AI_MODE_{mode_key}_MAX_TOKENS", default)


def _tp(mode_key: str, default: float) -> float:
    return _float(f"AI_MODE_{mode_key}_TEMPERATURE", default)


def _build_configs() -> Dict[str, ModeAIConfig]:
    return {
        "basic": ModeAIConfig(
            mode="basic", display_name="기본 학습",
            provider="ollama", model=DEFAULT_MODEL,
            temperature=_tp("BASIC", 0.45), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("BASIC", 3072),
            use_openai=True, use_ollama=True, use_tavily=False,
            use_wikipedia=True, use_rag=True, use_quality_validator=False,
            require_citations=False, require_examples=True,
            require_multiple_perspectives=False, require_terminology_explanation=True,
            answer_sections=["핵심 답변", "쉬운 설명", "예시", "주의할 점", "요약"],
            system_prompt=_prompt(_BASIC_ROLE),
        ),
        "expert": ModeAIConfig(
            mode="expert", display_name="전문가",
            provider=EXPERT_PROVIDER, model=EXPERT_MODEL,
            temperature=_tp("EXPERT", 0.30), top_p=_float("AI_EXPERT_TOP_P", 0.85),
            max_tokens=_mt("EXPERT", 8192),
            use_openai=True, use_ollama=True, use_tavily=True,
            use_wikipedia=True, use_rag=True, use_quality_validator=True,
            require_citations=True, require_examples=True,
            require_multiple_perspectives=True, require_terminology_explanation=True,
            answer_sections=[
                "한 줄 결론", "학문적 정의", "핵심 원리", "전문용어 풀이",
                "이론적 관점", "실무적/응용 관점", "비판적 관점", "예시",
                "흔한 오해", "한계", "최종 요약",
            ],
            system_prompt=_prompt(_EXPERT_ROLE),
        ),
        "socratic": ModeAIConfig(
            mode="socratic", display_name="소크라테스",
            provider="ollama", model=DEFAULT_MODEL,
            temperature=_tp("SOCRATIC", 0.50), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("SOCRATIC", 4096),
            use_openai=True, use_ollama=True, use_tavily=False,
            use_wikipedia=True, use_rag=True, use_quality_validator=False,
            require_citations=False, require_examples=False,
            require_multiple_perspectives=False, require_terminology_explanation=True,
            answer_sections=["현재 이해 확인", "핵심 질문", "힌트", "다음 사고 방향", "정리(요청 시)"],
            system_prompt=_prompt(_SOCRATIC_ROLE),
        ),
        "debate": ModeAIConfig(
            mode="debate", display_name="토론",
            provider=EXPERT_PROVIDER, model=EXPERT_MODEL,
            temperature=_tp("DEBATE", 0.55), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("DEBATE", 8192),
            use_openai=True, use_ollama=True, use_tavily=True,
            use_wikipedia=True, use_rag=True, use_quality_validator=True,
            require_citations=True, require_examples=True,
            require_multiple_perspectives=True, require_terminology_explanation=True,
            answer_sections=[
                "논제 정리", "찬성 측 주장", "반대 측 주장", "핵심 쟁점",
                "반론", "재반론", "중립적 평가", "최종 판단/열린 결론",
            ],
            system_prompt=_prompt(_DEBATE_ROLE),
        ),
        "roleplay": ModeAIConfig(
            mode="roleplay", display_name="상황극",
            provider="ollama", model=DEFAULT_MODEL,
            temperature=_tp("ROLEPLAY", 0.65), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("ROLEPLAY", 4096),
            use_openai=True, use_ollama=True, use_tavily=True,
            use_wikipedia=False, use_rag=False, use_quality_validator=False,
            require_citations=False, require_examples=False,
            require_multiple_perspectives=False, require_terminology_explanation=False,
            answer_sections=["상황 설정", "AI 역할 발화", "사용자 차례", "힌트(필요 시)", "피드백(종료 시)"],
            system_prompt=_prompt(_ROLEPLAY_ROLE),
        ),
        "rag": ModeAIConfig(
            mode="rag", display_name="자료 기반",
            provider="openai", model=EXPERT_MODEL,
            temperature=_tp("RAG", 0.25), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("RAG", 6144),
            primary_tool="rag",
            use_openai=True, use_ollama=True, use_tavily=True,
            use_wikipedia=True, use_rag=True, use_quality_validator=True,
            require_citations=True, require_examples=False,
            require_multiple_perspectives=False, require_terminology_explanation=True,
            answer_sections=[
                "문서 기반 결론", "근거 요약", "관련 개념 설명",
                "문서에 없는 부분", "추가로 확인할 점", "요약",
            ],
            system_prompt=_prompt(_RAG_ROLE),
        ),
        "multi_agent": ModeAIConfig(
            mode="multi_agent", display_name="멀티 에이전트",
            provider=EXPERT_PROVIDER, model=EXPERT_MODEL,
            temperature=_tp("MULTI_AGENT", 0.55), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("MULTI_AGENT", 8192),
            use_openai=True, use_ollama=True, use_tavily=True,
            use_wikipedia=True, use_rag=True, use_quality_validator=True,
            require_citations=False, require_examples=True,
            require_multiple_perspectives=True, require_terminology_explanation=True,
            answer_sections=[
                "질문 해석", "에이전트별 1차 답변", "에이전트 간 검증",
                "핵심 충돌 지점", "최종 종합 답변", "바로 쓸 요약",
            ],
            system_prompt=_prompt(_MULTI_AGENT_ROLE),
        ),
        "exam": ModeAIConfig(
            mode="exam", display_name="시험 대비",
            provider="ollama", model=DEFAULT_MODEL,
            temperature=_tp("EXAM", 0.40), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("EXAM", 6144),
            use_openai=True, use_ollama=True, use_tavily=False,
            use_wikipedia=True, use_rag=True, use_quality_validator=False,
            require_citations=False, require_examples=True,
            require_multiple_perspectives=False, require_terminology_explanation=True,
            answer_sections=[
                "시험 핵심", "반드시 외울 것", "자주 틀리는 부분",
                "예상문제", "정답", "해설", "오답 포인트",
            ],
            system_prompt=_prompt(_EXAM_ROLE),
        ),
        "code_review": ModeAIConfig(
            mode="code_review", display_name="코드 리뷰",
            provider="openai", model=EXPERT_MODEL,
            temperature=_tp("CODE_REVIEW", 0.25), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("CODE_REVIEW", 8192),
            use_openai=True, use_ollama=True, use_tavily=True,
            use_wikipedia=False, use_rag=True, use_quality_validator=True,
            require_citations=False, require_examples=True,
            require_multiple_perspectives=False, require_terminology_explanation=False,
            answer_sections=[
                "문제 요약", "원인 후보", "실제 근거", "수정 방향",
                "코드 변경안", "부작용", "검증 명령어", "롤백 방법",
            ],
            system_prompt=_prompt(_CODE_REVIEW_ROLE),
        ),
        "research": ModeAIConfig(
            mode="research", display_name="리서치",
            provider="openai", model=EXPERT_MODEL,
            temperature=_tp("RESEARCH", 0.35), top_p=DEFAULT_TOP_P,
            max_tokens=_mt("RESEARCH", 8192),
            primary_tool="tavily",
            use_openai=True, use_ollama=True, use_tavily=True,
            use_wikipedia=True, use_rag=True, use_quality_validator=True,
            require_citations=True, require_examples=False,
            require_multiple_perspectives=True, require_terminology_explanation=True,
            answer_sections=[
                "조사 질문 재정의", "핵심 결론", "근거 요약", "관점 비교",
                "적용 가능성", "한계", "보고서에 넣을 문장", "추가 조사 필요점",
            ],
            system_prompt=_prompt(_RESEARCH_ROLE),
        ),
    }


# 모듈 로드 시 1회 구성. (env는 프로세스 시작 시 고정되므로 캐시해도 안전)
MODE_AI_CONFIGS: Dict[str, ModeAIConfig] = _build_configs()


def get_mode_config(mode: Optional[str]) -> ModeAIConfig:
    """표준화된 mode에 해당하는 ModeAIConfig를 반환한다. 알 수 없으면 basic."""
    norm = normalize_mode(mode)
    cfg = MODE_AI_CONFIGS.get(norm)
    if cfg is None:
        logger.warning("[mode_ai_config] config 없음 mode=%r → basic", mode)
        return MODE_AI_CONFIGS["basic"]
    return cfg


def reload_configs() -> None:
    """env 변경 후(예: 핫리로드) 설정을 다시 읽는다. 평소엔 호출할 필요 없다."""
    global MODE_AI_CONFIGS, DEFAULT_PROVIDER, DEFAULT_MODEL, DEFAULT_TEMPERATURE
    global DEFAULT_TOP_P, DEFAULT_MAX_TOKENS, EXPERT_PROVIDER, EXPERT_MODEL
    DEFAULT_PROVIDER = _str("AI_DEFAULT_PROVIDER", "ollama")
    DEFAULT_MODEL = _str("AI_DEFAULT_MODEL", "qwen3:14b")
    DEFAULT_TEMPERATURE = _float("AI_DEFAULT_TEMPERATURE", 0.45)
    DEFAULT_TOP_P = _float("AI_DEFAULT_TOP_P", 0.85)
    DEFAULT_MAX_TOKENS = _int("AI_DEFAULT_MAX_TOKENS", 4096)
    EXPERT_PROVIDER = _str("AI_EXPERT_PROVIDER", "openai")
    EXPERT_MODEL = _str("AI_EXPERT_MODEL", "gpt-4o-mini")
    MODE_AI_CONFIGS = _build_configs()


# ──────────────────────────────────────────────────────────────────────────────
# Mode-aware Prompt API (Prompt Builder)
# 모드별 프롬프트를 "범용 프롬프트 하나"가 아니라 모드 계약 기준으로 조립한다.
# expert_answer_orchestrator(합성/보강)와 agent_chat_manager(폴백 경로)가 호출한다.
# 라이브 멀티챗의 프롬프트 SSOT인 prompt_builder.build_agent_system_prompt는 건드리지 않는다.
# ──────────────────────────────────────────────────────────────────────────────
def build_answer_contract(mode_config: ModeAIConfig, intent: Optional[dict] = None,
                          sections: Optional[List[str]] = None) -> str:
    """모드의 답변 구조(answer_sections) + require_* 계약을 프롬프트 블록으로 만든다.
    sections가 주어지면(게이트가 depth/max_sections로 조정한 목록) 그 목록을 우선 사용한다."""
    sections = list(sections) if sections else list(getattr(mode_config, "answer_sections", None) or [])
    lines: List[str] = []
    if sections:
        lines.append("[답변 구조 — 아래 섹션 제목을 그대로 사용해 빠짐없이 채운다]")
        for i, s in enumerate(sections, 1):
            lines.append(f"{i}) {s}")
    reqs: List[str] = []
    if getattr(mode_config, "require_terminology_explanation", False):
        reqs.append("핵심 전문용어는 처음 등장 시 '용어(영문): 한 줄 정의'로 즉시 풀어라.")
    if getattr(mode_config, "require_examples", False):
        reqs.append("구체적 예시(코드/JSON/시나리오 등)를 최소 1개 포함하라.")
    if getattr(mode_config, "require_multiple_perspectives", False):
        reqs.append("서로 다른 관점(이론/실무/설계/비판 등)을 구분해 비교하라.")
    if getattr(mode_config, "require_citations", False):
        reqs.append("사용한 근거(문서/검색/모델 지식)를 구분해 밝혀라. 모르는 것은 모른다고 하라.")
    if reqs:
        if lines:
            lines.append("")
        lines.append("[답변 계약]")
        lines.extend(f"- {r}" for r in reqs)
    return "\n".join(lines).strip()


def build_quality_rules(mode_config: ModeAIConfig) -> str:
    """검증기가 보는 품질 기준을 모델에게 사전 고지하는 블록(검증 사용 모드 한정)."""
    if not getattr(mode_config, "use_quality_validator", False):
        return ""
    rules = [
        "[품질 규칙 — 제출 전 스스로 점검]",
        "- 단순 요약이 아니라 원리·구조·예시·한계·흔한 오해를 함께 다뤘는가.",
    ]
    if getattr(mode_config, "require_terminology_explanation", False):
        rules.append("- 전문용어를 충분히 쓰되 각 용어의 뜻을 풀었는가.")
    if getattr(mode_config, "require_multiple_perspectives", False):
        rules.append("- 여러 관점을 실제로 비교했는가(한쪽으로 치우치지 않음).")
    if getattr(mode_config, "require_citations", False):
        rules.append("- 문서 근거와 일반 지식을 구분했는가.")
    return "\n".join(rules).strip()


def build_tool_context(rag_results=None, tavily_results=None, wiki_results=None) -> str:
    """수집한 근거(내부 RAG / Tavily / Wikipedia)를 프롬프트용 블록으로 합친다.
    각 인자는 문자열 또는 {title,url,content/snippet} dict 리스트를 허용한다."""
    blocks: List[str] = []

    def _fmt(tag: str, items) -> None:
        if not items:
            return
        if isinstance(items, str):
            if items.strip():
                blocks.append(f"[{tag}]\n{items.strip()}")
            return
        for it in items:
            if isinstance(it, str):
                if it.strip():
                    blocks.append(f"[{tag}] {it.strip()}")
            elif isinstance(it, dict):
                title = (it.get("title") or "").strip()
                url = (it.get("url") or "").strip()
                content = (it.get("content") or it.get("snippet") or "").strip()
                head = f"[{tag}] {title}".strip()
                if url:
                    head += f" ({url})"
                if content or title:
                    blocks.append(f"{head}\n{content}".strip())

    _fmt("내부 RAG", rag_results)
    _fmt("Wikipedia", wiki_results)
    _fmt("웹(Tavily)", tavily_results)
    if not blocks:
        return ""
    return "## 수집 근거\n" + "\n\n".join(blocks)


def build_system_prompt(mode_config: ModeAIConfig, intent: Optional[dict] = None, context: str = "") -> str:
    """모드별 시스템 프롬프트(역할 + 답변 계약 + 품질 규칙 [+ 추가 컨텍스트])를 조립한다."""
    parts = [
        (getattr(mode_config, "system_prompt", "") or COMMON_SYSTEM_HEADER).strip(),
        build_answer_contract(mode_config, intent),
        build_quality_rules(mode_config),
    ]
    if context and context.strip():
        parts.append(context.strip())
    return "\n\n".join(p for p in parts if p and p.strip())


def build_final_prompt(user_message: str, mode_config: ModeAIConfig, context: str = "") -> str:
    """사용자 메시지 + 수집 근거(context)를 합쳐 최종 user 프롬프트를 만든다."""
    body: List[str] = []
    if context and context.strip():
        body.append(context.strip())
    body.append(f"## 사용자 질문\n{(user_message or '').strip()}")
    body.append("위 지시(시스템 프롬프트의 답변 구조·계약·품질 규칙)를 반드시 따르라.")
    return "\n\n".join(body)
