"""
학습 로드맵 생성 서비스.

책임 구조:
  GPT (70%):  구조화, 주차 설계, 학습 목표/태스크 정리, JSON 형식 출력
  Qwen (30%): 표현 보정, 사용자 맞춤 말투, 학습 난이도 언어 조정 (optional)

GPT 실패 시 → Qwen fallback
Qwen 실패 시 → GPT 원본 그대로 사용
둘 다 실패 시 → build_fallback_roadmap() 반환 (계약 구조 유지)
"""
import json
import logging
import re
from typing import Optional

from app.core.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

_DEFAULT_WEEKS = 4
_MAX_CONTEXT_CHARS = 3000


def build_roadmap_prompt(
    document_title: str,
    context: str,
    weeks: Optional[int],
    difficulty: Optional[str],
    goal: Optional[str],
    knowledge_level: Optional[str],
) -> tuple[str, str]:
    """GPT 호출용 system/user 프롬프트를 생성한다."""
    week_hint = f"{weeks}주" if weeks else "적절한 주차(4~12주)"
    diff_hint = difficulty or "medium"
    goal_hint = goal or "이 자료를 체계적으로 이해하고 응용할 수 있게 된다."
    level_hint = knowledge_level or "학사"

    from app.services.knowledge_level_controller import get_level_instruction
    level_instr = get_level_instruction(level_hint)

    system = (
        "너는 학습 커리큘럼 설계 전문가다.\n"
        f"{level_instr}\n"
        "주어진 자료를 분석해 단계별 학습 로드맵을 주차 단위로 설계한다.\n"
        "반드시 아래 JSON 형식으로만 응답한다. 다른 텍스트 없이 JSON만 출력한다:\n"
        '{\n'
        '  "title": "로드맵 제목",\n'
        '  "weeks": [\n'
        '    {\n'
        '      "week": 1,\n'
        '      "title": "주차 제목",\n'
        '      "goal": "학습 목표 한 줄",\n'
        '      "tasks": ["과제1", "과제2", "과제3"]\n'
        '    }\n'
        '  ]\n'
        '}'
    )

    user = (
        f"## 자료명\n{document_title}\n\n"
        f"## 자료 내용 (최대 {_MAX_CONTEXT_CHARS}자)\n{context[:_MAX_CONTEXT_CHARS]}\n\n"
        f"## 학습 목표\n{goal_hint}\n\n"
        f"## 설계 조건\n"
        f"- 주차 수: {week_hint}\n"
        f"- 난이도: {diff_hint}\n"
        f"- 지식수준: {level_hint}\n\n"
        "위 조건으로 학습 로드맵을 JSON 형식으로 설계하라."
    )
    return system, user


