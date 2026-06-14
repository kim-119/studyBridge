"""
자료보관함 통합 AI — 자료 자동 분류 / 오답노트 유사문제 / 오답노트 AI 해설.

EC2(Spring/React)는 자료보관함 UI·DB를 담당하고, AI07은 내용 분석과 AI 생성 품질을
담당한다. 본 모듈은 Spring classify-before-save 및 오답노트 상세 화면이 호출하는
계약(camelCase JSON)을 그대로 구현한다. 기존 /api/ai/material/classify,
/api/ai/review/* (snake_case) 경로와는 별개의 신규 계약 경로다.

  POST /api/ai/material-classify            자료 자동 분류 (deterministic + LLM 보조)
  POST /api/ai/review-note/similar-question  오답노트 유사문제 생성 (원본 오답+PDF 근거)
  POST /api/ai/review-note/explanation       오답노트 AI 해설 생성 (왜 틀렸는지/왜 맞는지)

원칙:
  - 분류는 deterministic scoring 우선, 애매할 때만 LLM 보조.
  - 유사문제/해설은 반드시 검증 후 반환. 실패를 숨기지 않고 명확한 error code 반환.
  - markdown code fence/JSON 외 텍스트/빈 결과를 성공으로 반환하지 않는다.
"""
import asyncio
import difflib
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Review Note AI (contract)"])

CLASSIFY_TIMEOUT = int(os.getenv("AI_MATERIAL_CLASSIFY_TIMEOUT_SECONDS", "45"))
SIMILAR_TIMEOUT = int(os.getenv("AI_REVIEW_SIMILAR_TIMEOUT_SECONDS", "90"))
EXPLAIN_TIMEOUT = int(os.getenv("AI_REVIEW_EXPLANATION_TIMEOUT_SECONDS", "90"))

# ── MaterialType (계약: STUDY_LOG / STUDY_PDF / PLANNER / REVIEW_NOTE) ─────────
MATERIAL_TYPES = ("STUDY_LOG", "STUDY_PDF", "PLANNER", "REVIEW_NOTE")

# 토큰 추출: 영문/숫자 식별자(implementation 등) + 2자 이상 한글
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]{2,}")
# [로드맵 N주차 M일] 패턴 — 플래너의 매우 강한 신호
_ROADMAP_TITLE_RE = re.compile(r"\[\s*로드맵\s*\d+\s*주차.*?\d+\s*일")


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────
def _clean(value: Any) -> str:
    """사용자 표시 텍스트에서 마크다운/HTML 잔여물 제거 (sanitize 재사용)."""
    from app.utils.sanitize import sanitize_markdown_text
    return sanitize_markdown_text(value)


def _keywords(text: str) -> set:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}


def _significant(words: set) -> set:
    """근거 매칭에 의미 있는 토큰(4자 이상 한글 또는 영문/숫자 식별자)."""
    return {w for w in words if len(w) >= 4 or re.fullmatch(r"[a-z0-9_]+", w)}


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def _log(endpoint: str, *, request_id: str = "", material_id: Any = None,
         review_note_id: Any = None, difficulty: str = "", source_len: int = 0,
         elapsed_ms: int = 0, error_code: Optional[str] = None,
         validation_reason: Optional[str] = None) -> None:
    logger.info(
        "[%s] requestId=%s materialId=%s reviewNoteId=%s difficulty=%s "
        "sourceTextLength=%d elapsedMs=%d errorCode=%s validationFailureReason=%s",
        endpoint, request_id, material_id, review_note_id, difficulty,
        source_len, elapsed_ms, error_code, validation_reason,
    )


# ════════════════════════════════════════════════════════════════════════════
# [1] 자료 자동 분류 — POST /api/ai/material-classify
# ════════════════════════════════════════════════════════════════════════════
class ClassifyMetadata(BaseModel):
    mimeType: Optional[str] = ""
    pageCount: Optional[int] = None
    userSelectedType: Optional[str] = None


class MaterialClassifyRequest(BaseModel):
    requestId: Optional[str] = ""
    title: Optional[str] = ""
    fileName: Optional[str] = ""
    textPreview: Optional[str] = ""
    metadata: Optional[ClassifyMetadata] = None


