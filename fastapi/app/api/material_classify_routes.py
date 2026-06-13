"""
업로드 자료 유형 자동 판별 — 자료 추가 모달에서 파일을 올릴 때, 실제 파일 내용을
먼저 읽고 학습PDF / 플래너 / 오답노트 / 학습일지 / 알 수 없음 중 알맞은 유형을 추천한다.

  POST /api/ai/material/classify
    req:  {file_name, mime_type, selected_type, extracted_text, ocr_text,
           page_count, preview_text, metadata{title, keywords[]}}
    resp: {success, recommended_type, selected_type, is_mismatch, confidence,
           reason, user_message, allowed_actions[], capability_hint{}, error_code}

분류 전략 (E):
  1) Qwen(Ollama 주력) 1차 분류 — call_primary_llm
  2) OpenAI 보강 — call_verifier_llm (애매한 경우 type/reason/user_message 정리)
  3) 둘 다 실패하면 rule-based 키워드 분류 (F)

핵심 원칙 (C):
  - PDF에서 텍스트가 비어도 바로 STUDY_PDF 실패(PDF_TEXT_EMPTY)로 보지 않는다.
  - OCR/파일명/사용자 입력에서 플래너·오답노트 단서가 보이면 PLANNER/WRONG_NOTE로 추천한다.
  - 그래도 단서가 없으면 UNKNOWN.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai/material", tags=["Material AI (classify)"])

CLASSIFY_TIMEOUT = int(os.getenv("AI_MATERIAL_CLASSIFY_TIMEOUT_SECONDS", "45"))

# ── 유형 정의 ────────────────────────────────────────────────────────────────
VALID_TYPES = ("STUDY_PDF", "PLANNER", "WRONG_NOTE", "STUDY_LOG", "UNKNOWN")

TYPE_LABEL = {
    "STUDY_PDF": "학습PDF",
    "PLANNER": "플래너",
    "WRONG_NOTE": "오답노트",
    "STUDY_LOG": "학습일지",
    "UNKNOWN": "알 수 없음",
}

# 유형별 사용 가능 기능 힌트 (B)
CAPABILITY = {
    "STUDY_PDF": {"summary_enabled": True, "quiz_enabled": True, "roadmap_enabled": True,
                  "planner_enabled": False, "wrong_note_enabled": False},
    "PLANNER": {"summary_enabled": False, "quiz_enabled": False, "roadmap_enabled": False,
                "planner_enabled": True, "wrong_note_enabled": False},
    "WRONG_NOTE": {"summary_enabled": False, "quiz_enabled": False, "roadmap_enabled": False,
                   "planner_enabled": False, "wrong_note_enabled": True},
    "STUDY_LOG": {"summary_enabled": False, "quiz_enabled": False, "roadmap_enabled": False,
                  "planner_enabled": True, "wrong_note_enabled": False},
    "UNKNOWN": {"summary_enabled": False, "quiz_enabled": False, "roadmap_enabled": False,
                "planner_enabled": False, "wrong_note_enabled": False},
}

# rule-based 키워드 (F + B 종합). 소문자 비교.
KEYWORDS = {
    "PLANNER": [
        "공부 플래너", "학습 플래너", "플래너", "학습 계획", "학습계획표", "계획표",
        "시간표", "우선순위", "목표 학습 시간", "목표학습시간", "마감일", "마감", "d-day", "디데이",
        "과목명", "과목", "학습 목표", "학습목표", "세부 학습", "세부학습", "메모", "체크박스", "체크",
        "오늘 계획", "오늘 할 일", "할 일", "주간 계획", "주간계획", "오늘 공부 계획",
    ],
    "WRONG_NOTE": [
        "오답노트", "오답 노트", "오답", "틀린 문제", "틀린문제", "내가 고른 답", "내가 선택한 답",
        "정답", "해설", "다시 풀기", "다시풀기", "유사문제", "유사 문제", "복습", "ai 해설",
        "오답 원인", "오답원인", "문제 번호", "문항", "정답률",
    ],
    "STUDY_PDF": [
        "강의자료", "수업자료", "강의", "수업", "개념 설명", "개념", "실습", "코드", "예제",
        "아키텍처", "api", "목차", "챕터", "chapter", "이론", "슬라이드", "보고서", "문제 풀이 자료",
        "사용법", "정의", "원리",
    ],
    "STUDY_LOG": [
        "학습일지", "학습 일지", "일지", "회고", "배운 점", "배운점", "느낀 점", "느낀점",
        "오늘 공부한", "오늘 공부", "오늘 배운", "다음 목표", "학습 소감", "소감", "공부 기록",
        "학습 시간 기록", "오늘의 학습",
    ],
}


# ── 요청 모델 ────────────────────────────────────────────────────────────────
class MaterialMetadata(BaseModel):
    title: Optional[str] = ""
    keywords: Optional[List[str]] = None


class ClassifyRequest(BaseModel):
    file_name: Optional[str] = ""
    mime_type: Optional[str] = ""
    selected_type: Optional[str] = None
    extracted_text: Optional[str] = ""
    ocr_text: Optional[str] = ""
    page_count: Optional[int] = None
    preview_text: Optional[str] = ""
    metadata: Optional[MaterialMetadata] = None


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────
def _norm_type(value: Any) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    return v if v in VALID_TYPES else None


def _combined_text(req: ClassifyRequest) -> str:
    """분류에 쓸 모든 텍스트(추출/OCR/미리보기/파일명/제목/키워드)를 합친다."""
    md = req.metadata or MaterialMetadata()
    kw = " ".join(md.keywords or [])
    parts = [
        req.extracted_text or "", req.ocr_text or "", req.preview_text or "",
        req.file_name or "", md.title or "", kw,
    ]
    return "\n".join(parts).lower()


def _meaningful_len(req: ClassifyRequest) -> int:
    """본문(추출+OCR) 텍스트 길이. 빈 PDF 판단용."""
    return len((req.extracted_text or "").strip()) + len((req.ocr_text or "").strip())


def _label(t: str) -> str:
    return TYPE_LABEL.get(t, "알 수 없음")


def _build_user_message(recommended: str, selected: Optional[str], is_mismatch: bool) -> str:
    if recommended == "UNKNOWN":
        return "파일 유형을 확실히 판단하기 어렵습니다. 알맞은 곳에 넣으세요."
    if is_mismatch and selected:
        return (f"이 파일은 {_label(selected)}가 아니라 {_label(recommended)}로 보입니다. "
                "알맞은 곳에 넣으세요.")
    return f"이 파일은 {_label(recommended)}로 보입니다. 그대로 저장하면 됩니다."


def _build_allowed_actions(recommended: str, selected: Optional[str]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    if recommended != "UNKNOWN":
        actions.append({"label": f"{_label(recommended)}로 저장", "type": recommended, "recommended": True})
    # 선택 유형이 추천과 다르고 유효하면 "그래도 ~로 저장" 제공
    if selected and selected != recommended and selected in VALID_TYPES and selected != "UNKNOWN":
        actions.append({"label": f"그래도 {_label(selected)}로 저장", "type": selected, "recommended": False})
    actions.append({"label": "취소", "type": "CANCEL", "recommended": False})
    return actions


# ── rule-based fallback (F) ──────────────────────────────────────────────────
def _rule_based_classify(req: ClassifyRequest) -> Dict[str, Any]:
    text = _combined_text(req)
    fname = (req.file_name or "").lower()
    title = ((req.metadata.title if req.metadata else "") or "").lower()

    scores: Dict[str, int] = {}
    for t, kws in KEYWORDS.items():
        s = 0
        for kw in kws:
            if kw in text:
                s += 1
                # 파일명·제목에 직접 등장하면 강한 신호 → 가중치
                if kw in fname or kw in title:
                    s += 2
        scores[t] = s

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_type, top_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0

    # 단서가 전혀 없는 경우
    if top_score == 0:
        # 본문이 빈약한 빈 PDF지만 단서도 없음 → UNKNOWN (C-6)
        return {"type": "UNKNOWN", "confidence": 0.3,
                "reason": "추출 텍스트와 OCR, 파일명/입력값에서 유형을 판단할 단서를 찾지 못했습니다.",
                "scores": scores}

    confidence = min(0.93, 0.6 + 0.08 * (top_score - second_score) + 0.02 * top_score)
    reason = (f"'{_label(top_type)}' 관련 키워드가 다른 유형보다 우세하게 나타나 "
              f"{_label(top_type)}로 판단했습니다.")
    return {"type": top_type, "confidence": round(confidence, 2), "reason": reason, "scores": scores}


# ── Qwen 1차 분류 (E) ────────────────────────────────────────────────────────
def _classify_prompt(req: ClassifyRequest) -> tuple[str, str]:
    md = req.metadata or MaterialMetadata()
    body = (req.extracted_text or "")[:3000]
    ocr = (req.ocr_text or "")[:1500]
    system = (
        "너는 업로드된 학습 자료 파일의 유형을 판별하는 분류기다. "
        "파일 내용을 보고 다음 다섯 중 하나로만 분류한다: "
        "STUDY_PDF(강의/개념/이론/코드/슬라이드 등 학습 자료), "
        "PLANNER(공부 계획표/시간표/우선순위/목표 학습 시간/빈 양식 등), "
        "WRONG_NOTE(오답노트/틀린 문제/정답·해설/다시 풀기 등), "
        "STUDY_LOG(학습일지/회고/배운 점/느낀 점/오늘 공부 기록 등), "
        "UNKNOWN(텍스트가 거의 없고 단서도 없을 때). "
        "텍스트가 비어도 곧바로 STUDY_PDF로 단정하지 말고, 표/시간표/날짜/과목/목표 학습 시간 단서가 "
        "있으면 PLANNER, 문제/정답/해설 구조가 보이면 WRONG_NOTE로 분류하라. "
        "반드시 한국어로, 마크다운 없이 JSON 한 개로만 응답한다."
    )
    user = (
        f"## 파일명\n{req.file_name}\n"
        f"## MIME\n{req.mime_type}\n"
        f"## 페이지 수\n{req.page_count}\n"
        f"## 사용자 입력 제목\n{md.title}\n"
        f"## 사용자 입력 키워드\n{', '.join(md.keywords or [])}\n"
        f"## 추출 텍스트(앞부분)\n{body}\n"
        f"## OCR 텍스트(앞부분)\n{ocr}\n\n"
        "아래 JSON 형식으로만 응답하라(설명/마크다운 금지):\n"
        '{ "type": "STUDY_PDF|PLANNER|WRONG_NOTE|STUDY_LOG|UNKNOWN", '
        '"confidence": 0.0~1.0, "reason": "판단 근거 한국어 1~2문장" }'
    )
    return system, user


def _qwen_classify(req: ClassifyRequest) -> Optional[Dict[str, Any]]:
    from app.services.llm_engine_router import call_primary_llm
    from app.utils.json_parser import extract_json

    system, user = _classify_prompt(req)
    try:
        raw = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=400, temperature=0.1)
    except Exception as e:
        logger.info("Qwen 분류 실패: %s", e)
        return None
    if not raw or raw.strip().startswith("["):
        return None
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    t = _norm_type(parsed.get("type"))
    if not t:
        return None
    try:
        conf = float(parsed.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7
    return {"type": t, "confidence": max(0.0, min(1.0, conf)),
            "reason": str(parsed.get("reason") or "").strip()}


# ── OpenAI 보강 (E) ──────────────────────────────────────────────────────────
def _openai_refine(req: ClassifyRequest, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """애매한 후보를 GPT로 보강 — type 재확인 + reason 자연스럽게 정리."""
    from app.services.llm_engine_router import call_verifier_llm
    from app.utils.json_parser import extract_json

    md = req.metadata or MaterialMetadata()
    system = (
        "너는 학습 자료 유형 분류 결과를 검수·보정하는 검토자다. "
        "후보 분류가 타당한지 파일 내용으로 재확인하고, 필요하면 더 알맞은 유형으로 바로잡는다. "
        "유형은 STUDY_PDF, PLANNER, WRONG_NOTE, STUDY_LOG, UNKNOWN 중 하나. "
        "reason은 사용자가 이해하기 쉽게 한국어 1~2문장으로 정리한다. JSON으로만 응답한다."
    )
    user = (
        f"## 후보 분류\n{candidate.get('type')} (confidence={candidate.get('confidence')})\n"
        f"## 후보 근거\n{candidate.get('reason')}\n"
        f"## 파일명\n{req.file_name}\n"
        f"## 사용자 입력 제목\n{md.title}\n"
        f"## 추출 텍스트(앞부분)\n{(req.extracted_text or '')[:2000]}\n"
        f"## OCR 텍스트(앞부분)\n{(req.ocr_text or '')[:1000]}\n\n"
        "아래 JSON으로만 응답하라(마크다운 금지):\n"
        '{ "type": "STUDY_PDF|PLANNER|WRONG_NOTE|STUDY_LOG|UNKNOWN", '
        '"confidence": 0.0~1.0, "reason": "정리된 한국어 근거 1~2문장" }'
    )
    try:
        raw = call_verifier_llm(system_prompt=system, user_prompt=user, max_tokens=400)
    except Exception as e:
        logger.info("OpenAI 보강 실패: %s", e)
        return None
    if not raw or raw.strip().startswith("[GPT") or raw.strip().startswith("["):
        return None
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    t = _norm_type(parsed.get("type"))
    if not t:
        return None
    try:
        conf = float(parsed.get("confidence", candidate.get("confidence", 0.7)))
    except (TypeError, ValueError):
        conf = float(candidate.get("confidence", 0.7))
    return {"type": t, "confidence": max(0.0, min(1.0, conf)),
            "reason": str(parsed.get("reason") or candidate.get("reason") or "").strip()}


# ── 분류 본체 ────────────────────────────────────────────────────────────────
def _classify_sync(req: ClassifyRequest) -> Dict[str, Any]:
    # 0) rule-based는 항상 계산 — LLM 실패 시 fallback이자 신뢰 하한선
    rule = _rule_based_classify(req)
    final = {"type": rule["type"], "confidence": rule["confidence"], "reason": rule["reason"]}

    # 1) Qwen 1차 분류
    qwen = _qwen_classify(req)
    if qwen:
        final = qwen

    # 2) OpenAI 보강 (Qwen 결과가 있을 때만 의미 있음; Qwen 실패 시 rule 결과 보강도 허용)
    refined = _openai_refine(req, final)
    if refined:
        final = refined

    # 3) 빈 PDF 보정 (C): 본문이 거의 없는데 STUDY_PDF로 나왔고 단서가 약하면
    #    PLANNER/WRONG_NOTE 단서를 우선, 둘 다 없으면 UNKNOWN으로 낮춘다.
    if final["type"] == "STUDY_PDF" and _meaningful_len(req) < 30:
        scores = rule.get("scores", {})
        if scores.get("PLANNER", 0) > 0:
            final = {"type": "PLANNER", "confidence": 0.7,
                     "reason": "추출 텍스트가 거의 없지만 시간표/날짜/목표 학습 시간 등 플래너 양식 단서가 있어 플래너로 판단했습니다."}
        elif scores.get("WRONG_NOTE", 0) > 0:
            final = {"type": "WRONG_NOTE", "confidence": 0.7,
                     "reason": "추출 텍스트가 거의 없지만 문제/정답/해설 등 오답노트 단서가 있어 오답노트로 판단했습니다."}
        else:
            final = {"type": "UNKNOWN", "confidence": 0.3,
                     "reason": "PDF에서 추출된 텍스트가 거의 없고 다른 유형 단서도 찾지 못했습니다."}

    recommended = final["type"]
    selected = _norm_type(req.selected_type)
    is_mismatch = bool(selected) and selected != recommended

    response = {
        "success": True,
        "recommended_type": recommended,
        "selected_type": selected,
        "is_mismatch": is_mismatch,
        "confidence": round(float(final["confidence"]), 2),
        "reason": final["reason"] or f"{_label(recommended)}로 판단했습니다.",
        "user_message": _build_user_message(recommended, selected, is_mismatch),
        "allowed_actions": _build_allowed_actions(recommended, selected),
        "capability_hint": dict(CAPABILITY.get(recommended, CAPABILITY["UNKNOWN"])),
        "error_code": None,
    }
    return response


# ── 검증 (G) ─────────────────────────────────────────────────────────────────
def validate_material_classification(response: Dict[str, Any]) -> bool:
    """응답이 계약을 만족하는지 검증한다. 마크다운 잔여물도 거른다."""
    required = ["recommended_type", "selected_type", "is_mismatch", "confidence",
                "reason", "user_message", "allowed_actions", "capability_hint"]
    for key in required:
        if key not in response:
            return False
    if response["recommended_type"] not in VALID_TYPES:
        return False
    if not isinstance(response["allowed_actions"], list) or not response["allowed_actions"]:
        return False
    if not isinstance(response["capability_hint"], dict):
        return False
    for field in ("reason", "user_message"):
        val = response.get(field) or ""
        if any(mark in val for mark in ("**", "```", "###")):
            return False
    return True


# ── 엔드포인트 ───────────────────────────────────────────────────────────────
@router.post("/classify", summary="업로드 자료 유형 자동 판별")
async def classify_material(req: ClassifyRequest) -> Dict[str, Any]:
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_classify_sync, req), timeout=CLASSIFY_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("material/classify 타임아웃")
        return _fallback_response(req, "AI_TIMEOUT")
    except Exception as e:
        logger.error("material/classify 실패: %s", e)
        return _fallback_response(req, "CLASSIFY_FAILED")

    if not validate_material_classification(result):
        logger.warning("material/classify 검증 실패 → rule-based fallback")
        return _fallback_response(req, None)
    return result


def _fallback_response(req: ClassifyRequest, error_code: Optional[str]) -> Dict[str, Any]:
    """LLM/검증 실패 시 rule-based만으로 안전한 응답을 구성한다."""
    rule = _rule_based_classify(req)
    recommended = rule["type"]
    selected = _norm_type(req.selected_type)
    is_mismatch = bool(selected) and selected != recommended
    return {
        "success": error_code is None,
        "recommended_type": recommended,
        "selected_type": selected,
        "is_mismatch": is_mismatch,
        "confidence": round(float(rule["confidence"]), 2),
        "reason": rule["reason"],
        "user_message": _build_user_message(recommended, selected, is_mismatch),
        "allowed_actions": _build_allowed_actions(recommended, selected),
        "capability_hint": dict(CAPABILITY.get(recommended, CAPABILITY["UNKNOWN"])),
        "error_code": error_code,
    }
