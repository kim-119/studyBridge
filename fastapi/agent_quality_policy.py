from __future__ import annotations

import json
import logging
import re
from typing import Any


logger = logging.getLogger("studybridge.agent_quality")

ALLOWED_KNOWLEDGE_LEVELS = ["입문 수준", "학사 수준", "석사 수준", "박사 수준", "전문가 수준"]
ALLOWED_PERSONALITIES = ["전문적", "친근함", "솔직함", "독특함", "효율적", "냉소적"]

DEFAULT_KNOWLEDGE_LEVEL = "학사 수준"
DEFAULT_PERSONALITY = "전문적"
DEFAULT_TONE = "전문적"

DISCIPLINE_KEYWORDS = {
    "computer_science": [
        "java", "python", "알고리즘", "oop", "객체지향", "네트워크", "데이터베이스", "컴퓨터공학",
        "프로그래밍", "운영체제", "컴파일러", "api", "spring", "react", "fastapi", "분산", "자료구조",
    ],
    "linguistics": ["음운론", "통사론", "의미론", "형태소", "언어학", "화용론", "음성학", "담화", "구문"],
    "mathematics": ["미분", "적분", "대수", "확률", "통계", "기하", "미분방정식", "정리", "행렬", "위상"],
    "psychology": ["인지", "행동주의", "프로이트", "심리", "상담", "기억", "학습이론", "동기", "지능", "정신분석"],
    "philosophy": ["칸트", "존재론", "윤리학", "인식론", "형이상학", "공리주의", "철학", "헤겔", "데카르트"],
    "biology": ["세포", "유전자", "단백질", "생명과학", "세포호흡", "효소", "dna", "rna", "대사"],
    "medicine": ["의학", "진단", "질환", "임상", "치료", "병리", "약물", "환자", "수술"],
    "law": ["헌법", "민법", "판례", "계약", "형법", "소송", "법률", "행정법", "상법"],
    "business": ["마케팅", "회계", "전략", "조직", "stp", "재무", "브랜드", "시장", "kpi", "경영"],
    "education": ["교육학", "교수법", "학습자", "평가", "교육과정", "수업", "교수설계"],
    "engineering": ["회로", "제어", "역학", "열역학", "재료", "공정", "전기", "기계", "토목", "화학공학"],
    "social_science": ["사회학", "정치", "경제", "문화", "정책", "제도", "불평등", "국제관계"],
}

def normalize_knowledge_level(value: str | None, fallback_text: str = "") -> tuple[str, list[str]]:
    warnings: list[str] = []
    val = str(value or "").strip()
    if val in ALLOWED_KNOWLEDGE_LEVELS:
        return val, warnings
    # UI에서 전달받은 값 중 정규화 대상 매칭
    for canonical in ALLOWED_KNOWLEDGE_LEVELS:
        if canonical in val or canonical.replace(" ", "") in val.replace(" ", ""):
            return canonical, warnings
    return DEFAULT_KNOWLEDGE_LEVEL, warnings


