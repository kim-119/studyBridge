"""
성격 정합성 검증.

LLM 없이 휴리스틱으로 답변이 해당 성격(YAML 프로필)을 실제로 반영했는지 점수화한다.
- score_personality_alignment(): 항목별 점수 dict 계산
- validate_personality_alignment(): 에이전트/stage 컨텍스트로 종합 결과 반환
- repair_personality_if_needed(): 점수 미달 시 (regenerate 콜백이 있으면) 짧게 보정

3차 stage에서 personalityValidationSummary로 노출된다.
운영 임계값/재시도는 agent_settings(env)에서 읽는다.
"""
import re
from typing import Any, Callable, Dict, List, Optional

from app.core import agent_settings as A
from app.services.personality_prompt_builder import (
    get_profile, to_profile_key, normalize_personality, get_validation_hints,
)

# 성격별 톤 마커 (휴리스틱). YAML mustUse와 함께 사용한다.
_TONE_MARKERS: Dict[str, List[str]] = {
    "friendly":     ["쉽게", "천천히", "헷갈", "걱정", "예를 들", "어렵지 않", "간단합니다"],
    "critical":     ["방향은", "틀린다", "섞으면", "기준을", "주의", "개선", "구분"],
    "logical":      ["정의", "기준", "따라서", "반대로", "예시", "반례"],
    "creative":     ["비유", "처럼", "마치", "그림으로", "기억하면", "상상"],
    "concise":      ["결론", "핵심"],
    "professional": ["정확", "전제", "조건", "실무", "원리"],
    "sardonic":     ["자주 틀리", "깨진다", "기준은", "대충", "솔직히"],
    "custom":       [],
}

_METAPHOR_MARKERS = ["비유", "처럼", "마치", "그림으로", "상상", "은유", "라고 보면", "에 비유"]
_CRITIQUE_MARKERS = ["부족", "틀", "오류", "주의", "개선", "섞", "구분", "아니다", "하지 마"]
# creative(독특함) 전용 마커
_MEMORY_SENTENCE_MARKERS = ["기억하면", "기억법", "한 문장으로", "박아두면", "외워두면", "정리하면 이거다"]
_BULLET_PREFIXES = ("- ", "* ", "• ", "·", "1.", "2.", "3.", "4.", "5.")

# 사실성(개념 안전) 간단 점검: SQL DML/DDL 혼동
_SQL_DDL = ("CREATE", "ALTER", "DROP", "TRUNCATE")


def _word_set(text: str) -> set:
    return set(w for w in re.split(r"[^0-9A-Za-z가-힣]+", (text or "").lower()) if len(w) >= 2)


def _jaccard(a: str, b: str) -> float:
    sa, sb = _word_set(a), _word_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _keyword_hits(text: str, phrases: List[str]) -> int:
    t = text or ""
    return sum(1 for p in phrases if p and p in t)


def _factual_safety(text: str) -> tuple:
    """개념 오류 간단 점검. 현재는 SQL DML/DDL 혼동만 검사."""
    t = text or ""
    issues: List[str] = []
    if "DML" in t.upper():
        # DML 설명 문맥에서 CREATE/ALTER/DROP을 DML 예시로 끌어들이면 감점
        for ddl in _SQL_DDL:
            if ddl in t.upper():
                # 'DDL'을 함께 언급하며 구분하면 안전, 아니면 의심
                if "DDL" not in t.upper():
                    issues.append(f"{ddl}는 DDL인데 DML 설명에 섞였을 가능성")
                break
    score = 1.0 if not issues else 0.6
    return score, issues


def _first_sentence(text: str) -> str:
    for s in re.split(r"[\n。.!?]+", (text or "").strip()):
        if s.strip():
            return s.strip()
    return ""


