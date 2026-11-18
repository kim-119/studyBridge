"""사용자 노출 한국어 문장의 템플릿 조립 흔적 제거(도메인 무관, Spring `KoreanTextNormalizer`/`LearningConceptValidator` 와 같은 규칙).

- resolve_josa: "기법을(를)" → "기법을", "모델이(가)" → "모델이" 처럼 앞 글자 받침으로 조사를 확정한다.
- strip_bullets: 문장 앞/중간의 불릿 마커("•", "·" …)를 제거한다.
- is_concept_like: 짧은 명사구(개념명)인가. 설명문/예제 문장/코드 조각은 False(형태 신호만 사용).
"""
from __future__ import annotations

import re
from typing import List

_JOSA_PAIRS = ["을(를)", "를(을)", "이(가)", "가(이)", "은(는)", "는(은)", "과(와)", "와(과)",
               "으로(로)", "로(으로)", "이(라)", "이나(나)", "나(이나)", "이라(라)", "라(이라)"]
_JOSA_RE = re.compile(r"(?P<prev>[\w)\]”’\"'])\s*(?P<pair>" + "|".join(re.escape(p) for p in _JOSA_PAIRS) + ")", re.UNICODE)
_BULLET_RE = re.compile(r"(?:^|\s)[•·▪‣∙◦▶►■□]+(?=\s|$)|[•▪‣∙◦]")
_MULTISPACE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+(?=[.,!?])")

_PREDICATE_END = re.compile(
    r"(?:(?:이|하|되|있|없|않|같|많|르|크|작|좋|겠|었|았|였|된|한|인|온|운|는|린|난)다"
    r"|(?:이|하|되|있|없|않|가|오|나|지)고|(?:이|하|되|있|없)며|(?:하|되|이|라|다|있|없|으)면"
    r"|것|것들|하기|되기|니다|세요|보세요|십시오|까|죠|네요|때문에|때문"
    r"|(?:을|를|은|는|에|에서|으로|까지|부터|처럼|보다|에게|한테|이란|란|이라고|라고|라도|이라도))$"
)
_INNER_PARTICLE = re.compile(r"(?<=[가-힣)A-Za-z0-9])(?:을|를|은|는|이|가|의|에|에서|로|으로|와|과|도|만|까지|부터|처럼|보다|에게)(?=[가-힣])")
_INNER_VERB = re.compile(
    r"(?:하는|되는|있는|없는|않는|않은|하여|되어|해서|통해|따라|위해|대한|대해|가진|좋은|나쁜|높은|낮은|같은|많은|적은"
    r"|이용해|사용해|수록|하면|되면|라면|다면|이고|하고|되고|이며|하며|되며|중요한|필요한|가능한|다양한|유사한|불가능한"
    r"|간단한|복잡한|이라고|라고|했|됐|였|았|었|중에서|에서의|에대한|로부터|으로써|에의해|에따라|에따른|에대해)"
)
_CODE_LIKE = re.compile(r"[=;{}\[\]<>]|\w+_\w*\(|\b(?:import|from|def|return|print|self|class)\b")


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def josa(last: str, with_batchim: str, without_batchim: str) -> str:
    """앞 글자 받침 유무에 맞는 조사. ㄹ 받침 + '으로' 는 '로'. 숫자는 읽기 기준(0,1,3,6,7,8 받침)."""
    if last and _is_hangul(last):
        jong = (ord(last) - 0xAC00) % 28
        if with_batchim == "으로" and jong == 8:
            return without_batchim
        return without_batchim if jong == 0 else with_batchim
    if last and last.isdigit():
        return with_batchim if last in "013678" else without_batchim
    return without_batchim


def with_josa(word: str, with_batchim: str, without_batchim: str) -> str:
    w = (word or "").strip()
    if not w:
        return ""
    return w + josa(w[-1], with_batchim, without_batchim)


def resolve_josa(s: str) -> str:
    if not s:
        return s or ""

    def _sub(m: "re.Match[str]") -> str:
        pair = m.group("pair")
        a, b = pair[: pair.index("(")], pair[pair.index("(") + 1 : -1]
        prev_idx = m.start("pair") - 1
        while prev_idx >= 0 and s[prev_idx].isspace():
            prev_idx -= 1
        last = s[prev_idx] if prev_idx >= 0 else " "
        return m.group("prev") + josa(last, a, b)

    return _JOSA_RE.sub(_sub, s)


def strip_bullets(s: str) -> str:
    if not s:
        return s or ""
    return _MULTISPACE.sub(" ", _BULLET_RE.sub(" ", s)).strip()


def clean_sentence(s: str) -> str:
    """불릿 제거 + 조사 확정 + 공백 정리(문장 종결은 건드리지 않는다)."""
    if not s:
        return s or ""
    out = strip_bullets(s)
    out = resolve_josa(out)
    out = _SPACE_BEFORE_PUNCT.sub("", _MULTISPACE.sub(" ", out))
    return out.strip()


def is_concept_like(raw: str) -> bool:
    s = (raw or "").strip()
    if len(s) < 2:
        return False
    if re.match(r"^[^\w(\[\"'“‘]", s, re.UNICODE):
        return False
    if re.search(r"[.?!…:,]\s*$", s):
        return False
    if _CODE_LIKE.search(s):
        return False
    if s.count("(") != s.count(")"):
        return False
    compact = s.replace(" ", "")
    if len(compact) > 40 or len(s.split()) > 5:
        return False
    segments = [compact] + re.findall(r"\(([^()]*)\)", compact) + [re.sub(r"\([^()]*\)", "", compact)]
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        if _PREDICATE_END.search(seg):
            return False
        if len(seg) >= 4 and re.search(r"[가-힣]다$", seg):
            return False
    for w in s.split():
        if len(w) >= 3 and _PREDICATE_END.search(w):
            return False
    score = len(_INNER_PARTICLE.findall(compact)) + 2 * len(_INNER_VERB.findall(compact))
    if score >= 3:
        return False
    longest = max((len(m) for m in re.findall(r"[가-힣]+", compact)), default=0)
    if longest > 18 and score >= 1:
        return False
    return True


def concept_keywords(keywords: List[str]) -> List[str]:
    """개념 형태(명사구)인 키워드만 남긴다(설명문 조각 제외, 순서 유지)."""
    out: List[str] = []
    for k in keywords or []:
        k = (k or "").strip()
        if k and is_concept_like(k) and k not in out:
            out.append(k)
    return out
