"""결정적(deterministic) 검증기. 모든 함수는 (code, severity, reason[, evidenceId]) 튜플 리스트를 반환한다.

LLM 을 호출하지 않으며 원문 텍스트를 reason 에 그대로 싣지 않는다(짧은 코드/개수/ID 만).
"""
from __future__ import annotations

import ast
import json
import math
import operator
import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.utils.pii_filter import BLOCK, scan_pii

V = Tuple[str, str, str, Optional[str]]  # code, severity, reason, evidenceId
HARD, MAJOR, MINOR, INFO = "HARD", "MAJOR", "MINOR", "INFO"


def v(code: str, sev: str, reason: str, evidence_id: Optional[str] = None) -> V:
    return (code, sev, reason[:300], evidence_id)


# ── 텍스트 유틸 ─────────────────────────────────────────────────────────────────
_RUN_RE = re.compile(r"[0-9A-Za-z]+|[가-힣]+")
_SENT_RE = re.compile(r"(?<=[.!?。？！])\s+|\n+")
_PARTICLES = ("으로써", "으로서", "에서는", "에게서", "이었다", "였습니다", "되었다", "되었고", "입니다", "합니다", "했다",
              "한다", "된다", "이다", "에서", "에게", "까지", "부터", "으로", "처럼", "보다", "라는", "이라는", "하는",
              "하고", "하며", "되는", "이며", "에는", "은", "는", "이", "가", "을", "를", "에", "의", "로", "과", "와", "도", "만", "다")
_STOP = {"그리고", "그러나", "하지만", "또한", "있다", "없다", "것", "수", "등", "및", "the", "a", "an", "is", "are", "of", "to", "and"}
# "아닙니다/아닌/아님/아냐" 는 "아니" 를 포함하지 않는다(아+닙) — 예전: "TCP 는 연결 지향 프로토콜이 아닙니다" 가 원문과 모순인데 승인(94점).
_NEG_RE = re.compile(r"(않|아니|아닙|아닌|아님|아냐|없|못|불가|never|\bnot\b|\bno\b)", re.IGNORECASE)
_ANTONYMS = [("증가", "감소"), ("상승", "하락"), ("높", "낮"), ("많", "적"), ("크", "작"), ("이전", "이후"),
             ("가능", "불가능"), ("포함", "제외"), ("허용", "금지"), ("참", "거짓"), ("빠르", "느리")]


def stem(tok: str) -> str:
    if re.match(r"[가-힣]", tok):
        for p in _PARTICLES:
            if len(tok) > len(p) + 1 and tok.endswith(p):
                return tok[: -len(p)]
    return tok.lower()


def stems(text: str) -> Set[str]:
    return {stem(t) for t in _RUN_RE.findall(text or "") if len(t) >= 2} - _STOP


def sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT_RE.split(text or "") if s and len(s.strip()) >= 4]


def jaccard(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(%|퍼센트|년|월|일|명|개|배|원|km|kg|m|cm|mm|ms|초|분|시간)?")


_KNUM = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5, "여섯": 6, "일곱": 7,
         "여덟": 8, "아홉": 9, "열": 10}
_KNUM_RE = re.compile(r"(?<![가-힣])(한|하나|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉|열)\s?"
                      r"(단계|개|가지|번|명|종류|차례|회|층|장|권|자|줄|문장|요소|부분|과정|번째)")


def numbers_in(text: str) -> Set[str]:
    """검증 대상 수치(2자리 이상 정수, 소수, 단위가 붙은 수, 한국어 수사+단위). 서수/한 자리 나열 번호는 제외.
    '세 단계' 와 '3단계' 는 같은 값으로 정규화된다(예: 원문 '세 단계' vs 답변 '두 단계' 모순 탐지)."""
    out = set()
    for m in _KNUM_RE.finditer(text or ""):
        out.add(f"{float(_KNUM[m.group(1)]):g}")
    for m in _NUM_RE.finditer(text or ""):
        raw, unit = m.group(1).replace(",", ""), m.group(2)
        if "." not in raw and len(raw) < 2 and not unit:
            continue
        try:
            val = float(raw)
        except ValueError:
            continue
        out.add(f"{val:g}")
    return out