# 가중치 키워드 — (키워드, 가중치). 본문 키워드가 mime baseline보다 우세하도록 설계.
_CLASSIFY_KEYWORDS: Dict[str, List[Tuple[str, float]]] = {
    "REVIEW_NOTE": [
        ("오답노트", 2.5), ("오답 노트", 2.5), ("틀린 문제 수", 2.5), ("틀린 문제", 1.5),
        ("내가 고른 답", 2.5), ("내가 선택한 답", 2.0), ("ai 해설", 2.5), ("전체 피드백", 2.0),
        ("다시 풀기", 2.0), ("다시풀기", 2.0), ("유사문제", 2.0), ("유사 문제", 2.0),
        ("useranswer", 2.0), ("correctanswer", 2.0), ("reviewnoteid", 2.0),
        ("quizquestionid", 2.0), ("clientquestionid", 2.0), ("explanation", 1.5),
        ("정답", 1.0), ("해설", 1.0), ("오답", 1.0),
    ],
    "PLANNER": [
        ("플래너", 2.5), ("학습 계획", 2.0), ("학습계획", 2.0), ("로드맵", 1.5), ("주차", 1.0),
        ("일차", 1.0), ("할 일", 1.0), ("할일", 1.0), ("체크리스트", 1.5), ("duedate", 1.5),
        ("completed", 1.0), ("완료", 0.8), ("계획표", 1.5), ("시간표", 1.2), ("우선순위", 1.0),
    ],
    "STUDY_PDF": [
        ("강의자료", 2.0), ("수업자료", 2.0), ("강의", 1.0), ("목차", 1.2), ("챕터", 1.2),
        ("chapter", 1.2), ("슬라이드", 1.2), ("개념 설명", 1.0), ("이론", 1.0), ("예제", 0.8),
        ("아키텍처", 1.0), ("실습", 0.8), ("원리", 0.8), ("정의", 0.6),
    ],
    "STUDY_LOG": [
        ("학습일지", 2.5), ("학습 일지", 2.5), ("오늘 학습", 1.5), ("오늘의 학습", 1.5),
        ("회고", 1.8), ("느낀 점", 1.8), ("느낀점", 1.8), ("배운 점", 1.5), ("공부 시간", 1.2),
        ("날짜별 기록", 1.5), ("개선점", 1.5), ("학습 소감", 1.5), ("오늘 공부", 1.2),
    ],
}


def _classify_text(req: MaterialClassifyRequest) -> str:
    md = req.metadata or ClassifyMetadata()
    parts = [req.title or "", req.fileName or "", req.textPreview or "",
             md.userSelectedType or ""]
    return "\n".join(parts).lower()


def _norm_material_type(value: Any) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    # 기존 시스템 호환: WRONG_NOTE → REVIEW_NOTE
    if v == "WRONG_NOTE":
        v = "REVIEW_NOTE"
    return v if v in MATERIAL_TYPES else None


def _deterministic_classify(req: MaterialClassifyRequest) -> Dict[str, Any]:
    """가중 키워드 스코어링. (type, confidence, reasons, scores) 반환."""
    text = _classify_text(req)
    md = req.metadata or ClassifyMetadata()

    scores: Dict[str, float] = {t: 0.0 for t in MATERIAL_TYPES}
    reasons: Dict[str, List[str]] = {t: [] for t in MATERIAL_TYPES}

    for mtype, kws in _CLASSIFY_KEYWORDS.items():
        for kw, weight in kws:
            if kw in text:
                scores[mtype] += weight
                reasons[mtype].append(kw)

    # [로드맵 N주차 M일] 제목은 플래너의 결정적 신호
    if _ROADMAP_TITLE_RE.search(req.title or "") or _ROADMAP_TITLE_RE.search(req.fileName or ""):
        scores["PLANNER"] += 4.0
        reasons["PLANNER"].append("[로드맵 N주차 M일]")

    # PDF mime/pageCount → STUDY_PDF baseline (단, 본문 키워드보다 약하게)
    mime = (md.mimeType or "").lower()
    if "pdf" in mime:
        scores["STUDY_PDF"] += 1.0
        reasons["STUDY_PDF"].append("application/pdf")
    if md.pageCount and md.pageCount >= 3:
        scores["STUDY_PDF"] += 0.5
        reasons["STUDY_PDF"].append(f"pageCount={md.pageCount}")

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_type, top_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0
    margin = top_score - second_score

    if top_score <= 0:
        # 단서 없음 → 가장 안전한 후보(STUDY_PDF가 PDF면, 아니면 STUDY_PDF 기본) + 낮은 confidence
        safe = "STUDY_PDF"
        return {"materialType": safe, "confidence": 0.40,
                "reasons": ["판단 단서 부족"], "scores": scores}

    confidence = min(0.98, 0.45 + 0.10 * top_score + 0.10 * margin)
    return {"materialType": top_type, "confidence": round(confidence, 2),
            "reasons": reasons[top_type][:6] or [top_type], "scores": scores}


