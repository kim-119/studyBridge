"""
StudyBridge RAG 모듈
- PDF 텍스트를 청크로 분리, 인메모리 캐시로 관리
- 키워드 기반 빠른 검색 (임베딩 없이도 동작)
- 질문과 관련 있는 청크만 LLM에 전달해 응답 속도 개선
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("studybridge.rag")

# ── 설정 (환경변수로 오버라이드 가능) ────────────────────────────────────────
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "900"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
DEFAULT_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
SUMMARY_TOP_K = int(os.getenv("RAG_SUMMARY_TOP_K", "10"))
MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "7000"))
RECENT_MSG_COUNT = int(os.getenv("RAG_RECENT_MSG_COUNT", "8"))
MAX_MSG_CHARS = int(os.getenv("RAG_MAX_MSG_CHARS", "350"))

# ── 인메모리 캐시: text_hash → chunks list ───────────────────────────────────
_rag_cache: Dict[str, List[str]] = {}


def _hash(text: str) -> str:
    return hashlib.md5(text[:10000].encode("utf-8", errors="replace")).hexdigest()


# ── 청크 분리 ────────────────────────────────────────────────────────────────

def split_chunks(
    text: str,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[str]:
    """
    단락(\n\n) 기준 청크 분리 + overlap 적용.
    단락이 너무 길면 문장 단위로 추가 분리.
    동일 텍스트는 캐시에서 재사용.
    """
    key = _hash(text)
    if key in _rag_cache:
        logger.debug("rag_chunk HIT key=%s", key)
        return _rag_cache[key]

    paras = re.split(r"\n{2,}", text.strip())
    chunks: List[str] = []
    current = ""

    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(current) + len(p) <= size:
            current = (current + "\n\n" + p).strip()
        else:
            if current:
                chunks.append(current)
            # overlap: 이전 청크 끝부분 포함
            if chunks and overlap > 0:
                tail = chunks[-1][-overlap:]
                current = (tail + "\n\n" + p).strip()
            else:
                current = p

    if current:
        chunks.append(current)

    # 너무 긴 청크는 문장 단위 추가 분리
    final: List[str] = []
    for c in chunks:
        if len(c) <= size * 2:
            final.append(c)
            continue
        sents = re.split(r"(?<=[.!?。\n])\s+", c)
        sub = ""
        for s in sents:
            if len(sub) + len(s) <= size:
                sub = (sub + " " + s).strip()
            else:
                if sub:
                    final.append(sub)
                sub = s
        if sub:
            final.append(sub)

    result = [c for c in final if len(c.strip()) >= 20]
    _rag_cache[key] = result
    logger.info("rag_chunk BUILT key=%s total_chunks=%d", key, len(result))
    return result


# ── 키워드 점수 ──────────────────────────────────────────────────────────────

def _tokenize(text: str) -> set:
    norm = re.sub(r"[^\w\s가-힣]", " ", text.lower())
    return {t for t in norm.split() if len(t) >= 2}


def _score_chunk(chunk: str, q_tokens: set) -> float:
    if not q_tokens:
        return 0.0
    chunk_tokens = _tokenize(chunk)
    if not chunk_tokens:
        return 0.0
    overlap = q_tokens & chunk_tokens
    return len(overlap) / len(q_tokens)


# ── 검색 ─────────────────────────────────────────────────────────────────────

def retrieve(
    text: str,
    question: str,
    top_k: int = DEFAULT_TOP_K,
    always_include_first: bool = True,
) -> List[str]:
    """
    키워드 점수 기반 top-k 청크 검색.
    - 동일 텍스트는 청크화 반복 없음 (캐시 활용)
    - 원문 순서 유지
    """
    chunks = split_chunks(text)
    if not chunks:
        return []

    q_tokens = _tokenize(question)
    if not q_tokens:
        return chunks[:min(top_k, len(chunks))]

    scored = sorted(
        enumerate(chunks),
        key=lambda x: _score_chunk(x[1], q_tokens),
        reverse=True,
    )
    top_indices = {i for i, _ in scored[:top_k]}
    if always_include_first:
        top_indices.add(0)  # 첫 청크는 항상 포함 (문서 개요/제목)

    selected = [chunks[i] for i in sorted(top_indices) if i < len(chunks)]
    logger.info(
        "rag_retrieve q_tokens=%d top_k=%d selected=%d",
        len(q_tokens), top_k, len(selected),
    )
    return selected


def build_context(
    text: str,
    question: str,
    top_k: int = DEFAULT_TOP_K,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> Tuple[str, int]:
    """
    질문 관련 청크를 검색해 LLM prompt용 context string 반환.
    Returns: (context_text, chunk_count)
    """
    chunks = retrieve(text, question, top_k=top_k)
    if not chunks:
        return "", 0
    context = "\n\n---\n\n".join(chunks)
    return context[:max_chars], len(chunks)


def build_summary_context(
    text: str,
    max_chars: int = MAX_CONTEXT_CHARS,
    top_k: int = SUMMARY_TOP_K,
) -> str:
    """
    요약용 context: 전체를 그대로 보내지 않고
    앞/중간/뒤를 균등 샘플링해 핵심 섹션만 포함.
    문서가 짧으면 그대로 반환.
    """
    if len(text) <= max_chars:
        return text

    # 청크 기반 샘플링: 앞 top_k/3, 중간 top_k/3, 뒤 top_k/3
    chunks = split_chunks(text)
    n = len(chunks)
    if n == 0:
        return text[:max_chars]

    third = max(1, top_k // 3)
    front = chunks[:third]
    mid_start = max(0, n // 2 - third // 2)
    middle = chunks[mid_start: mid_start + third]
    back = chunks[max(0, n - third):]

    selected: List[str] = []
    seen = set()
    for c in front + middle + back:
        h = _hash(c)
        if h not in seen:
            seen.add(h)
            selected.append(c)

    context = "\n\n---\n\n".join(selected)
    return context[:max_chars]


# ── 채팅 이력 압축 ────────────────────────────────────────────────────────────

def compress_history(
    messages: List[Dict],
    question: Optional[str] = None,
    max_messages: int = RECENT_MSG_COUNT,
    max_chars_per_msg: int = MAX_MSG_CHARS,
    relevance_top_k: int = 3,
) -> str:
    """
    채팅 이력 압축:
    1. 최근 max_messages개만 사용
    2. 각 메시지를 max_chars_per_msg 글자로 잘라냄
    3. 질문이 있으면 관련 있는 과거 메시지도 추가 포함
    """
    if not messages:
        return ""

    recent = messages[-max_messages:]

    # 질문과 관련 있는 이전 메시지 (최근 외)
    relevant_extra: List[Dict] = []
    if question and len(messages) > max_messages:
        q_tokens = _tokenize(question)
        older = messages[:-max_messages]
        scored = sorted(
            older,
            key=lambda m: _score_chunk(
                str(m.get("answer") or m.get("content") or ""), q_tokens
            ),
            reverse=True,
        )
        relevant_extra = scored[:relevance_top_k]

    def fmt(m: Dict) -> str:
        name = m.get("agentName") or m.get("sender") or "AI"
        content = str(m.get("answer") or m.get("content") or "").strip()
        if len(content) > max_chars_per_msg:
            content = content[:max_chars_per_msg] + "..."
        return f"[{name}] {content}"

    lines: List[str] = []
    if relevant_extra:
        lines.append("[관련 이전 대화]")
        lines.extend(fmt(m) for m in relevant_extra)
        lines.append("[최근 대화]")
    lines.extend(fmt(m) for m in recent)
    return "\n".join(lines)