def get_knowledge_depth_policy(level: str, discipline: str = "general") -> dict:
    canonical, _ = normalize_knowledge_level(level)
    policies = {
        "입문 수준": {
            "level": "입문 수준",
            "target_reader": "해당 분야를 처음 접하는 사람",
            "depth_goal": "쉬운 말과 비유로 핵심 개념을 부담 없이 이해시키기",
            "required_dimensions": ["쉬운 정의", "일상적 비유", "핵심 용어 2~4개", "간단한 예시"],
            "forbidden_patterns": ["고급 이론 중심 설명", "학술 논쟁", "복잡한 수식", "전문 용어 과다"],
            "answer_strategy": "먼저 쉬운 정의를 말하고, 일상 비유와 짧은 예시로 핵심만 설명한다.",
        },
        "학사 수준": {
            "level": "학사 수준",
            "target_reader": "대학 전공 수업 수준의 학습자",
            "depth_goal": "전공 기본 개념, 핵심 용어, 대표 원리와 예시를 균형 있게 설명",
            "required_dimensions": ["전공 기본 개념", "핵심 용어 정의", "대표 예시", "기초 원리", "개념 간 차이"],
            "forbidden_patterns": ["입문 수준처럼 너무 얕게 끝내기", "전문가식 실무 전략만 나열", "과도한 이론 논쟁"],
            "answer_strategy": "정의, 핵심 용어, 기본 원리, 대표 예시, 시험/과제에 쓸 수 있는 구조로 설명한다.",
        },
        "석사 수준": {
            "level": "석사 수준",
            "target_reader": "전공 지식이 있고 더 깊은 구조와 원리를 알고 싶은 학습자",
            "depth_goal": "단순 정의를 넘어 구조, 원리, 설계 의도, 방법론, 적용 조건과 한계를 설명",
            "required_dimensions": ["개념 간 관계", "구조와 원리", "방법론적 관점", "적용 조건", "한계와 오해", "분석 기준"],
            "forbidden_patterns": ["단순 정의만 설명", "학사 수준 개념 나열로 끝내기", "원리 없이 실무 팁만 나열"],
            "answer_strategy": "개념 정의 후 구조와 원리를 설명하고, 적용 조건과 한계 및 분석 기준을 덧붙인다.",
        },
        "박사 수준": {
            "level": "박사 수준",
            "target_reader": "연구자 수준의 이론적·비판적 이해가 필요한 사람",
            "depth_goal": "이론적 기반, 가정, 논쟁점, 한계, 대안 이론과 연구 질문으로 확장",
            "required_dimensions": ["이론적 전제", "방법론적 기반", "한계와 반례", "논쟁점", "다른 패러다임과 비교", "연구 질문"],
            "forbidden_patterns": ["실무 팁만 나열", "단순 개념 설명으로 끝내기", "예시만 많고 이론적 분석 없음"],
            "answer_strategy": "개념의 가정과 이론적 기반을 밝히고, 한계·반례·논쟁·비교·연구 질문을 포함한다.",
        },
        "전문가 수준": {
            "level": "전문가 수준",
            "target_reader": "현업 고급 실무자, 아키텍트, 컨설턴트, 연구개발 리더",
            "depth_goal": "실제 문제 해결, 운영 가능성, 리스크, 트레이드오프, 의사결정 기준을 제시",
            "required_dimensions": ["실무 적용 조건", "설계/운영/관리 관점", "리스크", "트레이드오프", "의사결정 기준", "안티패턴", "고급 사례"],
            "forbidden_patterns": ["교과서 정의만 반복", "적용 전략 없이 이론만 설명", "추상적 당위만 제시"],
            "answer_strategy": "개념을 실제 의사결정과 운영 관점으로 연결하고 리스크·트레이드오프·안티패턴을 제시한다.",
        },
    }
    policy = dict(policies[canonical])
    policy["discipline"] = discipline
    return policy


def infer_discipline(user_message: str, agent_config: dict | None = None) -> str:
    fields = [user_message or ""]
    if agent_config:
        for key in ("role", "goal", "customInstruction", "custom_instruction", "persona", "name"):
            fields.append(str(agent_config.get(key) or ""))
    text = " ".join(fields).lower()
    scores: dict[str, int] = {}
    for discipline, keywords in DISCIPLINE_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in text:
                score += 1
        if score:
            scores[discipline] = score
    if not scores:
        return "general"
    return max(scores.items(), key=lambda item: item[1])[0]


