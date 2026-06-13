"""
오답노트 복습 AI — 틀린 문제 복습 관리 전용.
자료보관함 요약/키워드/로드맵, 플래너 로직과 분리된 별도 경로.

  POST /api/ai/review/wrong-note-feedback   틀린 문제별 오답노트 + 재풀이 문제 + PDF용 평문
  POST /api/ai/review/variant-question      개념 동일·난이도 조절 변형 4지선다 문제

모델: Ollama(Qwen) 1차 분석 → OpenAI 보강 → deterministic fallback.
모든 사용자 표시 필드와 pdf_plain_text는 마크다운/HTML 제거(sanitize)한다.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/review", tags=["Review AI"])

FEEDBACK_TIMEOUT = int(os.getenv("AI_REVIEW_FEEDBACK_TIMEOUT_SECONDS", "120"))
VARIANT_TIMEOUT = int(os.getenv("AI_REVIEW_VARIANT_TIMEOUT_SECONDS", "60"))

_VALID_DIFFICULTY = {"easy", "normal", "hard"}
_DIFFICULTY_GUIDE = {
    "easy": "같은 개념을 문서 표현에 가깝게 다시 질문한다.",
    "normal": "같은 개념을 다른 코드 흐름이나 상황에 적용하도록 변형한다.",
    "hard": "오류 상황, 설계 판단, 테스트 가능성, 유지보수 관점으로 변형한다.",
}


def _choices(value: Any) -> List[str]:
    from app.utils.sanitize import sanitize_markdown_text
    if isinstance(value, list):
        out = [sanitize_markdown_text(v) for v in value]
        return [c for c in out if c]
    return []


def _ensure_four_choices(choices: List[str], correct: str) -> List[str]:
    """4지선다 보장. 부족하면 채우고, 정답이 빠지면 포함시킨다."""
    out = [c for c in choices if c]
    if correct and correct not in out:
        if len(out) >= 4:
            out[3] = correct
        else:
            out.append(correct)
    fillers = ["보기 1", "보기 2", "보기 3", "보기 4"]
    i = 0
    while len(out) < 4:
        cand = fillers[i % len(fillers)]
        if cand not in out:
            out.append(cand)
        i += 1
    return out[:4]


# ── A. 오답노트 피드백 ────────────────────────────────────────────────────────
def _fallback_note(q: Dict[str, Any], index: int) -> Dict[str, Any]:
    from app.utils.sanitize import sanitize_markdown_text, sanitize_list
    question = sanitize_markdown_text(q.get("question")) or f"{index}번 문제"
    choices = _choices(q.get("choices"))
    user_answer = sanitize_markdown_text(q.get("user_answer"))
    correct_answer = sanitize_markdown_text(q.get("correct_answer"))
    concepts = sanitize_list(q.get("concepts"))
    user_memo = sanitize_markdown_text(q.get("user_memo"))
    explanation = sanitize_markdown_text(q.get("explanation"))
    key = concepts[0] if concepts else "핵심 개념"
    # 참고 페이지 (없으면 None) — PDF/응답에 그대로 노출
    raw_page = q.get("page") if q.get("page") is not None else q.get("pageNumber")
    try:
        page = int(raw_page) if raw_page not in (None, "", []) else None
    except (TypeError, ValueError):
        page = None
    # 미응답 판정: selectedAnswer/userAnswer 가 비어있거나 submitted=false 면 UNANSWERED
    submitted = q.get("submitted", q.get("isSubmitted", True))
    status_raw = str(q.get("status") or "").strip().upper()
    is_unanswered = (
        status_raw == "UNANSWERED"
        or submitted is False
        or not (user_answer or "").strip()
    )
    status = "UNANSWERED" if is_unanswered else "WRONG"
    return {
        "index": index,
        "question": question,
        "choices": choices,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "page": page,
        "status": status,
        "ai_explanation": explanation or f"정답은 '{correct_answer}'이며, {key} 개념을 문서 기준으로 적용하면 확인할 수 있습니다.",
        "why_user_answer_is_wrong": (
            f"선택한 '{user_answer}'은(는) {key}의 책임 범위를 정확히 구분하지 못해 부족합니다."
            if user_answer else f"{key} 개념을 정확히 적용하지 못해 오답이 발생했습니다."
        ),
        "key_concepts": concepts or [key],
        "review_point": f"{key}의 정의와 책임 경계를 다시 확인하세요.",
        "retry_strategy": "선택지를 고르기 전에 각 보기를 개념 정의와 직접 비교하며 근거를 적어보세요.",
        "user_memo_reflection": (
            f"메모에 적은 '{user_memo}' 부분을 개념 정의와 다시 대조하면 오해를 줄일 수 있습니다."
            if user_memo else "다음 복습 때 헷갈린 지점을 메모로 남기면 약점 파악에 도움이 됩니다."
        ),
        "retry_question": {
            "question": f"{key} 개념을 다시 확인하는 문제: {question}",
            "choices": _ensure_four_choices(choices, correct_answer),
            "correct_answer": correct_answer,
            "explanation": explanation or f"{key} 개념을 문서 기준으로 적용하면 '{correct_answer}'이(가) 정답입니다.",
        },
    }


def _enrich_note(base: Dict[str, Any], llm_item: Any) -> Dict[str, Any]:
    """LLM 결과로 fallback note의 설명 필드를 보강(없는 키는 fallback 유지)."""
    from app.utils.sanitize import sanitize_markdown_text, sanitize_list
    if not isinstance(llm_item, dict):
        return base
    for key in ("ai_explanation", "why_user_answer_is_wrong", "review_point",
                "retry_strategy", "user_memo_reflection"):
        v = sanitize_markdown_text(llm_item.get(key))
        if v:
            base[key] = v
    kc = sanitize_list(llm_item.get("key_concepts"))
    if kc:
        base["key_concepts"] = kc
    rq = llm_item.get("retry_question")
    if isinstance(rq, dict):
        rq_question = sanitize_markdown_text(rq.get("question"))
        rq_expl = sanitize_markdown_text(rq.get("explanation"))
        rq_correct = sanitize_markdown_text(rq.get("correct_answer")) or base["retry_question"]["correct_answer"]
        rq_choices = _choices(rq.get("choices"))
        if rq_question:
            base["retry_question"]["question"] = rq_question
        if rq_expl:
            base["retry_question"]["explanation"] = rq_expl
        base["retry_question"]["correct_answer"] = rq_correct
        if rq_choices:
            base["retry_question"]["choices"] = _ensure_four_choices(rq_choices, rq_correct)
    return base


def _build_pdf_plain_text(
    material_title: str,
    difficulty: str,
    overall: str,
    notes: List[Dict[str, Any]],
    order: List[str],
    memo_map: Dict[int, str],
) -> str:
    """PDF 오답노트에 바로 넣는 마크다운 없는 평문 (섹션 순서 고정).

    제목 → 자료명 → 난이도 → 틀린 문제 수 → 전체 피드백 → 각 문제(문제/보기/내 답/정답/
    해설/틀린 이유/다시 볼 개념/재풀이 전략/메모) → 추천 복습 순서.
    """
    from app.utils.sanitize import sanitize_markdown_text
    from datetime import date

    # 의미 없는 제목 방어 (ㅇㅇ/test/sample/무제/제목없음 등) → 핵심 개념 기반 제목
    _junk = {"", "ㅇㅇ", "ㅇ", "test", "sample", "무제", "제목없음", "제목 없음", "untitled", "none", "null"}
    safe_title = (material_title or "").strip()
    if safe_title.lower() in _junk or len(safe_title) <= 1:
        kw = ""
        for n in notes:
            if n.get("key_concepts"):
                kw = n["key_concepts"][0]
                break
        safe_title = kw or "학습 자료"

    unanswered_count = sum(1 for n in notes if n.get("status") == "UNANSWERED")
    wrong_count = sum(1 for n in notes if n.get("status") != "UNANSWERED")
    review_count = len(notes)

    lines: List[str] = []
    lines.append(f"{safe_title} 오답노트")
    lines.append("=" * 32)
    lines.append(f"자료명: {safe_title}")
    lines.append(f"난이도: {difficulty}")
    lines.append(f"생성일: {date.today().isoformat()}")
    lines.append(f"오답 수: {wrong_count}")
    lines.append(f"미응답 수: {unanswered_count}")
    lines.append(f"복습 필요 수: {review_count}")
    lines.append("")
    lines.append(f"[전체 피드백]\n{overall}")
    lines.append("")
    lines.append("-" * 32)
    for n in notes:
        idx = n["index"]
        is_un = n.get("status") == "UNANSWERED"
        lines.append(f"[문제 {idx}]{' (미응답)' if is_un else ''}")
        lines.append(f"문제: {n['question']}")
        if n.get("choices"):
            lines.append("보기:")
            for ci, c in enumerate(n["choices"], start=1):
                lines.append(f"  {ci}) {c}")
        lines.append(f"내가 고른 답: {'미응답' if is_un else (n.get('user_answer') or '미응답')}")
        lines.append(f"정답: {n['correct_answer']}")
        lines.append(f"AI 해설: {n['ai_explanation']}")
        lines.append(f"내가 틀린 이유: {n['why_user_answer_is_wrong']}")
        if n.get("key_concepts"):
            lines.append(f"다시 봐야 할 개념: {', '.join(n['key_concepts'])}")
        if n.get("page"):
            lines.append(f"참고 페이지: {n['page']}p")
        lines.append(f"재풀이 전략: {n['retry_strategy']}")
        memo = memo_map.get(idx, "")
        lines.append(f"내 메모: {memo or '(메모 없음)'}")
        lines.append("-" * 32)
    if order:
        lines.append("")
        lines.append("[추천 복습 순서]")
        for i, item in enumerate(order, start=1):
            lines.append(f"{i}. {item}")
    return sanitize_markdown_text("\n".join(lines))


def _wrong_note_sync(body: Dict[str, Any]) -> Dict[str, Any]:
    from app.utils.sanitize import sanitize_markdown_text, sanitize_list
    from app.services.ai_pipeline import generate_structured, repair_to_valid

    material_id = body.get("material_id") or body.get("materialId")
    material_title = sanitize_markdown_text(body.get("material_title") or body.get("materialTitle")) or "오답노트"
    difficulty = sanitize_markdown_text(body.get("difficulty") or body.get("difficultyLabel")) or "보통"
    wrong_questions = body.get("wrong_questions") or body.get("wrongQuestions") or []
    if not isinstance(wrong_questions, list):
        wrong_questions = []
    document_context = sanitize_markdown_text(body.get("document_context") or body.get("documentContext"))

    # 1. deterministic note 먼저 구성 (LLM 실패해도 구조/길이 보장)
    notes = [_fallback_note(q if isinstance(q, dict) else {}, i + 1) for i, q in enumerate(wrong_questions)]
    memo_map = {
        i + 1: sanitize_markdown_text(q.get("user_memo") or q.get("userMemo"))
        for i, q in enumerate(wrong_questions) if isinstance(q, dict)
    }

    overall = ""
    order: List[str] = []

    def _wn_valid(d: Dict[str, Any]) -> bool:
        return (
            isinstance(d, dict)
            and isinstance(d.get("notes"), list) and len(d.get("notes")) >= 1
            and isinstance(d.get("overall_feedback"), str) and bool(d.get("overall_feedback", "").strip())
        )

    # 2. Qwen 1차 분석 → OpenAI 보강 (오답 원인/해설/재풀이 문제 품질 보강)
    if notes and not body.get("_no_llm"):
        try:
            qlines = []
            for i, q in enumerate(wrong_questions, start=1):
                if not isinstance(q, dict):
                    continue
                qlines.append(
                    f"{i}. 문제: {q.get('question')}\n   보기: {q.get('choices')}\n"
                    f"   사용자 답: {q.get('user_answer')}\n   정답: {q.get('correct_answer')}\n"
                    f"   개념: {q.get('concepts')}\n   사용자 메모: {q.get('user_memo')}"
                )
            questions_block = (
                f"## 자료: {material_title}\n## 난이도: {difficulty}\n## 문서 요약\n{document_context}\n\n"
                f"## 틀린 문제\n" + "\n".join(qlines)
            )
            schema = (
                "{\n"
                '  "overall_feedback": "전체 오답 원인 종합 2~3문장 (무엇을 잘 이해했는지/왜 틀렸는지/어떤 개념을 혼동했는지)",\n'
                '  "recommended_review_order": ["복습 순서 3개"],\n'
                '  "notes": [{"index":1, "ai_explanation":"정답이 왜 맞는지 문서 기반 설명", '
                '"why_user_answer_is_wrong":"사용자 답이 왜 부족/틀렸는지", "key_concepts":["혼동한 개념"], '
                '"review_point":"다시 볼 핵심", "retry_strategy":"다시 풀 때 확인 기준", '
                '"user_memo_reflection":"사용자 메모 기반 보완점", '
                '"retry_question":{"question":"같은 개념 재풀이 문제","choices":["1","2","3","4"],"correct_answer":"정답","explanation":"해설"}}]\n'
                "}\n"
                f"notes는 정확히 {len(notes)}개, 입력 순서대로 index를 부여한다."
            )
            draft_system = (
                "너는 오답노트 복습 코치다. 틀린 문제, 보기, 사용자 오답, 정답, 문서 context를 기반으로 "
                "오답 원인을 개념 단위로 1차 분석한다. 문서 밖 내용을 과도하게 만들지 않고, 새 단원을 가르치거나 "
                "로드맵/요약/통계 대시보드를 만들지 않는다. 반드시 한국어, 마크다운 없이 JSON으로만 응답한다."
            )
            draft_user = questions_block + "\n\n아래 JSON으로만 응답하라(마크다운/별표/해시/백틱 금지):\n" + schema
            refine_system = (
                "너는 오답노트 결과 보강기다. 1차 분석 JSON을 받아 AI 해설을 더 명확하게, 오답 원인을 구체적으로, "
                "다시 풀기 전략을 실행 가능하게 다듬고, retry_question 품질을 높이며 피드백을 균형 있게(잘한 점/왜 틀렸는지/"
                "혼동 개념/다음 풀이법) 정리한다. 새 단원·로드맵·통계는 추가하지 않는다. "
                "반드시 한국어, 마크다운 없이 같은 JSON 스키마로만 응답한다."
            )

            def _wn_refine_user(draft: Dict[str, Any]) -> str:
                import json as _json
                draft_txt = _json.dumps(draft, ensure_ascii=False) if draft else "(초안 없음 — 직접 생성)"
                return (
                    questions_block + f"\n\n## 1차 분석 초안\n{draft_txt}\n\n"
                    "위 초안을 보강해 아래 JSON으로만 응답하라(마크다운/별표/해시/백틱 금지):\n" + schema
                )

            parsed = generate_structured(
                draft_system=draft_system, draft_user=draft_user,
                refine_system=refine_system, refine_user_builder=_wn_refine_user,
                validator=_wn_valid, max_tokens=2600,
            )
            if parsed is not None and not _wn_valid(parsed):
                repaired = repair_to_valid(
                    repair_system=refine_system, repair_user=_wn_refine_user(parsed or {}),
                    validator=_wn_valid, max_tokens=2600,
                )
                if repaired:
                    parsed = repaired

            if isinstance(parsed, dict):
                overall = sanitize_markdown_text(parsed.get("overall_feedback"))
                order = sanitize_list(parsed.get("recommended_review_order"))
                llm_notes = parsed.get("notes")
                if isinstance(llm_notes, list):
                    by_index = {}
                    for it in llm_notes:
                        if isinstance(it, dict):
                            try:
                                by_index[int(it.get("index"))] = it
                            except Exception:
                                pass
                    for n in notes:
                        if n["index"] in by_index:
                            _enrich_note(n, by_index[n["index"]])
                    # index 매칭 실패 시 순서 매칭
                    if not by_index:
                        for n, it in zip(notes, llm_notes):
                            _enrich_note(n, it)
        except Exception as e:  # noqa: BLE001
            logger.info("wrong-note-feedback 파이프라인 실패, fallback 유지: %s", e)

    if not overall:
        first_concept = (notes[0]["key_concepts"][0] if notes and notes[0]["key_concepts"] else "핵심 개념")
        overall = (
            f"이번 오답은 {first_concept}의 책임 범위와 적용 맥락을 정확히 구분하지 못한 데서 발생했습니다. "
            "정의를 다시 확인하고 예제 흐름으로 연결하면 같은 실수를 줄일 수 있습니다."
        )
    if not order:
        concepts_seen: List[str] = []
        for n in notes:
            for c in n["key_concepts"]:
                if c not in concepts_seen:
                    concepts_seen.append(c)
        order = [f"{c} 정의와 책임 경계 정리" for c in concepts_seen[:3]] or ["핵심 개념 정의 복습"]

    pdf_plain_text = _build_pdf_plain_text(material_title, difficulty, overall, notes, order, memo_map)

    unanswered_count = sum(1 for n in notes if n.get("status") == "UNANSWERED")
    answered_wrong_count = len(notes) - unanswered_count
    result = {
        "material_id": material_id,
        "material_title": material_title,
        "wrong_count": len(notes),              # 하위호환: 복습 대상 총합(오답+미응답)
        "answered_wrong_count": answered_wrong_count,
        "unanswered_count": unanswered_count,
        "review_count": len(notes),             # = answered_wrong_count + unanswered_count
        "feedback_title": f"{material_title} 오답노트",
        "overall_feedback": overall,
        "wrong_notes": notes,
        "recommended_review_order": order,
        "pdf_plain_text": pdf_plain_text,
        "error_code": None,
    }
    try:
        from app.utils.ai_validators import validate_wrong_note_feedback
        if not validate_wrong_note_feedback(result, len(wrong_questions)):
            logger.warning("wrong-note-feedback 최종 검증 실패 — 응답 구조 점검 필요")
    except Exception:  # noqa: BLE001
        pass
    return result


@router.post("/wrong-note-feedback", summary="틀린 문제 오답노트 + 재풀이 문제 + PDF 평문")
async def wrong_note_feedback(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """틀린 문제 복습 관리 전용. wrong_notes 길이=wrong_questions 길이, retry_question/pdf_plain_text 보장."""
    if not isinstance(body, dict):
        body = {}
    try:
        return await asyncio.wait_for(asyncio.to_thread(_wrong_note_sync, body), timeout=FEEDBACK_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            result = _wrong_note_sync({**body, "_no_llm": True})
        except Exception:  # noqa: BLE001
            result = {"material_id": body.get("material_id"), "wrong_notes": []}
        result["error_code"] = "AI_TIMEOUT"
        return result
    except Exception as e:  # noqa: BLE001
        logger.error("wrong-note-feedback 실패: %s", e)
        return {"material_id": body.get("material_id"), "wrong_notes": [], "error_code": "WRONG_NOTE_FEEDBACK_FAILED"}


# ── B. 변형 문제 ──────────────────────────────────────────────────────────────
def _variant_sync(body: Dict[str, Any]) -> Dict[str, Any]:
    from app.utils.sanitize import sanitize_markdown_text, sanitize_list

    material_title = sanitize_markdown_text(body.get("material_title") or body.get("materialTitle")) or "학습 자료"
    original = sanitize_markdown_text(body.get("original_question") or body.get("originalQuestion"))
    correct_answer = sanitize_markdown_text(body.get("correct_answer") or body.get("correctAnswer"))
    user_wrong = sanitize_markdown_text(body.get("user_wrong_answer") or body.get("userWrongAnswer"))
    concepts = sanitize_list(body.get("concepts"))
    document_context = sanitize_markdown_text(body.get("document_context") or body.get("documentContext"))
    difficulty = str(body.get("difficulty") or "normal").strip().lower()
    if difficulty not in _VALID_DIFFICULTY:
        difficulty = "normal"

    question = ""
    choices: List[str] = []
    explanation = ""
    out_correct = correct_answer
    out_concepts = concepts

    if not body.get("_no_llm"):
        try:
            from app.services.ai_pipeline import generate_structured
            base_block = (
                f"## 자료: {material_title}\n## 문서 요약\n{document_context}\n"
                f"## 기존 문제\n{original}\n## 정답\n{correct_answer}\n## 사용자 오답\n{user_wrong}\n"
                f"## 개념\n{concepts}\n## 난이도\n{difficulty} — {_DIFFICULTY_GUIDE[difficulty]}\n\n"
            )
            schema = (
                '{ "question": "변형 문제", "choices": ["1","2","3","4"], "correct_answer": "정답", '
                '"explanation": "해설", "concepts": ["개념"] }\n'
                "choices는 정확히 4개, 그 중 하나가 정답."
            )
            draft_system = (
                "너는 오답 복습용 변형 문제 출제기다. 같은 개념을 유지하되 난이도 기준에 맞게 변형한 "
                "4지선다 문제 1개를 1차로 만든다. 반드시 한국어, 마크다운 없이 JSON으로만 응답한다."
            )
            draft_user = base_block + "아래 JSON으로만 응답하라(마크다운/별표/해시/백틱 금지):\n" + schema
            refine_system = (
                "너는 변형 문제 보강기다. 1차 문제를 받아 보기의 매력적인 오답(distractor) 품질과 해설을 "
                "난이도 기준에 맞게 개선한다. 개념은 유지하고 정답은 보기 중 하나여야 한다. "
                "반드시 한국어, 마크다운 없이 같은 JSON 스키마로만 응답한다."
            )

            def _v_refine_user(draft: Dict[str, Any]) -> str:
                import json as _json
                draft_txt = _json.dumps(draft, ensure_ascii=False) if draft else "(초안 없음 — 직접 생성)"
                return base_block + f"## 1차 문제\n{draft_txt}\n\n위 문제를 보강해 아래 JSON으로만 응답하라:\n" + schema

            def _v_valid(d: Dict[str, Any]) -> bool:
                return (
                    isinstance(d, dict) and isinstance(d.get("question"), str) and bool(d.get("question", "").strip())
                    and isinstance(d.get("choices"), list) and len([c for c in d.get("choices") if c]) >= 2
                )

            parsed = generate_structured(
                draft_system=draft_system, draft_user=draft_user,
                refine_system=refine_system, refine_user_builder=_v_refine_user,
                validator=_v_valid, max_tokens=900,
            )
            if isinstance(parsed, dict):
                question = sanitize_markdown_text(parsed.get("question"))
                choices = _choices(parsed.get("choices"))
                explanation = sanitize_markdown_text(parsed.get("explanation"))
                pc = sanitize_markdown_text(parsed.get("correct_answer"))
                if pc:
                    out_correct = pc
                pconcepts = sanitize_list(parsed.get("concepts"))
                if pconcepts:
                    out_concepts = pconcepts
        except Exception as e:  # noqa: BLE001
            logger.info("variant-question LLM 실패, fallback 사용: %s", e)

    # deterministic fallback / 보정
    key = out_concepts[0] if out_concepts else "핵심 개념"
    if not question:
        question = f"{key} 개념을 다시 확인하는 문제입니다. {original or '다음 설명 중 옳은 것은?'}"
    if not explanation:
        explanation = f"{key} 개념을 문서 기준으로 적용하면 '{out_correct}'이(가) 정답입니다."
    choices = _ensure_four_choices(choices, out_correct)
    if not out_correct:
        out_correct = choices[0]
    if not out_concepts:
        out_concepts = [key]

    return {
        "question": question,
        "choices": choices,
        "correct_answer": out_correct,
        "explanation": explanation,
        "difficulty_applied": difficulty,
        "concepts": out_concepts,
        "error_code": None,
    }


@router.post("/variant-question", summary="개념 유지·난이도 조절 변형 4지선다 문제")
async def variant_question(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """오답 복습용 변형 문제. choices 4개·correct_answer·explanation·difficulty_applied 보장."""
    if not isinstance(body, dict):
        body = {}
    try:
        return await asyncio.wait_for(asyncio.to_thread(_variant_sync, body), timeout=VARIANT_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            result = _variant_sync({**body, "_no_llm": True})
        except Exception:  # noqa: BLE001
            result = {}
        result["error_code"] = "AI_TIMEOUT"
        return result
    except Exception as e:  # noqa: BLE001
        logger.error("variant-question 실패: %s", e)
        return {"question": "", "choices": [], "error_code": "VARIANT_QUESTION_FAILED"}