def _llm_classify(req: MaterialClassifyRequest, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """애매한 경우(0.45~0.75)에만 LLM 보조 판단."""
    from app.services.llm_engine_router import call_primary_llm
    from app.utils.json_parser import extract_json

    md = req.metadata or ClassifyMetadata()
    system = (
        "너는 업로드된 학습 자료의 유형을 판별하는 분류기다. "
        "다음 넷 중 하나로만 분류한다: "
        "STUDY_PDF(강의/개념/이론/슬라이드 등 학습 자료), "
        "PLANNER(학습 계획/로드맵/주차·일차/할 일/체크리스트), "
        "REVIEW_NOTE(오답노트/틀린 문제/정답·내가 고른 답/AI 해설/다시 풀기), "
        "STUDY_LOG(학습일지/회고/느낀 점/오늘 학습 기록). "
        "오답노트 구조(정답/내가 고른 답/AI 해설)가 보이면 PDF여도 REVIEW_NOTE로, "
        "[로드맵 N주차 M일] 제목은 PLANNER로 분류하라. "
        "반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다."
    )
    user = (
        f"## 제목\n{req.title}\n## 파일명\n{req.fileName}\n"
        f"## MIME\n{md.mimeType}\n## 페이지 수\n{md.pageCount}\n"
        f"## 미리보기 텍스트\n{(req.textPreview or '')[:2500]}\n\n"
        "아래 JSON으로만 응답하라(설명/마크다운 금지):\n"
        '{ "materialType": "STUDY_PDF|PLANNER|REVIEW_NOTE|STUDY_LOG", '
        '"confidence": 0.0~1.0, "reasons": ["근거 키워드 또는 짧은 사유"] }'
    )
    try:
        raw = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=350, temperature=0.1)
    except Exception as e:  # noqa: BLE001
        logger.info("classify LLM 보조 실패: %s", e)
        return None
    if not raw or raw.strip().startswith("["):
        return None
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    t = _norm_material_type(parsed.get("materialType") or parsed.get("type"))
    if not t:
        return None
    try:
        conf = float(parsed.get("confidence", candidate.get("confidence", 0.6)))
    except (TypeError, ValueError):
        conf = float(candidate.get("confidence", 0.6))
    rs = parsed.get("reasons")
    reasons = [str(x) for x in rs if str(x).strip()] if isinstance(rs, list) else []
    return {"materialType": t, "confidence": max(0.0, min(1.0, conf)),
            "reasons": reasons or candidate.get("reasons", [])}


def validate_classification(resp: Dict[str, Any]) -> Optional[str]:
    """계약 검증. 통과 시 None, 실패 시 사유 문자열."""
    if resp.get("materialType") not in MATERIAL_TYPES:
        return "materialType invalid"
    conf = resp.get("confidence")
    if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
        return "confidence out of range"
    if not isinstance(resp.get("reasons"), list) or not resp.get("reasons"):
        return "reasons missing"
    return None


def _classify_sync(req: MaterialClassifyRequest) -> Dict[str, Any]:
    det = _deterministic_classify(req)
    mode = "DETERMINISTIC"
    final = {"materialType": det["materialType"], "confidence": det["confidence"],
             "reasons": det["reasons"]}

    conf = det["confidence"]
    if 0.45 <= conf < 0.75:
        # 애매한 구간만 LLM 보조
        llm = _llm_classify(req, det)
        if llm:
            mode = "DETERMINISTIC_PLUS_LLM"
            final = llm
    # conf >= 0.75 → deterministic 그대로, conf < 0.45 → 안전 후보 + 낮은 confidence 그대로

    meta: Dict[str, Any] = {"requestId": req.requestId or "", "mode": mode}

    # userSelectedType 우선 처리
    md = req.metadata or ClassifyMetadata()
    user_sel = _norm_material_type(md.userSelectedType)
    if user_sel:
        meta["userOverride"] = True
        meta["mode"] = "USER_OVERRIDE"
        meta["aiSuggestedType"] = final["materialType"]
        final["materialType"] = user_sel
        final["confidence"] = max(final["confidence"], 0.99)
        final.setdefault("reasons", [])
        final["reasons"] = [f"사용자 지정 유형({user_sel}) 우선"] + final["reasons"]

    return {
        "materialType": final["materialType"],
        "confidence": round(float(final["confidence"]), 2),
        "reasons": final.get("reasons") or [final["materialType"]],
        "meta": meta,
    }