def get_discipline_depth_adjustment(discipline: str, level: str) -> dict:
    canonical, _ = normalize_knowledge_level(level)
    adjustments = {
        "computer_science": {
            "학사 수준": ["문법", "자료구조", "기본 원리", "간단한 코드"],
            "석사 수준": ["설계 원칙", "복잡도", "시스템 구조", "테스트 가능성"],
            "박사 수준": ["계산 모델", "타입 시스템", "형식 의미론", "분산 시스템 이론", "한계"],
            "전문가 수준": ["아키텍처", "운영", "확장성", "장애 대응", "보안", "비용"],
        },
        "linguistics": {
            "학사 수준": ["음운론", "형태론", "통사론", "의미론의 기본 개념"],
            "석사 수준": ["이론 간 차이", "분석 방법론", "코퍼스/실험 접근"],
            "박사 수준": ["생성문법", "인지언어학", "형식 의미론", "언어철학", "논쟁점"],
            "전문가 수준": ["언어 교육", "NLP 적용", "번역", "언어 정책", "실제 분석 전략"],
        },
        "mathematics": {
            "학사 수준": ["정의", "정리", "예제", "계산 절차"],
            "석사 수준": ["증명 아이디어", "구조", "일반화", "조건"],
            "박사 수준": ["공리적 기반", "추상 구조", "연구 문제", "반례"],
            "전문가 수준": ["모델링", "최적화", "수치 안정성", "실제 적용"],
        },
        "psychology": {
            "학사 수준": ["이론 정의", "대표 실험", "핵심 개념"],
            "석사 수준": ["연구 방법", "측정", "통계", "이론 비교"],
            "박사 수준": ["방법론 비판", "재현성", "이론적 논쟁", "메타분석 관점"],
            "전문가 수준": ["상담/조직/교육/임상 적용", "윤리", "개입 전략"],
        },
        "biology": {
            "학사 수준": ["구조와 기능", "기본 과정"],
            "석사 수준": ["조절 메커니즘", "실험 방법", "경로 분석"],
            "박사 수준": ["분자 수준 메커니즘", "연구 가설", "최신 논쟁"],
            "전문가 수준": ["실험 설계", "임상/산업 적용", "데이터 해석", "리스크"],
        },
        "philosophy": {
            "학사 수준": ["주요 개념", "사상가", "기본 논증"],
            "석사 수준": ["논증 구조", "전제", "반론", "학파 비교"],
            "박사 수준": ["존재론/인식론/윤리학적 전제", "해석 논쟁", "메타철학"],
            "전문가 수준": ["현대 쟁점", "적용 윤리", "정책/기술/사회 문제와 연결"],
        },
        "law": {
            "학사 수준": ["법 개념", "조문 구조", "기본 판례"],
            "석사 수준": ["법리", "판례 비교", "해석론", "적용 요건"],
            "박사 수준": ["법철학", "입법론", "비교법", "판례 비판"],
            "전문가 수준": ["실무 리스크", "소송 전략", "계약/컴플라이언스 적용"],
        },
        "business": {
            "학사 수준": ["기본 개념", "프레임워크", "사례"],
            "석사 수준": ["전략적 분석", "시장/조직/재무 구조", "한계"],
            "박사 수준": ["이론 모델", "실증 연구", "방법론", "논쟁"],
            "전문가 수준": ["의사결정", "KPI", "실행 전략", "리스크", "운영 적용"],
        },
    }
    focus = adjustments.get(discipline, {}).get(canonical)
    if not focus:
        focus = ["분야 핵심 개념", "적용 맥락", "수준에 맞는 예시", "한계와 주의점"]
    return {"discipline": discipline, "level": canonical, "focus_points": focus}


def normalize_personality_tone(agent: dict) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    raw_val = (
        agent.get("personality")
        or agent.get("style")
        or agent.get("tone")
        or str(agent.get("persona") or "")
    )
    val = str(raw_val or "").strip()
    if val in ALLOWED_PERSONALITIES:
        return val, val, warnings
        
    for canonical in ALLOWED_PERSONALITIES:
        if canonical in val or canonical.replace(" ", "") in val.replace(" ", ""):
            return canonical, canonical, warnings
            
    return DEFAULT_PERSONALITY, DEFAULT_TONE, warnings


def normalize_agent_config(agent: dict, user_message: str = "") -> dict:
    warnings: list[str] = []
    persona = str(agent.get("persona") or "")
    level_value = agent.get("knowledgeLevel") or agent.get("knowledge_level")
    fallback_text = " ".join([persona, str(agent.get("goal") or ""), str(agent.get("role") or "")])
    knowledge_level, level_warnings = normalize_knowledge_level(level_value, fallback_text)
    warnings.extend(level_warnings)
    personality, tone, tone_warnings = normalize_personality_tone(agent)
    warnings.extend(tone_warnings)
    custom_instruction = _merge_custom_instruction(agent)
    discipline = infer_discipline(user_message, {**agent, "customInstruction": custom_instruction})
    policy = get_knowledge_depth_policy(knowledge_level, discipline)
    adjustment = get_discipline_depth_adjustment(discipline, knowledge_level)
    return {
        "name": _clean_value(agent.get("name"), "AI 에이전트"),
        "role": _clean_value(agent.get("role"), "학습 도우미"),
        "goal": _clean_value(agent.get("goal"), "사용자의 학습을 돕는다"),
        "persona": persona.strip(),
        "customInstruction": custom_instruction,
        "canonical_personality": personality,
        "canonical_tone": tone,
        "canonical_knowledge_level": knowledge_level,
        "discipline": discipline,
        "knowledge_depth_policy": policy,
        "discipline_adjustment": adjustment,
        "validation_warnings": warnings,
    }


