"""
AI 학습 피드백 빌더 — 장점/권장사항/우려사항/다음 행동을 균형 있게 생성.

목표(스펙 H~M):
  - 마크다운(**, ###, ##, #, -, *, backtick, HTML)이 사용자 표시 텍스트에 남지 않게 sanitize.
  - 장점만 나열 금지: strengths≥8, recommendations≥8, concerns≥8, next_actions≥5 균형 보장.
  - 근거가 부족하면 거짓 칭찬/비판 대신 "현재 기록 기준으로는" 톤으로 학습 개선 관점 작성하고
    assumption_notice에 명시한다.
  - LLM 실패/분량 부족 시 (1) OpenAI repair → (2) Ollama → (3) deterministic balanced fallback.

1차 초안=Ollama, 균형 보정=OpenAI(study_action_router.refiner_llm: OpenAI→Ollama fallback).
모델/temperature/max_tokens/분량 최소값은 .env로 제어(하드코딩 금지).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from app.services.material_summary_builder import sanitize_markdown_text

logger = logging.getLogger(__name__)

MIN_STRENGTHS = int(os.getenv("AI_FEEDBACK_MIN_STRENGTHS", "8"))
MIN_RECOMMENDATIONS = int(os.getenv("AI_FEEDBACK_MIN_RECOMMENDATIONS", "8"))
MIN_CONCERNS = int(os.getenv("AI_FEEDBACK_MIN_CONCERNS", "8"))
MIN_NEXT_ACTIONS = int(os.getenv("AI_FEEDBACK_MIN_NEXT_ACTIONS", "5"))


# ── 개념 추출 ─────────────────────────────────────────────────────────────────
def _concepts(content: str, context: str) -> List[str]:
    from app.services.material_ai_manager import _keywords_from_text
    pool = _keywords_from_text((content or "") + "\n" + (context or ""), limit=20)
    cleaned: List[str] = []
    seen = set()
    for k in pool:
        t = sanitize_markdown_text(k).strip()
        if len(t) <= 1 or t.lower() in seen:
            continue
        seen.add(t.lower())
        cleaned.append(t)
    return cleaned or ["학습 내용"]


# ── 항목 정규화 ───────────────────────────────────────────────────────────────
def _norm_items(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for it in raw or []:
        if isinstance(it, dict):
            title = sanitize_markdown_text(it.get("title") or it.get("heading") or "")
            content = sanitize_markdown_text(it.get("content") or it.get("description") or it.get("text") or "")
        else:
            content = sanitize_markdown_text(it)
            title = content.split(".")[0][:40] if content else ""
        if not content:
            continue
        if not title:
            title = content[:30]
        out.append({"title": title, "content": content})
    return out


def _reindex(items: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    return [{"index": i + 1, "title": it["title"], "content": it["content"]} for i, it in enumerate(items)]


# ── deterministic 균형 보강 ───────────────────────────────────────────────────
_STRENGTH_T = [
    ("{c} 학습 방향 설정", "현재 기록 기준으로는 {c}의 핵심 의도를 파악하려는 방향이 보입니다. 무엇을 왜 배우는지 인식하고 있다는 점은 좋은 출발입니다."),
    ("{c} 개념 정리 시도", "{c}을(를) 본인 언어로 정리하려는 시도가 드러납니다. 단순 암기가 아니라 이해하려는 태도는 장기 학습에 유리합니다."),
    ("{c} 우선순위 인식", "{c}을(를) 학습 목표 안에서 우선순위로 두고 접근하고 있습니다. 한정된 시간에서 무엇부터 볼지 고르는 감각이 보입니다."),
]
_RECOMMEND_T = [
    ("{c} 코드 예시로 재정리", "{c}의 역할을 글로만 설명하지 말고 짧은 코드 예시와 함께 다시 정리해보세요. 입력과 출력, 호출 흐름까지 연결하면 이해가 단단해집니다."),
    ("{c} 비교 학습", "{c}과(와) 비슷한 대안 개념을 하나 골라 차이와 선택 기준을 표로 비교해보세요. 경계가 분명해지면 응용이 쉬워집니다."),
    ("{c} 실습 후 회고", "{c} 관련 예제를 직접 실행하고, 막힌 지점과 해결 과정을 한 문단으로 회고로 남겨보세요. 다음 학습의 출발점이 됩니다."),
]
_CONCERN_T = [
    ("{c} 책임 경계 불명확 가능성", "현재 기록만 보면 {c}와(과) 주변 요소의 책임 경계가 명확히 구분되었는지 확인하기 어렵습니다. 규모가 커지면 로직이 한 곳에 몰릴 위험이 있어 기준을 세워두는 것이 좋습니다."),
    ("{c} 적용 근거 부족 가능성", "{c}을(를) 왜 그렇게 적용했는지에 대한 근거가 현재 기록에는 충분히 드러나지 않습니다. 선택 이유를 적어두지 않으면 나중에 같은 실수를 반복하기 쉽습니다."),
    ("{c} 예외/오류 대비 미흡 가능성", "{c} 사용 중 발생할 수 있는 오류나 예외 상황에 대한 점검이 현재 내용에서는 보이지 않습니다. 실패 케이스를 미리 정리해두면 디버깅 시간이 줄어듭니다."),
]
_NEXT_T = [
    ("{c} 예제 직접 구현", "{c}을(를) 사용하는 최소 예제를 직접 작성하고 실행 결과를 확인합니다."),
    ("{c} 핵심 질문 3개 정리", "{c}에 대해 스스로 묻고 답할 핵심 질문 3개를 만들고 답을 적어봅니다."),
    ("{c} 오답/오개념 노트", "{c}에서 헷갈렸던 부분을 오개념 노트로 정리하고 다음 복습 때 다시 확인합니다."),
]


def _pad(items: List[Dict[str, str]], templates: List, concepts: List[str], need: int,
         filler_title: str) -> tuple[List[Dict[str, str]], bool]:
    out = list(items)
    seen = {it["content"][:30] for it in out}
    used_filler = False
    i = 0
    guard = 0
    while len(out) < need and guard < need * 4:
        guard += 1
        c = concepts[i % len(concepts)]
        tmpl = templates[(i // len(concepts)) % len(templates)] if concepts else templates[i % len(templates)]
        i += 1
        title = tmpl[0].format(c=c)
        content = tmpl[1].format(c=c)
        if content[:30] in seen:
            continue
        seen.add(content[:30])
        out.append({"title": title, "content": content})
    # 그래도 부족하면 '다음 학습에서 점검할 항목'으로 채움(거짓 생성 대신 점검 항목)
    j = 0
    while len(out) < need:
        c = concepts[j % len(concepts)]
        j += 1
        content = f"현재 입력 내용만으로는 근거가 제한적이므로, 다음 학습에서 {c} 관련 내용을 추가로 점검할 항목으로 남깁니다."
        if content[:30] in seen:
            content += f" ({j})"
        seen.add(content[:30])
        out.append({"title": f"{filler_title}", "content": content})
        used_filler = True
    return out, used_filler


# ── 검증 (스펙 L) ─────────────────────────────────────────────────────────────
def validate_feedback_quality(response: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    strengths = response.get("strengths") or []
    recommendations = response.get("recommendations") or []
    concerns = response.get("concerns") or []

    if len(strengths) < MIN_STRENGTHS:
        errors.append(f"strengths<{MIN_STRENGTHS} ({len(strengths)})")
    if len(recommendations) < MIN_RECOMMENDATIONS:
        errors.append(f"recommendations<{MIN_RECOMMENDATIONS} ({len(recommendations)})")
    if len(concerns) < MIN_CONCERNS:
        errors.append(f"concerns<{MIN_CONCERNS} ({len(concerns)})")

    for label, arr in (("strengths", strengths), ("recommendations", recommendations),
                       ("concerns", concerns), ("next_actions", response.get("next_actions") or [])):
        for i, it in enumerate(arr):
            if not (it.get("title") or "").strip() or not (it.get("content") or "").strip():
                errors.append(f"{label}[{i}] 빈 title/content")

    if strengths and not recommendations and not concerns:
        errors.append("장점만 있고 권장/우려 없음")

    # 권장/우려가 장점 문장 그대로 반복인지
    s_set = {(it.get("content") or "")[:40] for it in strengths}
    rep_r = sum(1 for it in recommendations if (it.get("content") or "")[:40] in s_set)
    rep_c = sum(1 for it in concerns if (it.get("content") or "")[:40] in s_set)
    if recommendations and rep_r == len(recommendations):
        errors.append("recommendations가 strengths 반복")
    if concerns and rep_c == len(concerns):
        errors.append("concerns가 strengths 반복")

    blob = str(response)
    for sym in ("**", "###", "`"):
        if sym in blob:
            errors.append(f"마크다운 기호 잔존({sym})")

    return {"ok": not errors, "errors": errors}


# ── LLM 초안 ──────────────────────────────────────────────────────────────────
def _llm_feedback(content: str, context: str, level: str) -> Optional[Dict[str, Any]]:
    from app.services.study_action_router import refiner_llm  # OpenAI→Ollama fallback
    from app.services.material_ai_manager import _extract_json

    system = (
        "너는 학습 코치다. 학생의 학습 기록을 받아 균형 잡힌 피드백을 만든다. "
        "장점만 나열하지 말고 장점, 권장사항, 우려사항(비판적 개선점), 다음 행동을 함께 만든다. "
        "비판은 인신공격이 아니라 학습 개선 관점이어야 하고, 근거가 부족하면 '현재 기록 기준으로는'이라고 표현한다. "
        "없는 학습 내용을 사실처럼 칭찬하지 마라. 마크다운(**, #, -, *, backtick) 없이 일반 문장으로, JSON만 출력한다."
    )
    user = (
        f"## 학습 기록\n{(content or '')[:4000]}\n\n"
        f"## 참고 맥락\n{(context or '')[:1500]}\n\n## 학습 수준\n{level}\n\n"
        "아래 JSON 형식으로만 응답하라(설명/마크다운 금지):\n"
        '{ "summary":"전체 요약", '
        '"strengths":[{"title":"...","content":"..."}], '
        '"recommendations":[{"title":"...","content":"..."}], '
        '"concerns":[{"title":"...","content":"..."}], '
        '"next_actions":[{"title":"...","content":"..."}] }\n'
        f"strengths {MIN_STRENGTHS}개 이상, recommendations {MIN_RECOMMENDATIONS}개 이상, "
        f"concerns {MIN_CONCERNS}개 이상, next_actions {MIN_NEXT_ACTIONS}개 이상. 같은 문장 반복 금지."
    )
    try:
        raw = refiner_llm(system, user, max_tokens=3000)
    except Exception as e:  # noqa: BLE001
        logger.warning("feedback LLM 예외: %s", e)
        return None
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    return parsed


# ── 메인 빌더 ─────────────────────────────────────────────────────────────────
def build_balanced_feedback(content: str, context: str = "", level: str = "undergraduate") -> Dict[str, Any]:
    concepts = _concepts(content, context)
    short_input = len((content or "").strip()) < 120

    parsed = _llm_feedback(content, context, level) or {}
    strengths = _norm_items(parsed.get("strengths"))
    recommendations = _norm_items(parsed.get("recommendations"))
    concerns = _norm_items(parsed.get("concerns"))
    next_actions = _norm_items(parsed.get("next_actions"))

    strengths, f1 = _pad(strengths, _STRENGTH_T, concepts, MIN_STRENGTHS, "다음 학습에서 점검할 항목")
    recommendations, f2 = _pad(recommendations, _RECOMMEND_T, concepts, MIN_RECOMMENDATIONS, "추가 확인 필요")
    concerns, f3 = _pad(concerns, _CONCERN_T, concepts, MIN_CONCERNS, "추가 확인 필요")
    next_actions, f4 = _pad(next_actions, _NEXT_T, concepts, MIN_NEXT_ACTIONS, "다음 학습 점검 항목")
    used_filler = any([f1, f2, f3, f4])

    summary = sanitize_markdown_text(parsed.get("summary")) or (
        f"현재 기록 기준으로 {concepts[0]} 등을 중심으로 학습한 내용을 정리했습니다. "
        "잘한 방향과 함께 보완하면 좋은 권장사항, 점검이 필요한 우려사항, 다음에 할 행동을 균형 있게 제시합니다."
    )

    assumption_notice = None
    if short_input or used_filler:
        assumption_notice = (
            "입력 내용이 제한적이므로 일부 항목은 학습 개선 관점의 권장사항으로 작성되었습니다."
        )

    result: Dict[str, Any] = {
        "feedback_title": "AI 학습 피드백",
        "summary": summary,
        "strengths": _reindex(strengths),
        "recommendations": _reindex(recommendations),
        "concerns": _reindex(concerns),
        "next_actions": _reindex(next_actions),
        "feedback_balance": {
            "strength_count": len(strengths),
            "recommendation_count": len(recommendations),
            "concern_count": len(concerns),
            "balanced": True,
        },
        "assumption_notice": assumption_notice,
        "error_code": None,
    }

    check = validate_feedback_quality(result)
    if not check["ok"]:
        logger.warning("feedback 검증 실패 → 보강: %s", check["errors"])
        # deterministic 재보강(절대 균형 보장)
        s, _ = _pad(strengths, _STRENGTH_T, concepts, MIN_STRENGTHS, "다음 학습에서 점검할 항목")
        r, _ = _pad(recommendations, _RECOMMEND_T, concepts, MIN_RECOMMENDATIONS, "추가 확인 필요")
        co, _ = _pad(concerns, _CONCERN_T, concepts, MIN_CONCERNS, "추가 확인 필요")
        na, _ = _pad(next_actions, _NEXT_T, concepts, MIN_NEXT_ACTIONS, "다음 학습 점검 항목")
        result["strengths"] = _reindex(s)
        result["recommendations"] = _reindex(r)
        result["concerns"] = _reindex(co)
        result["next_actions"] = _reindex(na)
        result["feedback_balance"] = {
            "strength_count": len(s), "recommendation_count": len(r),
            "concern_count": len(co), "balanced": True,
        }
        recheck = validate_feedback_quality(result)
        if not recheck["ok"]:
            result["warning"] = "; ".join(recheck["errors"])
    result["feedback_balance"]["balanced"] = validate_feedback_quality(result)["ok"]
    return result


def to_legacy_text(result: Dict[str, Any]) -> str:
    """하위호환: 기존 feedbackData(문자열)용 — 마크다운 없는 자연어 묶음."""
    parts: List[str] = [result.get("summary", "")]
    for label, key in (("강점", "strengths"), ("권장사항", "recommendations"),
                       ("우려사항", "concerns"), ("다음 행동", "next_actions")):
        parts.append(f"\n[{label}]")
        for it in result.get(key, []):
            parts.append(f"{it['index']}. {it['title']}: {it['content']}")
    return sanitize_markdown_text("\n".join(p for p in parts if p))
