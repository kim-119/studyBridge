"""
PDF 기반 + 개념 확장 학습일지 검증 API (4단계 파이프라인).

  POST /api/ai/study-journal/validate

역할 분리:
  - ai07 FastAPI: 학습일지 입력 "검증"만 수행한다. 원문을 저장하지 않는다.
  - OpenAI API: 꼬리를 무는 "개념 확장 최종 판정"을 담당한다(4단계).
  - Qwen3 14B: 개념 확장 최종 판정에 사용하지 않는다.
  - S3 / DB 저장: ai07에서 하지 않는다. 저장 책임은 EC2 Spring에 있다.

4단계 파이프라인:
  [1] Deterministic Safety Filter  — 욕설/광고/무의미/반복/길이 등 명백한 위험 즉시 차단.
                                     이 단계에서 ACCEPT를 최종 확정하지 않는다.
  [2] PDF Direct Grounding Check   — materialId 기준 기존 RAG 청크/제목/키워드 조회.
  [3] Semantic Similarity Check    — memoText 임베딩 유사도(로컬 e5, OpenAI와 독립).
  [4] OpenAI Concept Expansion     — PDF 핵심 개념에서 이어지는 개념까지 OpenAI가 최종 판정.

장애 정책:
  - OpenAI timeout/장애/JSON 파싱 실패/스키마 검증 실패 시 Qwen3로 대체하지 않고
    보수적으로 REQUEST_REVISION을 반환한다.
  - 단, 1단계에서 BLOCK이면 4단계로 넘기지 않는다.

로그 정책:
  - memoText 원문, PDF 청크 원문, 욕설 원문, API Key 등 비밀값을 로그에 남기지 않는다.
  - 길이/판정/관계유형/유사도/소요시간/에러코드만 기록한다.
"""
import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Study Journal Validator"])

# ── 설정값 (코드에 마구 박지 않고 환경변수/상수로 분리) ─────────────────────────
# OpenAI 모델: 전용 환경변수 우선, 없으면 기존 프로젝트 OpenAI 모델 재사용.
STUDY_JOURNAL_MODEL = os.getenv("OPENAI_STUDY_JOURNAL_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
# OpenAI 요청 timeout(초) — 8~15초 범위 권장.
STUDY_JOURNAL_OPENAI_TIMEOUT = float(os.getenv("STUDY_JOURNAL_OPENAI_TIMEOUT", "12"))
# OpenAI 재시도 횟수 (1회 이하로 제한).
STUDY_JOURNAL_OPENAI_RETRY = min(1, int(os.getenv("STUDY_JOURNAL_OPENAI_RETRY", "1")))
# DIRECT 후보로 둘 의미 유사도 임계값.
STUDY_JOURNAL_DIRECT_SIM_THRESHOLD = float(os.getenv("STUDY_JOURNAL_DIRECT_SIM_THRESHOLD", "0.78"))
# RAG 조회 청크 수.
STUDY_JOURNAL_RAG_TOP_K = int(os.getenv("STUDY_JOURNAL_RAG_TOP_K", "5"))
# 의미 있는 입력으로 보는 최소 길이.
STUDY_JOURNAL_MIN_LEN = int(os.getenv("STUDY_JOURNAL_MIN_LEN", "6"))
# OpenAI에 보낼 청크 요약 1개당 최대 길이.
STUDY_JOURNAL_CHUNK_PREVIEW = int(os.getenv("STUDY_JOURNAL_CHUNK_PREVIEW", "300"))

# ── enum 정의 ─────────────────────────────────────────────────────────────────
DECISIONS = {"ACCEPT", "REQUEST_REVISION", "BLOCK"}
CATEGORIES = {
    "PDF_CONCEPT_SUMMARY", "PDF_QUESTION", "LEARNING_REFLECTION",
    "COMMON_MISCONCEPTION", "OFF_TOPIC", "TOXIC_OR_ABUSIVE",
    "MEANINGLESS", "ADVERTISEMENT",
}
RELATION_TYPES = {
    "DIRECT", "CHILD_CONCEPT", "PARENT_CONCEPT", "PREREQUISITE",
    "APPLICATION", "COMPARISON", "COMMON_MISCONCEPTION",
    "SAME_TERM_DIFFERENT_CONTEXT", "NONE",
}
# ACCEPT가 허용되지 않는 관계 유형.
RELATION_NOT_ACCEPTABLE = {"NONE", "SAME_TERM_DIFFERENT_CONTEXT"}

# 토큰 추출: 영문/숫자 식별자 + 2자 이상 한글.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]{2,}")
# 구조적 무의미 신호(도메인 단어가 아닌 패턴): 같은 글자 4회 이상, ㅋㅎ류 자음 연타.
_REPEAT_RE = re.compile(r"(.)\1{3,}")
_JAMO_RUN_RE = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]{3,}")
# URL 신호(구조적 패턴). 광고 "내용" 판정은 OpenAI 4단계가 담당한다.
_URL_RE = re.compile(r"(https?://|www\.|t\.me/)", re.IGNORECASE)


