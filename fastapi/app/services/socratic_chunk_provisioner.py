"""소크라테스 복습 on-demand 문서 청크 준비.

배경(근본 원인):
  소크라테스 복습은 rag.document_chunk 행을 요구한다. 그러나 자료 업로드/분석 파이프라인은
  RAG ingest 를 자동 실행하지 않으므로, 분석이 끝나(extracted_text 보유) 충분히 복습 가능한
  자료도 rag.document_chunk 가 0행인 경우가 대부분이다. 그 결과 ai07 start_session 이
  "문서 청크를 찾지 못했습니다" 로 하드 실패하고, Spring 은 sessionId 부재를 보고
  "문서 청크가 아직 준비되지 않았거나 분석 가능한 자료가 아닙니다" 경고를 띄운다.

이 모듈은 청크가 없을 때 자료 원문을 우선순위대로 확보해 **1회** 실제 ingest 한다.
임시방편이 아니라 실제 청크를 생성/저장하므로 이후 RAG/평가 grounding 에도 그대로 쓰인다.

입력 우선순위:
  1. 이미 존재하는 rag/document chunks   (호출부 start_session 에서 선처리 — 여기 도달 안 함)
  2. public.materials.extracted_text                                  → source_kind=extracted_text
  3. material_study_note_analysis + material_summaries 조합            → source_kind=summary_fallback
     (page_summaries / detailed_core_contents / core_contents / overview / keywords / learning_content)
  4. S3 PDF 원본 다운로드 후 텍스트 추출(PyMuPDF→pypdf→OCR→VL normalizer)→ source_kind=pdf_extract
     - qwen3:14b/임베딩은 항상 "텍스트만" 받는다. 이미지 PDF 는 VL normalizer 가 텍스트화한다.
  5. 전부 실패 → 명확한 reason 반환

reason 코드:
  MATERIAL_NOT_FOUND | PDF_TEXT_EMPTY | S3_NOT_FOUND | OCR_REQUIRED | UNSUPPORTED_FILE | INTERNAL_ERROR

로그 prefix: [socratic:provision] [socratic:extract] [socratic:rag] [socratic:error]
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 완전 빈 텍스트만 실패로 본다("짧은 텍스트도 최소 1 청크 허용"). 노이즈 한두 글자는 배제.
_MIN_SOURCE_CHARS = 10


# ── 결과 빌더 ──────────────────────────────────────────────────────────────────
_REASON_MESSAGE = {
    "MATERIAL_NOT_FOUND": "자료를 찾을 수 없습니다.",
    "PDF_TEXT_EMPTY": "문서에서 추출 가능한 텍스트가 없습니다. 이미지 PDF라면 OCR 처리가 필요합니다.",
    "S3_NOT_FOUND": "원본 PDF를 저장소에서 찾지 못했습니다.",
    "OCR_REQUIRED": "이미지/스캔 PDF로 보입니다. OCR 처리가 필요해 텍스트를 확보하지 못했습니다.",
    "UNSUPPORTED_FILE": "소크라테스 복습을 지원하지 않는 자료 형식입니다.",
    "INTERNAL_ERROR": "문서 청크 준비 중 내부 오류가 발생했습니다.",
}


def _fail(reason: str, message: Optional[str] = None) -> dict:
    return {
        "ok": False,
        "source_kind": None,
        "chunk_count": 0,
        "text_length": 0,
        "reason": reason,
        "message": message or _REASON_MESSAGE.get(reason, "문서 청크를 준비하지 못했습니다."),
    }


def _ok(source_kind: str, chunk_count: int, text_length: int) -> dict:
    return {
        "ok": True,
        "source_kind": source_kind,
        "chunk_count": chunk_count,
        "text_length": text_length,
        "reason": None,
        "message": "소크라테스 복습을 시작할 수 있습니다.",
    }


# ── 주입 가능한 경계 함수(테스트는 이 셋을 monkeypatch 한다) ─────────────────────
def _get_material_source(material_id: int) -> Optional[dict]:
    """material_id 로 자료 원문 소스를 모은다.

    반환: {exists, material_type, extracted_text, summary_text, s3_key, title, file_name}
    자료가 없으면 None.
    DB(AI_DATABASE_URL == 운영 DB)에서 public.materials / material_study_note_analysis /
    material_summaries 를 읽는다. 소크라테스 서비스와 동일한 psycopg 연결 헬퍼를 재사용한다.
    """
    from app.services.socratic_review_service import _get_connection

    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT material_type, extraction_status, extracted_text, learning_content,
                       s3_file_url, stored_file_name, original_file_name, title
                FROM public.materials
                WHERE material_id = %s
                """,
                (material_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            (material_type, _extraction_status, extracted_text, learning_content,
             s3_file_url, stored_file_name, original_file_name, title) = row

            analysis = _fetch_analysis_text(cur, material_id)

    s3_key = (s3_file_url or stored_file_name or "").strip() or None
    return {
        "exists": True,
        "material_type": (material_type or "").upper(),
        "extracted_text": extracted_text or "",
        "summary_text": _assemble_summary_text(analysis, learning_content),
        "s3_key": s3_key,
        "title": (title or "").strip() or None,
        "file_name": (original_file_name or "").strip(),
    }


def _fetch_analysis_text(cur, material_id: int) -> dict:
    """분석/요약 테이블에서 fallback context 재료를 모은다(있는 것만)."""
    out: dict[str, Any] = {}
    try:
        cur.execute(
            """
            SELECT document_overview, core_contents_json, detailed_core_contents_json,
                   page_summaries_json, keywords_json
            FROM public.material_study_note_analysis
            WHERE material_id = %s
            ORDER BY updated_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            (material_id,),
        )
        r = cur.fetchone()
        if r:
            out["document_overview"] = r[0]
            out["core_contents_json"] = r[1]
            out["detailed_core_contents_json"] = r[2]
            out["page_summaries_json"] = r[3]
            out["keywords_json"] = r[4]
    except Exception as e:  # noqa: BLE001 — 분석 테이블 없거나 컬럼 차이 시 무시
        logger.warning("[socratic:provision] analysis 조회 실패 mat=%s: %s", material_id, type(e).__name__)
    try:
        cur.execute(
            """
            SELECT overview, core_contents
            FROM public.material_summaries
            WHERE material_id = %s
            ORDER BY created_at DESC NULLS LAST, summary_id DESC
            LIMIT 1
            """,
            (material_id,),
        )
        r = cur.fetchone()
        if r:
            out["summary_overview"] = r[0]
            out["summary_core_contents"] = r[1]
    except Exception as e:  # noqa: BLE001
        logger.warning("[socratic:provision] summaries 조회 실패 mat=%s: %s", material_id, type(e).__name__)
    return out


def _flatten_json_text(raw: Any) -> str:
    """JSON 문자열/구조에서 사람이 읽을 텍스트만 평탄화한다(키 제외, 값만)."""
    if raw is None:
        return ""
    val = raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return ""
        try:
            val = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return s  # 평문이면 그대로
    parts: list[str] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str):
            t = node.strip()
            if t:
                parts.append(t)
        elif isinstance(node, (int, float, bool)):
            return
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    walk(val)
    return "\n".join(parts)


def _assemble_summary_text(analysis: dict, learning_content: Optional[str]) -> str:
    """분석/요약/learning_content 를 fallback 학습 본문으로 합친다."""
    pieces: list[str] = []
    for key in (
        "document_overview", "summary_overview",
        "core_contents_json", "summary_core_contents",
        "detailed_core_contents_json", "page_summaries_json", "keywords_json",
    ):
        flat = _flatten_json_text(analysis.get(key))
        if flat:
            pieces.append(flat)
    if learning_content and learning_content.strip():
        pieces.append(learning_content.strip())
    # 중복 줄 제거(요약/상세가 겹치는 경우)
    seen: set[str] = set()
    merged: list[str] = []
    for block in pieces:
        for line in block.splitlines():
            line = line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            merged.append(line)
    return "\n".join(merged)


def _extract_text_from_s3(s3_key: str, file_name: str) -> str:
    """S3 PDF 원본에서 텍스트 추출(PyMuPDF→pypdf→OCR→VL normalizer 사다리).

    이미지/스캔 PDF 는 내부 VL normalizer 가 텍스트화한다 → qwen3 는 항상 텍스트만 받는다.
    S3 접근 자체 실패 시 RuntimeError 가 전파된다(호출부에서 S3_NOT_FOUND 로 분기).
    """
    from app.services.s3_pdf_loader import load_text_from_s3_pdf

    return load_text_from_s3_pdf(s3_key, file_name or "") or ""


def _run_ingest(material_id: int, title: str, text: str) -> int:
    """실제 RAG ingest(청킹→임베딩→pgvector 저장). 저장된 청크 수를 반환한다."""
    from app.services.rag_ingest_service import ingest_document

    result = ingest_document(material_id=material_id, document_title=title, text=text)
    return int(result.get("chunk_count") or 0)


# ── 공개 API ──────────────────────────────────────────────────────────────────
def ensure_material_chunks(material_id: int, title: Optional[str] = None) -> dict:
    """청크가 없는 자료에 대해 원문을 확보·ingest 해 복습 가능 상태로 만든다.

    호출 전제: 호출부가 이미 기존 청크 부재를 확인했다(중복 ingest 방지).
    반환: {ok, source_kind, chunk_count, text_length, reason, message}
    """
    try:
        src = _get_material_source(material_id)
    except Exception as e:  # noqa: BLE001
        logger.error("[socratic:error] source 조회 실패 mat=%s: %s", material_id, type(e).__name__)
        return _fail("INTERNAL_ERROR")

    if not src or not src.get("exists"):
        logger.warning("[socratic:provision] material 없음 mat=%s", material_id)
        return _fail("MATERIAL_NOT_FOUND")

    title = (title or src.get("title") or f"material_{material_id}")

    # 우선순위 2: extracted_text
    source_kind: Optional[str] = None
    text: Optional[str] = None
    ext = (src.get("extracted_text") or "").strip()
    if len(ext) >= _MIN_SOURCE_CHARS:
        source_kind, text = "extracted_text", ext
    else:
        # 우선순위 3: summary/analysis 조합
        summ = (src.get("summary_text") or "").strip()
        if len(summ) >= _MIN_SOURCE_CHARS:
            source_kind, text = "summary_fallback", summ

    # 우선순위 4: S3 PDF 원본
    if text is None:
        s3_key = src.get("s3_key")
        if not s3_key:
            logger.warning("[socratic:provision] 텍스트/요약/S3키 전무 mat=%s", material_id)
            return _fail("PDF_TEXT_EMPTY")
        try:
            s3_text = (_extract_text_from_s3(s3_key, src.get("file_name") or "") or "").strip()
        except RuntimeError as e:  # S3 접근 실패(NoSuchKey 등)
            logger.warning("[socratic:error] S3 다운로드 실패 mat=%s key=%s: %s",
                           material_id, s3_key, e)
            return _fail("S3_NOT_FOUND")
        except Exception as e:  # noqa: BLE001
            logger.error("[socratic:error] S3 추출 예외 mat=%s: %s", material_id, type(e).__name__)
            return _fail("INTERNAL_ERROR")
        if len(s3_text) >= _MIN_SOURCE_CHARS:
            source_kind, text = "pdf_extract", s3_text
        else:
            # PyMuPDF/pypdf/OCR/VL 까지 갔는데도 비었다 → 이미지/스캔 PDF
            logger.warning("[socratic:extract] S3 추출 비어있음(이미지 PDF) mat=%s len=%s",
                           material_id, len(s3_text))
            return _fail("OCR_REQUIRED")

    # 실제 ingest
    try:
        n = _run_ingest(material_id, title, text)
    except ValueError as e:
        logger.warning("[socratic:rag] ingest 빈 텍스트 mat=%s: %s", material_id, e)
        return _fail("PDF_TEXT_EMPTY")
    except Exception as e:  # noqa: BLE001 — 임베딩/DB 저장 실패
        logger.error("[socratic:error] ingest 실패 mat=%s: %s", material_id, type(e).__name__)
        return _fail("INTERNAL_ERROR")

    if not n or n <= 0:
        logger.warning("[socratic:rag] ingest chunk_count=0 mat=%s kind=%s", material_id, source_kind)
        return _fail("PDF_TEXT_EMPTY")

    logger.info("[socratic:rag] provision 완료 mat=%s kind=%s chunks=%s text_len=%s",
                material_id, source_kind, n, len(text))
    return _ok(source_kind, n, len(text))