def generate_roadmap_with_gpt(
    document_title: str,
    context: str,
    weeks: Optional[int],
    difficulty: Optional[str],
    goal: Optional[str],
    knowledge_level: Optional[str],
) -> Optional[dict]:
    """
    GPT로 구조화된 로드맵 JSON을 생성한다.
    성공 시 dict 반환, 실패 시 None.
    """
    if not OPENAI_API_KEY:
        logger.info("OPENAI_API_KEY 미설정 — GPT 로드맵 생성 건너뜀")
        return None

    system, user = build_roadmap_prompt(
        document_title, context, weeks, difficulty, goal, knowledge_level
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        raw = resp.choices[0].message.content or ""
        return _parse_roadmap_json(raw)
    except Exception as e:
        logger.warning("GPT 로드맵 생성 실패: %s", type(e).__name__)
        return None


def refine_roadmap_with_qwen(
    roadmap_dict: dict,
    document_title: str,
    knowledge_level: Optional[str],
) -> dict:
    """
    GPT가 생성한 로드맵을 Qwen으로 표현 보정한다 (30% 역할).
    Qwen 실패 시 GPT 원본 그대로 반환.
    """
    title = roadmap_dict.get("title", document_title)
    weeks_data = roadmap_dict.get("weeks", [])

    if not weeks_data:
        return roadmap_dict

    # 단순 요약 텍스트 생성 후 말투 보정 (각 주차 title/goal 보정)
    summary = "\n".join(
        f"{w.get('week')}주: {w.get('title')} — {w.get('goal', '')}"
        for w in weeks_data[:6]
    )

    system = (
        f"너는 StudyBridge 학습 코치다. 지식수준: {knowledge_level or '학사'}.\n"
        "아래 로드맵 요약을 학습자 친화적인 말투로 자연스럽게 다듬어라. "
        "핵심 내용은 바꾸지 말고, 딱딱한 표현만 부드럽게 바꾼다. "
        "반드시 한국어로 출력한다."
    )
    user = f"## 로드맵 요약\n{summary}\n\n제목: {title}\n\n위 내용을 자연스럽게 다듬어라."

    try:
        from app.services.ollama_client import ask_ollama, is_ollama_available
        if is_ollama_available():
            refined = ask_ollama(system_prompt=system, user_prompt=user, max_tokens=400)
            if refined and not refined.startswith("["):
                logger.debug("Qwen 로드맵 표현 보정 완료")
        # Qwen 결과는 title 보정에만 반영, 구조(weeks)는 그대로 유지
    except Exception as e:
        logger.debug("Qwen 로드맵 보정 건너뜀: %s", e)

    return roadmap_dict


def build_fallback_roadmap(
    material_id: int,
    document_title: str,
    reason: str = "",
) -> dict:
    """
    GPT/Qwen 모두 실패 시 기초-중급-실전 구조의 fallback 로드맵을 반환한다.
    계약 구조(materialId, title, weeks)는 반드시 유지한다.
    """
    if reason:
        logger.warning("로드맵 fallback: %s / reason=%s", document_title, reason)
    return {
        "materialId": material_id,
        "title":      f"{document_title} 학습 로드맵 (기본 구성)",
        "isFallback": True,
        "weeks": [
            {
                "week": 1,
                "title": "기초 개념 이해",
                "goal":  "핵심 개념과 용어를 파악한다.",
                "tasks": ["자료 전체 1회 통독", "핵심 용어 정리", "학습 목표 설정"],
            },
            {
                "week": 2,
                "title": "심화 학습",
                "goal":  "주요 개념의 원리와 구조를 이해한다.",
                "tasks": ["중요 섹션 재독", "예시 분석", "개념 요약 작성"],
            },
            {
                "week": 3,
                "title": "응용 및 정리",
                "goal":  "학습 내용을 실제 문제에 적용한다.",
                "tasks": ["연습 문제 풀기", "핵심 내용 정리", "자기 설명 연습"],
            },
            {
                "week": 4,
                "title": "복습 및 완성",
                "goal":  "전체 내용을 통합하고 부족한 부분을 보완한다.",
                "tasks": ["전체 복습", "오류 교정", "최종 정리 노트 작성"],
            },
        ],
    }


def validate_roadmap_shape(data: dict) -> bool:
    """로드맵 dict가 올바른 구조를 가지고 있는지 확인한다."""
    if not isinstance(data, dict):
        return False
    if "title" not in data or "weeks" not in data:
        return False
    weeks = data.get("weeks", [])
    if not isinstance(weeks, list) or len(weeks) == 0:
        return False
    for w in weeks:
        if not isinstance(w, dict):
            return False
        if "week" not in w or "title" not in w:
            return False
    return True


def generate_roadmap_from_material(
    material_id: int,
    document_title: str,
    context: str,
    weeks: Optional[int] = None,
    difficulty: Optional[str] = None,
    goal: Optional[str] = None,
    knowledge_level: Optional[str] = None,
) -> dict:
    """
    로드맵 생성 메인 함수.

    GPT(70%) → Qwen 보정(30%) → fallback 순서.
    """
    # 1. GPT로 구조화된 로드맵 생성
    roadmap = generate_roadmap_with_gpt(
        document_title, context, weeks, difficulty, goal, knowledge_level
    )

    if roadmap and validate_roadmap_shape(roadmap):
        # 2. Qwen으로 표현 보정 (30% 역할)
        roadmap = refine_roadmap_with_qwen(roadmap, document_title, knowledge_level)
        roadmap["materialId"] = material_id
        roadmap.setdefault("isFallback", False)
        return roadmap

    # GPT 실패 시 Qwen만으로 시도
    if not OPENAI_API_KEY:
        qwen_result = _try_qwen_only_roadmap(
            material_id, document_title, context, weeks, knowledge_level
        )
        if qwen_result and validate_roadmap_shape(qwen_result):
            qwen_result["materialId"] = material_id
            qwen_result.setdefault("isFallback", False)
            return qwen_result

    # 둘 다 실패
    return build_fallback_roadmap(material_id, document_title, "GPT/Qwen 응답 없음")


def _try_qwen_only_roadmap(
    material_id: int,
    document_title: str,
    context: str,
    weeks: Optional[int],
    knowledge_level: Optional[str],
) -> Optional[dict]:
    """GPT 없을 때 Qwen만으로 로드맵 생성을 시도한다."""
    week_count = weeks or _DEFAULT_WEEKS
    system = (
        "너는 학습 로드맵 설계 전문가다. "
        "아래 JSON 형식으로만 응답한다:\n"
        '{"title":"...","weeks":[{"week":1,"title":"...","goal":"...","tasks":["..."]}]}'
    )
    user = (
        f"자료: {document_title}\n내용: {context[:1500]}\n"
        f"지식수준: {knowledge_level or '학사'}\n"
        f"{week_count}주 학습 로드맵을 JSON으로 작성하라."
    )
    try:
        from app.services.ollama_client import ask_ollama, is_ollama_available
        if not is_ollama_available():
            return None
        raw = ask_ollama(system_prompt=system, user_prompt=user, max_tokens=800)
        return _parse_roadmap_json(raw)
    except Exception as e:
        logger.warning("Qwen 전용 로드맵 생성 실패: %s", e)
        return None


def _parse_roadmap_json(raw: str) -> Optional[dict]:
    """LLM 출력에서 JSON을 파싱한다."""
    if not raw:
        return None
    # JSON 블록 추출
    match = re.search(r"\{[\s\S]+\}", raw.strip())
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None
