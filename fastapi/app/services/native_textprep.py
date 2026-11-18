"""
PDF 텍스트 전처리/청크 분할 — C Native Engine(secret_sauce_engine/textprep) wrapper.

설계 원칙(native_scheduler 와 동일):
  - import 시점에 .so 로딩 금지(lazy). FastAPI 기동 절대 방해 금지.
  - C: normalize_text(공백/페이지줄 정리) + compute_chunk_boundaries(바이트 경계, UTF-8 안전).
  - Python: 최종 decode 와 chunk 슬라이싱/검증 담당. C 실패/오류 → Python fallback.
  - 로그는 길이/개수/engine/fallback 만. 원문/사용자 입력 전체 로그 금지.

ABI:
  int normalize_text(const char* in, int in_len, char* out, int out_cap, int* out_len)
  int compute_chunk_boundaries(const char* in, int in_len, int chunk_size, int overlap,
                               int* out_starts, int* out_ends, int max_chunks, int* out_count)
"""
from __future__ import annotations

import ctypes
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 안전 한도 (라우터 검증과 별개로 wrapper 방어)
MAX_TEXT_BYTES = 2 * 1024 * 1024  # 2MB
MIN_CHUNK = 200
MAX_CHUNK = 3000
MAX_CHUNK_COUNT = 20000

_REL_LIB_PATH = "secret_sauce_engine/textprep/libtextprep.so"
_LIB_PATH = Path(__file__).resolve().parents[2] / _REL_LIB_PATH

_WS_RUN = re.compile(r"[ \t\f\v]+")
_PAGE_LINE = re.compile(r"^\s*(?:[Pp][Aa][Gg][Ee]\s*)?\d{1,4}\s*$")
_PAGE_DASH = re.compile(r"^\s*[-|/]?\s*\d{1,4}\s*[-|/]\s*\d{0,4}\s*$")


