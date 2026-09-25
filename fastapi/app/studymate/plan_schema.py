"""Persona-aware Structured Plan Schema + Shared Contribution Plan.

Planner 단계만 JSON Schema(Ollama format)로 구조를 강제한다. Renderer 는 자유 생성.
Ollama 0.24 의 format=JSON schema 동작은 2026-09-17 실측으로 확인했다(required/minItems 반영).
스키마 강제가 실패하면(파싱/검증 실패) 동일 스키마로 1회 repair, 그래도 실패하면
결정론적 최소 plan 으로 내려가고 trace 에 planFallback 을 남긴다.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.studymate import knowledge_policy as KP
from app.studymate import persona_policy as PP

STR_MAX = 70
ITEM_MAX = 60


def _field_schema(ftype: str, min_items: int) -> Dict[str, Any]:
    if ftype == "array":
        return {"type": "array", "items": {"type": "string", "minLength": 2, "maxLength": ITEM_MAX},
                "minItems": max(1, min_items), "maxItems": max(1, min_items)}
    return {"type": "string", "minLength": 2, "maxLength": STR_MAX}


def required_fields(persona: str, level: str) -> Dict[str, Tuple[str, int]]:
    fields: Dict[str, Tuple[str, int]] = {}
    for name, ftype, mi in PP.PLAN_FIELDS.get(persona, []) + KP.PLAN_FIELDS.get(level, []):
        if name in fields:
            ptype, pmin = fields[name]
            ftype = "array" if "array" in (ptype, ftype) else "string"
            mi = max(mi, pmin)
        fields[name] = (ftype, mi)
    return fields


def agent_plan_schema(persona: str, level: str) -> Dict[str, Any]:
    props: Dict[str, Any] = {
        "claims": {"type": "array", "items": {"type": "string", "minLength": 4, "maxLength": ITEM_MAX},
                   "minItems": 2, "maxItems": 2},
    }
    for name, (ftype, mi) in required_fields(persona, level).items():
        props[name] = _field_schema(ftype, mi)
    return {"type": "object", "properties": props, "required": list(props.keys())}


def single_plan_schema(persona: str, level: str) -> Dict[str, Any]:
    return agent_plan_schema(persona, level)


def shared_plan_schema(agents: List[Tuple[str, str, str]]) -> Dict[str, Any]:
    """agents: [(agentId, persona, level)]"""
    props = {aid: agent_plan_schema(p, l) for aid, p, l in agents}
    return {
        "type": "object",
        "properties": {
            "question_focus": {"type": "string", "minLength": 2, "maxLength": 80},
            "agents": {"type": "object", "properties": props, "required": [a for a, _, _ in agents]},
        },
        "required": ["question_focus", "agents"],
    }


def _check(value: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: not object")
            return
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}.{req}: missing")
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                _check(value[k], sub, f"{path}.{k}", errors)
    elif t == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: not array")
            return
        items = [v for v in value if isinstance(v, str) and v.strip()]
        if len(items) < schema.get("minItems", 0):
            errors.append(f"{path}: minItems {schema.get('minItems')} (got {len(items)})")
    elif t == "string":
        if not isinstance(value, str) or len(value.strip()) < schema.get("minLength", 0):
            errors.append(f"{path}: empty/short string")


def validate(obj: Any, schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    _check(obj, schema, "$", errors)
    return errors


def parse_json(text: str) -> Optional[Any]:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def plan_to_contribution_text(plan: Dict[str, Any], others_claims: Optional[List[str]] = None) -> str:
    """plan dict → 렌더러 프롬프트용 구조화 요약. 다른 교수의 '원문'이 아니라 주장 목록만 전달한다."""
    lines = []
    label = {
        "contribution": "맡은 기여", "main_claim": "중심 주장", "claims": "반드시 다룰 주장",
        "concepts": "핵심 개념", "intuition": "직관", "analogy": "비유", "analogy_limit": "비유의 한계",
        "assumptions": "전제/가정", "counterexamples": "반례", "limitations": "한계",
        "cross_domain_connections": "다른 분야 연결", "alternative_views": "다른 관점",
        "key_points": "핵심 요점", "conclusion": "결론", "common_misconception": "흔한 착각",
        "why_wrong": "착각인 이유", "correct_model": "올바른 모델", "definition": "정의",
        "premises": "전제", "inference_steps": "추론 단계", "why_it_matters": "왜 중요한가",
        "concrete_example": "구체 예시", "jargon_explained": "풀어줄 용어", "mechanism": "동작 원리",
        "standard_approach": "표준 방식", "architecture": "구조", "tradeoffs": "트레이드오프",
        "failure_modes": "실패 모드", "comparison": "비교", "boundary_conditions": "경계조건",
        "failure_domain": "실패 영역", "production_constraints": "운영 제약", "failure_domains": "장애 영역",
        "operational_tradeoffs": "운영 트레이드오프", "observability": "관측 가능성",
        "formal_model": "형식 모델(수식·상태전이·불변식 중 하나를 본문에서 풀어 설명)",
    }
    for k, v in plan.items():
        name = label.get(k, k)
        if isinstance(v, list):
            vals = [str(x).strip() for x in v if str(x).strip()]
            if vals:
                lines.append(f"- {name}: " + " / ".join(vals))
        elif isinstance(v, str) and v.strip():
            lines.append(f"- {name}: {v.strip()}")
    if others_claims:
        lines.append("- 다른 교수가 맡은 주장(반복 금지, 필요하면 한 번만 짧게 언급): " + " / ".join(others_claims[:8]))
    lines.append("- 위 계획의 항목을 모두 자연스러운 문장으로 녹여 설명하라(라벨·목록 머리표를 그대로 복사하지 않는다).")
    return "\n".join(lines)


def minimal_plan(persona: str, level: str, question: str, role: str) -> Dict[str, Any]:
    """planner 실패 시 결정론 fallback. 필드는 '지시문'으로 채운다(내용을 지어내지 않음)."""
    plan: Dict[str, Any] = {
        "claims": ["질문의 핵심 개념을 정확히 설명한다", "구체적 사례로 확인한다"],
    }
    for name, (ftype, mi) in required_fields(persona, level).items():
        plan[name] = ["(질문에 맞게 직접 채워 설명)"] * max(1, mi) if ftype == "array" else "(질문에 맞게 직접 채워 설명)"
    return plan