def build_agent_system_prompt(agent_config: dict) -> str:
    policy = agent_config["knowledge_depth_policy"]
    adjustment = agent_config["discipline_adjustment"]
    return f"""너는 "{agent_config['name']}"이라는 StudyBridge AI 에이전트다.

[역할]
{agent_config['role']}

[목표]
{agent_config['goal']}

[성격]
{agent_config['canonical_personality']}

[말투]
{agent_config['canonical_tone']}

[지식수준]
{agent_config['canonical_knowledge_level']}

[학문 분야]
{agent_config['discipline']}

[지식수준별 답변 깊이 정책]
대상 독자: {policy['target_reader']}
답변 목표: {policy['depth_goal']}
반드시 포함할 관점: {", ".join(policy['required_dimensions'])}
피해야 할 답변: {", ".join(policy['forbidden_patterns'])}
답변 전략: {policy['answer_strategy']}

[학문 분야별 보정 정책]
{", ".join(adjustment['focus_points'])}

[사용자 추가 요구사항]
{agent_config['customInstruction'] or "없음"}

응답 규칙:
1. 같은 질문이라도 지식수준에 따라 답변의 깊이, 용어 수준, 분석 관점, 예시 수준을 반드시 다르게 한다.
2. 입문 수준은 쉬운 비유와 핵심 개념 중심으로 답한다.
3. 학사 수준은 전공 기본 개념, 용어 정의, 대표 예시 중심으로 답한다.
4. 석사 수준은 구조, 원리, 방법론, 적용 조건, 한계까지 설명한다.
5. 박사 수준은 이론적 기반, 가정, 논쟁점, 반례, 다른 이론과의 비교까지 설명한다.
6. 전문가 수준은 실무 적용, 아키텍처, 리스크, 트레이드오프, 의사결정 기준까지 설명한다.
7. 선택된 지식수준보다 낮은 수준으로 답하지 않는다.
8. 선택된 지식수준보다 과도하게 높은 수준으로 튀지 않는다.
9. 사용자 추가 요구사항을 반영하되, 지식수준 정책을 무시하지 않는다.
10. 모르는 내용은 추측하지 않는다.
11. 한국어로 답변하되, 사용자가 명시적으로 다른 언어를 요구하면 그 언어를 사용할 수 있다."""


def validate_prompt_contains_agent_constraints(prompt: str, agent_config: dict) -> list[str]:
    warnings: list[str] = []
    required_values = [
        ("지식수준", agent_config["canonical_knowledge_level"]),
        ("학문 분야", agent_config["discipline"]),
        ("성격", agent_config["canonical_personality"]),
        ("말투", agent_config["canonical_tone"]),
        ("depth policy", agent_config["knowledge_depth_policy"]["depth_goal"]),
    ]
    if agent_config.get("customInstruction") and agent_config["customInstruction"] not in prompt:
        warnings.append("customInstruction 누락")
    for label, value in required_values:
        if value and value not in prompt:
            warnings.append(f"{label} 제약 누락: {value}")
    if "지식수준에 따라 답변의 깊이" not in prompt:
        warnings.append("지식수준별 차별화 규칙 누락")
    return warnings


def validate_answer_quality(answer: str, agent_config: dict, user_message: str) -> dict:
    text = answer or ""
    issues: list[str] = []
    level = agent_config["canonical_knowledge_level"]
    score = 0.35
    if len(text.strip()) >= 80:
        score += 0.1
    if _contains_any(text, _keywords_for_level(level)):
        score += 0.25
    else:
        issues.append(f"{level} 필수 관점 부족")
    if _contains_any(text, agent_config["discipline_adjustment"]["focus_points"]):
        score += 0.15
    else:
        issues.append("학문 분야별 보정 관점 부족")
    if _personality_signal_ok(text, agent_config["canonical_personality"]):
        score += 0.1
    else:
        issues.append("성격/말투 반영 약함")
    if agent_config.get("customInstruction") and not _custom_instruction_likely_satisfied(text, agent_config["customInstruction"]):
        issues.append("사용자 추가 요구사항 반영 확인 필요")
    else:
        score += 0.05
    score = min(score, 1.0)
    return {
        "knowledge_level_ok": not any("필수 관점" in issue for issue in issues),
        "depth_ok": score >= 0.65,
        "discipline_ok": not any("학문 분야" in issue for issue in issues),
        "personality_ok": not any("성격" in issue for issue in issues),
        "tone_ok": not any("성격" in issue for issue in issues),
        "custom_instruction_ok": not any("추가 요구사항" in issue for issue in issues),
        "issues": issues,
        "score": round(score, 2),
        "passed": score >= 0.8,
    }


