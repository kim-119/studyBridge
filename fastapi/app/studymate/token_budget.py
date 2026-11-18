"""Token Budget Allocator — 실제 Qwen3 토크나이저 기반.

2026-09-16 실측: 한국어는 약 1.1자/토큰. 문자 수 기반 추정(2자/토큰)으로는 8559자 프롬프트가
4096 컨텍스트를 넘는 걸 못 잡았다(prompt_eval_count==4096 절단).

max_input_tokens = num_ctx - output_reserve - TEMPLATE_OVERHEAD - SAFETY_MARGIN

필수(절대 제거 금지): safety / mode / role / persona / knowledge / final reminder / current question
(+ customInstruction 격리 블록, 기여 계획은 필수로 취급)
overflow 처리 순서: 무관한 이력 제거 → 오래된 원문 턴 제거 → 요약만 사용 → grounding 절삭 → few-shot 축소
앞에서부터 잘라내는(=시스템/페르소나 유실) 방식은 쓰지 않는다.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("studybridge.studymate.tokens")

TEMPLATE_OVERHEAD = 48      # chat template(<|im_start|> 등) + think 태그
SAFETY_MARGIN = 96

_TOKENIZER = None
_TOKENIZER_TRIED = False
_LOCK = threading.Lock()


def _tokenizer():
    global _TOKENIZER, _TOKENIZER_TRIED
    if _TOKENIZER_TRIED:
        return _TOKENIZER
    with _LOCK:
        if _TOKENIZER_TRIED:
            return _TOKENIZER
        _TOKENIZER_TRIED = True
        path = os.getenv("STUDYMATE_TOKENIZER_PATH", "").strip()
        if not path:
            cands = sorted(glob.glob(os.path.expanduser(
                "~/.cache/huggingface/hub/models--Qwen--Qwen3-14B/snapshots/*/tokenizer.json")))
            path = cands[-1] if cands else ""
        if path and os.path.exists(path):
            try:
                import tokenizers
                _TOKENIZER = tokenizers.Tokenizer.from_file(path)
                logger.info("[TOKENS] Qwen3 tokenizer loaded path=%s", path)
            except Exception as e:  # 토크나이저가 없어도 보수적 추정으로 동작
                logger.warning("[TOKENS] tokenizer load failed (%s) — conservative estimator", type(e).__name__)
        else:
            logger.warning("[TOKENS] tokenizer.json not found — conservative estimator")
    return _TOKENIZER


def count_tokens(text: str) -> int:
    if not text:
        return 0
    tk = _tokenizer()
    if tk is not None:
        return len(tk.encode(text).ids)
    # 보수적 추정: 한글/한자 1자≈1토큰, 그 외 3.5자≈1토큰
    hangul = len(re.findall(r"[ㄱ-힣一-鿿]", text))
    return int(hangul * 1.0 + (len(text) - hangul) / 3.5) + 1


def tokenizer_kind() -> str:
    return "qwen3" if _tokenizer() is not None else "estimator"


@dataclass
class Section:
    name: str
    text: str
    required: bool
    drop_rank: int = 0           # 작을수록 먼저 줄인다(선택 섹션만)
    items: List[str] = field(default_factory=list)   # 턴 단위로 줄일 수 있는 섹션(이력/grounding)
    tokens: int = 0


@dataclass
class Allocation:
    sections: List[Section]
    max_input_tokens: int
    total_tokens: int
    dropped: List[str]
    overflow_required: bool

    def get(self, name: str) -> str:
        for s in self.sections:
            if s.name == name:
                return s.text
        return ""


def max_input_tokens(num_ctx: int, output_reserve: int) -> int:
    return max(512, num_ctx - output_reserve - TEMPLATE_OVERHEAD - SAFETY_MARGIN)


def _render_items(header: str, items: List[str]) -> str:
    return (header + "\n" + "\n".join(items)).strip() if items else ""


def allocate(sections: List[Section], *, num_ctx: int, output_reserve: int,
             question: str = "") -> Allocation:
    limit = max_input_tokens(num_ctx, output_reserve)
    for s in sections:
        s.tokens = count_tokens(s.text)
    dropped: List[str] = []

    def total() -> int:
        return sum(s.tokens for s in sections)

    q_tokens = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", question or ""))

    # 1) 무관한 이력 제거(현재 질문과 어휘 겹침 0 인 턴), 단 최근 2턴은 유지
    for s in sections:
        if total() <= limit:
            break
        if s.name == "recent_context" and s.items:
            header = s.text.split("\n", 1)[0]
            keep = []
            for i, it in enumerate(s.items):
                recent = i >= len(s.items) - 2
                overlap = q_tokens & set(re.findall(r"[가-힣A-Za-z0-9]{2,}", it))
                if recent or overlap:
                    keep.append(it)
                else:
                    dropped.append("recent_context:irrelevant_turn")
            s.items = keep
            s.text = _render_items(header, keep)
            s.tokens = count_tokens(s.text)
    # 2) 오래된 원문 턴 제거(가장 오래된 것부터)
    for s in sections:
        if s.name != "recent_context":
            continue
        header = s.text.split("\n", 1)[0] if s.text else ""
        while total() > limit and s.items:
            s.items.pop(0)
            dropped.append("recent_context:old_turn")
            s.text = _render_items(header, s.items)
            s.tokens = count_tokens(s.text)
    # 3) 요약도 초과면 요약을 절반으로 절삭
    for s in sections:
        if s.name == "rolling_summary" and total() > limit and s.text:
            s.text = s.text[: max(200, len(s.text) // 2)] + "…"
            s.tokens = count_tokens(s.text)
            dropped.append("rolling_summary:trimmed")
    # 4) grounding 절삭(뒤쪽 항목부터 제거)
    for s in sections:
        if s.name != "grounding":
            continue
        header = s.text.split("\n", 1)[0] if s.text else ""
        while total() > limit and s.items:
            s.items.pop()
            dropped.append("grounding:item")
            s.text = _render_items(header, s.items)
            s.tokens = count_tokens(s.text)
    # 5) few-shot 축소(마지막 수단, 선택 섹션)
    for s in sections:
        if s.name == "few_shot" and total() > limit and s.items:
            header = s.text.split("\n", 1)[0] if s.text else ""
            while total() > limit and s.items:
                s.items.pop()
                dropped.append("few_shot:example")
                s.text = _render_items(header, s.items)
                s.tokens = count_tokens(s.text)
    overflow_required = total() > limit
    if overflow_required:
        logger.warning("[TOKENS] 필수 섹션만으로 입력 한도 초과 total=%d limit=%d", total(), limit)
    if dropped:
        logger.info("[TOKENS] allocation dropped=%s total=%d limit=%d", dropped, total(), limit)
    return Allocation(sections=sections, max_input_tokens=limit, total_tokens=total(),
                      dropped=dropped, overflow_required=overflow_required)
