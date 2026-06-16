"""
소크라테스 복습 세션 서비스 (자료 상세용, 문서 기반 coverage 복습).

일반 RAG QA와 다른 점:
  - 일반 RAG QA: 질문에 맞는 청크를 전체 코퍼스에서 검색해 답변.
  - 소크라테스 복습: 하나의 자료(material_id) 전체 청크를 page/chunk_index 순서로
    빠짐없이 순회하며 유도 질문을 던지는 coverage 기반 복습.

핵심 불변식(반드시 지켜야 함):
  1. 세션 시작 시 material_id(=document)를 고정한다.
  2. 모든 청크/벡터 조회는 반드시 WHERE material_id = :material_id 로 제한한다.
     (전체 코퍼스 검색 금지, 다른 자료 청크 유입 금지)
  3. 출제 순서는 벡터 검색이 아니라 page_start ASC → chunk_index ASC → id ASC 순회로 정한다.
  4. 벡터 검색은 "학생 답변 평가 grounding" 용도로만 쓴다(역시 material_id 고정).
  5. 학생에게 정답을 직접 말하지 않는다. 한 번에 질문 하나만 한다.

세션 상태:
  - 운영 ai.conversation_session 테이블은 user_id NOT NULL + mode/status/summary_json 컬럼이
    없어 이 계약(materialId만 수신)으로는 안전히 재사용할 수 없다. 따라서 세션 상태는
    프로세스 내 메모리에 보관한다(짧은 단일 세션 수명). 기존 ai.* 세션 테이블은 건드리지 않는다.
  - 청크 lazy annotation(core_concepts/rubric/difficulty/question_seed)만 기존
    rag.document_chunk.metadata(jsonb)에 additive 하게 저장(최초 1회)한다.

임베딩: 기존 RAG 인덱스와 동일한 intfloat/multilingual-e5-base(768차원)를 그대로 사용한다.
LLM: 운영 OLLAMA_MODEL(qwen3:14b). qwen3 thinking은 think=False 로 비활성(예산/지연/누출 방지).
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
from datetime import date, timedelta
from typing import Any, Optional

import psycopg
import requests
from pgvector.psycopg import register_vector

from app.core.config import (
    AI_DATABASE_URL,
    VECTOR_DATABASE_URL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)

logger = logging.getLogger(__name__)

_TABLE = "rag.document_chunk"

# ── 튜닝 상수 ────────────────────────────────────────────────────────────────
_MIN_CHUNK_CHARS = 40          # 이보다 짧은 청크는 출제에서 skip
_DEFAULT_MAX_CHUNKS = 12       # 발표 안정성: 기본 12개로 제한
_HARD_MAX_CHUNKS = 15          # 상한
_DEFAULT_MAX_TURNS_PER_CHUNK = 2
_GROUNDING_TOP_K = 3
_ANNOTATION_CONTENT_LIMIT = 1800   # annotation 프롬프트에 넣는 청크 본문 최대 길이
_QUESTION_CONTENT_LIMIT = 700      # 질문 생성기에 노출하는 청크 본문 최대 길이
_LLM_TIMEOUT_TEXT = 30
_LLM_TIMEOUT_JSON = 35

# correctness 임계값
_PASS_THRESHOLD = 0.75
_FOLLOWUP_THRESHOLD = 0.40

# ── 세션 메모리 저장소 ────────────────────────────────────────────────────────
_SESSIONS: dict[str, dict] = {}
_LOCK = threading.RLock()
_SESSION_TTL_SEC = 60 * 60 * 6  # 6시간 후 만료(메모리 보호)


# ── DB 연결 ──────────────────────────────────────────────────────────────────
def _get_connection() -> psycopg.Connection:
    url = AI_DATABASE_URL or VECTOR_DATABASE_URL
    if not url:
        raise RuntimeError("AI_DATABASE_URL/VECTOR_DATABASE_URL 미설정")
    conn = psycopg.connect(url, connect_timeout=8)
    register_vector(conn)
    return conn


# ── document_id ↔ material_id 매핑 ───────────────────────────────────────────
class SessionError(Exception):
    """세션 생성/진행 실패를 호출부(라우터)로 명확히 전달하기 위한 예외."""

    def __init__(self, message: str, status: str = "FAILED"):
        super().__init__(message)
        self.message = message
        self.status = status


def resolve_material_id(material_id: Optional[int], document_id: Optional[str]) -> int:
    """
    materialId 또는 documentId 를 내부 material_id(int)로 매핑한다.
    document_id 를 확정하지 못하면 전체 코퍼스로 넘어가지 않고 명확히 실패한다.
    folderId 등 다른 식별자는 호출부에서 무시한다(여기로 넘어오지 않는다).
    """
    if material_id is not None:
        try:
            return int(material_id)
        except (TypeError, ValueError):
            raise SessionError("materialId가 정수가 아닙니다.")

    if document_id is not None:
        s = str(document_id).strip()
        m = re.fullmatch(r"(?:doc[_-])?(\d+)", s)
        if m:
            return int(m.group(1))
        raise SessionError(f"documentId '{document_id}' 를 material_id로 매핑할 수 없습니다.")

    raise SessionError("materialId 또는 documentId 중 하나는 반드시 필요합니다.")


def document_id_of(material_id: int) -> str:
    return f"doc_{material_id}"


# ── 청크 로드 (출제 plan: 벡터 검색 아님, 순회) ─────────────────────────────────
def load_document_chunks(material_id: int) -> list[dict]:
    """
    해당 material_id 의 모든 청크를 출제 순서(page_start→chunk_index→id)로 로드한다.
    반드시 WHERE material_id = %s 로 문서 고정. 전체 코퍼스 검색 금지.
    """
    sql = f"""
        SELECT id, chunk_index, page_start, page_end, content, content_hash, metadata
        FROM {_TABLE}
        WHERE material_id = %s
        ORDER BY
            COALESCE(page_start, 2147483647) ASC,
            chunk_index ASC,
            id ASC
    """
    rows: list[dict] = []
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (material_id,))
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                rows.append(dict(zip(cols, r)))
    return rows


def build_plan(chunks: list[dict], max_chunks: int) -> list[dict]:
    """순회 청크에서 너무 짧거나 중복인 청크를 skip 하고 max_chunks 로 제한한다."""
    seen_hashes: set[str] = set()
    seen_content: set[str] = set()
    plan: list[dict] = []
    for c in chunks:
        content = (c.get("content") or "").strip()
        if len(content) < _MIN_CHUNK_CHARS:
            continue
        h = c.get("content_hash")
        norm = content[:200]
        if h and h in seen_hashes:
            continue
        if norm in seen_content:
            continue
        if h:
            seen_hashes.add(h)
        seen_content.add(norm)
        plan.append(c)
        if len(plan) >= max_chunks:
            break
    return plan


# ── grounding 검색 (평가 전용, 문서 고정) ──────────────────────────────────────
def grounding_search(material_id: int, answer_embedding: list[float], top_k: int = _GROUNDING_TOP_K) -> list[dict]:
    """
    학생 답변 평가용 top-k 검색. 반드시 WHERE material_id 고정.
    임베딩 생성 실패 등으로 answer_embedding 이 없으면 호출하지 않는다(호출부 책임).
    """
    sql = f"""
        SELECT id, content, metadata,
               1 - (embedding <=> %s::vector) AS sim
        FROM {_TABLE}
        WHERE material_id = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    results: list[dict] = []
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (answer_embedding, material_id, answer_embedding, top_k))
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                results.append(dict(zip(cols, r)))
    return results