def _env_words(env_name: str, default: str) -> tuple:
    """
    위험어/광고어 같은 도메인 단어는 소스에 박지 않고 환경변수로 외부화한다.
    값이 없으면 '최소 안전망' 기본값만 사용하며, 실제 문맥 판정은 OpenAI 4단계가 담당한다.
    빈 문자열을 명시하면 해당 deterministic 단어 검사를 끌 수 있다(LLM 판정에 일임).
    """
    raw = os.getenv(env_name)
    source = raw if raw is not None else default
    return tuple(w.strip().lower() for w in source.split(",") if w.strip())


# 최소 안전망(OpenAI 부재/장애 시에도 명백한 케이스는 막기 위함). 모두 환경변수로 교체/비활성 가능.
# 원문/매칭어는 로그에 남기지 않는다. 문맥 판단(욕설+학습개념, 광고성 등)은 OpenAI 4단계가 보강한다.
_PROFANITY = _env_words("STUDY_JOURNAL_PROFANITY_WORDS", "씨발,시발,ㅅㅂ,병신,ㅂㅅ,개새끼,좆,fuck,shit,bitch")
_AD_HINTS = _env_words("STUDY_JOURNAL_AD_WORDS", "구매하세요,지금 신청,최저가,무료체험,카카오톡 문의,텔레그램")


# ── 요청/응답 모델 ────────────────────────────────────────────────────────────
class StudyJournalValidateRequest(BaseModel):
    # materialId는 "123"/"test-oop" 등 문자열로 올 수 있어 Any로 받는다.
    materialId: Optional[Any] = None
    title: Optional[str] = ""
    memoText: str = ""
    mode: Optional[str] = "PDF_GROUNDED_CONCEPT_EXPANSION"


class StudyJournalValidateResponse(BaseModel):
    decision: str
    category: str
    relationType: str
    relationPath: Optional[str] = None
    studyRelated: bool = False
    pdfGrounded: bool = False
    conceptExpanded: bool = False
    confidence: float = 0.0
    reason: str = ""
    suggestion: Optional[str] = None


# OpenAI 응답 검증 전용 Pydantic 모델 (스키마 강제).
class OpenAIJournalVerdict(BaseModel):
    decision: str
    category: str
    relationType: str
    relationPath: Optional[str] = None
    studyRelated: bool = False
    pdfGrounded: bool = False
    conceptExpanded: bool = False
    confidence: float = 0.0
    reason: str = ""
    suggestion: Optional[str] = None


# ── 응답 빌더 ─────────────────────────────────────────────────────────────────
def _resp(decision: str, category: str, *, relationType: str = "NONE",
          relationPath: Optional[str] = None, studyRelated: bool = False,
          pdfGrounded: bool = False, conceptExpanded: bool = False,
          confidence: float = 0.0, reason: str = "",
          suggestion: Optional[str] = None) -> StudyJournalValidateResponse:
    return StudyJournalValidateResponse(
        decision=decision, category=category, relationType=relationType,
        relationPath=relationPath, studyRelated=studyRelated, pdfGrounded=pdfGrounded,
        conceptExpanded=conceptExpanded, confidence=round(max(0.0, min(1.0, confidence)), 2),
        reason=reason, suggestion=suggestion,
    )


