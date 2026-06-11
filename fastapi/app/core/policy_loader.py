"""
YAML 정책 파일 로더.
agent_modes.yaml / feedback_policy.yaml / validation_policy.yaml 및
prompt_templates/*.md 를 시작 시 한 번 로드하고 캐싱한다.
파일 없으면 내장 기본값 사용. 파싱 실패 시 서버를 죽이지 않고 기본값 fallback.
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CORE_DIR = Path(__file__).parent
_TEMPLATES_DIR = _CORE_DIR / "prompt_templates"

# ── 내장 기본값 ──────────────────────────────────────────────────────────────
_DEFAULT_AGENT_MODES: Dict[str, Any] = {
    "modes": {
        "tikitaka": {
            "enabled": True,
            "rounds": ["initial_answer", "critique", "rebuttal_or_refinement"],
            "default_delay_ms": 700,
            "max_rewrite_attempts": 1,
        },
        "debate": {
            "enabled": True,
            "chain": [
                {"role": "supporter",  "speech_type": "support_argument",  "prompt_template": "debate_supporter.md"},
                {"role": "critic",     "speech_type": "counter_argument",  "prompt_template": "debate_critic.md"},
                {"role": "moderator",  "speech_type": "moderation_summary","prompt_template": "debate_moderator.md"},
            ],
            "default_delay_ms": 700,
            "max_rewrite_attempts": 1,
        },
        "socratic": {
            "enabled": True,
            "chain": [
                {"role": "socratic_tutor", "speech_type": "follow_up_question", "prompt_template": "socratic_tutor.md"},
            ],
            "max_follow_up_questions": 1,
            "direct_answer_policy": "block",
            "max_rewrite_attempts": 1,
        },
    }
}

_DEFAULT_FEEDBACK_POLICY: Dict[str, Any] = {
    "blocked_patterns": [
        "멍청", "쓰레기", "말도 안", "한심", "바보", "뇌가 없",
        "형편없", "최악", "개소리", "헛소리", "수준 이하",
        "아무것도 모르", "글렀", "조잡", "엉망",
    ],
    "personal_attack_patterns": [
        r"\d+번\s*(에이전트|답변).*?(이상|못|안)",
        r"이\s*(에이전트|답).*?(가치\s*없|무능)",
        r"저\s*(에이전트|답).*?(가치\s*없|무능)",
    ],
    "mockery_terms": ["ㅋㅋ", "ㅎㅎ", "웃기", "말도 안 되는", "진짜로?", "그게 전부?"],
    "improvement_keywords": [
        "보완", "개선", "추가", "대신", "더 나은", "더욱",
        "이렇게", "하면 좋", "하면 더", "해야", "필요", "제안", "방향",
    ],
    "thresholds": {
        "max_toxicity_score": 0.35,
        "max_personal_attack_score": 0.5,
        "max_mockery_score": 0.4,
        "toxicity_weight_per_match": 0.35,
        "attack_weight_per_match": 0.5,
        "mockery_weight_per_match": 0.4,
        "constructiveness_base": 0.3,
        "constructiveness_weight_per_match": 0.15,
        "max_rewrite_attempts": 1,
    },
    "safe_fallback": "해당 피드백은 표현이 부적절하여 건설적인 개선 의견으로 대체되었습니다.",
}

_DEFAULT_VALIDATION_POLICY: Dict[str, Any] = {
    "debate": {
        "require_support_argument": True,
        "require_counter_argument": True,
        "require_moderator_question": True,
        "support_keywords": ["장점", "긍정", "유익", "효과", "도움", "가치", "이점", "근거", "옹호", "지지"],
        "counter_keywords": ["부족", "누락", "한계", "위험", "반례", "맹점", "문제", "단점", "오해", "반론"],
        "moderator_question_markers": ["?", "어떻게 생각", "어느 관점", "당신은", "여러분은", "어떻습니까"],
    },
    "socratic": {
        "max_questions": 1,
        "block_direct_answer": True,
        "max_answer_length_chars": 350,
        "direct_answer_markers": [
            "정답은", "결론은", "결론부터", "즉, 답은", "완성 답안은", "정확한 답은",
            "답은 다음과", "정답을 말하자면", "정리하자면", "요약하자면", "쉽게 설명하면",
        ],
        "lecture_markers": [
            "로 설명됩니다", "로 설명할 수 있습니다", "라고 할 수 있습니다",
            "다음과 같습니다", "첫째,", "둘째,",
        ],
    },
    "tikitaka": {
        "critique_keywords": [
            "부족", "누락", "빠뜨", "한계", "오해", "위험", "반례",
            "근거가 약", "설명이 불충분", "보완 필요", "관점이 좁", "전제가 불명확",
            "놓쳤", "불명확",
        ],
        "rebuttal_keywords": [
            "맞습니다", "수정", "보완", "실제로", "정확히",
            "덧붙이", "다시 말", "재고", "추가로", "보충",
        ],
        "blend_markers": ["첫째", "둘째", "셋째", "각각", "모두", "세 답변", "세 가지"],
    },
    "timeouts": {"per_agent_seconds": 45, "total_seconds": 90},
    "display": {"default_delay_ms": 700},
}

# ── 캐시 ──────────────────────────────────────────────────────────────────────
_agent_modes: Optional[Dict[str, Any]] = None
_feedback_policy: Optional[Dict[str, Any]] = None
_validation_policy: Optional[Dict[str, Any]] = None
_prompt_cache: Dict[str, str] = {}


def _load_yaml(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        logger.debug("설정 파일 없음 (기본값 사용): %s", path.name)
        return default
    try:
        import yaml  # pyyaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning("YAML 파싱 결과가 dict가 아님 (기본값 사용): %s", path.name)
            return default
        return data
    except ImportError:
        logger.warning("pyyaml 없음 (기본값 사용). pip install pyyaml 권장.")
        return default
    except Exception as e:
        logger.warning("YAML 로드 실패 (기본값 사용): %s — %s", path.name, e)
        return default


def get_agent_modes() -> Dict[str, Any]:
    global _agent_modes
    if _agent_modes is None:
        _agent_modes = _load_yaml(_CORE_DIR / "agent_modes.yaml", _DEFAULT_AGENT_MODES)
    return _agent_modes


def get_feedback_policy() -> Dict[str, Any]:
    global _feedback_policy
    if _feedback_policy is None:
        _feedback_policy = _load_yaml(_CORE_DIR / "feedback_policy.yaml", _DEFAULT_FEEDBACK_POLICY)
    return _feedback_policy


def get_validation_policy() -> Dict[str, Any]:
    global _validation_policy
    if _validation_policy is None:
        _validation_policy = _load_yaml(_CORE_DIR / "validation_policy.yaml", _DEFAULT_VALIDATION_POLICY)
    return _validation_policy


def get_prompt_template(template_name: str) -> str:
    """프롬프트 템플릿 파일을 읽어 반환한다. 없으면 빈 문자열."""
    if template_name in _prompt_cache:
        return _prompt_cache[template_name]
    path = _TEMPLATES_DIR / template_name
    if not path.exists():
        logger.warning("프롬프트 템플릿 없음 (빈 문자열 반환): %s", template_name)
        return ""
    try:
        text = path.read_text(encoding="utf-8").strip()
        _prompt_cache[template_name] = text
        return text
    except Exception as e:
        logger.warning("프롬프트 템플릿 로드 실패: %s — %s", template_name, e)
        return ""


def get_mode_config(mode: str) -> Dict[str, Any]:
    return get_agent_modes().get("modes", {}).get(mode, {})


def get_debate_chain() -> List[Dict[str, Any]]:
    cfg = get_mode_config("debate")
    return cfg.get("chain", _DEFAULT_AGENT_MODES["modes"]["debate"]["chain"])


def get_socratic_chain() -> List[Dict[str, Any]]:
    cfg = get_mode_config("socratic")
    return cfg.get("chain", _DEFAULT_AGENT_MODES["modes"]["socratic"]["chain"])


def get_feedback_thresholds() -> Dict[str, float]:
    return get_feedback_policy().get("thresholds", _DEFAULT_FEEDBACK_POLICY["thresholds"])


def get_blocked_patterns() -> List[str]:
    return get_feedback_policy().get("blocked_patterns", _DEFAULT_FEEDBACK_POLICY["blocked_patterns"])


def get_improvement_keywords() -> List[str]:
    return get_feedback_policy().get("improvement_keywords", _DEFAULT_FEEDBACK_POLICY["improvement_keywords"])


def get_mockery_terms() -> List[str]:
    return get_feedback_policy().get("mockery_terms", _DEFAULT_FEEDBACK_POLICY["mockery_terms"])


def get_personal_attack_patterns() -> List[str]:
    return get_feedback_policy().get("personal_attack_patterns", _DEFAULT_FEEDBACK_POLICY["personal_attack_patterns"])


def get_safe_fallback() -> str:
    return get_feedback_policy().get("safe_fallback", _DEFAULT_FEEDBACK_POLICY["safe_fallback"])


def get_debate_validation() -> Dict[str, Any]:
    return get_validation_policy().get("debate", _DEFAULT_VALIDATION_POLICY["debate"])


def get_socratic_validation() -> Dict[str, Any]:
    return get_validation_policy().get("socratic", _DEFAULT_VALIDATION_POLICY["socratic"])


def get_tikitaka_validation() -> Dict[str, Any]:
    return get_validation_policy().get("tikitaka", _DEFAULT_VALIDATION_POLICY["tikitaka"])


def get_display_delay_ms() -> int:
    return get_validation_policy().get("display", {}).get(
        "default_delay_ms", _DEFAULT_VALIDATION_POLICY["display"]["default_delay_ms"]
    )


def get_timeout_per_agent() -> int:
    return get_validation_policy().get("timeouts", {}).get(
        "per_agent_seconds", _DEFAULT_VALIDATION_POLICY["timeouts"]["per_agent_seconds"]
    )


_generation_policy: Optional[Dict[str, Any]] = None
_source_policy: Optional[Dict[str, Any]] = None
_domain_depth_profiles: Optional[Dict[str, Any]] = None
_prompt_engineering_policy: Optional[Dict[str, Any]] = None
_academic_domain_policy: Optional[Dict[str, Any]] = None


def get_generation_policy() -> Dict[str, Any]:
    global _generation_policy
    if _generation_policy is None:
        _generation_policy = _load_yaml(_CORE_DIR / "generation_policy.yaml", {})
    return _generation_policy


def get_source_policy() -> Dict[str, Any]:
    global _source_policy
    if _source_policy is None:
        _source_policy = _load_yaml(_CORE_DIR / "source_policy.yaml", {})
    return _source_policy


def get_domain_depth_profiles() -> Dict[str, Any]:
    global _domain_depth_profiles
    if _domain_depth_profiles is None:
        _domain_depth_profiles = _load_yaml(_CORE_DIR / "domain_depth_profiles.yaml", {})
    return _domain_depth_profiles


def get_prompt_engineering_policy() -> Dict[str, Any]:
    global _prompt_engineering_policy
    if _prompt_engineering_policy is None:
        _prompt_engineering_policy = _load_yaml(_CORE_DIR / "prompt_engineering_policy.yaml", {})
    return _prompt_engineering_policy


def get_academic_domain_policy() -> Dict[str, Any]:
    global _academic_domain_policy
    if _academic_domain_policy is None:
        _academic_domain_policy = _load_yaml(_CORE_DIR / "academic_domain_policy.yaml", {})
    return _academic_domain_policy


def reload_all() -> None:
    """설정 파일을 강제로 다시 로드한다."""
    global _agent_modes, _feedback_policy, _validation_policy
    global _generation_policy, _source_policy, _domain_depth_profiles
    global _prompt_engineering_policy, _academic_domain_policy
    _agent_modes = None
    _feedback_policy = None
    _validation_policy = None
    _generation_policy = None
    _source_policy = None
    _domain_depth_profiles = None
    _prompt_engineering_policy = None
    _academic_domain_policy = None
    _prompt_cache.clear()
    get_agent_modes()
    get_feedback_policy()
    get_validation_policy()
    get_generation_policy()
    get_source_policy()
    get_domain_depth_profiles()
    logger.info("정책 설정 재로드 완료")