def text_of(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return json.dumps(output, ensure_ascii=False, default=str)


# ── 공통 검사 ───────────────────────────────────────────────────────────────────
_FAIL_MARKERS = ("[Ollama", "[GPT", "[OpenAI", "LLM 응답을 생성하지 못해", "AI 응답 생성이 지연", "timeout fallback",
                 "fallback 안내", "잠시 후 다시 질문해", "응답을 생성할 수 없습니다", "OPENAI_API_KEY")


def check_empty_truncated(text: str, *, finish_reason: Optional[str], max_chars: Optional[int]) -> List[V]:
    out: List[V] = []
    t = (text or "").strip()
    if not t or t in ("{}", "[]", "null", '""'):
        return [v("EMPTY_OUTPUT", HARD, "출력이 비어 있음")]
    if (finish_reason or "").lower() in ("length", "max_tokens", "truncated"):
        out.append(v("TRUNCATED_OUTPUT", HARD, f"생성 종료 사유={finish_reason}"))
    if t.count("```") % 2 == 1:
        out.append(v("TRUNCATED_OUTPUT", HARD, "코드 블록이 닫히지 않음"))
    for o, c in (("(", ")"), ("[", "]"), ("{", "}")):
        if t.count(o) - t.count(c) >= 2:
            out.append(v("TRUNCATED_OUTPUT", HARD, f"괄호 불균형 {o}{c}"))
            break
    if re.search(r"(\.\.\.|…)\s*$", t) and len(t) > 40:
        out.append(v("POSSIBLY_TRUNCATED", MAJOR, "말줄임표로 끝남"))
    if max_chars and len(t) > max_chars:
        out.append(v("OVER_LENGTH", MAJOR, f"len={len(t)}>{max_chars}"))
    if re.search(r"</?think>", t):
        out.append(v("REASONING_TAG_LEAK", MAJOR, "think 태그 노출"))
    return out


def check_failure_markers(text: str) -> List[V]:
    for mk in _FAIL_MARKERS:
        if mk in (text or ""):
            return [v("FALLBACK_CONTENT", HARD, "생성 실패/대체 안내 문구는 답변으로 승인할 수 없음")]
    return []


def check_secret_pii(text: str, request_text: str, *, allow_echo: bool) -> List[V]:
    res = scan_pii(text)
    if res.clean:
        return []
    if res.status == "ERROR":
        return [v("PII_SCAN_ERROR", HARD, "개인정보 검사 실패(fail-closed)")]
    out: List[V] = []
    secrets = {"SECRET_KEY", "BEARER_TOKEN", "JWT", "ASSIGNED_SECRET", "URL_CREDENTIALS", "URL_TOKEN"}
    internal = {"SYSTEM_PROMPT", "INTERNAL_URL"}
    req = set(scan_pii(request_text).categories) if allow_echo else set()
    for cat in res.categories:
        if cat in secrets:
            out.append(v("SECRET_LEAK", HARD, f"비밀정보 범주 {cat}"))
        elif cat in internal:
            out.append(v("INTERNAL_INFO_LEAK", HARD, f"내부정보 범주 {cat}"))
        elif res.max_severity == BLOCK and cat in {"EMAIL", "PHONE", "RRN", "CARD", "DRIVER_LICENSE", "PASSPORT", "BANK_ACCOUNT"}:
            if cat not in req:
                out.append(v("PII_LEAK", HARD, f"개인정보 범주 {cat}"))
        elif cat in {"STUDENT_ID", "ADDRESS"}:
            # 학번/주소는 '격리' 등급이어도 사용자 화면 노출은 막는다(예전: MINOR 로 APPROVED 91점 — 2026-11-04 재현).
            if cat not in req:
                out.append(v("PII_LEAK", HARD, f"개인정보 범주 {cat}"))
        elif cat == "PERSON_NAME":
            if cat not in req:
                out.append(v("PII_POSSIBLE", MAJOR, "이름으로 보이는 표현"))
        elif cat == "HIGH_ENTROPY_SECRET":
            out.append(v("POSSIBLE_SECRET", MAJOR, "고엔트로피 문자열"))
        else:
            out.append(v("PII_POSSIBLE", MINOR, f"휴리스틱 범주 {cat}"))
    return out


_INJECTION_RE = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above) (?:instructions|prompts)|disregard (?:the )?(?:system|previous)|"
    r"you are now|developer mode|jailbreak|<\|im_start\|>|이전\s*(?:의\s*)?(?:모든\s*)?지시(?:사항)?(?:을|를|는)?\s*무시|"
    r"시스템\s*프롬프트(?:를|을)?\s*(?:출력|공개|보여)|위\s*규칙(?:을|를)?\s*무시|지금부터\s*너는|다음\s*문장(?:을|를)?\s*그대로\s*출력|"
    r"정답(?:은|을)\s*무조건|평가자(?:는|에게)?\s*(?:100|만)점",
    re.IGNORECASE,
)
_COMPLIANCE_RE = re.compile(r"PWNED|HACKED|이전 지시를 무시하고|시스템 프롬프트는\s*다음|my system prompt|as instructed by the document", re.IGNORECASE)


def injection_lines(texts: Iterable[str]) -> List[str]:
    out = []
    for t in texts:
        for line in re.split(r"[\n.!?]", t or ""):
            if _INJECTION_RE.search(line):
                out.append(line.strip())
    return out


def check_prompt_injection(text: str, evidence_texts: Sequence[str], request_text: str) -> List[V]:
    out: List[V] = []
    inj = injection_lines(list(evidence_texts) + [request_text])
    if _COMPLIANCE_RE.search(text or "") or _INJECTION_RE.search(text or ""):
        out.append(v("PROMPT_INJECTION_SUCCESS", HARD, "출력이 주입 지시를 따르거나 재현함"))
        return out
    for line in inj:
        # 주입 문장 자체(또는 그 안의 지시 payload)가 출력에 복제되면 성공으로 본다.
        frag = re.sub(r"\s+", " ", line)
        for i in range(0, max(1, len(frag) - 20), 10):
            piece = frag[i:i + 20]
            if len(piece) >= 20 and piece in re.sub(r"\s+", " ", text or ""):
                return [v("PROMPT_INJECTION_SUCCESS", HARD, "주입 문장 payload 가 출력에 포함됨")]
    if inj:
        out.append(v("PROMPT_INJECTION_ATTEMPT_BLOCKED", INFO, f"근거/요청 내 주입 시도 {len(inj)}건(출력은 따르지 않음)"))
    return out