def _is_bullet_only(text: str) -> bool:
    """본문이 거의 bullet/번호 목록으로만 구성됐는지(문장 리듬 없음)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    bullets = sum(1 for ln in lines if ln.startswith(_BULLET_PREFIXES))
    return bullets >= max(3, int(len(lines) * 0.7))


def _creative_adjustments(text: str) -> tuple:
    """
    creative(독특함/4차원) 전용 보정: 비유 필수·기억문장·bullet-only·평범정의 시작 점검.
    반환: (delta, issues) — delta는 종합 score에 가산/감산.
    """
    t = text or ""
    delta = 0.0
    issues: List[str] = []

    has_metaphor = _keyword_hits(t, _METAPHOR_MARKERS) > 0
    if not has_metaphor:
        delta -= 0.18
        issues.append("비유가 없다(독특함은 기억 가능한 비유가 최소 1개 필요)")

    # 첫 문장이 '~는/은 ~이다/입니다'식 평범한 정의로만 시작하고 비유가 없으면 감점
    fs = _first_sentence(t)
    plain_def = bool(re.search(r"(은|는|란|이란)\s.*(이다|입니다|이라고 한다|을 말한다)\s*$", fs)) \
        and _keyword_hits(fs, _METAPHOR_MARKERS) == 0
    if plain_def and not has_metaphor:
        delta -= 0.06
        issues.append("첫 문장이 평범한 정의문이다(이미지/비유로 시작 권장)")

    # 마지막에 한 문장 기억법이 있으면 가점
    if _keyword_hits(t, _MEMORY_SENTENCE_MARKERS) > 0:
        delta += 0.06
    else:
        issues.append("마지막 '한 문장 기억법'이 없다")

    # bullet만 나열하면 감점
    if _is_bullet_only(t):
        delta -= 0.1
        issues.append("bullet만 나열했다(문장과 비유를 섞어라)")

    return delta, issues


def score_personality_alignment(
    answer: str, profile: dict, canonical_key: str,
    peer_answers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """항목별 점수(0~1)와 종합 score를 계산한다."""
    text = answer or ""
    must = profile.get("mustUse") or []
    markers = _TONE_MARKERS.get(canonical_key, [])
    params = A.get_personality_params(canonical_key)

    # 1. persona_keyword: mustUse 충족 비율 (mustUse 없으면 0.7 기본)
    if must:
        persona_keyword = min(1.0, _keyword_hits(text, must) / max(1, min(2, len(must))))
        persona_keyword = max(persona_keyword, 0.4 if _keyword_hits(text, must) == 0 else persona_keyword)
    else:
        persona_keyword = 0.7

    # 2. tone: 성격 마커 등장 여부
    tone = 0.5 + min(0.5, 0.2 * _keyword_hits(text, markers)) if markers else 0.65

    # 3. structure: answerShape 길이대/구획 휴리스틱
    seg = len([s for s in re.split(r"[\n。.!?]+", text) if s.strip()])
    if canonical_key == "concise":
        structure = 1.0 if len(text) <= 400 else max(0.4, 1.0 - (len(text) - 400) / 1200)
    else:
        structure = min(1.0, 0.5 + 0.1 * seg)

    # 4. forbidden_penalty: 인신공격/욕설 (안전) — policy_loader 기반
    forbidden_penalty = 0.0
    try:
        from app.core.policy_loader import get_blocked_patterns
        if _keyword_hits(text, get_blocked_patterns()) > 0:
            forbidden_penalty = 0.4
    except Exception:
        pass

    # 5. contrast: peer와의 비유사도
    if peer_answers:
        contrast = 1.0 - max((_jaccard(text, p) for p in peer_answers if p), default=0.0)
    else:
        contrast = 1.0

    # 6. knowledge_level: 너무 짧지 않으면 통과 (간이)
    knowledge_level = 0.9 if len(text) >= 40 else 0.6

    # 7. factual_safety
    factual_safety, fact_issues = _factual_safety(text)

    # 8~10. verbosity / metaphor / critique 매칭 (프로필 기대치 대비)
    length_norm = min(1.0, len(text) / 600.0)
    verbosity_match = 1.0 - abs(length_norm - params["verbosity"])
    metaphor_present = min(1.0, 0.5 * _keyword_hits(text, _METAPHOR_MARKERS))
    metaphor_match = 1.0 - abs(metaphor_present - params["metaphor_density"])
    critique_present = min(1.0, 0.4 * _keyword_hits(text, _CRITIQUE_MARKERS))
    critique_match = 1.0 - abs(critique_present - params["critique_density"])

    scores = {
        "personaKeyword": round(persona_keyword, 3),
        "tone": round(min(1.0, tone), 3),
        "structure": round(min(1.0, structure), 3),
        "contrast": round(max(0.0, contrast), 3),
        "knowledgeLevel": round(knowledge_level, 3),
        "factualSafety": round(factual_safety, 3),
        "verbosityMatch": round(max(0.0, verbosity_match), 3),
        "metaphorMatch": round(max(0.0, metaphor_match), 3),
        "critiqueMatch": round(max(0.0, critique_match), 3),
    }
    # 종합: 핵심 항목 가중 평균 - forbidden_penalty
    core = (
        scores["personaKeyword"] * 0.22 + scores["tone"] * 0.18 + scores["structure"] * 0.12 +
        scores["contrast"] * 0.12 + scores["knowledgeLevel"] * 0.1 + scores["factualSafety"] * 0.16 +
        scores["verbosityMatch"] * 0.04 + scores["metaphorMatch"] * 0.03 + scores["critiqueMatch"] * 0.03
    )
    # creative(독특함) 전용 보정: 비유 필수/기억문장/bullet-only/평범정의 시작
    extra_issues: List[str] = []
    if canonical_key == "creative":
        delta, extra_issues = _creative_adjustments(text)
        core = core + delta
        scores["creativeAdjust"] = round(delta, 3)

    overall = round(max(0.0, min(1.0, core - forbidden_penalty)), 3)
    return {
        "score": overall, "scores": scores,
        "issues": fact_issues + extra_issues, "forbiddenPenalty": forbidden_penalty,
    }


def validate_personality_alignment(
    answer: str, agent, stage: int, peer_answers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """에이전트 답변의 성격 정합성을 검증해 표준 결과 dict를 반환한다."""
    personality = getattr(agent, "personality", None) or getattr(agent, "tone", None) or getattr(agent, "style", None)
    canonical = to_profile_key(personality)
    profile = get_profile(personality)
    result = score_personality_alignment(answer, profile, canonical, peer_answers)
    min_score = A.personality_validation_min_score()
    passed = result["score"] >= min_score

    issues = list(result["issues"])
    repair_instruction = ""
    if not passed:
        weakest = min(result["scores"].items(), key=lambda kv: kv[1])[0]
        hints = {
            "personaKeyword": f"{profile.get('displayName','이 성격')}다운 표현을 더 살려라.",
            "tone": "성격 특유의 말투가 약하다. 톤을 더 분명히 해라.",
            "structure": "권장 답변 구성 순서를 따르라: " + " → ".join(profile.get("answerShape", []) or ["정의","예시","정리"]),
            "contrast": "다른 에이전트와 문체가 비슷하다. 더 차별화하라.",
            "metaphorMatch": "비유 사용량을 성격에 맞게 조정하라.",
            "critiqueMatch": "지적/비평 강도를 성격에 맞게 조정하라.",
            "verbosityMatch": "답변 길이를 성격에 맞게 조정하라.",
            "factualSafety": "개념 정확성을 점검하라(예: DML/DDL 구분).",
            "knowledgeLevel": "선택한 지식수준에 맞게 밀도를 높여라.",
        }
        repair_instruction = hints.get(weakest, "성격이 더 분명히 드러나게 보완하라.")
        issues.append(f"성격 반영 부족: {weakest}={result['scores'][weakest]}")

    return {
        "agentId": getattr(agent, "agentId", None),
        "agentName": getattr(agent, "name", None),
        "personalityType": canonical,
        "stage": stage,
        "score": result["score"],
        "passed": passed,
        "scores": result["scores"],
        "issues": issues,
        "validationHints": get_validation_hints(personality),
        "repairInstruction": repair_instruction,
        "note": "성격이 충분히 반영됨" if passed else repair_instruction,
    }


def repair_personality_if_needed(
    answer: str, validation_result: Dict[str, Any], agent, stage: int,
    regenerate: Optional[Callable[[str], str]] = None,
) -> tuple:
    """
    점수 미달 시 보정한다.
    regenerate(repair_instruction) 콜백이 주어지면 짧게 재생성, 없으면 원문 유지.
    반환: (answer, repaired: bool, retries_used: int)
    """
    if validation_result.get("passed", True) or not A.enable_personality_validation():
        return answer, False, 0
    if regenerate is None:
        return answer, False, 0
    max_retry = A.personality_validation_max_retry()
    repaired = answer
    used = 0
    for _ in range(max(0, max_retry)):
        used += 1
        try:
            new_text = regenerate(validation_result.get("repairInstruction", ""))
        except Exception:
            break
        if new_text and new_text.strip() and not new_text.startswith("["):
            repaired = new_text.strip()
            # 재검증
            re_val = validate_personality_alignment(repaired, agent, stage)
            if re_val.get("passed"):
                return repaired, True, used
    return repaired, (repaired != answer), used