# ════════════════════════════════════════════════════════════════════════════
# [1단계] Deterministic Safety Filter
# ════════════════════════════════════════════════════════════════════════════
def _stage1_safety(text: str) -> Optional[StudyJournalValidateResponse]:
    """명백히 위험/무의미하면 BLOCK 또는 REQUEST_REVISION 반환. 통과 시 None."""
    raw = (text or "").strip()

    # null/빈 입력/너무 짧음 → REQUEST_REVISION
    if not raw:
        return _resp("REQUEST_REVISION", "MEANINGLESS", confidence=0.2,
                     reason="학습일지 내용이 비어 있습니다.",
                     suggestion="예: OOP에서 클래스와 객체의 차이가 헷갈린다.")

    low = raw.lower()
    low_ns = low.replace(" ", "")

    # 욕설/공격 표현 → BLOCK (원문/매칭어 로그 금지)
    if _PROFANITY and any(p in low_ns for p in _PROFANITY):
        return _resp("BLOCK", "TOXIC_OR_ABUSIVE", confidence=0.95,
                     reason="욕설 또는 공격적 표현은 학습일지에 저장할 수 없습니다.",
                     suggestion="학습 개념 중심으로 순화해서 다시 작성해 주세요.")

    # URL/광고성 → BLOCK
    if _URL_RE.search(raw) or (_AD_HINTS and any(h in low for h in _AD_HINTS)):
        return _resp("BLOCK", "ADVERTISEMENT", confidence=0.9,
                     reason="광고/홍보/링크성 내용은 학습일지에 저장할 수 없습니다.",
                     suggestion="학습한 개념이나 궁금한 점을 작성해 주세요.")

    # 반복 문자/자음 연타만 있는 경우 → REQUEST_REVISION (무의미)
    stripped = re.sub(r"\s+", "", raw)
    if _JAMO_RUN_RE.fullmatch(stripped) or _REPEAT_RE.fullmatch(stripped):
        return _resp("REQUEST_REVISION", "MEANINGLESS", confidence=0.2,
                     reason="의미 있는 학습 내용이 없습니다.",
                     suggestion="학습한 개념이나 헷갈리는 점을 구체적으로 적어 주세요.")

    # 의미 토큰이 전혀 없거나 너무 짧음 → REQUEST_REVISION
    tokens = _TOKEN_RE.findall(raw)
    if not tokens or len(stripped) < STUDY_JOURNAL_MIN_LEN:
        return _resp("REQUEST_REVISION", "MEANINGLESS", confidence=0.25,
                     reason="학습 내용이 너무 짧거나 구체적이지 않습니다.",
                     suggestion="예: 상속에서 부모 클래스와 자식 클래스 관계가 헷갈린다.")

    return None  # 통과 — 절대 여기서 ACCEPT 확정하지 않는다.