def persist_chunk_annotation(chunk_id: int, material_id: int, annotation: dict) -> None:
    """
    lazy annotation 결과를 기존 metadata(jsonb)에 additive 병합 저장(최초 1회).
    반드시 material_id 까지 함께 조건으로 걸어 오삽입을 방지한다.
    """
    sql = f"""
        UPDATE {_TABLE}
        SET metadata = COALESCE(metadata, '{{}}'::jsonb) || %s::jsonb,
            updated_at = now()
        WHERE id = %s AND material_id = %s
    """
    try:
        with _get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (json.dumps(annotation, ensure_ascii=False), chunk_id, material_id))
            conn.commit()
    except Exception as e:  # 저장 실패해도 세션은 메모리 annotation으로 계속 진행
        logger.warning("annotation 저장 실패 chunk_id=%s: %s", chunk_id, type(e).__name__)


# ── LLM 호출 (qwen3 think=False, <think> 제거) ────────────────────────────────
def _strip_think(text: str) -> str:
    """qwen3 <think>...</think> 블록 제거. 닫히지 않은 경우도 방어."""
    if not text:
        return ""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    # 닫는 태그만 있는 경우: 그 뒤만 사용
    if "</think>" in text.lower():
        idx = text.lower().rfind("</think>")
        text = text[idx + len("</think>"):]
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _call_ollama(system_prompt: str, user_prompt: str, *, num_predict: int,
                 temperature: float, timeout: int) -> Optional[str]:
    """
    Ollama /api/chat 직접 호출(think=False). 실패 시 None.
    내부 reasoning(<think>)은 절대 저장/노출하지 않으며 호출 직후 제거한다.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": num_predict, "num_ctx": 4096},
    }
    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        cleaned = _strip_think(content)
        return cleaned or None
    except requests.Timeout:
        logger.warning("socratic-review Ollama timeout(%ss)", timeout)
        return None
    except requests.ConnectionError:
        logger.warning("socratic-review Ollama 연결 실패(%s)", OLLAMA_BASE_URL)
        return None
    except Exception as e:
        logger.warning("socratic-review Ollama 예외: %s", type(e).__name__)
        return None


def _extract_json_object(text: Optional[str]) -> Optional[dict]:
    """think 제거 후 JSON object 추출 + 1회 repair 시도."""
    if not text:
        return None
    from app.utils.json_parser import extract_json

    parsed = extract_json(text)
    if isinstance(parsed, dict):
        return parsed
    # repair 1회: 가장 바깥 중괄호만 다시 추출
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start:end + 1]
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


# ── 임베딩 (기존 RAG와 동일 모델/차원) ─────────────────────────────────────────
def _embed_answer(answer: str) -> Optional[list[float]]:
    """
    학생 답변 임베딩. 기존 document_chunk와 동일한 multilingual-e5-base(768)를 사용.
    차원 불일치/모델 로드 실패 시 None → 호출부는 current chunk만 grounding으로 사용.
    """
    try:
        from app.services.embedding_service import embed_query
        return embed_query(answer)
    except Exception as e:
        logger.warning("answer 임베딩 실패(차원/모델): %s", type(e).__name__)
        return None


# ── LLM 역할 프롬프트 ─────────────────────────────────────────────────────────
_QUESTION_SYSTEM = (
    "너는 소크라테스식 복습 튜터다.\n"
    "규칙:\n"
    "1. 질문만 한다.\n"
    "2. 정답, 정의, 핵심 내용을 직접 말하지 않는다.\n"
    "3. 학생이 스스로 도달하도록 유도한다.\n"
    "4. 한 번에 질문 하나만 한다.\n"
    "5. 문서 밖의 내용을 끌어오지 않는다.\n"
    "6. 질문은 현재 청크의 핵심 개념을 겨냥해야 한다.\n"
    "7. 한국어로 작성한다.\n"
    "8. 친절하지만 답을 알려주지 않는다.\n\n"
    "출력은 질문 문장 하나만 작성한다. 설명/머리말/번호 없이 질문만."
)

_FOLLOWUP_SYSTEM = (
    "너는 소크라테스식 복습 튜터다.\n"
    "학생의 부족한 부분을 직접 알려주지 말고, 그 부분을 스스로 생각하게 만드는 질문을 작성한다.\n"
    "정답을 말하지 않는다. 한 번에 질문 하나만 한다. 한국어로 작성한다.\n"
    "출력은 질문 문장 하나만. 설명/머리말 없이 질문만."
)

_EVAL_SYSTEM = (
    "너는 소크라테스 복습의 답변 평가기다. 학생 답변을 grounding 근거와 채점 기준으로 평가한다.\n"
    "반드시 JSON object 하나만 출력한다. 마크다운/설명/<think> 금지.\n"
    "정답 문장을 출력에 직접 노출하지 않는다.\n"
    "형식:\n"
    '{"on_topic": true, "correctness": 0.0~1.0, "covered": ["..."], '
    '"missing": ["..."], "next_action": "next|follow_up|easier", "direction": "되물을 방향"}\n'
    "기준: 0.75이상이면 next, 0.4~0.75이면 follow_up, 0.4미만이면 easier. "
    "학생이 문서 밖 주제를 말하면 on_topic=false."
)

_SUMMARY_SYSTEM = (
    "너는 소크라테스 복습의 세션 요약기다. 청크별 평가들을 종합해 mastery와 복습 추천을 만든다.\n"
    "반드시 JSON object 하나만 출력한다. 마크다운/설명/<think> 금지.\n"
    "형식:\n"
    '{"per_chunk":[{"chunk_id":123,"page":1,"mastery":0.0~1.0,"weak":["..."],"review_in_days":1}],'
    '"overall_mastery":0.0~1.0,"recommend_review_in_days":1,"weak_concepts":["..."],'
    '"summary_for_planner":"플래너용 한국어 요약 한두 문장"}\n'
    "정답을 직접 노출하지 말고 무엇을 복습해야 하는지만 쓴다."
)


# ── annotation 생성 (lazy, 최초 1회) ──────────────────────────────────────────
def _annotate_chunk(chunk: dict, difficulty_pref: str) -> dict:
    """
    청크에 core_concepts/rubric/difficulty/question_seed 가 없으면 LLM으로 생성.
    실패 시 content 기반 최소 annotation fallback(질문 가능 수준 보장).
    """
    meta = chunk.get("metadata") or {}
    if all(k in meta for k in ("core_concepts", "rubric", "difficulty", "question_seed")):
        return {
            "core_concepts": meta.get("core_concepts") or [],
            "rubric": meta.get("rubric") or "",
            "difficulty": meta.get("difficulty") or "medium",
            "question_seed": meta.get("question_seed") or "",
            "_from": "cache",
        }

    content = (chunk.get("content") or "")[:_ANNOTATION_CONTENT_LIMIT]
    sys_p = (
        "다음 학습 청크를 분석해 소크라테스 복습용 메타데이터 JSON 하나만 출력한다.\n"
        "마크다운/설명/<think> 금지. 한국어.\n"
        '형식: {"core_concepts":["핵심개념1","핵심개념2"],'
        '"rubric":"채점 기준(무엇이 포함되면 맞는지)",'
        '"difficulty":"easy|medium|hard",'
        '"question_seed":"학생이 스스로 비교/설명해야 할 핵심 쟁점"}'
    )
    user_p = f"[난이도 선호: {difficulty_pref}]\n[청크 본문]\n{content}"
    raw = _call_ollama(sys_p, user_p, num_predict=400, temperature=0.2, timeout=_LLM_TIMEOUT_JSON)
    obj = _extract_json_object(raw)
    if isinstance(obj, dict) and obj.get("core_concepts"):
        annotation = {
            "core_concepts": obj.get("core_concepts") or [],
            "rubric": str(obj.get("rubric") or ""),
            "difficulty": (obj.get("difficulty") or "medium"),
            "question_seed": str(obj.get("question_seed") or ""),
        }
        # 최초 1회 DB 저장
        persist_chunk_annotation(chunk["id"], chunk["_material_id"], annotation)
        annotation["_from"] = "llm"
        return annotation

    # fallback: content 기반 최소 annotation (정답 노출 금지)
    head = re.sub(r"\s+", " ", content).strip()[:120]
    return {
        "core_concepts": [head] if head else [],
        "rubric": "",
        "difficulty": "medium" if difficulty_pref in (None, "auto", "") else difficulty_pref,
        "question_seed": "이 청크에서 가장 중요한 개념과 그 근거",
        "_from": "fallback",
    }


# ── 질문/꼬리질문/요약 생성 ────────────────────────────────────────────────────
_DEFAULT_QUESTION = "이 페이지에서 가장 중요해 보이는 개념을 하나 고른다면 무엇일까요? 왜 그렇게 생각했나요?"


def _generate_question(chunk: dict, annotation: dict) -> str:
    concepts = ", ".join((annotation.get("core_concepts") or [])[:4])
    content = (chunk.get("content") or "")[:_QUESTION_CONTENT_LIMIT]
    page = chunk.get("page_start")
    user_p = (
        f"[핵심 개념] {concepts or '(미상)'}\n"
        f"[난이도] {annotation.get('difficulty', 'medium')}\n"
        f"[페이지] {page if page is not None else '미상'}\n"
        f"[출제 쟁점] {annotation.get('question_seed', '')}\n"
        f"[청크 본문(참고용, 인용 금지)]\n{content}\n\n"
        "위 핵심 개념을 학생이 스스로 설명/비교하게 만드는 유도 질문 1개만 작성하라."
    )
    raw = _call_ollama(_QUESTION_SYSTEM, user_p, num_predict=180, temperature=0.5, timeout=_LLM_TIMEOUT_TEXT)
    q = _first_question_line(raw)
    return q or _DEFAULT_QUESTION


def _generate_followup(eval_obj: dict, visible_history: list[dict]) -> str:
    direction = eval_obj.get("direction") or ""
    missing = ", ".join((eval_obj.get("missing") or [])[:3])
    covered = ", ".join((eval_obj.get("covered") or [])[:3])
    recent = "\n".join(
        f"{t['role']}: {t['content']}" for t in visible_history[-4:]
    )
    user_p = (
        f"[학생이 이미 다룬 부분] {covered or '(없음)'}\n"
        f"[학생이 아직 놓친 부분] {missing or '(불명확)'}\n"
        f"[되물을 방향] {direction}\n"
        f"[최근 대화]\n{recent}\n\n"
        "놓친 부분을 직접 알려주지 말고 스스로 생각하게 만드는 꼬리질문 1개만 작성하라."
    )
    raw = _call_ollama(_FOLLOWUP_SYSTEM, user_p, num_predict=180, temperature=0.55, timeout=_LLM_TIMEOUT_TEXT)
    q = _first_question_line(raw)
    return q or "방금 답변에서 그렇게 판단한 근거를 한 가지만 더 설명해 줄 수 있을까요?"


def _first_question_line(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    from app.utils.response_cleaner import strip_markdown

    text = strip_markdown(text).strip()
    # 여러 줄이면 물음표가 있는 첫 줄 우선
    for line in text.splitlines():
        line = line.strip().lstrip("0123456789.-) ").strip()
        if "?" in line:
            return line
    return text.splitlines()[0].strip() if text.splitlines() else None


# ── 답변 평가 ──────────────────────────────────────────────────────────────────
def _fallback_eval() -> dict:
    return {
        "on_topic": True,
        "correctness": 0.5,
        "covered": [],
        "missing": ["평가 결과를 안정적으로 생성하지 못했습니다."],
        "next_action": "follow_up",
        "direction": "학생에게 근거를 더 설명하게 하기",
    }


def evaluate_answer(material_id: int, chunk: dict, annotation: dict, answer: str,
                    visible_history: list[dict]) -> dict:
    """
    학생 답변을 평가한다. grounding 검색은 반드시 material_id 고정.
    실패 시 deterministic fallback eval 반환.
    """
    answer_emb = _embed_answer(answer)
    grounding: list[dict] = []
    if answer_emb is not None:
        try:
            grounding = grounding_search(material_id, answer_emb)
        except Exception as e:
            logger.warning("grounding 검색 실패: %s", type(e).__name__)
            grounding = []
    # current chunk 는 항상 grounding 에 포함
    ground_texts = [(chunk.get("content") or "")[:600]]
    for g in grounding:
        if g.get("id") != chunk.get("id"):
            ground_texts.append((g.get("content") or "")[:400])
    ground_blob = "\n---\n".join(ground_texts[:4])

    concepts = ", ".join((annotation.get("core_concepts") or [])[:5])
    recent = "\n".join(f"{t['role']}: {t['content']}" for t in visible_history[-4:])
    user_p = (
        f"[채점 기준] {annotation.get('rubric') or '핵심 개념을 정확히 설명했는지'}\n"
        f"[핵심 개념] {concepts}\n"
        f"[문서 근거(grounding)]\n{ground_blob}\n\n"
        f"[최근 대화]\n{recent}\n"
        f"[학생 답변]\n{answer}\n\n"
        "위 답변을 평가해 JSON object 하나만 출력하라."
    )
    raw = _call_ollama(_EVAL_SYSTEM, user_p, num_predict=350, temperature=0.1, timeout=_LLM_TIMEOUT_JSON)
    obj = _extract_json_object(raw)
    if not isinstance(obj, dict):
        return _fallback_eval()
    return _normalize_eval(obj)


def _normalize_eval(obj: dict) -> dict:
    try:
        correctness = float(obj.get("correctness", 0.5))
    except (TypeError, ValueError):
        correctness = 0.5
    correctness = max(0.0, min(1.0, correctness))
    na = str(obj.get("next_action") or "").strip().lower()
    if na not in ("next", "follow_up", "easier"):
        # correctness 기반 보정
        na = ("next" if correctness >= _PASS_THRESHOLD
              else "follow_up" if correctness >= _FOLLOWUP_THRESHOLD else "easier")
    return {
        "on_topic": bool(obj.get("on_topic", True)),
        "correctness": correctness,
        "covered": [str(x) for x in (obj.get("covered") or [])][:8],
        "missing": [str(x) for x in (obj.get("missing") or [])][:8],
        "next_action": na,
        "direction": str(obj.get("direction") or ""),
    }


# ── mastery / 복습일 계산 ─────────────────────────────────────────────────────
def _review_days_for(mastery: float) -> int:
    if mastery >= 0.85:
        return 7
    if mastery >= 0.70:
        return 4
    if mastery >= 0.50:
        return 2
    return 1


def _chunk_mastery(evals: list[dict]) -> float:
    """청크의 mastery: 평가 correctness 가중 평균(최신 답변에 가중)."""
    if not evals:
        return 0.5
    total_w = 0.0
    acc = 0.0
    for i, e in enumerate(evals):
        w = 1.0 + 0.5 * i  # 뒤 턴일수록 가중
        acc += w * float(e.get("correctness", 0.5))
        total_w += w
    base = acc / total_w if total_w else 0.5
    if any(e.get("on_topic") is False for e in evals):
        base *= 0.85
    return round(max(0.0, min(1.0, base)), 4)


# ── 공개 API: 세션 생성/답변/완료/조회 ─────────────────────────────────────────
def _new_session_id() -> str:
    return "sr_" + secrets.token_urlsafe(12)


def _gc_expired() -> None:
    now = time.time()
    expired = [sid for sid, s in _SESSIONS.items() if now - s["_ts"] > _SESSION_TTL_SEC]
    for sid in expired:
        _SESSIONS.pop(sid, None)


def _progress(session: dict) -> dict:
    return {
        "answeredChunks": session["answered_chunks"],
        "totalChunks": len(session["plan"]),
    }


def _ensure_annotation(session: dict, pos: int) -> dict:
    """현재 청크 annotation 을 캐시에서 가져오거나 생성한다(최초 1회)."""
    chunk = session["plan"][pos]
    cache = session["annotations"]
    if chunk["id"] in cache:
        return cache[chunk["id"]]
    chunk["_material_id"] = session["material_id"]
    ann = _annotate_chunk(chunk, session["difficulty"])
    cache[chunk["id"]] = ann
    return ann


def start_session(material_id: Optional[int], document_id: Optional[str], title: Optional[str],
                  max_turns_per_chunk: int, max_chunks: Optional[int], difficulty: str) -> dict:
    """세션 시작 → 첫 질문 생성."""
    mid = resolve_material_id(material_id, document_id)

    raw_chunks = load_document_chunks(mid)
    if not raw_chunks:
        raise SessionError(
            "이 자료에서 복습 세션을 만들 수 있는 문서 청크를 찾지 못했습니다."
        )

    cap = _DEFAULT_MAX_CHUNKS if not max_chunks else min(int(max_chunks), _HARD_MAX_CHUNKS)
    plan = build_plan(raw_chunks, cap)
    if not plan:
        raise SessionError("출제 가능한 유효 청크가 없습니다(모두 너무 짧거나 중복).")

    sid = _new_session_id()
    session = {
        "session_id": sid,
        "material_id": mid,
        "document_id": document_id_of(mid),
        "title": title,
        "status": "IN_PROGRESS",
        "plan": plan,
        "total_chunks_in_doc": len(raw_chunks),
        "current_pos": 0,
        "answered_chunks": 0,
        "max_turns_per_chunk": max(1, int(max_turns_per_chunk or _DEFAULT_MAX_TURNS_PER_CHUNK)),
        "difficulty": difficulty or "auto",
        "annotations": {},
        "evals_by_chunk": {},   # chunk_id -> [eval, ...]
        "turns_by_chunk": {},   # chunk_id -> int
        "visible": [],          # [{role, content}]
        "current_question": None,
        "_ts": time.time(),
    }

    ann = _annotate_chunk(plan[0] | {"_material_id": mid}, session["difficulty"])
    session["annotations"][plan[0]["id"]] = ann
    question = _generate_question(plan[0], ann)
    session["current_question"] = question
    session["visible"].append({"role": "tutor", "content": question})

    with _LOCK:
        _gc_expired()
        _SESSIONS[sid] = session

    return {
        "sessionId": sid,
        "mode": "socratic_review",
        "materialId": mid,
        "documentId": session["document_id"],
        "status": session["status"],
        "totalChunks": len(plan),
        "selectedChunks": len(plan),
        "totalChunksInDocument": len(raw_chunks),
        "currentChunkIndex": 0,
        "currentChunkId": plan[0]["id"],
        "question": question,
        "progress": _progress(session),
    }


def _get_session(session_id: str) -> dict:
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if session is None:
        raise SessionError("세션을 찾을 수 없거나 만료되었습니다.", status="FAILED")
    return session


def submit_answer(session_id: str, answer: str) -> dict:
    session = _get_session(session_id)
    with _LOCK:
        if session["status"] not in ("IN_PROGRESS", "WAITING_ANSWER"):
            raise SessionError(f"세션 상태가 답변을 받을 수 없습니다({session['status']}).")
        answer = (answer or "").strip()
        if not answer:
            raise SessionError("답변이 비어 있습니다.")

        session["_ts"] = time.time()
        pos = session["current_pos"]
        chunk = session["plan"][pos]
        chunk_id = chunk["id"]
        ann = _ensure_annotation(session, pos)

        session["visible"].append({"role": "student", "content": answer})

        eval_obj = evaluate_answer(
            session["material_id"], chunk, ann, answer, session["visible"]
        )
        session["evals_by_chunk"].setdefault(chunk_id, []).append(eval_obj)
        turns = session["turns_by_chunk"].get(chunk_id, 0) + 1
        session["turns_by_chunk"][chunk_id] = turns

        pass_now = eval_obj["correctness"] >= _PASS_THRESHOLD
        reached_limit = turns >= session["max_turns_per_chunk"]

        # 다음 청크로 이동할지 결정
        advance = pass_now or reached_limit

        if advance:
            session["answered_chunks"] += 1
            next_pos = pos + 1
            if next_pos < len(session["plan"]):
                session["current_pos"] = next_pos
                next_ann = _ensure_annotation(session, next_pos)
                next_q = _generate_question(session["plan"][next_pos], next_ann)
                session["current_question"] = next_q
                session["visible"].append({"role": "tutor", "content": next_q})
                return {
                    "sessionId": session_id,
                    "status": "IN_PROGRESS",
                    "visibleMessageType": "NEXT_QUESTION",
                    "message": next_q,
                    "currentChunkId": session["plan"][next_pos]["id"],
                    "currentChunkIndex": next_pos,
                    "progress": _progress(session),
                    "debug": None,
                }
            # 마지막 청크까지 끝남 → 완료 준비
            session["status"] = "READY_TO_FINISH"
            session["current_question"] = None
            msg = "모든 학습 내용을 함께 살펴봤어요. 복습 세션을 마치고 결과를 확인할까요?"
            session["visible"].append({"role": "tutor", "content": msg})
            return {
                "sessionId": session_id,
                "status": "READY_TO_FINISH",
                "visibleMessageType": "SESSION_COMPLETE_READY",
                "message": msg,
                "currentChunkId": chunk_id,
                "currentChunkIndex": pos,
                "progress": _progress(session),
                "debug": None,
            }

        # follow-up / easier 꼬리질문
        followup = _generate_followup(eval_obj, session["visible"])
        session["current_question"] = followup
        session["visible"].append({"role": "tutor", "content": followup})
        vtype = "FOLLOW_UP" if eval_obj["next_action"] != "easier" else "EASIER_HINT"
        return {
            "sessionId": session_id,
            "status": "IN_PROGRESS",
            "visibleMessageType": vtype,
            "message": followup,
            "currentChunkId": chunk_id,
            "currentChunkIndex": pos,
            "progress": _progress(session),
            "debug": None,
        }


def finish_session(session_id: str) -> dict:
    session = _get_session(session_id)
    with _LOCK:
        session["_ts"] = time.time()
        per_chunk_det = _deterministic_per_chunk(session)

        # LLM 요약기(선택): 실패 시 deterministic 사용
        summary = _llm_summary(session, per_chunk_det)
        session["status"] = "COMPLETED"

        today = date.today()
        rec_days = summary["recommend_review_in_days"]
        return {
            "sessionId": session_id,
            "status": "COMPLETED",
            "overallMastery": summary["overall_mastery"],
            "recommendReviewInDays": rec_days,
            "recommendedReviewDate": (today + timedelta(days=rec_days)).isoformat(),
            "weakConcepts": summary["weak_concepts"],
            "perChunk": summary["per_chunk"],
            "summaryForPlanner": summary["summary_for_planner"],
        }


def _deterministic_per_chunk(session: dict) -> list[dict]:
    out = []
    for chunk in session["plan"]:
        cid = chunk["id"]
        evals = session["evals_by_chunk"].get(cid, [])
        mastery = _chunk_mastery(evals) if evals else None
        if mastery is None:
            # 다루지 않은 청크는 약점으로 간주(coverage 복습 취지)
            mastery = 0.4
        weak = []
        for e in evals:
            weak.extend(e.get("missing") or [])
        # 중복 제거 + 상위 4개
        weak = list(dict.fromkeys([w for w in weak if w and "안정적으로" not in w]))[:4]
        out.append({
            "chunkId": cid,
            "page": chunk.get("page_start"),
            "mastery": mastery,
            "weak": weak,
            "reviewInDays": _review_days_for(mastery),
        })
    return out


def _llm_summary(session: dict, per_chunk_det: list[dict]) -> dict:
    """LLM 세션 요약. 실패 시 deterministic 집계로 fallback."""
    masteries = [c["mastery"] for c in per_chunk_det]
    overall_det = round(sum(masteries) / len(masteries), 4) if masteries else 0.5
    weak_all = []
    for c in per_chunk_det:
        weak_all.extend(c["weak"])
    weak_all = list(dict.fromkeys(weak_all))[:6]
    det_days = _review_days_for(overall_det)
    det_summary = (
        f"약점 개념({', '.join(weak_all[:3]) or '전반'})을 중심으로 다시 복습하세요."
    )

    # LLM 입력 구성(내부 eval 요약만, 정답/원문 미노출)
    compact = []
    for c in per_chunk_det:
        compact.append({
            "chunk_id": c["chunkId"], "page": c["page"],
            "mastery": c["mastery"], "weak": c["weak"],
        })
    user_p = (
        f"[청크별 평가 요약]\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        "위를 종합해 세션 요약 JSON 하나만 출력하라. per_chunk 의 chunk_id/page 는 그대로 유지하라."
    )
    raw = _call_ollama(_SUMMARY_SYSTEM, user_p, num_predict=500, temperature=0.2, timeout=_LLM_TIMEOUT_JSON)
    obj = _extract_json_object(raw)

    if not isinstance(obj, dict):
        return {
            "per_chunk": per_chunk_det,
            "overall_mastery": overall_det,
            "recommend_review_in_days": det_days,
            "weak_concepts": weak_all,
            "summary_for_planner": det_summary,
        }

    # LLM 결과 정규화(perChunk 는 deterministic 우선 — chunk_id 무결성 보장)
    try:
        overall = float(obj.get("overall_mastery", overall_det))
        overall = round(max(0.0, min(1.0, overall)), 4)
    except (TypeError, ValueError):
        overall = overall_det
    try:
        rec_days = int(obj.get("recommend_review_in_days", det_days))
        rec_days = max(1, min(30, rec_days))
    except (TypeError, ValueError):
        rec_days = det_days
    weak_concepts = [str(x) for x in (obj.get("weak_concepts") or weak_all)][:6] or weak_all
    summary_for_planner = str(obj.get("summary_for_planner") or det_summary).strip() or det_summary

    return {
        "per_chunk": per_chunk_det,
        "overall_mastery": overall,
        "recommend_review_in_days": rec_days,
        "weak_concepts": weak_concepts,
        "summary_for_planner": summary_for_planner,
    }


def get_session_state(session_id: str) -> dict:
    session = _get_session(session_id)
    with _LOCK:
        pos = session["current_pos"]
        chunk = session["plan"][pos] if pos < len(session["plan"]) else None
        turns = [
            {"role": t["role"], "content": t["content"]}
            for t in session["visible"]
        ]
        return {
            "sessionId": session_id,
            "status": session["status"],
            "materialId": session["material_id"],
            "documentId": session["document_id"],
            "currentChunkId": chunk["id"] if chunk else None,
            "currentChunkIndex": pos,
            "currentQuestion": session["current_question"],
            "turns": turns,
            "progress": _progress(session),
        }