def revise_answer_to_match_quality_policy(
    answer: str,
    agent_config: dict,
    validation_result: dict,
    user_message: str,
    openai_client=None,
    model: str = "gpt-4o-mini",
) -> str:
    if openai_client is None:
        logger.warning("답변 품질 보정이 필요하지만 OpenAI client가 없어 원문 반환: %s", validation_result)
        return answer
    policy_text = json.dumps(agent_config["knowledge_depth_policy"], ensure_ascii=False)
    adjustment_text = json.dumps(agent_config["discipline_adjustment"], ensure_ascii=False)
    prompt = f"""아래 답변은 선택된 지식수준 정책을 충분히 반영하지 못했습니다.

[사용자 질문]
{user_message}

[선택된 지식수준]
{agent_config['canonical_knowledge_level']}

[학문 분야]
{agent_config['discipline']}

[지식수준별 답변 깊이 정책]
{policy_text}

[학문 분야별 보정 정책]
{adjustment_text}

[성격/말투]
{agent_config['canonical_personality']} / {agent_config['canonical_tone']}

[사용자 추가 요구사항]
{agent_config['customInstruction'] or "없음"}

[기존 답변]
{answer}

[검증 실패 사유]
{", ".join(validation_result.get("issues", []))}

기존 답변의 핵심 내용은 유지하되, 선택된 지식수준과 학문 분야에 맞게 답변의 깊이, 용어 수준, 분석 관점, 예시 수준을 재작성하세요.
마크다운 코드블록은 쓰지 말고 자연스러운 학습 답변으로 작성하세요."""
    try:
        response = openai_client.responses.create(model=model, input=prompt)
        output = getattr(response, "output_text", None)
        return output.strip() if output else answer
    except Exception as exc:
        logger.warning("답변 품질 보정 실패: %s", exc)
        return answer


def _keywords_for_level(level: str) -> list[str]:
    if level == "입문 수준":
        return ["쉽게", "비유", "예를 들면", "핵심", "간단히"]
    if level == "학사 수준":
        return ["정의", "원리", "개념", "예시", "차이", "구조"]
    if level == "석사 수준":
        return ["구조", "원리", "방법론", "적용 조건", "한계", "분석"]
    if level == "박사 수준":
        return ["이론", "가정", "논쟁", "반례", "비교", "연구", "패러다임"]
    if level == "전문가 수준":
        return ["실무", "아키텍처", "리스크", "트레이드오프", "의사결정", "안티패턴", "운영"]
    return []


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(str(keyword).lower() in lowered for keyword in keywords)


def _merge_custom_instruction(agent: dict) -> str:
    values = [
        agent.get("customInstruction"),
        agent.get("custom_instruction"),
        agent.get("customPersonality"),
        agent.get("custom_personality"),
    ]
    seen = []
    for value in values:
        cleaned = _normalize_space(str(value or ""))
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return " / ".join(seen)


def _extract_tag_value(text: str, label: str) -> str:
    match = re.search(rf"\[{re.escape(label)}\s*:\s*([^\]]+)\]", text or "")
    return match.group(1).strip() if match else ""


def _clean_value(value: Any, default: str) -> str:
    cleaned = _normalize_space(str(value or ""))
    return cleaned or default


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _personality_signal_ok(answer: str, personality: str) -> bool:
    if personality == "효율적":
        return len(answer) < 2500
    return True


def _custom_instruction_likely_satisfied(answer: str, instruction: str) -> bool:
    lowered_instruction = instruction.lower()
    if "영어" in instruction or "english" in lowered_instruction:
        ascii_letters = sum(1 for char in answer if "a" <= char.lower() <= "z")
        return ascii_letters >= 20
    return True