@router.post("/api/ai/material-classify", summary="자료 자동 분류 (deterministic + LLM 보조)")
async def material_classify(req: MaterialClassifyRequest):
    started = time.time()
    src_len = len(req.textPreview or "")
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_classify_sync, req), timeout=CLASSIFY_TIMEOUT)
    except asyncio.TimeoutError:
        # 분류는 deterministic으로도 항상 답을 낼 수 있으므로 timeout 시 deterministic만 사용
        try:
            det = _deterministic_classify(req)
            result = {
                "materialType": det["materialType"],
                "confidence": round(float(det["confidence"]), 2),
                "reasons": det["reasons"] or [det["materialType"]],
                "meta": {"requestId": req.requestId or "", "mode": "DETERMINISTIC"},
            }
        except Exception as e:  # noqa: BLE001
            logger.error("material-classify deterministic fallback 실패: %s", e)
            _log("material-classify", request_id=req.requestId or "", source_len=src_len,
                 elapsed_ms=int((time.time() - started) * 1000),
                 error_code="MATERIAL_CLASSIFY_FAILED", validation_reason="timeout+fallback")
            return _error("MATERIAL_CLASSIFY_FAILED", "자료 유형 분류에 실패했습니다.", 500)
    except Exception as e:  # noqa: BLE001
        logger.error("material-classify 실패: %s", e)
        _log("material-classify", request_id=req.requestId or "", source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="MATERIAL_CLASSIFY_FAILED", validation_reason=str(e))
        return _error("MATERIAL_CLASSIFY_FAILED", "자료 유형 분류에 실패했습니다.", 500)

    reason = validate_classification(result)
    if reason:
        _log("material-classify", request_id=req.requestId or "", source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="AI_RESPONSE_CONTRACT_VIOLATION", validation_reason=reason)
        return _error("AI_RESPONSE_CONTRACT_VIOLATION", "AI 응답 형식이 올바르지 않습니다.", 422)

    _log("material-classify", request_id=req.requestId or "", source_len=src_len,
         elapsed_ms=int((time.time() - started) * 1000), error_code=None)
    return result


# ════════════════════════════════════════════════════════════════════════════
# [2] 오답노트 유사문제 생성 — POST /api/ai/review-note/similar-question
# ════════════════════════════════════════════════════════════════════════════
class SimilarQuestionRequest(BaseModel):
    requestId: Optional[str] = ""
    materialId: Optional[int] = None
    sourceMaterialId: Optional[int] = None
    reviewNoteId: Optional[int] = None
    questionText: str = ""
    options: List[str] = Field(default_factory=list)
    correctAnswer: str = ""
    userAnswer: Optional[str] = ""
    explanation: Optional[str] = ""
    difficulty: str = "normal"
    sourceText: Optional[str] = ""


_GENERIC_QUESTION_MARKERS = ("세부 핵심 내용", "핵심 개념은 무엇인가")
_GENERIC_ABSTRACT = ("다음 중 올바른 것은", "다음 중 옳은 것은", "다음 중 알맞은 것은")


def _is_generic_question(q: str) -> bool:
    ql = (q or "").replace(" ", "")
    for g in _GENERIC_QUESTION_MARKERS:
        if g.replace(" ", "") in ql:
            return True
    core = ql
    matched_abstract = False
    for a in _GENERIC_ABSTRACT:
        a2 = a.replace(" ", "")
        if a2 in core:
            matched_abstract = True
            core = core.replace(a2, "")
    core = core.replace("?", "").replace(".", "").replace("무엇인가", "")
    if matched_abstract and len(core) < 6:
        return True
    return False