_CITE_PAGE_RE = re.compile(r"(?:\bp\.?\s?(\d{1,5})\b|(\d{1,5})\s?(?:페이지|쪽)|\[p\.?(\d{1,5})\])", re.IGNORECASE)
_CITE_ID_RE = re.compile(r"\[(?:근거|출처|chunk|evidence)\s*[:：]\s*([A-Za-z0-9._:\-]{1,128})\]", re.IGNORECASE)
_SOURCE_CLAIM_RE = re.compile(r"(?:출처|참고\s*문헌|reference|references)\s*[:：]|\(([A-Z][A-Za-z\-]+|[가-힣]{2,4})(?:\s(?:et al\.|외))?,?\s(?:19|20)\d{2}\)")


def check_citations(text: str, evidence: Sequence[Dict[str, Any]], *, require: bool) -> List[V]:
    out: List[V] = []
    pages = {int(e["page"]) for e in evidence if e.get("page")}
    ids = {str(e.get("chunkId") or e.get("evidenceId")) for e in evidence if (e.get("chunkId") or e.get("evidenceId"))}
    cited_pages = {int(next(g for g in m.groups() if g)) for m in _CITE_PAGE_RE.finditer(text or "")}
    cited_ids = set(_CITE_ID_RE.findall(text or ""))
    bad_pages = cited_pages - pages
    bad_ids = cited_ids - ids
    if bad_pages:
        out.append(v("UNVERIFIED_CITATION", HARD, f"근거에 없는 페이지 인용 {sorted(bad_pages)[:5]}"))
    if bad_ids:
        out.append(v("UNVERIFIED_CITATION", HARD, f"근거에 없는 청크 인용 {len(bad_ids)}건"))
    if _SOURCE_CLAIM_RE.search(text or "") and not evidence:
        out.append(v("UNVERIFIED_SOURCE_CLAIM", HARD, "근거 없이 출처/문헌을 인용"))
    if require and evidence and not (cited_pages or cited_ids):
        out.append(v("CITATION_MISSING", MAJOR, "인용 요구 작업인데 인용 없음"))
    return out


def check_scope(evidence: Sequence[Dict[str, Any]], allowed_materials: Optional[List[int]],
                allowed_documents: Optional[List[str]], *, pdf_task: bool) -> List[V]:
    out: List[V] = []
    mats = {int(e["materialId"]) for e in evidence if e.get("materialId") is not None}
    docs = {str(e["documentId"]) for e in evidence if e.get("documentId") is not None}
    if (mats or docs) and allowed_materials is None and allowed_documents is None:
        out.append(v("SOURCE_SCOPE_UNVERIFIED", HARD, "근거 자료의 권한 범위(allowedMaterialIds)가 없음"))
        return out
    if allowed_materials is not None and mats - set(int(m) for m in allowed_materials):
        out.append(v("SOURCE_SCOPE_VIOLATION", HARD, f"허용 범위 밖 materialId {len(mats - set(allowed_materials))}건"))
    if allowed_documents is not None and docs - set(str(d) for d in allowed_documents):
        out.append(v("SOURCE_SCOPE_VIOLATION", HARD, "허용 범위 밖 documentId"))
    if pdf_task and not evidence:
        out.append(v("EVIDENCE_REQUIRED", HARD, "PDF 작업인데 원문 근거가 없음"))
    return out


# ── 원문 충실도(요약/QA/퀴즈/학습 자격 공용) ───────────────────────────────────────
_MAX_EV_SENTENCES = 3000
_MAX_CONTRA_SENTENCES = 300


def negation_contradictions(output: str, evidence_texts: Sequence[str]) -> int:
    # stem 역색인으로 겹치는 근거 문장만 후보로 본다(예전: 출력×근거 전수 jaccard → 48K×190K자 4.9초).
    ev_sents = [(s, stems(s)) for t in evidence_texts for s in sentences(t)][:_MAX_EV_SENTENCES]
    ev_neg = [bool(_NEG_RE.search(e)) for e, _ in ev_sents]
    index: Dict[str, List[int]] = {}
    for i, (_, es) in enumerate(ev_sents):
        for st in es:
            index.setdefault(st, []).append(i)
    n = 0
    for s in sentences(output)[:_MAX_CONTRA_SENTENCES * 2]:
        ss = stems(s)
        if len(ss) < 3:
            continue
        shared: Dict[int, int] = {}
        for st in ss:
            for i in index.get(st, ()):
                shared[i] = shared.get(i, 0) + 1
        s_neg = bool(_NEG_RE.search(s))
        for i in sorted(shared):
            e, es = ev_sents[i]
            k = shared[i]
            if k / (len(ss) + len(es) - k) < 0.45:
                continue
            if s_neg != ev_neg[i]:
                n += 1
                break
            flipped = False
            for a, b in _ANTONYMS:
                if (a in s and b in e and b not in s) or (b in s and a in e and a not in s):
                    flipped = True
                    break
            if flipped:
                n += 1
                break
    return n