# ════════════════════════════════════════════════════════════════════════════
# [2단계+3단계] PDF Direct Grounding + Semantic Similarity
# ════════════════════════════════════════════════════════════════════════════
def _to_material_id_int(value: Any) -> Optional[int]:
    """materialId가 정수로 해석 가능하면 int, 아니면 None(RAG 조회 생략)."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _gather_pdf_context(material_id: Optional[int], memo_text: str) -> Dict[str, Any]:
    """
    materialId 기준 RAG 청크를 조회해 PDF 근거를 모은다.
    반환: {title, keywords, chunks, max_similarity, has_context}
    DB/RAG 실패 시 빈 컨텍스트(서버 죽지 않음).
    """
    ctx: Dict[str, Any] = {
        "title": "", "keywords": [], "chunks": [],
        "max_similarity": 0.0, "has_context": False,
    }
    if material_id is None:
        return ctx
    try:
        from app.services.rag_retriever import retrieve_similar_chunks
        results = retrieve_similar_chunks(memo_text, material_id=material_id,
                                          top_k=STUDY_JOURNAL_RAG_TOP_K)
    except Exception as e:  # noqa: BLE001
        logger.warning("study-journal RAG 조회 실패(계속 진행): %s", type(e).__name__)
        return ctx

    if not results:
        return ctx

    sims = [float(r.get("similarity", 0.0)) for r in results]
    title = ""
    for r in results:
        if r.get("document_title"):
            title = str(r["document_title"])
            break

    # 청크에서 의미 토큰을 키워드로 추출(상위 빈도).
    freq: Dict[str, int] = {}
    previews: List[str] = []
    for r in results[:STUDY_JOURNAL_RAG_TOP_K]:
        content = str(r.get("content", ""))
        previews.append(content[:STUDY_JOURNAL_CHUNK_PREVIEW])
        for t in _TOKEN_RE.findall(content):
            if len(t) >= 2:
                freq[t] = freq.get(t, 0) + 1
    keywords = [w for w, _ in sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:15]]

    ctx.update({
        "title": title, "keywords": keywords, "chunks": previews,
        "max_similarity": round(max(sims), 4) if sims else 0.0,
        "has_context": True,
    })
    return ctx


# ════════════════════════════════════════════════════════════════════════════
# [4단계] OpenAI Concept Expansion Validator (최종 판정자)
# ════════════════════════════════════════════════════════════════════════════
def _openai_system_prompt() -> str:
    return (
        "너는 전 학문 범용 'PDF 기반 개념 확장 학습일지 검증기'다. "
        "사용자의 학습일지 입력이 PDF 학습 내용과 관련 있는지 판단한다.\n"
        "임무:\n"
        "1. 욕설/비방/잡담/무의미 입력은 저장하지 못하게 한다.\n"
        "2. PDF에 직접 나온 개념은 허용한다.\n"
        "3. PDF 핵심 개념에서 논리적으로 이어지는 하위 개념(CHILD_CONCEPT), 상위 개념(PARENT_CONCEPT), "
        "선수 개념(PREREQUISITE), 응용 개념(APPLICATION), 비교 개념(COMPARISON), "
        "관련 오개념(COMMON_MISCONCEPTION)도 허용한다.\n"
        "4. 단어만 같고 문맥이 다르면(SAME_TERM_DIFFERENT_CONTEXT) 허용하지 않는다. "
        "예: OOP 자료에서 '상속세/재산 상속' 이야기.\n"
        "5. ACCEPT하려면 반드시 relationType과 relationPath를 함께 제시해야 한다.\n"
        "6. relationPath를 설명할 수 없으면 REQUEST_REVISION으로 처리한다.\n"
        "7. 욕설이나 인신공격이 있으면 학습 내용이 있어도 ACCEPT하지 않고 BLOCK한다.\n"
        "8. PDF 청크/키워드가 없으면 제공된 PDF 제목(title)을 그 자료의 핵심 주제로 간주해 판단하되, "
        "관계가 불명확하면 과도하게 ACCEPT하지 말고 REQUEST_REVISION한다.\n"
        "9. BLOCK은 오직 욕설/인신공격/혐오/성적 모욕/공격적 조롱/광고·홍보·스팸/악성 링크에만 사용한다. "
        "단순히 학습과 무관하거나(off-topic), 모호하거나, 감정만 있고 개념이 없거나, "
        "같은 단어의 다른 문맥(SAME_TERM_DIFFERENT_CONTEXT)인 경우에는 BLOCK하지 말고 REQUEST_REVISION으로 처리한다. "
        "예: '이거 너무 어렵다', '헷갈린다', '집 가고 싶다'는 REQUEST_REVISION이다.\n"
        "10. PDF 개념과 비교되는 개념을 정리한 회고(예: '절차지향과 객체지향의 차이를 비교해서 정리했다')는 "
        "relationPath를 제시할 수 있으면 COMPARISON으로 ACCEPT한다.\n"
        "11. 출력은 JSON 객체 하나만 한다. 마크다운/설명/chain-of-thought를 출력하지 않는다.\n"
        "relationType 허용값: DIRECT, CHILD_CONCEPT, PARENT_CONCEPT, PREREQUISITE, "
        "APPLICATION, COMPARISON, COMMON_MISCONCEPTION, SAME_TERM_DIFFERENT_CONTEXT, NONE.\n"
        "판정: DIRECT/CHILD_CONCEPT/PARENT_CONCEPT/PREREQUISITE/APPLICATION/COMPARISON/"
        "COMMON_MISCONCEPTION 중 하나이고 학습 문맥이 명확하면 ACCEPT 가능. "
        "SAME_TERM_DIFFERENT_CONTEXT/NONE이면 ACCEPT 금지. 애매하면 REQUEST_REVISION."
    )


def _openai_user_prompt(req: StudyJournalValidateRequest, ctx: Dict[str, Any],
                        sim_candidate: bool) -> str:
    keywords = ", ".join(ctx.get("keywords", [])[:15]) or "(없음)"
    chunk_text = "\n---\n".join(ctx.get("chunks", [])[:3]) or "(관련 청크 없음 — 제목으로 판단)"
    return (
        f"## PDF 제목\n{req.title or '(제목 없음)'}\n"
        f"## PDF 핵심 키워드\n{keywords}\n"
        f"## 관련 PDF 청크 요약\n{chunk_text}\n"
        f"## 의미 유사도 DIRECT 후보 여부\n{'예' if sim_candidate else '아니오'}\n"
        f"## 사용자 학습일지 입력\n{req.memoText}\n\n"
        "위 정보를 바탕으로 아래 JSON 스키마로만 응답하라(마크다운/설명 금지):\n"
        '{ "decision": "ACCEPT|REQUEST_REVISION|BLOCK", '
        '"category": "PDF_CONCEPT_SUMMARY|PDF_QUESTION|LEARNING_REFLECTION|COMMON_MISCONCEPTION|'
        'OFF_TOPIC|TOXIC_OR_ABUSIVE|MEANINGLESS|ADVERTISEMENT", '
        '"relationType": "DIRECT|CHILD_CONCEPT|PARENT_CONCEPT|PREREQUISITE|APPLICATION|COMPARISON|'
        'COMMON_MISCONCEPTION|SAME_TERM_DIFFERENT_CONTEXT|NONE", '
        '"relationPath": "예: OOP → 상속 (없으면 null)", '
        '"studyRelated": true, "pdfGrounded": true, "conceptExpanded": true, '
        '"confidence": 0.0, "reason": "사용자에게 보여줄 짧은 이유", '
        '"suggestion": "수정 예시 또는 null" }'
    )


# OpenAI Structured Outputs용 JSON Schema.
_OPENAI_JSON_SCHEMA = {
    "name": "study_journal_verdict",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {"type": "string", "enum": sorted(DECISIONS)},
            "category": {"type": "string", "enum": sorted(CATEGORIES)},
            "relationType": {"type": "string", "enum": sorted(RELATION_TYPES)},
            "relationPath": {"type": ["string", "null"]},
            "studyRelated": {"type": "boolean"},
            "pdfGrounded": {"type": "boolean"},
            "conceptExpanded": {"type": "boolean"},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "suggestion": {"type": ["string", "null"]},
        },
        "required": [
            "decision", "category", "relationType", "relationPath", "studyRelated",
            "pdfGrounded", "conceptExpanded", "confidence", "reason", "suggestion",
        ],
    },
}


def _call_openai_validator(system: str, user: str) -> Optional[str]:
    """
    OpenAI 호출(동기). Structured Outputs(json_schema) 강제, 실패 시 json_object 폴백.
    예외/장애 시 None 반환 → 호출부에서 보수적 REQUEST_REVISION.
    chain-of-thought를 요구하지 않으며 응답 본문(JSON)만 반환한다.
    """
    from app.services.openai_client import is_enabled, get_sync_client
    if not is_enabled():
        logger.info("study-journal: OPENAI_API_KEY 미설정 → 개념 확장 검증 불가")
        return None

    client = get_sync_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    attempts = 1 + STUDY_JOURNAL_OPENAI_RETRY
    last_err = None
    for i in range(attempts):
        try:
            resp = client.chat.completions.create(
                model=STUDY_JOURNAL_MODEL,
                messages=messages,
                temperature=0.0,
                max_tokens=500,
                timeout=STUDY_JOURNAL_OPENAI_TIMEOUT,
                response_format={"type": "json_schema", "json_schema": _OPENAI_JSON_SCHEMA},
            )
            return resp.choices[0].message.content or None
        except Exception as e:  # noqa: BLE001
            last_err = e
            # json_schema 미지원 모델 등은 json_object로 1회 폴백.
            try:
                resp = client.chat.completions.create(
                    model=STUDY_JOURNAL_MODEL,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=500,
                    timeout=STUDY_JOURNAL_OPENAI_TIMEOUT,
                    response_format={"type": "json_object"},
                )
                return resp.choices[0].message.content or None
            except Exception as e2:  # noqa: BLE001
                last_err = e2
                if i < attempts - 1:
                    continue
    logger.warning("study-journal OpenAI 호출 실패: %s", type(last_err).__name__ if last_err else "unknown")
    return None


def _stage4_openai(req: StudyJournalValidateRequest, ctx: Dict[str, Any],
                   sim_candidate: bool) -> StudyJournalValidateResponse:
    """OpenAI 최종 판정. 장애/스키마 실패 시 보수적 REQUEST_REVISION."""
    from app.utils.json_parser import extract_json

    raw = _call_openai_validator(_openai_system_prompt(),
                                 _openai_user_prompt(req, ctx, sim_candidate))
    if not raw:
        # OpenAI 장애/timeout/미설정 → Qwen3로 대체하지 않고 보수적 REQUEST_REVISION.
        return _resp("REQUEST_REVISION", "OFF_TOPIC", confidence=0.3,
                     reason="개념 확장 검증을 완료할 수 없어 저장을 보류합니다. 잠시 후 다시 시도해 주세요.",
                     suggestion="학습한 개념을 조금 더 구체적으로 작성해 주세요.")

    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return _resp("REQUEST_REVISION", "OFF_TOPIC", confidence=0.3,
                     reason="검증 응답 형식이 올바르지 않아 저장을 보류합니다.",
                     suggestion="학습한 개념을 조금 더 구체적으로 작성해 주세요.")

    # Pydantic 스키마 검증 — 실패 시 REQUEST_REVISION.
    try:
        verdict = OpenAIJournalVerdict(**parsed)
    except Exception as e:  # noqa: BLE001
        logger.info("study-journal OpenAI 스키마 검증 실패: %s", type(e).__name__)
        return _resp("REQUEST_REVISION", "OFF_TOPIC", confidence=0.3,
                     reason="검증 결과가 기준을 충족하지 않아 저장을 보류합니다.",
                     suggestion="학습한 개념을 조금 더 구체적으로 작성해 주세요.")

    decision = verdict.decision if verdict.decision in DECISIONS else "REQUEST_REVISION"
    category = verdict.category if verdict.category in CATEGORIES else "OFF_TOPIC"
    relation = verdict.relationType if verdict.relationType in RELATION_TYPES else "NONE"
    relation_path = (verdict.relationPath or "").strip() or None
    reason = (verdict.reason or "").strip()
    suggestion = (verdict.suggestion or None)

    # ACCEPT 강등 규칙: 조건 불충족 시 REQUEST_REVISION으로 강등.
    if decision == "ACCEPT":
        if (not verdict.studyRelated or relation in RELATION_NOT_ACCEPTABLE
                or not relation_path or not reason):
            return _resp("REQUEST_REVISION",
                         category if category != "TOXIC_OR_ABUSIVE" else "OFF_TOPIC",
                         relationType=relation, relationPath=relation_path,
                         studyRelated=verdict.studyRelated, pdfGrounded=verdict.pdfGrounded,
                         conceptExpanded=verdict.conceptExpanded, confidence=verdict.confidence,
                         reason=reason or "학습 자료와의 연결 관계를 명확히 설명할 수 없습니다.",
                         suggestion=suggestion or "예: OOP에서 클래스와 객체의 차이가 헷갈린다.")
        return _resp("ACCEPT", category, relationType=relation, relationPath=relation_path,
                     studyRelated=True, pdfGrounded=verdict.pdfGrounded,
                     conceptExpanded=verdict.conceptExpanded, confidence=verdict.confidence,
                     reason=reason, suggestion=suggestion)

    if decision == "BLOCK":
        # BLOCK은 욕설/공격/광고에만 한정. 그 외(off-topic·모호·same-term)는 REQUEST_REVISION으로 강등.
        if category not in ("TOXIC_OR_ABUSIVE", "ADVERTISEMENT"):
            return _resp("REQUEST_REVISION",
                         category if category in CATEGORIES else "OFF_TOPIC",
                         relationType=relation, relationPath=relation_path,
                         studyRelated=verdict.studyRelated, pdfGrounded=verdict.pdfGrounded,
                         conceptExpanded=verdict.conceptExpanded, confidence=verdict.confidence,
                         reason=reason or "학습 자료와 연결되는 개념이나 질문이 부족합니다.",
                         suggestion=suggestion or "예: OOP에서 클래스와 객체의 차이가 헷갈린다.")
        return _resp("BLOCK", category,
                     relationType="NONE", relationPath=None, studyRelated=False,
                     pdfGrounded=False, conceptExpanded=False, confidence=verdict.confidence,
                     reason=reason or "학습일지에 저장할 수 없는 표현이 포함되어 있습니다.",
                     suggestion=suggestion or "학습 개념 중심으로 순화해서 다시 작성해 주세요.")

    # REQUEST_REVISION
    return _resp("REQUEST_REVISION", category, relationType=relation,
                 relationPath=relation_path, studyRelated=verdict.studyRelated,
                 pdfGrounded=verdict.pdfGrounded, conceptExpanded=verdict.conceptExpanded,
                 confidence=verdict.confidence,
                 reason=reason or "학습 자료와 연결되는 개념이나 질문이 부족합니다.",
                 suggestion=suggestion or "예: OOP에서 클래스와 객체의 차이가 헷갈린다.")


# ── 동기 파이프라인 (to_thread에서 실행) ──────────────────────────────────────
def _validate_sync(req: StudyJournalValidateRequest) -> StudyJournalValidateResponse:
    # [1단계] Deterministic Safety Filter
    blocked = _stage1_safety(req.memoText)
    if blocked is not None:
        return blocked  # BLOCK이면 4단계로 넘어가지 않음

    # [2단계+3단계] PDF Grounding + Semantic Similarity
    material_id = _to_material_id_int(req.materialId)
    ctx = _gather_pdf_context(material_id, req.memoText)
    sim_candidate = ctx.get("max_similarity", 0.0) >= STUDY_JOURNAL_DIRECT_SIM_THRESHOLD

    # [4단계] OpenAI Concept Expansion Validator (최종 판정자)
    return _stage4_openai(req, ctx, sim_candidate)


# ── 엔드포인트 ────────────────────────────────────────────────────────────────
@router.post("/api/ai/study-journal/validate",
             response_model=StudyJournalValidateResponse,
             summary="PDF 기반 + 개념 확장 학습일지 검증 (저장 안 함, 검증만)")
async def validate_study_journal(req: StudyJournalValidateRequest) -> StudyJournalValidateResponse:
    started = time.time()
    memo_len = len((req.memoText or "").strip())
    title_len = len((req.title or "").strip())
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_validate_sync, req),
            timeout=STUDY_JOURNAL_OPENAI_TIMEOUT + 8,  # OpenAI 자체 timeout 바깥 안전벽
        )
    except asyncio.TimeoutError:
        # 전체 타임아웃도 OpenAI 장애에 준해 보수적 REQUEST_REVISION (Qwen3 대체 금지).
        logger.warning("study-journal 전체 timeout → REQUEST_REVISION")
        result = _resp("REQUEST_REVISION", "OFF_TOPIC", confidence=0.3,
                       reason="검증이 지연되어 저장을 보류합니다. 잠시 후 다시 시도해 주세요.",
                       suggestion="학습한 개념을 조금 더 구체적으로 작성해 주세요.")
    except Exception as e:  # noqa: BLE001
        logger.error("study-journal 검증 예외: %s", type(e).__name__)
        result = _resp("REQUEST_REVISION", "OFF_TOPIC", confidence=0.3,
                       reason="검증 중 오류가 발생해 저장을 보류합니다.",
                       suggestion="학습한 개념을 조금 더 구체적으로 작성해 주세요.")

    # 로그: 원문/욕설/PDF 본문 금지 — 길이/판정/관계/소요시간만 기록.
    logger.info(
        "[study-journal] materialId=%s titleLen=%d memoLen=%d decision=%s "
        "relationType=%s pdfGrounded=%s conceptExpanded=%s confidence=%.2f elapsedMs=%d",
        req.materialId, title_len, memo_len, result.decision, result.relationType,
        result.pdfGrounded, result.conceptExpanded, result.confidence,
        int((time.time() - started) * 1000),
    )
    return result