def validate_similar_question(resp: Dict[str, Any], req: SimilarQuestionRequest) -> Optional[str]:
    """유사문제 계약 검증. 통과 시 None, 실패 시 사유."""
    q = (resp.get("questionText") or "").strip()
    if not q:
        return "questionText empty"
    opts = resp.get("options")
    if not isinstance(opts, list) or len(opts) != 4:
        return f"options length != 4 (got {len(opts) if isinstance(opts, list) else 'N/A'})"
    if any(not str(o).strip() for o in opts):
        return "options contain empty"
    if len(set(o.strip() for o in opts)) != 4:
        return "options not distinct"
    correct = (resp.get("correctAnswer") or "").strip()
    if not correct:
        return "correctAnswer empty"
    if correct not in [str(o).strip() for o in opts]:
        return "correctAnswer not in options"
    if not (resp.get("explanation") or "").strip():
        return "explanation empty"
    if (resp.get("difficulty") or "") != req.difficulty:
        return "difficulty changed"
    # 원본 복붙 reject
    ratio = difflib.SequenceMatcher(None, q, (req.questionText or "")).ratio()
    if ratio > 0.85:
        return f"too similar to original ({ratio:.2f})"
    # generic reject
    if _is_generic_question(q):
        return "generic question"
    # sourceText/explanation 근거 overlap 요구
    basis = _significant(_keywords(req.sourceText or "") | _keywords(req.explanation or ""))
    if basis:
        gen = _keywords(q + " " + (resp.get("explanation") or ""))
        if not (basis & gen):
            return "no overlap with sourceText/explanation"
    return None