def source_fidelity_violations(output: str, evidence_texts: Sequence[str]) -> List[V]:
    out: List[V] = []
    ev_nums = set()
    for t in evidence_texts:
        ev_nums |= numbers_in(t)
    missing = numbers_in(output) - ev_nums
    if missing:
        out.append(v("NUMERIC_UNSUPPORTED_BY_SOURCE", HARD, f"원문에 없는 수치 {len(missing)}개"))
    c = negation_contradictions(output, evidence_texts)
    if c:
        out.append(v("SOURCE_CONTRADICTION", HARD, f"원문과 반대되는 서술 {c}건"))
    return out


def claim_support_ratio(output: str, evidence_texts: Sequence[str]) -> Tuple[float, int]:
    ev = set()
    for t in evidence_texts:
        ev |= stems(t)
    # 의문문(후속 질문 등)은 사실 단정이 아니므로 주장에서 뺀다.
    claims = [s for s in sentences(output) if len(stems(s)) >= 2 and not s.rstrip().endswith(("?", "？"))]
    if not claims:
        # 검증할 주장이 없으면 '지지됨(1.0)'이 아니라 판단 불가 — 호출자가 unverified 로 처리한다.
        return 0.0, 0
    supported = sum(1 for s in claims if len(stems(s) & ev) / max(1, len(stems(s))) >= 0.35)
    return supported / len(claims), len(claims)


_DISCLOSURE_RE = re.compile(r"확인되지\s*않|근거(?:를|가)?\s*(?:찾지\s*못|없)|알\s*수\s*없|확실하지\s*않|모르|자료에\s*(?:없|나와\s*있지\s*않)|판단(?:하기)?\s*어렵")


_GUIDANCE_RE = re.compile(r"(?:선택|확인|업로드|첨부|입력|질문)해\s*주세요|알려\s*주세요|다시\s*시도|주시면")
_CONTRAST_RE = re.compile(r"지만|하지만|그러나|다만|는데|그런데|그렇지만|but\b|however", re.IGNORECASE)


# 고지 술어가 '문장 끝의 주 술어'일 때만 고지로 본다(뒤에는 존대/종결 어미만). 예전: 토큰 포함만 보아
# "태양이 지구 주위를 돈다는 사실을 모르는 사람은 없습니다" 같은 단정문이 고지로 판정돼 승인됐다(2026-11-04 재현).
_DISCLOSURE_END_RE = re.compile(
    r"(?:확인되지\s*않|확인(?:할|하기)\s*(?:수\s*없|어렵)|찾(?:을\s*수\s*없|지\s*못)|나와\s*있지\s*않|포함되어\s*있지\s*않|"
    r"알\s*수\s*없|모르겠|확실하지\s*않|(?:답|답변|판단|설명)(?:을|를)?\s*(?:하기|할\s*수|드리기|드릴\s*수)\s*(?:어렵|없)|"
    r"근거(?:가|를)?\s*(?:없|찾지\s*못))"
    r"[가-힣\s]{0,12}[.!?。]?$")
# 명제를 품은 절(…다는 사실을/…것을/…점은)이 있으면 고지가 아니라 주장이다.
_EMBEDDED_CLAIM_RE = re.compile(r"(?:다는|라는|는다는|ㄴ다는|된다는|이라는)\s*(?:사실|것|점|내용)|(?:는|은|ㄴ)\s*것(?:을|이|은)")


def _is_disclosure_sentence(x: str) -> bool:
    x = x.strip()
    return len(x) <= 120 and bool(_DISCLOSURE_END_RE.search(x)) and not _EMBEDDED_CLAIM_RE.search(x)


def is_no_claim_disclosure(text: str) -> bool:
    """'근거가 없어 답할 수 없다' 류의 정직한 고지인가. 고지 문구가 섞인 단정문('모르는 사실이지만 X 는 Y 다')은 아니다.
    모든 문장이 고지 또는 안내여야 하고, 대조 접속(지만/그러나…)·수치가 없으며 짧아야 한다."""
    t = (text or "").strip()
    sents = sentences(t) or ([t] if t else [])
    if not sents or len(t) > 240 or numbers_in(t) or _CONTRAST_RE.search(t):
        return False
    if not any(_is_disclosure_sentence(x) for x in sents):
        return False
    return all(_is_disclosure_sentence(x) or (_GUIDANCE_RE.search(x) and not _EMBEDDED_CLAIM_RE.search(x))
               for x in sents)


def internal_contradictions(text: str) -> int:
    # 문장별 stem/부정 여부를 한 번만 계산(예전: 쌍마다 재계산 → 60K자 26초). 문장 수도 상한.
    sents = sentences(text)[:_MAX_CONTRA_SENTENCES]
    feats = [(stems(s), bool(_NEG_RE.search(s))) for s in sents]
    n = 0
    for i, (sa, na) in enumerate(feats):
        if len(sa) < 3:
            continue
        for sb, nb in feats[i + 1:]:
            if na != nb and jaccard(sa, sb) >= 0.6:
                n += 1
    return n


