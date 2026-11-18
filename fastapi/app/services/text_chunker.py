"""
텍스트 청킹 서비스.
긴 PDF 원문을 RAG 저장에 적합한 크기의 청크로 분리한다.

처리 전략:
  1. 문단('\n\n') 기준으로 먼저 분리한다.
  2. 문단이 chunk_size를 초과하면 글자 수 기준으로 강제 분리한다.
  3. overlap을 적용해 문맥 연속성을 유지한다.
  4. 빈 청크와 앞뒤 공백을 제거한다.
"""
import re


def split_text_into_chunks(
    text: str,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """
    긴 텍스트를 overlap이 있는 청크 목록으로 분리한다.

    Args:
        text:       분리할 원본 텍스트
        chunk_size: 청크 최대 글자 수
        overlap:    인접 청크 간 중복 글자 수 (문맥 연결 유지)

    Returns:
        청크 문자열 목록 (빈 항목 제거됨)
    """
    if not text or not text.strip():
        return []

    # 과도한 공백/줄바꿈 정리
    text = re.sub(r"\n{3,}", "\n\n", text.strip())

    # 문단 단위 1차 분리
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]

    # 문단을 chunk_size 이하의 세그먼트로 다시 분리
    segments: list[str] = []
    for para in paragraphs:
        if len(para) <= chunk_size:
            segments.append(para)
        else:
            # 문단이 너무 길면 글자 수 기준으로 강제 분리
            for start in range(0, len(para), chunk_size - overlap):
                piece = para[start : start + chunk_size].strip()
                if piece:
                    segments.append(piece)

    if not segments:
        return []

    # overlap 적용: 인접 세그먼트 경계에서 이전 청크의 뒷부분을 이어 붙임
    chunks: list[str] = [segments[0]]
    for seg in segments[1:]:
        prev_tail = chunks[-1][-overlap:] if overlap > 0 else ""
        merged = (prev_tail + "\n" + seg).strip() if prev_tail else seg
        chunks.append(merged)

    # 최종 빈 항목 제거 및 공백 정리
    return [c.strip() for c in chunks if c.strip()]


def split_text_with_metadata(
    text: str,
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    """
    overlap 슬라이딩 윈도우로 청크를 만들고 각 청크의 char offset 메타데이터를 함께 반환한다.
    (RAG 정확도 개선 파이프라인 전용 — 기존 split_text_into_chunks 동작은 그대로 둔다.)

    윈도우 예(chunk_size=400, overlap=100):
        chunk_0: 0~400, chunk_1: 300~700, chunk_2: 600~1000 ...

    Returns:
        [{"chunkIndex": int, "text": str, "charStart": int, "charEnd": int,
          "tokenEstimate": int}, ...]  (빈 청크 제거)
    """
    if not text or not text.strip():
        return []

    cleaned = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text.strip()))
    n = len(cleaned)
    size = max(50, int(chunk_size))
    step = max(1, size - max(0, int(overlap)))

    out: list[dict] = []
    start = 0
    idx = 0
    while start < n:
        end = min(start + size, n)
        seg = cleaned[start:end].strip()
        if seg:
            out.append({
                "chunkIndex": idx,
                "text": seg,
                "charStart": start,
                "charEnd": end,
                "tokenEstimate": max(1, len(seg) // 2),
            })
            idx += 1
        if end >= n:
            break
        start += step
    return out