def _gen_similar(req: SimilarQuestionRequest) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """유사문제 생성: generate_structured → repair → 재시도. (result, fail_reason)."""
    from app.services.ai_pipeline import generate_structured, repair_to_valid

    base_block = (
        f"## 원본 문제\n{req.questionText}\n"
        f"## 원본 보기\n{req.options}\n"
        f"## 정답\n{req.correctAnswer}\n"
        f"## 사용자가 고른 오답\n{req.userAnswer}\n"
        f"## 원본 해설\n{req.explanation}\n"
        f"## PDF 근거(sourceText)\n{(req.sourceText or '')[:2500]}\n"
        f"## 난이도(고정)\n{req.difficulty}\n\n"
    )
    schema = (
        '{ "questionText": "원본과 같은 개념을 다른 맥락으로 묻는 새 문제", '
        '"options": ["보기1","보기2","보기3","보기4"], '
        '"correctAnswer": "options 중 정확히 하나와 동일", '
        '"explanation": "왜 그 보기가 정답인지 PDF 근거 기반 해설" }\n'
        "options는 정확히 4개, 그 중 하나가 correctAnswer와 글자까지 동일해야 한다. "
        "원본 문제를 복붙하거나 단어만 바꾸지 말고, 같은 개념을 다른 상황/코드/맥락에 적용하라. "
        "PDF sourceText 또는 원본 해설의 핵심 개념을 반드시 활용하고, 외부 일반 지식으로 확장하지 마라."
    )
    draft_system = (
        "너는 오답 복습용 유사문제 출제기다. 원본 오답과 같은 핵심 개념을 다른 맥락으로 묻는 "
        "4지선다 문제 1개를 만든다. 사용자가 고른 오답의 오개념을 겨냥한 매력적인 distractor를 "
        "구성한다. 반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다."
    )
    draft_user = base_block + "아래 JSON으로만 응답하라(마크다운/별표/해시/백틱 금지):\n" + schema
    refine_system = (
        "너는 유사문제 보강기다. 1차 문제를 받아 개념 정확성, distractor 품질, 해설을 다듬는다. "
        "개념과 난이도는 유지하고 correctAnswer는 반드시 options 중 하나와 글자까지 동일해야 하며 "
        "options는 정확히 4개여야 한다. 반드시 한국어, 마크다운 없이 같은 JSON 스키마로만 응답한다."
    )

    def _refine_user(draft: Dict[str, Any]) -> str:
        import json as _json
        draft_txt = _json.dumps(draft, ensure_ascii=False) if draft else "(초안 없음 — 직접 생성)"
        return base_block + f"## 1차 문제\n{draft_txt}\n\n위 문제를 보강해 아래 JSON으로만 응답하라:\n" + schema

    def _normalize(parsed: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(parsed, dict):
            return None
        opts_raw = parsed.get("options")
        options = [_clean(o) for o in opts_raw if str(o).strip()] if isinstance(opts_raw, list) else []
        out = {
            "questionText": _clean(parsed.get("questionText") or parsed.get("question")),
            "options": options,
            "correctAnswer": _clean(parsed.get("correctAnswer") or parsed.get("correct_answer")),
            "explanation": _clean(parsed.get("explanation")),
            "difficulty": req.difficulty,  # 난이도는 항상 요청값으로 고정
        }
        return out

    def _pass(parsed: Any) -> bool:
        norm = _normalize(parsed)
        return norm is not None and validate_similar_question(norm, req) is None

    # 1차: Qwen 초안 → OpenAI 보강
    parsed = generate_structured(
        draft_system=draft_system, draft_user=draft_user,
        refine_system=refine_system, refine_user_builder=_refine_user,
        validator=_pass, max_tokens=1100,
    )
    norm = _normalize(parsed)
    if norm and validate_similar_question(norm, req) is None:
        return norm, None

    # 2차: JSON repair 1회
    repaired = repair_to_valid(
        repair_system=refine_system, repair_user=_refine_user(parsed or {}),
        validator=_pass, max_tokens=1100,
    )
    rnorm = _normalize(repaired)
    if rnorm and validate_similar_question(rnorm, req) is None:
        return rnorm, None

    # 3차: LLM 재시도 1회 (제약 강조)
    retry = generate_structured(
        draft_system=draft_system,
        draft_user=draft_user + "\n주의: options는 반드시 4개, correctAnswer는 options 중 하나와 정확히 동일, "
                                "원본 문제 복붙 금지, PDF 근거 핵심어 포함.",
        refine_system=refine_system, refine_user_builder=_refine_user,
        validator=_pass, max_tokens=1100,
    )
    tnorm = _normalize(retry)
    if tnorm and validate_similar_question(tnorm, req) is None:
        return tnorm, None

    fail_reason = validate_similar_question(tnorm or rnorm or norm or {}, req) if (tnorm or rnorm or norm) else "no parseable JSON"
    return None, fail_reason


@router.post("/api/ai/review-note/similar-question", summary="오답노트 유사문제 생성")
async def review_note_similar_question(req: SimilarQuestionRequest):
    started = time.time()
    src_len = len(req.sourceText or "")
    if not (req.questionText or "").strip() or not (req.correctAnswer or "").strip():
        _log("similar-question", request_id=req.requestId or "", material_id=req.materialId,
             review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="AI_RESPONSE_CONTRACT_VIOLATION", validation_reason="missing questionText/correctAnswer")
        return _error("AI_RESPONSE_CONTRACT_VIOLATION", "AI 응답 형식이 올바르지 않습니다.", 422)
    try:
        result, fail = await asyncio.wait_for(
            asyncio.to_thread(_gen_similar, req), timeout=SIMILAR_TIMEOUT)
    except asyncio.TimeoutError:
        _log("similar-question", request_id=req.requestId or "", material_id=req.materialId,
             review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="SIMILAR_QUESTION_GENERATION_FAILED", validation_reason="timeout")
        return _error("SIMILAR_QUESTION_GENERATION_FAILED", "유사문제 생성에 실패했습니다.", 504)
    except Exception as e:  # noqa: BLE001
        logger.error("similar-question 실패: %s", e)
        _log("similar-question", request_id=req.requestId or "", material_id=req.materialId,
             review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="SIMILAR_QUESTION_GENERATION_FAILED", validation_reason=str(e))
        return _error("SIMILAR_QUESTION_GENERATION_FAILED", "유사문제 생성에 실패했습니다.", 502)

    if not result:
        _log("similar-question", request_id=req.requestId or "", material_id=req.materialId,
             review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="SIMILAR_QUESTION_GENERATION_FAILED", validation_reason=fail)
        return _error("SIMILAR_QUESTION_GENERATION_FAILED", "유사문제 생성에 실패했습니다.", 502)

    response = {
        "questionText": result["questionText"],
        "options": result["options"],
        "correctAnswer": result["correctAnswer"],
        "explanation": result["explanation"],
        "difficulty": req.difficulty,
        "basis": "원본 오답과 PDF 근거 기반",
        "meta": {"requestId": req.requestId or "", "validated": True, "source": "AI"},
    }
    _log("similar-question", request_id=req.requestId or "", material_id=req.materialId,
         review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
         elapsed_ms=int((time.time() - started) * 1000), error_code=None)
    return response


# ════════════════════════════════════════════════════════════════════════════
# [3] 오답노트 AI 해설 생성 — POST /api/ai/review-note/explanation
# ════════════════════════════════════════════════════════════════════════════
class ExplanationRequest(BaseModel):
    requestId: Optional[str] = ""
    materialId: Optional[int] = None
    sourceMaterialId: Optional[int] = None
    reviewNoteId: Optional[int] = None
    questionText: str = ""
    options: List[str] = Field(default_factory=list)
    correctAnswer: str = ""
    userAnswer: Optional[str] = ""
    existingExplanation: Optional[str] = ""
    difficulty: str = "normal"
    sourceText: Optional[str] = ""


_EXPLANATION_FIELDS = ("feedback", "whyUserAnswerWrong", "whyCorrectAnswerRight",
                       "sourceConcept", "reviewPoint", "nextRule")


def validate_explanation(resp: Dict[str, Any], req: ExplanationRequest) -> Optional[str]:
    """AI 해설 계약 검증. 통과 시 None, 실패 시 사유."""
    for f in _EXPLANATION_FIELDS:
        if not (resp.get(f) or "").strip():
            return f"{f} empty"
    blob = " ".join(str(resp.get(f) or "") for f in _EXPLANATION_FIELDS)
    # userAnswer/correctAnswer 둘 다 언급 (userAnswer가 있을 때만 강제)
    user_ans = (req.userAnswer or "").strip()
    correct = (req.correctAnswer or "").strip()
    if correct and correct not in blob:
        return "correctAnswer not mentioned"
    if user_ans and user_ans not in blob:
        return "userAnswer not mentioned"
    # sourceText 또는 existingExplanation 근거 반영
    basis = _significant(_keywords(req.sourceText or "") | _keywords(req.existingExplanation or ""))
    if basis:
        gen = _keywords(blob)
        if not (basis & gen):
            return "no overlap with sourceText/explanation"
    return None


def _gen_explanation(req: ExplanationRequest) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    from app.services.ai_pipeline import generate_structured, repair_to_valid

    base_block = (
        f"## 문제\n{req.questionText}\n"
        f"## 보기\n{req.options}\n"
        f"## 정답\n{req.correctAnswer}\n"
        f"## 사용자가 고른 답(오답)\n{req.userAnswer}\n"
        f"## 기존 해설\n{req.existingExplanation}\n"
        f"## PDF 근거(sourceText)\n{(req.sourceText or '')[:2500]}\n"
        f"## 난이도\n{req.difficulty}\n\n"
    )
    schema = (
        '{ "feedback": "전체 피드백 2~3문장", '
        '"whyUserAnswerWrong": "사용자가 고른 답이 왜 틀렸는지 (오개념 분석)", '
        '"whyCorrectAnswerRight": "정답이 왜 맞는지", '
        '"sourceConcept": "원본 PDF/자료의 핵심 개념과 연결", '
        '"reviewPoint": "다시 볼 포인트", '
        '"nextRule": "다음에 헷갈리지 않는 판단 기준" }\n'
        "반드시 사용자가 고른 답과 정답을 모두 언급하고, PDF sourceText의 개념과 연결하라. "
        "단순히 '정답은 X입니다'로 끝내지 말고 오답 원인을 분석하라. PDF에 없는 내용으로 확장하지 마라."
    )
    draft_system = (
        "너는 오답 분석 코치다. 단순 정답 설명이 아니라, 사용자가 왜 틀렸는지/정답이 왜 맞는지/"
        "원본 PDF 개념과 어떻게 연결되는지를 분석한다. 반드시 한국어, 마크다운 없이 JSON 한 개로만 응답한다."
    )
    draft_user = base_block + "아래 JSON으로만 응답하라(마크다운/별표/해시/백틱 금지):\n" + schema
    refine_system = (
        "너는 오답 해설 보강기다. 1차 분석을 받아 오답 원인을 더 구체적으로, 정답 근거를 더 명확하게, "
        "PDF 개념 연결을 분명하게 다듬는다. 6개 필드를 모두 채우고 사용자 답·정답을 모두 언급해야 한다. "
        "반드시 한국어, 마크다운 없이 같은 JSON 스키마로만 응답한다."
    )

    def _refine_user(draft: Dict[str, Any]) -> str:
        import json as _json
        draft_txt = _json.dumps(draft, ensure_ascii=False) if draft else "(초안 없음 — 직접 생성)"
        return base_block + f"## 1차 분석\n{draft_txt}\n\n위 분석을 보강해 아래 JSON으로만 응답하라:\n" + schema

    def _normalize(parsed: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(parsed, dict):
            return None
        return {f: _clean(parsed.get(f)) for f in _EXPLANATION_FIELDS}

    def _pass(parsed: Any) -> bool:
        norm = _normalize(parsed)
        return norm is not None and validate_explanation(norm, req) is None

    parsed = generate_structured(
        draft_system=draft_system, draft_user=draft_user,
        refine_system=refine_system, refine_user_builder=_refine_user,
        validator=_pass, max_tokens=1300,
    )
    norm = _normalize(parsed)
    if norm and validate_explanation(norm, req) is None:
        return norm, None

    repaired = repair_to_valid(
        repair_system=refine_system, repair_user=_refine_user(parsed or {}),
        validator=_pass, max_tokens=1300,
    )
    rnorm = _normalize(repaired)
    if rnorm and validate_explanation(rnorm, req) is None:
        return rnorm, None

    retry = generate_structured(
        draft_system=draft_system,
        draft_user=draft_user + "\n주의: 6개 필드 모두 채우고, 사용자가 고른 답과 정답을 둘 다 명시하며, "
                                "PDF sourceText 개념을 반드시 연결하라.",
        refine_system=refine_system, refine_user_builder=_refine_user,
        validator=_pass, max_tokens=1300,
    )
    tnorm = _normalize(retry)
    if tnorm and validate_explanation(tnorm, req) is None:
        return tnorm, None

    fail_reason = validate_explanation(tnorm or rnorm or norm or {}, req) if (tnorm or rnorm or norm) else "no parseable JSON"
    return None, fail_reason


@router.post("/api/ai/review-note/explanation", summary="오답노트 AI 해설 생성")
async def review_note_explanation(req: ExplanationRequest):
    started = time.time()
    src_len = len(req.sourceText or "")
    if not (req.questionText or "").strip() or not (req.correctAnswer or "").strip():
        _log("explanation", request_id=req.requestId or "", material_id=req.materialId,
             review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="AI_RESPONSE_CONTRACT_VIOLATION", validation_reason="missing questionText/correctAnswer")
        return _error("AI_RESPONSE_CONTRACT_VIOLATION", "AI 응답 형식이 올바르지 않습니다.", 422)
    try:
        result, fail = await asyncio.wait_for(
            asyncio.to_thread(_gen_explanation, req), timeout=EXPLAIN_TIMEOUT)
    except asyncio.TimeoutError:
        _log("explanation", request_id=req.requestId or "", material_id=req.materialId,
             review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="REVIEW_NOTE_EXPLANATION_FAILED", validation_reason="timeout")
        return _error("REVIEW_NOTE_EXPLANATION_FAILED", "오답 해설 생성에 실패했습니다.", 504)
    except Exception as e:  # noqa: BLE001
        logger.error("explanation 실패: %s", e)
        _log("explanation", request_id=req.requestId or "", material_id=req.materialId,
             review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="REVIEW_NOTE_EXPLANATION_FAILED", validation_reason=str(e))
        return _error("REVIEW_NOTE_EXPLANATION_FAILED", "오답 해설 생성에 실패했습니다.", 502)

    if not result:
        _log("explanation", request_id=req.requestId or "", material_id=req.materialId,
             review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
             elapsed_ms=int((time.time() - started) * 1000),
             error_code="REVIEW_NOTE_EXPLANATION_FAILED", validation_reason=fail)
        return _error("REVIEW_NOTE_EXPLANATION_FAILED", "오답 해설 생성에 실패했습니다.", 502)

    response = {**result,
               "meta": {"requestId": req.requestId or "", "validated": True, "source": "AI"}}
    _log("explanation", request_id=req.requestId or "", material_id=req.materialId,
         review_note_id=req.reviewNoteId, difficulty=req.difficulty, source_len=src_len,
         elapsed_ms=int((time.time() - started) * 1000), error_code=None)
    return response