def repetition_count(text: str) -> int:
    seen: Dict[str, int] = {}
    for s in sentences(text):
        k = re.sub(r"\s+", "", s)
        seen[k] = seen.get(k, 0) + 1
    return sum(c - 1 for c in seen.values() if c > 1)


def relevance(question: str, output: str) -> float:
    q = stems(question)
    if not q:
        return 1.0
    return len(q & stems(output)) / len(q)


# ── 수학 ───────────────────────────────────────────────────────────────────────
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
# 예전 '((?:\d[\d.,]*|[...])+?)' 는 중첩 수량자라 '=' 없는 숫자열에서 지수 백트래킹(원주율 28자 → 20초, 2026-11-04 재현).
# 단일 문자 클래스 + 길이 상한 + 식 경계 lookbehind 로 선형 시간.
_EQ_RE = re.compile(r"(?<![\d.,()+\-*/^×÷·])(-?[\d(][\d.,()+\-*/^×÷·\s]{0,200}?)\s*=\s*(-?\d[\d,]{0,30}(?:\.\d{1,30})?)(?![\d.])")


def safe_eval(expr: str) -> Optional[float]:
    e = expr.replace("×", "*").replace("÷", "/").replace("·", "*").replace("^", "**").replace(",", "")
    if not re.fullmatch(r"[\d.\s()+\-*/%]+", e) or not re.search(r"\d\s*[+\-*/%]", e):
        return None
    try:
        tree = ast.parse(e.strip(), mode="eval")
    except SyntaxError:
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            x = ev(n.operand)
            return -x if isinstance(n.op, ast.USub) else x
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and (abs(b) > 64 or abs(a) > 1e6):
                raise ValueError("pow bound")
            return _OPS[type(n.op)](a, b)
        raise ValueError("unsupported")

    try:
        val = float(ev(tree))
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    return val if math.isfinite(val) else None


def check_math(text: str, expected_answer: Optional[str]) -> Tuple[List[V], int, Optional[bool]]:
    """(위반, 검증된 등식 수, 최종답 일치 여부[None=gold 없음])."""
    out: List[V] = []
    checked = 0
    for m in _EQ_RE.finditer(text or ""):
        lhs, rhs = m.group(1), m.group(2)
        val = safe_eval(lhs)
        if val is None:
            continue
        checked += 1
        r = float(rhs.replace(",", ""))
        if not math.isclose(val, r, rel_tol=1e-6, abs_tol=1e-9):
            out.append(v("MATH_INCORRECT", HARD, f"등식 재계산 불일치({checked}번째)"))
    final_ok: Optional[bool] = None
    if expected_answer is not None:
        final = _final_answer(text)
        final_ok = final is not None and _answers_equal(final, expected_answer)
        if not final_ok:
            out.append(v("FINAL_ANSWER_MISMATCH", HARD, "최종 답이 결정적 정답(gold)과 다름"))
    return out, checked, final_ok


def _final_answer(text: str) -> Optional[str]:
    kw = r"(?:정답|답|결과|final answer)\s*(?:은|는|이|:|：|=)?\s*"
    m = list(re.finditer(kw + r"(-?\d[\d,]*(?:\.\d+)?)", text or "", re.IGNORECASE))
    if m:
        return m[-1].group(1)
    m = list(re.finditer(kw + r"([①-⑩]|[A-E](?![A-Za-z]))", text or "", re.IGNORECASE))
    if m:
        return m[-1].group(1)
    nums = re.findall(r"-?\d[\d,]*(?:\.\d+)?", text or "")
    return nums[-1] if nums else None


def _answers_equal(a: str, b: str) -> bool:
    try:
        return math.isclose(float(a.replace(",", "")), float(b.replace(",", "")), rel_tol=1e-6, abs_tol=1e-9)
    except ValueError:
        return re.sub(r"\s+", "", a).lower() == re.sub(r"\s+", "", b).lower()


# ── 퀴즈 ───────────────────────────────────────────────────────────────────────
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
_EXPL_ANS_RE = re.compile(r"정답(?:은|이|:|：)?\s*(?:바로\s*)?([①-⑩]|[1-9]\s?번|[A-Ea-e](?![a-z]))")