class NativeTextPrepService:
    def __init__(self) -> None:
        self._lib = None
        self._load_tried = False
        self._available = False
        self._lock = threading.Lock()

    def _load_library(self) -> None:
        if self._load_tried:
            return
        with self._lock:
            if self._load_tried:
                return
            self._load_tried = True
            try:
                if not _LIB_PATH.exists():
                    logger.info("[native_textprep] .so 없음 → Python fallback")
                    return
                lib = ctypes.CDLL(str(_LIB_PATH))
                lib.normalize_text.restype = ctypes.c_int
                lib.normalize_text.argtypes = [
                    ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int),
                ]
                lib.compute_chunk_boundaries.restype = ctypes.c_int
                lib.compute_chunk_boundaries.argtypes = [
                    ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                    ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                ]
                self._lib = lib
                self._available = True
                logger.info("[native_textprep] C 엔진 로드 완료")
            except Exception as e:  # noqa: BLE001
                self._lib = None
                self._available = False
                logger.warning("[native_textprep] C 로드 실패(%s) → Python fallback", type(e).__name__)

    def _usable(self) -> bool:
        # 런타임에 .so 가 삭제/이동되면 즉시 fallback 으로 전환한다.
        return bool(self._available) and self._lib is not None and _LIB_PATH.exists()

    def health(self) -> Dict[str, Any]:
        self._load_library()
        usable = self._usable()
        return {
            "available": usable,
            "engine": "c-native" if usable else "python-fallback",
            "libraryPath": _REL_LIB_PATH,
        }

    # ── public API ──────────────────────────────────────────────────
    def preprocess_and_chunk(self, text: str, chunk_size: int = 800, overlap: int = 120) -> Dict[str, Any]:
        text = text if isinstance(text, str) else ""
        chunk_size = max(MIN_CHUNK, min(MAX_CHUNK, int(chunk_size) if str(chunk_size).lstrip("-").isdigit() else 800))
        try:
            overlap = int(overlap)
        except (TypeError, ValueError):
            overlap = 120
        overlap = max(0, min(overlap, chunk_size // 2))

        self._load_library()
        if self._usable():
            try:
                result = self._run_c(text, chunk_size, overlap)
                if result is not None:
                    return result
            except Exception as e:  # noqa: BLE001
                logger.warning("[native_textprep] C 처리 예외(%s) → fallback", type(e).__name__)

        return self._run_python(text, chunk_size, overlap)

    # ── C 경로 ──────────────────────────────────────────────────────
    def _run_c(self, text: str, chunk_size: int, overlap: int) -> Dict[str, Any] | None:
        raw = text.encode("utf-8")
        if len(raw) > MAX_TEXT_BYTES:
            raw = raw[:MAX_TEXT_BYTES]
        in_len = len(raw)
        if in_len == 0:
            return {"engine": "c-native", "fallback": False, "cleaned_text": "",
                    "chunks": [], "chunkCount": 0}

        # 1) normalize
        out_cap = in_len + 1  # 정규화는 길이를 늘리지 않음
        out_buf = ctypes.create_string_buffer(out_cap)
        out_len = ctypes.c_int(0)
        rc = self._lib.normalize_text(raw, in_len, out_buf, out_cap, ctypes.byref(out_len))
        if rc != 0:
            logger.info("[native_textprep] normalize_text rc=%s → fallback", rc)
            return None
        cleaned_bytes = out_buf.raw[: out_len.value]
        cleaned_text = cleaned_bytes.decode("utf-8", errors="ignore")

        # 2) chunk boundaries (정규화된 UTF-8 바이트 기준)
        cb = cleaned_text.encode("utf-8")
        cb_len = len(cb)
        if cb_len == 0:
            return {"engine": "c-native", "fallback": False, "cleaned_text": "",
                    "chunks": [], "chunkCount": 0}
        step = max(1, chunk_size - overlap)
        max_chunks = min(MAX_CHUNK_COUNT, cb_len // step + 4)
        BArr = ctypes.c_int * max_chunks
        starts = BArr()
        ends = BArr()
        cnt = ctypes.c_int(0)
        rc = self._lib.compute_chunk_boundaries(
            cb, cb_len, chunk_size, overlap, starts, ends, max_chunks, ctypes.byref(cnt))
        if rc != 0:
            logger.info("[native_textprep] compute_chunk_boundaries rc=%s → fallback", rc)
            return None
        n = cnt.value
        if n < 0 or n > max_chunks:
            return None

        chunks: List[Dict[str, Any]] = []
        for i in range(n):
            s, e = starts[i], ends[i]
            if not (0 <= s < e <= cb_len):
                continue
            piece = cb[s:e].decode("utf-8", errors="ignore").strip()
            if piece:
                chunks.append({"index": len(chunks), "text": piece, "length": len(piece)})

        logger.info("[native_textprep] engine=c-native textLen=%s cleanedLen=%s chunkCount=%s",
                    in_len, len(cleaned_text), len(chunks))
        return {"engine": "c-native", "fallback": False, "cleaned_text": cleaned_text,
                "chunks": chunks, "chunkCount": len(chunks)}

    # ── Python fallback ─────────────────────────────────────────────
    def _run_python(self, text: str, chunk_size: int, overlap: int) -> Dict[str, Any]:
        cleaned = _python_normalize(text)
        chunks = _python_chunk(cleaned, chunk_size, overlap)
        logger.info("[native_textprep] engine=python-fallback textLen=%s cleanedLen=%s chunkCount=%s",
                    len(text or ""), len(cleaned), len(chunks))
        return {"engine": "python-fallback", "fallback": True, "cleaned_text": cleaned,
                "chunks": chunks, "chunkCount": len(chunks)}


def _python_normalize(text: str) -> str:
    if not text:
        return ""
    kept: List[str] = []   # content 줄 + 사이 빈 줄("") 토큰
    blank = 0
    for raw_line in text.split("\n"):
        line = _WS_RUN.sub(" ", raw_line).strip()
        if _PAGE_LINE.match(line) or _PAGE_DASH.match(line):
            continue  # 페이지번호성 줄 제거
        if not line:
            blank += 1
            continue
        if kept and blank > 0:
            kept.append("")  # 빈 줄 1개로 축소(3+ 개행 → 2). join 이 줄 구분 \n 추가.
        blank = 0
        kept.append(line)
    return "\n".join(kept).strip()


def _python_chunk(text: str, chunk_size: int, overlap: int) -> List[Dict[str, Any]]:
    if not text:
        return []
    step = max(1, chunk_size - overlap)
    chunks: List[Dict[str, Any]] = []
    pos = 0
    n = len(text)
    while pos < n and len(chunks) < MAX_CHUNK_COUNT:
        end = min(n, pos + chunk_size)
        if end < n:
            window = max(pos + 1, end - min(80, chunk_size // 4))
            nl = text.rfind("\n", window, end)
            sp = text.rfind(" ", window, end)
            cut = nl if nl >= window else (sp if sp >= window else end)
            end = cut
        piece = text[pos:end].strip()
        if piece:
            chunks.append({"index": len(chunks), "text": piece, "length": len(piece)})
        if end >= n:
            break
        nxt = end - overlap
        pos = nxt if nxt > pos else pos + 1
    return chunks


_SERVICE: NativeTextPrepService | None = None
_SERVICE_LOCK = threading.Lock()


def get_textprep_service() -> NativeTextPrepService:
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = NativeTextPrepService()
    return _SERVICE


def preprocess_and_chunk(text: str, chunk_size: int = 800, overlap: int = 120) -> Dict[str, Any]:
    return get_textprep_service().preprocess_and_chunk(text, chunk_size, overlap)


def textprep_health() -> Dict[str, Any]:
    return get_textprep_service().health()
