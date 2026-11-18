"""
PDF/플래너 기반 'AI 계획 분석' + '다음 학습 추천' 엔진.

설계 원칙(스펙 [2]~[8]):
  - 단순 text.split(".") 금지. 코드/패키지/URL/email/version/decimal 토큰은 온점이 있어도
    절대 분해하지 않는다(placeholder 보호).
  - PDF 줄바꿈으로 깨진 한글/코드 토큰("단위 테스트하\n기" → "단위 테스트하기")을 복원한다.
  - chunk → sentence → action item 의 결정론(deterministic) 파이프라인이 1차 결과를 보장한다.
  - LLM 은 보조 품질 보정에만 쓰고, 검증 실패 시 deterministic 결과를 반환한다(빈 배열/일반 조언 금지).
  - PDF/플래너 원문에 없는 일반 조언("열심히 복습하세요")은 생성/통과시키지 않는다.

LLM provider/temperature/max_tokens 는 .env(study_action_router / llm_engine_router)로 제어한다.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 청크/문장 정책 상수 ───────────────────────────────────────────────────────
CHUNK_MAX_CHARS = 1000
CHUNK_SOFT_CHARS = 500
MIN_SENTENCE_CHARS = 6
MIN_ITEM_CHARS = 5
DEFAULT_MAX_ITEMS = 50

# placeholder 경계 문자(원문에 나타날 일이 거의 없는 제어문자)
_PH_OPEN = "\x01"
_PH_CLOSE = "\x02"

# ── 보호 토큰 패턴(온점이 있어도 분리 금지) ───────────────────────────────────
# 순서 중요: 더 긴/구체적인 패턴을 먼저 적용한다(URL > email > dotted-id > version > decimal).
_PROTECT_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("URL", re.compile(r"https?://[^\s)\]}>,，。]+", re.IGNORECASE)),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    # 점으로 연결된 식별자/패키지/클래스경로/파일명: com.example.data.dto, java.lang.String,
    # build.gradle.kts, MainActivity.kt, example.com
    ("DOTTED", re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+")),
    # version: v2.0, v1.2.3
    ("VERSION", re.compile(r"\bv\d+(?:\.\d+)+", re.IGNORECASE)),
    # decimal: 1.5, 3.14 (소수점 보호)
    ("DECIMAL", re.compile(r"\d+\.\d+")),
]

# 문장 끝으로 인정하는 패턴(코드 토큰은 이미 보호된 상태에서 적용)
#  - 종결어미 '다.' / '요.' 등 + 공백/개행/끝
#  - 일반 '.', '?', '!' + 공백/개행/끝
_SENTENCE_TERMINATOR = re.compile(r"(?<=[.?!])(?=\s|$)|(?<=다)(?=\s|$)(?<=다)")
# 위 lookbehind 는 한계가 있어, split 은 전용 함수에서 처리한다.

# 목록/번호 경계
_BULLET_LINE = re.compile(r"^\s*(?:[-*•·▪◦]|\d+[.)]\s|\(\d+\)\s|[가-힣][.)]\s|[①-⑳]|[ivxIVX]+[.)]\s)")
_NUMBER_PREFIX = re.compile(r"^\s*(?:[-*•·▪◦]+\s*|\d+[.)]\s*|\(\d+\)\s*|[가-힣][.)]\s*|[①-⑳]\s*)")

# header/footer/page-number 후보(통째로 버릴 줄)
_PAGE_NOISE = [
    re.compile(r"^\s*-?\s*\d{1,4}\s*-?\s*$"),          # "12", "- 12 -"
    re.compile(r"^\s*page\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),              # "3 / 10"
]

# 행동 동사 어간 → 정규화 종결형
_ACTION_VERBS: List[Tuple[str, str]] = [
    ("설계", "설계한다"), ("구현", "구현한다"), ("추가", "추가한다"),
    ("분리", "분리한다"), ("정리", "정리한다"), ("작성", "작성한다"),
    ("확인", "확인한다"), ("구성", "구성한다"), ("점검", "점검한다"),
    ("정의", "정의한다"), ("설정", "설정한다"), ("생성", "생성한다"),
    ("적용", "적용한다"), ("분석", "분석한다"), ("테스트", "테스트한다"),
]
_VERB_ALT = "|".join(v for v, _ in _ACTION_VERBS)
_VERB_NORM = dict(_ACTION_VERBS)
# 절의 맨 앞 '산출물 생성' 패턴: "<코드토큰/명사> 패키지|클래스|... 추가|생성|설계|..."
_DELIVERABLE_NOUNS = "패키지|클래스|인터페이스|모듈|함수|메서드|컴포넌트|테이블|엔드포인트|화면|페이지"
_LEAD_DELIVERABLE = re.compile(
    rf"^\s*((?:{_PH_OPEN}P\d+{_PH_CLOSE}|[^\s,]+)(?:\s+[^\s,]+){{0,3}}?)\s*"
    rf"({_DELIVERABLE_NOUNS})\s*(추가|생성|정의|구현|설계|작성)"
)
# 절 분리(접속) 경계
_CONJ_SPLIT = re.compile(r"(?:하고|하며|한\s*뒤|한\s*후|하여|, ?그리고|\s및\s|\s그리고\s)")

# validator: 의미 없는 일반 항목(원문 근거 없는 추상 조언) 차단
_GENERIC_BAD = [
    "핵심 내용", "세부 내용", "세부 핵심", "학습하기", "복습하기", "열심히",
    "꾸준히", "자료를 이해", "자료를 읽", "다음을 공부", "중요 개념을 다시",
    "내용 정리", "내용 학습",
]


# ══════════════════════════════════════════════════════════════════════════════
# [2] 텍스트 정규화 (PDF 줄바꿈/공백 복원, header/footer 제거)
# ══════════════════════════════════════════════════════════════════════════════
def _is_hangul(ch: str) -> bool:
    return bool(ch) and "가" <= ch <= "힣"


def _is_code_char(ch: str) -> bool:
    return bool(ch) and (ch.isascii() and (ch.isalnum() or ch in "_./:@-"))


def normalize_text(raw: str) -> str:
    """PDF/플래너 원문을 분석 가능한 형태로 정규화한다.

    - CRLF 통일, page-number/단독 noise 줄 제거
    - bullet/번호 목록 구조 보존(줄 유지)
    - 줄바꿈으로 깨진 한글 단어/코드 토큰을 복원(다음 줄과 병합)
    - 과도한 공백 축소
    """
    if not raw or not raw.strip():
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("­", "")  # soft hyphen 제거

    raw_lines = text.split("\n")
    lines: List[str] = []
    for ln in raw_lines:
        s = ln.strip()
        if not s:
            lines.append("")  # 문단 경계 보존
            continue
        if any(p.match(s) for p in _PAGE_NOISE):
            continue  # page number / header-footer noise 제거
        # 행 내부 과도 공백 축소(코드 토큰 내부에는 공백이 없으므로 안전)
        s = re.sub(r"[ \t ]{2,}", " ", s)
        lines.append(s)

    # 줄 병합: 직전 줄이 종결되지 않았고 다음 줄이 목록 시작이 아니면 깨진 줄로 보고 합친다.
    merged: List[str] = []
    for ln in lines:
        if ln == "":
            if merged and merged[-1] != "":
                merged.append("")
            continue
        if not merged or merged[-1] == "" or _BULLET_LINE.match(ln) or _looks_terminated(merged[-1]):
            merged.append(ln)
            continue
        prev = merged[-1]
        merged[-1] = _join_wrapped(prev, ln)

    out = "\n".join(merged)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def _looks_terminated(line: str) -> bool:
    """이 줄이 문장 종결(다./한다./. /?/!/:)로 끝나 다음 줄과 별개인지."""
    s = line.rstrip()
    if not s:
        return True
    if s.endswith((".", "?", "!", ":", "：")):
        return True
    if re.search(r"(다|요|음|함|임)\.?$", s) and s.endswith("."):
        return True
    return False


def _join_wrapped(prev: str, nxt: str) -> str:
    """PDF 줄바꿈으로 깨진 두 줄을 적절히 병합한다.

    - 한글-한글 연속(다음 줄이 공백 없이 이어짐) → 공백 없이 병합('테스트하'+'기' → '테스트하기')
    - 코드/식별자 연속(점 인접) → 공백 없이 병합('...data'+'.dto')
    - 그 외 → 공백 1개로 병합
    """
    if not prev:
        return nxt
    if not nxt:
        return prev
    last, first = prev[-1], nxt[0]
    no_space = (
        (_is_hangul(last) and _is_hangul(first))
        or first == "."
        or last == "."
        or (_is_code_char(last) and first == ".")
        or (last == "." and _is_code_char(first))
    )
    return prev + ("" if no_space else " ") + nxt


# ══════════════════════════════════════════════════════════════════════════════
# [3] 코드 토큰 보호 sentence splitter
# ══════════════════════════════════════════════════════════════════════════════
def protect_tokens(text: str) -> Tuple[str, Dict[str, str]]:
    """보호 대상 토큰을 placeholder 로 치환하고 (치환된 텍스트, 매핑)을 반환한다."""
    mapping: Dict[str, str] = {}
    idx = 0

    def _sub(m: "re.Match[str]") -> str:
        nonlocal idx
        key = f"{_PH_OPEN}P{idx}{_PH_CLOSE}"
        mapping[key] = m.group(0)
        idx += 1
        return key

    out = text
    for _name, pat in _PROTECT_PATTERNS:
        out = pat.sub(_sub, out)
    return out, mapping


def restore_tokens(text: str, mapping: Dict[str, str]) -> str:
    """placeholder 를 원래 토큰으로 복원한다."""
    if not mapping:
        return text
    for key, val in mapping.items():
        text = text.replace(key, val)
    return text


def split_sentences(text: str) -> List[str]:
    """코드 토큰을 보호한 뒤 문장 경계로 분리한다(스펙 [3]).

    절차: 1) 토큰 보호 → 2) 문장 끝/목록 경계 분리 → 3) placeholder 복원
          → 4) 짧은 조각 병합 → 5) 의미 없는 조각 제거
    """
    if not text or not text.strip():
        return []
    protected, mapping = protect_tokens(text)

    # 줄(목록 경계) 단위로 1차 분리 후, 각 줄을 종결부호로 2차 분리한다.
    raw_parts: List[str] = []
    for line in protected.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 종결부호(. ? !) 뒤에서 분리. 보호된 코드 점은 placeholder 라 영향 없음.
        for piece in re.split(r"(?<=[.?!])\s+", line):
            piece = piece.strip()
            if piece:
                raw_parts.append(piece)

    # placeholder 복원
    restored = [restore_tokens(p, mapping) for p in raw_parts]

    # 짧은 조각 병합 + 의미 없는 조각 제거
    merged: List[str] = []
    for p in restored:
        clean = _strip_list_prefix(p)
        if not clean:
            continue
        if len(clean) < MIN_SENTENCE_CHARS and merged:
            # 직전 문장에 붙여 의미를 보존(예: 잘린 꼬리)
            merged[-1] = (merged[-1] + " " + clean).strip()
        else:
            merged.append(clean)
    return [m for m in merged if _is_meaningful(m)]


def _strip_list_prefix(s: str) -> str:
    return _NUMBER_PREFIX.sub("", s, count=1).strip()


def _is_meaningful(s: str) -> bool:
    if len(s.strip()) < MIN_SENTENCE_CHARS:
        return False
    # 한글/영문 글자가 최소 2개 이상은 있어야 한다(기호/숫자만 X)
    return len(re.findall(r"[가-힣A-Za-z]", s)) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# [4] chunk 생성 (sourceType/pageNumber/chunkIndex/originalText/normalizedText)
# ══════════════════════════════════════════════════════════════════════════════
def build_chunks(source_texts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """sourceTexts 를 chunk metadata 목록으로 변환한다(스펙 [4])."""
    chunks: List[Dict[str, Any]] = []
    chunk_index = 0
    for src in source_texts or []:
        source_type = str(src.get("sourceType") or src.get("source_type") or "PLANNER").upper()
        page_number = src.get("pageNumber", src.get("page_number"))
        raw = str(src.get("text") or "")
        normalized = normalize_text(raw)
        if not normalized:
            continue
        for block in _split_blocks(normalized):
            for piece in _enforce_chunk_size(block):
                chunks.append({
                    "sourceType": source_type,
                    "pageNumber": page_number,
                    "chunkIndex": chunk_index,
                    "originalText": piece,
                    "normalizedText": piece,
                })
                chunk_index += 1
    return chunks


def _split_blocks(normalized: str) -> List[str]:
    """빈 줄(문단)/목록 경계 기준 1·2차 분리."""
    blocks: List[str] = []
    for para in re.split(r"\n\s*\n", normalized):
        para = para.strip()
        if not para:
            continue
        # 목록(번호/불릿)이 섞여 있으면 항목 묶음을 유지하되 과도하게 길면 아래에서 분할
        blocks.append(para)
    return blocks


def _enforce_chunk_size(block: str) -> List[str]:
    """긴 chunk 를 문장 경계 기준 500~1000자 단위로 분할(overlap 1문장)."""
    if len(block) <= CHUNK_MAX_CHARS:
        return [block]
    sentences = split_sentences(block) or [block]
    out: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for s in sentences:
        if cur and cur_len + len(s) > CHUNK_MAX_CHARS:
            out.append(" ".join(cur).strip())
            # overlap: 직전 마지막 문장 1개 유지
            cur = [cur[-1], s] if cur_len > CHUNK_SOFT_CHARS else [s]
            cur_len = sum(len(x) for x in cur)
        else:
            cur.append(s)
            cur_len += len(s)
    if cur:
        out.append(" ".join(cur).strip())
    return [o for o in out if o]


# ══════════════════════════════════════════════════════════════════════════════
# [5] action item extraction (행동 체크리스트 단위)
# ══════════════════════════════════════════════════════════════════════════════
def extract_action_items(sentence: str) -> List[str]:
    """한 문장을 체크 가능한 행동 단위 목록으로 분해한다(스펙 [5]).

    절차: 1) 코드 토큰 보호 → 2) 접속('하고/하며/및' 등) 경계로 절 분리
          → 3) 절 맨 앞 '산출물 생성'(예: 'X 패키지 추가') 분리
          → 4) 나머지 절을 행동 종결형으로 보정 → 5) 토큰 복원/검증.
    코드/패키지/파일/URL 토큰은 보호된 상태로만 다루므로 절대 분해되지 않는다.
    """
    sentence = sentence.strip()
    if not sentence:
        return []
    protected, mapping = protect_tokens(sentence)
    items: List[str] = []
    seen: set = set()

    def _add(prot_text: str) -> None:
        t = restore_tokens(prot_text, mapping)
        t = re.sub(r"\s{2,}", " ", t.strip()).rstrip(",;·:：").strip()
        if not t:
            return
        key = re.sub(r"\s+", "", t)
        if key in seen:
            return
        if not _is_meaningful(t) or _is_generic_item(t):
            return
        seen.add(key)
        items.append(t)

    clauses = [c.strip() for c in _CONJ_SPLIT.split(protected) if c and c.strip()]
    if not clauses:
        clauses = [protected]

    for clause in clauses:
        clause = _strip_list_prefix(clause)
        m = _LEAD_DELIVERABLE.match(clause)
        if m:
            # 산출물 항목: "<코드토큰/명사> <패키지/클래스/...> <추가/생성/...>"
            _add(f"{m.group(1)} {m.group(2)} {m.group(3)}")
            # 나머지 절(산출물 명사부터): 본 행동으로 별도 항목
            _add(_finalize_clause(clause[m.start(2):]))
        else:
            _add(_finalize_clause(clause))
    # 아무 것도 못 뽑았으면 원문 문장 자체를 보정해 1개 보존(빈 결과 금지)
    if not items:
        _add(_finalize_clause(protected))
    return items


def _finalize_clause(clause: str) -> str:
    """동사 종결이 없는 절을 자연스러운 행동 문장으로 보정(placeholder 보존 상태)."""
    c = _strip_list_prefix(clause).rstrip(" ,;·")
    if not c:
        return ""
    if re.search(r"(다|요|함|음)$", c):
        return c + "."
    if c.endswith((".", "?", "!")):
        return c
    # 마지막 동사 어간이 있으면 종결형으로 보정
    for stem, norm in _ACTION_VERBS:
        if c.endswith(stem):
            return c[: -len(stem)] + norm
    return c


def _is_generic_item(text: str) -> bool:
    """원문 근거 없는 일반/추상 항목인지(스펙 [5] 나쁜 항목, [7] reject)."""
    t = text.strip()
    if any(bad in t for bad in _GENERIC_BAD):
        return True
    # 동사/명사 없이 추상적인 짧은 명사구만 있는 경우
    if len(t) < 8 and not re.search(rf"({_VERB_ALT})", t):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# deterministic 파이프라인 (chunk → sentence → action item)
# ══════════════════════════════════════════════════════════════════════════════
def deterministic_items(chunks: List[Dict[str, Any]], max_items: int) -> Tuple[List[Dict[str, Any]], int]:
    """chunk 목록에서 결정론적으로 action item 을 생성한다. (items, sentence_count)."""
    items: List[Dict[str, Any]] = []
    sentence_count = 0
    seen: set = set()
    for ch in chunks:
        sentences = split_sentences(ch["normalizedText"])
        for s_idx, sent in enumerate(sentences):
            sentence_count += 1
            for action in extract_action_items(sent):
                key = re.sub(r"\s+", "", action)
                if key in seen:
                    continue
                seen.add(key)
                items.append({
                    "type": "ACTION",
                    "text": action,
                    "sourceText": sent,
                    "sourceType": ch["sourceType"],
                    "pageNumber": ch["pageNumber"],
                    "chunkIndex": ch["chunkIndex"],
                    "sentenceIndex": s_idx,
                })
                if len(items) >= max_items:
                    return items, sentence_count
    return items, sentence_count


# ══════════════════════════════════════════════════════════════════════════════
# [7] validator
# ══════════════════════════════════════════════════════════════════════════════
def validate_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """분석 결과 item 목록을 검증한다. {passed, reason}."""
    if not items:
        return {"passed": False, "reason": "items 가 비어 있음"}
    generic_only = True
    for i, it in enumerate(items):
        text = str(it.get("text") or "").strip()
        if len(text) < MIN_ITEM_CHARS:
            return {"passed": False, "reason": f"#{i+1} item.text 가 너무 짧음"}
        if not str(it.get("sourceText") or "").strip():
            return {"passed": False, "reason": f"#{i+1} sourceText 없음"}
        if any(m in text for m in ("```", "**", "###")):
            return {"passed": False, "reason": f"#{i+1} markdown/code fence 포함"}
        if "\n" in text or "\x01" in text or "\x02" in text:
            return {"passed": False, "reason": f"#{i+1} 깨진 줄바꿈/placeholder 잔여"}
        # 패키지명 중간 잘림: 점으로 끝나거나 점으로 시작
        if re.search(r"(^|\s)\.[A-Za-z]", text) or re.search(r"[A-Za-z]\.(\s|$)", text):
            return {"passed": False, "reason": f"#{i+1} 코드 토큰이 중간에서 잘림"}
        # com / example / dto 가 단독 item 으로 분해된 경우
        if text.strip().lower() in ("com", "example", "dto", "org", "java", "kt", "kts"):
            return {"passed": False, "reason": f"#{i+1} 코드 토큰 파편이 단독 item"}
        if not _is_generic_item(text):
            generic_only = False
    if generic_only:
        return {"passed": False, "reason": "일반/추상 항목만 존재(원문 근거 행동 없음)"}
    return {"passed": True, "reason": "원문 근거 행동 체크리스트 검증 통과"}


# ══════════════════════════════════════════════════════════════════════════════
# [6] LLM 보정(보조) — 실패/검증불통과 시 deterministic 반환
# ══════════════════════════════════════════════════════════════════════════════
def _llm_refine_items(det_items: List[Dict[str, Any]], language: str = "ko") -> Optional[List[Dict[str, Any]]]:
    """deterministic 후보를 LLM 으로 다듬는다(원문 근거/코드 토큰 보존). 실패 시 None."""
    try:
        from app.api.planner_ai_routes import _llm  # Ollama 우선 + GPT fallback 공용 헬퍼
        from app.utils.json_parser import extract_json
    except Exception as e:  # noqa: BLE001
        logger.info("plan-analysis LLM 헬퍼 임포트 실패: %s", e)
        return None

    payload = [{"text": it["text"], "sourceText": it["sourceText"]} for it in det_items[:30]]
    import json as _json
    system = (
        "너는 학습 계획을 '체크 가능한 행동 항목'으로 다듬는 도우미다. "
        "반드시 제공된 sourceText 원문 안의 내용만 사용한다. 원문에 없는 일반 조언은 금지한다. "
        "패키지/클래스/파일명/URL/버전 같은 코드 토큰은 원문 그대로 보존한다. "
        "마크다운 없이 JSON 으로만 응답한다."
    )
    user = (
        "아래 후보를 각각 더 명확한 행동 문장으로 다듬어라. 개수는 유지하거나 의미 단위로 분리만 허용한다.\n"
        f"## 후보(JSON)\n{_json.dumps(payload, ensure_ascii=False)}\n\n"
        '아래 형식으로만 응답하라: {"items":[{"text":"행동 문장","sourceText":"근거 원문"}]}'
    )
    try:
        raw = _llm(system, user, 1200)
    except Exception as e:  # noqa: BLE001
        logger.info("plan-analysis LLM 호출 실패: %s", e)
        return None
    if not raw or raw.strip().startswith("[GPT") or raw.strip().startswith("["):
        return None
    parsed = extract_json(raw)
    arr = parsed.get("items") if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else None)
    if not isinstance(arr, list) or not arr:
        return None
    # LLM 결과를 deterministic 메타(출처)에 다시 매핑(원문 보존)
    out: List[Dict[str, Any]] = []
    for i, obj in enumerate(arr):
        if not isinstance(obj, dict):
            continue
        text = re.sub(r"\s{2,}", " ", str(obj.get("text") or "").strip())
        src = str(obj.get("sourceText") or "").strip()
        base = det_items[i] if i < len(det_items) else det_items[-1]
        if not text or not src:
            continue
        out.append({**base, "text": text, "sourceText": src})
    return out or None


# ══════════════════════════════════════════════════════════════════════════════
# 메인 진입점: 계획 분석
# ══════════════════════════════════════════════════════════════════════════════
def analyze_plan(req: Dict[str, Any]) -> Dict[str, Any]:
    """PDF/플래너 sourceTexts 를 계획 분석 결과로 변환한다.

    Returns: 성공 시 {summary, items, recommendations, meta}.
             실패 시 {code, message, meta?} (빈 배열로 숨기지 않음 — 스펙 [9]).
    """
    options = req.get("options") or {}
    max_items = int(options.get("maxItems") or DEFAULT_MAX_ITEMS)
    language = str(options.get("language") or "ko")
    no_llm = bool(req.get("_no_llm"))
    source_texts = req.get("sourceTexts") or []

    total_src_len = sum(len(str(s.get("text") or "")) for s in source_texts)
    if not source_texts or total_src_len == 0:
        return {"code": "PLAN_ANALYSIS_TEXT_EMPTY", "message": "분석할 PDF/플래너 텍스트가 없습니다."}

    chunks = build_chunks(source_texts)
    if not chunks:
        return {"code": "PLAN_ANALYSIS_TEXT_EMPTY", "message": "분석할 PDF/플래너 텍스트가 없습니다."}

    det_items, sentence_count = deterministic_items(chunks, max_items)
    if not det_items:
        return {"code": "PLAN_ANALYSIS_TEXT_EMPTY", "message": "분석할 PDF/플래너 텍스트가 없습니다."}

    # LLM 보정 1회 시도 → 검증 통과 시만 사용, 아니면 deterministic
    mode = "DETERMINISTIC_ONLY"
    final_items = det_items
    if not no_llm:
        refined = _llm_refine_items(det_items, language)
        if refined:
            check = validate_items(refined)
            if check["passed"]:
                final_items = refined
                mode = "DETERMINISTIC_PLUS_LLM"
            else:
                logger.info("plan-analysis LLM 보정 검증 실패 → deterministic 사용: %s", check["reason"])

    check = validate_items(final_items)
    if not check["passed"]:
        # 계약 위반: deterministic 으로 한 번 더 확정
        check_det = validate_items(det_items)
        if check_det["passed"]:
            final_items, mode = det_items, "DETERMINISTIC_ONLY"
            check = check_det
        else:
            return {"code": "PLAN_ANALYSIS_CONTRACT_VIOLATION",
                    "message": "분석 결과 형식이 올바르지 않습니다.",
                    "validation": check}

    final_items = final_items[:max_items]
    recommendations = build_recommendations(final_items)
    summary = _build_summary(final_items, chunks)

    return {
        "summary": summary,
        "items": final_items,
        "recommendations": recommendations,
        "meta": {
            "requestId": req.get("requestId"),
            "materialId": req.get("materialId"),
            "sourceTextCount": len(source_texts),
            "sourceTextLength": total_src_len,
            "chunkCount": len(chunks),
            "sentenceCount": sentence_count,
            "itemCount": len(final_items),
            "mode": mode,
        },
    }


def _build_summary(items: List[Dict[str, Any]], chunks: List[Dict[str, Any]]) -> str:
    n = len(items)
    pages = sorted({c["pageNumber"] for c in chunks if c.get("pageNumber") is not None})
    page_str = (f" (p.{', p.'.join(str(p) for p in pages)})" if pages else "")
    head = items[0]["text"] if items else ""
    return (f"PDF/플래너에서 {len(chunks)}개 청크를 분석해 {n}개의 실행 항목을 도출했습니다{page_str}. "
            f"대표 항목: {head}")


# ══════════════════════════════════════════════════════════════════════════════
# [8] 다음 학습 추천 (미완료 item 기반)
# ══════════════════════════════════════════════════════════════════════════════
def build_recommendations(items: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    """미완료(completed=false, hidden=false) item 을 근거로 추천 문장을 만든다.

    PDF/플래너 원문에 없는 일반 조언은 만들지 않는다(스펙 [8]).
    """
    pending = [
        it for it in items
        if not bool(it.get("completed")) and not bool(it.get("hidden"))
    ]
    # 앞쪽 chunk/sentence 우선 + 명확한 action(테스트/구현/정리/설계/분리) 우선
    def _rank(it: Dict[str, Any]) -> Tuple[int, int, int]:
        text = str(it.get("text") or "")
        strong = 0 if re.search(r"(테스트|구현|설계|분리|정리|작성|구성)", text) else 1
        return (strong, int(it.get("chunkIndex") or 0), int(it.get("sentenceIndex") or 0))

    pending.sort(key=_rank)
    recs: List[str] = []
    for it in pending[:limit]:
        text = str(it.get("text") or "").strip().rstrip(".")
        if not text:
            continue
        page = it.get("pageNumber")
        src_type = it.get("sourceType") or "PLANNER"
        loc = ""
        if src_type == "PDF" and page is not None:
            loc = f"PDF p.{page}의 "
        if re.search(r"테스트", text):
            recs.append(f"다음에는 {loc}'{text}' 항목이 아직 남아 있으므로, 성공/실패/예외 케이스로 나누어 먼저 완료하세요.")
        else:
            recs.append(f"다음에는 {loc}'{text}' 항목을 먼저 완료하세요.")
    return recs


def recommend_next(req: Dict[str, Any]) -> Dict[str, Any]:
    """/api/ai/plan-recommendation 진입점."""
    items = req.get("items") or []
    norm: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        norm.append({
            "text": str(it.get("text") or "").strip(),
            "completed": bool(it.get("completed")),
            "hidden": bool(it.get("hidden")),
            "sourceText": str(it.get("sourceText") or "").strip(),
            "sourceType": it.get("sourceType") or "PLANNER",
            "pageNumber": it.get("pageNumber"),
            "chunkIndex": it.get("chunkIndex") or 0,
            "sentenceIndex": it.get("sentenceIndex") or 0,
        })
    basis = [it for it in norm if it["text"] and not it["completed"] and not it["hidden"]]
    recommendations = build_recommendations(norm)
    return {
        "recommendations": recommendations,
        "meta": {
            "requestId": req.get("requestId"),
            "materialId": req.get("materialId"),
            "basisItemCount": len(basis),
        },
    }