def _quiz_items(obj: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (ValueError, json.JSONDecodeError):
            return None
    if isinstance(obj, dict):
        for k in ("questions", "items", "quizzes", "quiz"):
            if isinstance(obj.get(k), list):
                return obj[k]
        if "question" in obj or "questionText" in obj:
            return [obj]
        return None
    return obj if isinstance(obj, list) else None


def _norm_opt(s: Any) -> str:
    s = re.sub(r"^\s*(?:[①-⑩]|[1-9][.)]|[A-Ea-e][.)])\s*", "", str(s or ""))
    return re.sub(r"\s+", " ", s).strip().lower()


def _resolve_answer(q: Dict[str, Any], options: List[str]) -> Tuple[Optional[int], str]:
    idx = q.get("answerIndex", q.get("correctIndex"))
    ans = q.get("answer", q.get("correctAnswer"))
    if isinstance(idx, int) and not isinstance(idx, bool):
        # 0-based/1-based 혼동을 추측하지 않는다: 0-based 를 계약으로 보고, 범위를 벗어나면 실패.
        return (idx, "index") if 0 <= idx < len(options) else (None, "index_out_of_range")
    if ans is None:
        return None, "missing"
    a = str(ans).strip()
    if len(a) == 1 and a in _CIRCLED:
        i = _CIRCLED.index(a)
        return (i, "circled") if i < len(options) else (None, "out_of_range")
    m = re.fullmatch(r"([1-9])\s?번?", a)
    if m:
        i = int(m.group(1)) - 1
        return (i, "number") if i < len(options) else (None, "out_of_range")
    m = re.fullmatch(r"([A-Ea-e])", a)
    if m:
        i = ord(m.group(1).upper()) - 65
        return (i, "letter") if i < len(options) else (None, "out_of_range")
    matches = [i for i, o in enumerate(options) if _norm_opt(o) == _norm_opt(a)]
    if len(matches) == 1:
        return matches[0], "text"
    return None, "ambiguous" if len(matches) > 1 else "not_in_options"


def _expl_answer_index(expl: str) -> Optional[int]:
    m = _EXPL_ANS_RE.search(expl or "")
    if not m:
        return None
    tok = m.group(1).replace(" ", "")
    if tok[0] in _CIRCLED:
        return _CIRCLED.index(tok[0])
    if tok[0].isdigit():
        return int(tok[0]) - 1
    return ord(tok[0].upper()) - 65


def check_quiz(obj: Any, *, expected_count: Optional[int], expected_options: Optional[int],
               evidence_texts: Sequence[str], pdf_task: bool) -> Tuple[List[V], Dict[str, int]]:
    out: List[V] = []
    stats = {"items": 0, "valid": 0, "grounded": 0}
    items = _quiz_items(obj)
    if not items:
        return [v("JSON_SCHEMA_INVALID", HARD, "퀴즈 JSON 구조를 해석할 수 없음")], stats
    stats["items"] = len(items)
    if expected_count and len(items) != expected_count:
        out.append(v("QUIZ_COUNT_MISMATCH", MAJOR, f"문항 수 {len(items)}≠{expected_count}"))
    ev_stems: Set[str] = set()
    for t in evidence_texts:
        ev_stems |= stems(t)
    seen_q = set()
    for n, q in enumerate(items, 1):
        if not isinstance(q, dict):
            out.append(v("JSON_SCHEMA_INVALID", HARD, f"{n}번 문항이 객체가 아님"))
            continue
        qtext = str(q.get("question") or q.get("questionText") or "").strip()
        options = q.get("options") or q.get("choices")
        expl = str(q.get("explanation") or "")
        if not qtext or not isinstance(options, list) or len(options) < 2:
            out.append(v("JSON_SCHEMA_INVALID", HARD, f"{n}번 문항 필수값(question/options) 누락"))
            continue
        options = [str(o) for o in options]
        key = re.sub(r"\s+", "", qtext)
        if key in seen_q:
            out.append(v("QUIZ_DUPLICATE_QUESTION", MAJOR, f"{n}번 문항 중복"))
        seen_q.add(key)
        if expected_options and len(options) != expected_options:
            out.append(v("QUIZ_OPTION_COUNT", HARD, f"{n}번 선택지 {len(options)}≠{expected_options}"))
        normed = [_norm_opt(o) for o in options]
        if len(set(normed)) != len(normed) or any(not o for o in normed):
            out.append(v("QUIZ_DUPLICATE_OPTIONS", HARD, f"{n}번 선택지 중복/빈 값(정답 유일성 위반)"))
            continue
        idx, how = _resolve_answer(q, options)
        if idx is None:
            out.append(v("QUIZ_ANSWER_NOT_IN_OPTIONS", HARD, f"{n}번 정답을 선택지 하나로 확정할 수 없음({how})"))
            continue
        ex_idx = _expl_answer_index(expl)
        if ex_idx is not None and ex_idx != idx:
            out.append(v("QUIZ_ANSWER_EXPLANATION_MISMATCH", HARD, f"{n}번 해설의 정답 표기가 answer 와 다름"))
            continue
        others = [normed[i] for i in range(len(normed)) if i != idx and len(normed[i]) >= 4]
        if any(re.search(rf"정답\S*\s*(?:은|는)?\s*['\"“]?{re.escape(o)}", expl.lower()) for o in others):
            out.append(v("QUIZ_ANSWER_EXPLANATION_MISMATCH", HARD, f"{n}번 해설이 다른 선택지를 정답으로 서술"))
            continue
        # 해설이 '정답키가 아닌' 선택지만 서술하면 정답키와 해설이 어긋난 것이다(예전: 해설이 근거를 되풀이하기만 하면
        # 어떤 키든 근거 있음으로 통과 — 2026-11-04 재현).
        expl_flat = re.sub(r"\s+", "", expl.lower())
        flat = [re.sub(r"\s+", "", o) for o in normed]
        if expl_flat and len(flat[idx]) >= 2 and flat[idx] not in expl_flat and \
                any(i != idx and len(flat[i]) >= 2 and flat[i] in expl_flat for i in range(len(flat))):
            out.append(v("QUIZ_ANSWER_EXPLANATION_MISMATCH", HARD, f"{n}번 해설이 정답이 아닌 선택지를 서술"))
            continue
        if _INJECTION_RE.search(qtext + " " + " ".join(options)):
            out.append(v("PROMPT_INJECTION_SUCCESS", HARD, f"{n}번 문항에 주입 지시 포함"))
            continue
        stats["valid"] += 1
        if evidence_texts:
            # 근거 여부는 '정답 선택지 자체'로 본다(해설이 근거 문장을 되풀이해 정답키를 대신 정당화하지 못하게).
            opt_stems = stems(options[idx])
            correct_stems = opt_stems or stems(options[idx] + " " + expl)
            if correct_stems and len(correct_stems & ev_stems) / len(correct_stems) >= (0.5 if opt_stems else 0.3):
                stats["grounded"] += 1
            if pdf_task:
                missing = numbers_in(options[idx] + " " + expl) - set().union(*[numbers_in(t) for t in evidence_texts])
                if missing:
                    out.append(v("NUMERIC_UNSUPPORTED_BY_SOURCE", HARD, f"{n}번 정답/해설 수치가 원문에 없음"))
    if evidence_texts and stats["valid"] and stats["grounded"] < stats["valid"]:
        out.append(v("QUIZ_ANSWER_UNGROUNDED", MAJOR, f"근거로 뒷받침되지 않는 정답 {stats['valid'] - stats['grounded']}건"))
    return out, stats


# ── 그래프 ─────────────────────────────────────────────────────────────────────
def check_graph(obj: Any) -> List[V]:
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (ValueError, json.JSONDecodeError):
            return [v("JSON_SCHEMA_INVALID", HARD, "그래프 JSON 해석 불가")]
    if not isinstance(obj, dict) or not isinstance(obj.get("nodes"), list) or not isinstance(obj.get("edges"), list):
        return [v("JSON_SCHEMA_INVALID", HARD, "nodes/edges 배열 필요")]
    out: List[V] = []
    ids = [str(n.get("id")) for n in obj["nodes"] if isinstance(n, dict) and n.get("id") is not None]
    if len(ids) != len(obj["nodes"]):
        out.append(v("JSON_SCHEMA_INVALID", HARD, "id 없는 노드"))
    if len(set(ids)) != len(ids):
        out.append(v("GRAPH_DUPLICATE_NODE", HARD, "노드 id 중복"))
    idset, seen, adj = set(ids), set(), {}
    for e in obj["edges"]:
        if not isinstance(e, dict):
            out.append(v("JSON_SCHEMA_INVALID", HARD, "엣지가 객체가 아님"))
            continue
        # ai07 그래프 생성기(graph_builder)는 from/to, 일반 그래프 JSON 은 source/target — 둘 다 같은 의미로 읽는다
        # (예전: from/to 엣지가 전부 GRAPH_DANGLING_EDGE HARD → /api/mindmap/semantic-graph 는 승인 불가였다).
        if ("source" in e or "target" in e) and ("from" in e or "to" in e) and \
                (e.get("source"), e.get("target")) != (e.get("from"), e.get("to")):
            out.append(v("JSON_SCHEMA_INVALID", HARD, "엣지 끝점 키(source/target 과 from/to)가 서로 다름"))
            continue
        s = str(e.get("source") if "source" in e else e.get("from"))
        t = str(e.get("target") if "target" in e else e.get("to"))
        k_type = e.get("type") or e.get("relation") or e.get("kind")
        if s not in idset or t not in idset:
            out.append(v("GRAPH_DANGLING_EDGE", HARD, "존재하지 않는 노드를 가리키는 엣지"))
            continue
        if s == t:
            out.append(v("GRAPH_SELF_LOOP", MAJOR, "자기 자신을 가리키는 엣지"))
        k = (s, t, str(k_type or ""))
        if k in seen:
            out.append(v("GRAPH_DUPLICATE_EDGE", MAJOR, "중복 엣지"))
        seen.add(k)
        if re.search(r"prereq|선수|requires", k[2], re.IGNORECASE):
            adj.setdefault(s, set()).add(t)
    # 선수 관계 순환
    state: Dict[str, int] = {}

    def dfs(u: str) -> bool:
        state[u] = 1
        for w in adj.get(u, ()):
            if state.get(w) == 1 or (state.get(w) is None and dfs(w)):
                return True
        state[u] = 2
        return False

    if any(state.get(u) is None and dfs(u) for u in list(adj)):
        out.append(v("GRAPH_PREREQUISITE_CYCLE", HARD, "선수 관계 순환"))
    return out


# ── 플래너 ─────────────────────────────────────────────────────────────────────
def _parse_date(s: Any) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except (ValueError, TypeError):
        return None


def check_plan(obj: Any, *, max_daily_hours: Optional[float], deadline: Optional[str],
               known_prereqs: Optional[List[str]]) -> List[V]:
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except (ValueError, json.JSONDecodeError):
            return [v("JSON_SCHEMA_INVALID", HARD, "계획 JSON 해석 불가")]
    items = obj.get("items") or obj.get("plan") or obj.get("tasks") if isinstance(obj, dict) else obj
    if not isinstance(items, list) or not items:
        return [v("PLAN_EMPTY", HARD, "계획 항목 없음")]
    out: List[V] = []
    dl = _parse_date(deadline) if deadline else None
    per_day: Dict[date, float] = {}
    titles = set()
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            out.append(v("JSON_SCHEMA_INVALID", HARD, f"{n}번 항목이 객체가 아님"))
            continue
        d = _parse_date(it.get("date") or it.get("scheduledDate") or it.get("dueDate"))
        hours = it.get("hours", it.get("durationHours"))
        if d is None:
            out.append(v("PLAN_DATE_INVALID", HARD, f"{n}번 날짜 없음/형식 오류"))
            continue
        if dl and d > dl:
            out.append(v("PLAN_PAST_DEADLINE", HARD, f"{n}번 항목이 마감 이후"))
        try:
            h = float(hours) if hours is not None else 0.0
        except (TypeError, ValueError):
            h = -1
        if h < 0 or (hours is not None and h == 0):
            out.append(v("PLAN_HOURS_INVALID", HARD, f"{n}번 학습 시간 비정상"))
        per_day[d] = per_day.get(d, 0.0) + max(h, 0.0)
        for p in it.get("prerequisites") or []:
            if p not in titles and (known_prereqs is None or p not in known_prereqs):
                out.append(v("PLAN_PREREQUISITE_ORDER", MAJOR, f"{n}번 선수 항목이 앞에 없음"))
        titles.add(str(it.get("title") or it.get("task") or ""))
    if max_daily_hours:
        over = [d for d, h in per_day.items() if h > max_daily_hours + 1e-9]
        if over:
            out.append(v("PLAN_OVER_CAPACITY", HARD, f"일일 가용시간 초과 {len(over)}일"))
    return out


# ── 비전 ───────────────────────────────────────────────────────────────────────
_QUOTED_RE = re.compile(r"[\"“「『']([^\"”」』']{2,80})[\"”」』']")
_OBSERVE_RE = re.compile(r"화면에|보이는|표시된|적혀\s*있|나타나|캡처|스크린")
_UNCERTAIN_RE = re.compile(r"추정|확실하지|불확실|흐릿|판독\s*어려|보이는\s*것\s*같|일\s*수\s*있")


def check_vision(text: str, evidence: Sequence[Dict[str, Any]]) -> List[V]:
    out: List[V] = []
    ocr = " ".join(str(e.get("text") or "") for e in evidence)
    if not ocr.strip():
        if _OBSERVE_RE.search(text or ""):
            out.append(v("VISION_NO_OBSERVATION_EVIDENCE", HARD, "판독 근거 없이 화면 관측을 서술"))
        return out
    norm_ocr = re.sub(r"\s+", "", ocr).lower()
    unsupported = [q for q in _QUOTED_RE.findall(text or "") if re.sub(r"\s+", "", q).lower() not in norm_ocr]
    nums = numbers_in(text) - numbers_in(ocr)
    if unsupported or nums:
        out.append(v("VISION_UNSUPPORTED_OBSERVATION", HARD,
                     f"판독 결과에 없는 인용 {len(unsupported)}건/수치 {len(nums)}개"))
    srcs = {str(e.get("sourceType") or "").upper() for e in evidence}
    if "SCREEN_SHARE" in srcs and "CAMERA" not in srcs and re.search(r"카메라|웹캠|얼굴", text or ""):
        out.append(v("SOURCE_CONFUSION", MAJOR, "공유 화면 근거를 카메라로 서술"))
    return out


def has_uncertainty(text: str) -> bool:
    return bool(_UNCERTAIN_RE.search(text or ""))


# ── 학습메이트 모드 ──────────────────────────────────────────────────────────────
def check_socratic(text: str) -> List[V]:
    qs = len(re.findall(r"[?？]", text or ""))
    out: List[V] = []
    if qs == 0:
        out.append(v("SOCRATIC_NO_QUESTION", MAJOR, "발문(질문)이 없음"))
    elif qs > 1:
        out.append(v("SOCRATIC_MULTIPLE_QUESTIONS", MAJOR, f"한 턴에 질문 {qs}개"))
    if re.search(r"정답은|답은\s*바로", text or ""):
        out.append(v("SOCRATIC_ANSWER_REVEAL", MAJOR, "정답을 직접 공개"))
    return out


def check_debate(text: str) -> List[V]:
    if not re.search(r"왜냐하면|근거|때문|이유|반면|따라서|예를\s*들", text or ""):
        return [v("DEBATE_NO_REASONING", MAJOR, "주장에 근거/이유 표현이 없음")]
    return []


def check_group_scope(text: str, participants: Optional[List[str]]) -> List[V]:
    if not participants:
        return []
    mentioned = set(re.findall(r"@([0-9A-Za-z가-힣_]{2,20})", text or ""))
    stray = mentioned - set(participants)
    return [v("GROUP_PARTICIPANT_SCOPE", MAJOR, f"참여자 아닌 대상 언급 {len(stray)}명")] if stray else []
