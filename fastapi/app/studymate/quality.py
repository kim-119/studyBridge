"""품질 파이프라인: Cheap Evaluator → (조건부) Judge → Repair-first → bounded Regenerate.

연속 점수(personaScore=0.87 등)를 게이트로 쓰지 않는다. 모든 판정은 이진 루브릭 Y/N 이다.
  4/4 → PASS, 3/4 → REPAIR, ≤2/4 → REGENERATE (한 루브릭 기준)
Major 위반(빈 출력/메타·프롬프트 누출/명백한 중복/근거 없는 구체 수치 다수)은 REGENERATE.
런타임 재시도는 bounded: repair 최대 1회, regenerate 최대 1회. 예산이 없으면 시작하지 않는다.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.studymate import knowledge_policy as KP
from app.studymate import persona_policy as PP

logger = logging.getLogger("studybridge.studymate.quality")

PASS, REPAIR, REGENERATE = "PASS", "REPAIR", "REGENERATE"


# ── 중복 / 신규성 ─────────────────────────────────────────────────────────────
def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def char_ngrams(text: str, n: int = 4) -> set:
    s = _norm(text)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def jaccard(a: str, b: str, n: int = 4) -> float:
    A, B = char_ngrams(a, n), char_ngrams(b, n)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def longest_common_run(a: str, b: str) -> int:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0
    m = difflib.SequenceMatcher(None, na, nb, autojunk=False).find_longest_match(0, len(na), 0, len(nb))
    return m.size


def common_prefix(a: str, b: str) -> int:
    na, nb = _norm(a), _norm(b)
    i = 0
    while i < min(len(na), len(nb)) and na[i] == nb[i]:
        i += 1
    return i


# 2026-09-16 실측 보정: 서로 다른 교수 정상 답변끼리 LCS 9~12자(공백제거), 복제 사례 80자.
DUP_LCS = 48
DUP_JACCARD = 0.42
DUP_PREFIX = 28


@dataclass
class DupVerdict:
    duplicate: bool
    reason: str = ""
    lcs: int = 0
    jaccard: float = 0.0
    prefix: int = 0


def duplicate_against(text: str, priors: List[str]) -> DupVerdict:
    best = DupVerdict(False)
    for p in priors or []:
        lcs = longest_common_run(text, p)
        jac = jaccard(text, p)
        pre = common_prefix(text, p)
        if lcs > best.lcs:
            best.lcs = lcs
        best.jaccard = max(best.jaccard, jac)
        best.prefix = max(best.prefix, pre)
        if lcs >= DUP_LCS:
            return DupVerdict(True, f"lcs={lcs}", lcs, jac, pre)
        if jac >= DUP_JACCARD:
            return DupVerdict(True, f"jaccard={jac:.2f}", lcs, jac, pre)
        if pre >= DUP_PREFIX:
            return DupVerdict(True, f"prefix={pre}", lcs, jac, pre)
    return best


def prefix_guard(priors: List[str]) -> Callable[[str], Optional[str]]:
    """스트리밍 초반(≈120자)에 이전 교수 답변을 그대로 따라 쓰면 생성을 조기 중단한다."""
    def guard(acc: str) -> Optional[str]:
        if len(_norm(acc)) < 60:
            return None
        v = duplicate_against(acc, priors)
        if v.duplicate and (v.prefix >= DUP_PREFIX or v.lcs >= DUP_LCS):
            return f"duplicate_prefix({v.reason})"
        return None
    return guard


def _bigrams(s: str) -> set:
    n = _norm(s)
    return {n[i:i + 2] for i in range(max(0, len(n) - 1))}


def claim_covered(text: str, claim: str, threshold: float = 0.55) -> bool:
    cb = _bigrams(claim)
    if not cb:
        return True
    tb = _bigrams(text)
    return len(cb & tb) / len(cb) >= threshold


def novel_claims(claims: List[str], other_claims: List[str], threshold: float = 0.5) -> List[str]:
    out = []
    for c in claims:
        if all(jaccard(c, o, 2) < threshold for o in other_claims):
            out.append(c)
    return out


# ── 누출 / 근거 정책 / 길이 ───────────────────────────────────────────────────
_LEAK = re.compile(
    r"(\[FINAL BEHAVIOR|USER_CUSTOM_INSTRUCTION|\[PERSONALITY|\[KNOWLEDGE LEVEL|\[MODE:|FEW-SHOT|"
    r"시스템 프롬프트|system prompt|페르소나(로서|라서|이므로)|나는\s*(비판형|친근함|독특함|효율적|냉소적|논리형)|"
    r"(비판형|냉소적|논리형|효율적|독특함|친근함)\s*(교수|페르소나)(로서|라서|답게)|<예시 (질문|답변)>)",
    re.IGNORECASE,
)
_UNSUPPORTED = [
    re.compile(r"\d+(?:\.\d+)?\s*(?:%|퍼센트|ms|밀리초|배\s*(?:빠|느|향상|증가|감소)|x\s*faster)"),
    re.compile(r"\((?:19|20)\d{2}\)|et al\.|arXiv|논문\s*[「『\"'][^」』\"']{3,}"),
    re.compile(r"\b(?:v|버전\s*)\d+\.\d+(?:\.\d+)?\b"),
]


def leakage(text: str) -> Optional[str]:
    m = _LEAK.search(text or "")
    return m.group(0) if m else None


def unsupported_specifics(text: str, evidence: str) -> List[str]:
    found = []
    ev = evidence or ""
    for rx in _UNSUPPORTED:
        for m in rx.finditer(text or ""):
            frag = m.group(0).strip()
            if frag and frag not in ev:
                found.append(frag)
    return found[:6]


# ── 이진 루브릭(휴리스틱 cheap evaluator) ─────────────────────────────────────
def _has(rx: str, text: str) -> bool:
    return re.search(rx, text or "") is not None


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?。])\s|\n", (text or "").strip(), maxsplit=1)[0]


def _persona_checks(persona: str, t: str) -> Dict[str, bool]:
    t = t or ""
    head = t[:60]
    first2 = " ".join(re.split(r"(?<=[.!?])\s+", t.strip())[:2])
    sentences = [x for x in re.split(r"(?<=[.!?])\s+|\n+", t.strip()) if x.strip()]
    ends = re.findall(r"([가-힣]{1,3})[.!?](?:\s|$)", t)
    n_end = max(1, len(ends))
    yo = sum(1 for e in ends if e.endswith("요") or e.endswith("죠")) / n_end
    da = sum(1 for e in ends if re.search(r"(다|까)$", e)) / n_end
    banmal = sum(1 for e in ends if re.search(r"(야|지|어|아|거든|잖아|네|군|래|자)$", e) and not e.endswith("요")) / n_end
    if persona == "friendly":
        return {
            "warm_honorific": yo >= 0.5,
            "encouragement": _has(r"괜찮|걱정|좋은 질문|잘 하고|힘내|천천히|헷갈릴 수|많이들|충분히 이해", t),
            "everyday_analogy": _has(r"처럼|마치|비유|떠올려|생각해\s*(보|봐)|예를 들어", t),
            "no_irony_or_attack": not _has(r"퍽이나|참 편리한|마법처럼|그래,|착각이다|전제부터", t),
        }
    if persona == "critical":
        return {
            "premise_challenge": _has(r"전제|가정|깔려|숨은|무조건|항상\s|라는 생각|믿음|통념", t),
            "concrete_counterexample": _has(r"반례|예외|깨지|성립하지 않|반대로|오히려|그렇지 않은 경우", t),
            "formal_no_irony": da >= 0.6 and banmal < 0.2 and not _has(r"퍽이나|마법처럼|그래,", first2),
            "no_praise": not _has(r"좋은 질문|훌륭|멋진 질문|아주 좋|좋아요|정말 좋", head),
        }
    if persona == "creative":
        return {
            "unusual_domain_scene": _has(r"우주|별|행성|세포|유전자|생태|진화|연극|무대|신화|신전|게임 규칙|체스|오케스트라|화산|바다 생물|개미|벌집", t),
            "thought_experiment": _has(r"만약|라면\?|상상해\s*(보|봐)|가정해\s*(보|봐)", t),
            "returns_to_concept": _has(r"정확히는|즉[,\s]|다시 말해|기술적으로|정의하면|핵심은|실제로는", t),
            "not_textbook_opening": not _has(r"^[^.!?\n]{0,40}(은|는|이란|란)\s[^.!?\n]{0,60}(이다|입니다|이에요)[.!]", t.strip()),
        }
    if persona == "concise":
        bullets = len(re.findall(r"^\s*[-•*]\s", t, re.M))
        return {
            "very_short": (len(sentences) <= 7 or bullets <= 6) and len(t) <= 700,
            "explicit_conclusion": _has(r"결론\s*[:：]|결론은|결론적으로", t),
            "no_filler": not _has(r"^(안녕|좋은 질문|음+|자,|네,|오늘은)", t.strip()),
            "core_first": len(sentences[0]) <= 140 if sentences else False,
        }
    if persona == "sardonic":
        return {
            "banmal": banmal >= 0.3,
            "ironic_opening": _has(r"그래,|참\s|정말\s|마법|퍽이나|대단|하겠지|이겠지|잖아|라니|편리한 믿음|착각|현실은", first2),
            "gives_correct_model": _has(r"제대로|올바른|정확히는|요점은|핵심은|맞는|진짜는|실제로는|현실은", t),
            "no_insult": not _has(r"멍청|바보|한심|병신|닥쳐|꺼져|개새|씨발|무식", t),
        }
    return {
        "numbered_steps": len(re.findall(r"(^|\n)\s*\d\)", t)) >= 2,
        "explicit_premises": _has(r"전제", t),
        "explicit_conclusion": _has(r"결론", t),
        "definition_first": _has(r"정의|이란|란\s|이다", (sentences[0] if sentences else "")),
    }


def _level_checks(level: str, t: str) -> Dict[str, bool]:
    if level == "beginner":
        return {
            "why_it_matters": _has(r"중요|필요|왜\s|덕분|쓰는 이유|때문에 쓰", t),
            "concrete_example": _has(r"예를 들어|예시|예컨대|처럼|가령", t),
            "jargon_explained": _has(r"쉽게 말하면|즉[,\s]|라는 뜻|말하자면|다시 말해", t),
            "intuition_first": _has(r"비유|처럼|생각해|상상|예를|마치|떠올", (t or "")[:220]),
        }
    if level == "bachelor":
        return {
            "definition": _has(r"정의|이란|란\s|이다[.\s]|입니다|을 말한|(은|는)\s[^.!?\n]{2,60}(예요|이에요|이죠|죠|다)[.!?\s]", t),
            "mechanism": _has(r"단계|과정|먼저|그다음|다음으로|순서|동작|원리|방식으로|저장해|처리해|때문에", t),
            "standard_approach": _has(r"알고리즘|방식|구현|방법|표준|자료구조|프로토콜", t),
            "no_research_depth_only": len(t or "") >= 200,
        }
    if level == "master":
        return {
            "architecture": _has(r"구조|아키텍처|구성 요소|계층|컴포넌트|설계", t),
            "tradeoff": _has(r"트레이드오프|반면|대신|비용|장단점|대가|희생", t),
            "failure_mode": _has(r"실패|장애|병목|문제가 생|위험|깨지|유실|불일치", t),
            "practical_connection": _has(r"실무|현업|운영|서비스|연구|사례|실제", t),
        }
    if level == "phd":
        return {
            "states_assumptions": _has(r"가정|전제", t),
            "has_limitation": _has(r"한계|제약|성립하지|불가능|보장하지", t),
            "has_boundary_condition": _has(r"경계|조건에서|경우에만|일 때|이상일|이하일|극한|규모가|조건이", t),
            "counterexample_or_failure_domain": _has(r"반례|실패|깨지|성립하지 않|예외|붕괴", t),
        }
    return {
        "production_architecture": _has(r"운영|프로덕션|배포|클러스터|아키텍처|인프라", t),
        "reliability_or_observability": _has(r"신뢰성|장애|가용성|모니터링|지표|로그|트레이스|관측|알람", t),
        "capacity_or_security": _has(r"용량|메모리|스케일|확장|보안|권한|인증|암호|처리량", t),
        "operational_tradeoff": _has(r"트레이드오프|비용|제약|운영 부담|복잡도|대가", t),
    }


@dataclass
class RubricResult:
    persona: Dict[str, bool]
    level: Dict[str, bool]
    source: str = "heuristic"

    @staticmethod
    def _verdict(d: Dict[str, bool]) -> str:
        if not d:
            return PASS
        passed = sum(1 for v in d.values() if v)
        miss = len(d) - passed
        if miss == 0:
            return PASS
        if miss == 1:
            return REPAIR
        return REGENERATE

    @property
    def verdict(self) -> str:
        vs = {self._verdict(self.persona), self._verdict(self.level)}
        if REGENERATE in vs:
            return REGENERATE
        if REPAIR in vs:
            return REPAIR
        return PASS

    def missing(self) -> List[str]:
        return [k for k, v in {**self.persona, **self.level}.items() if not v]

    def borderline(self) -> bool:
        return self.verdict != PASS

    def to_dict(self) -> Dict[str, Any]:
        return {"persona": self.persona, "level": self.level, "source": self.source,
                "verdict": self.verdict, "missing": self.missing()}


def heuristic_rubric(text: str, persona: str, level: str) -> RubricResult:
    return RubricResult(_persona_checks(persona, text or ""), _level_checks(level, text or ""))


# ── 조건부 Judge (LLM, 이진 JSON) ─────────────────────────────────────────────
def judge_schema(persona: str, level: str) -> Tuple[Dict[str, Any], List[Tuple[str, str]]]:
    items = [(f"p_{k}", d) for k, d in PP.RUBRIC.get(persona, [])] + \
            [(f"k_{k}", d) for k, d in KP.RUBRIC.get(level, [])]
    schema = {"type": "object", "properties": {k: {"type": "boolean"} for k, _ in items},
              "required": [k for k, _ in items]}
    return schema, items


def judge_prompts(text: str, persona: str, level: str, question: str) -> Tuple[str, str, Dict[str, Any]]:
    schema, items = judge_schema(persona, level)
    system = ("너는 답변 평가기다. 각 항목이 답변에 '명확히' 충족되면 true, 아니면 false 만 출력한다. "
              "설명을 쓰지 않는다. JSON 만 출력한다.")
    lines = "\n".join(f"- {k}: {d}" for k, d in items)
    user = f"[질문]\n{question}\n\n[답변]\n{text}\n\n[평가 항목]\n{lines}"
    return system, user, schema


def parse_judge(raw: str, persona: str, level: str) -> Optional[RubricResult]:
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    p = {k[2:]: bool(v) for k, v in obj.items() if k.startswith("p_")}
    k = {kk[2:]: bool(v) for kk, v in obj.items() if kk.startswith("k_")}
    if not p or not k:
        return None
    return RubricResult(p, k, source="judge")


# ── Repair 지시 ──────────────────────────────────────────────────────────────
_MISSING_HINT = {
    "counterexample": "반례 또는 경계조건 1개", "contains_counterexample": "반례 1개",
    "contains_limitation": "적용 한계 1개", "identified_assumption": "질문에 깔린 전제 1개",
    "no_unnecessary_praise": "시작 부분의 칭찬 문구 삭제", "uses_analogy": "일상 비유 1개",
    "warm_honorific": "다정한 존댓말(~요)", "encouragement": "안심/격려 한 문장", "everyday_analogy": "일상 생활 비유 1개",
    "no_irony_or_attack": "반어·비꼼 제거", "premise_challenge": "질문/통념의 전제를 지목하는 문장", "concrete_counterexample": "구체적 반례 1개",
    "formal_no_irony": "평서체(~다), 반어·반말 제거", "no_praise": "칭찬 시작 문구 삭제", "unusual_domain_scene": "의외의 분야 장면(생물·우주·연극 등)",
    "thought_experiment": "'만약 ~라면?' 사고실험 1개", "very_short": "6문장/불릿 이내로 압축", "explicit_conclusion": "'결론:' 한 줄",
    "no_filler": "인사·서론 삭제", "banmal": "반말로 전환", "ironic_opening": "첫 문장을 반어적 맞장구로", "numbered_steps": "번호 매긴 추론 단계",
    "explicit_premises": "전제 명시", "definition_first": "정의로 시작",
    "explains_jargon": "전문용어 쉬운 풀이", "warm_tone": "존댓말의 따뜻한 어조",
    "cross_domain": "다른 분야와의 연결 1개", "novel_angle": "새로운 관점 1개",
    "returns_to_concept": "비유를 정확한 개념으로 연결하는 문장", "not_textbook_opening": "교과서식 정의가 아닌 도입",
    "short": "불필요한 문장 삭제(8문장 이내)", "core_first": "첫 문장에 핵심", "has_reason": "근거 한 줄",
    "has_conclusion": "결론 한 줄", "ironic_hook": "흔한 착각을 짚는 건조한 반어 한 문장",
    "explains_why_wrong": "착각이 틀린 이유", "gives_correct_model": "올바른 모델", "no_insult": "모욕 표현 삭제",
    "has_definition": "용어 정의", "has_premises": "전제 명시", "has_inference": "번호 매긴 추론 단계",
    "why_it_matters": "왜 중요한지 한 문장", "concrete_example": "구체 예시 1개",
    "jargon_explained": "전문용어 풀이", "intuition_first": "정의 앞에 직관적 설명",
    "definition": "정확한 정의", "mechanism": "동작 원리 단계", "standard_approach": "표준 알고리즘/구현 언급",
    "no_research_depth_only": "구체 메커니즘", "architecture": "구조 관점", "tradeoff": "트레이드오프 1개",
    "failure_mode": "실패 모드 1개", "practical_connection": "실무/연구 연결",
    "states_assumptions": "가정 명시", "has_limitation": "한계 명시", "has_boundary_condition": "경계조건 1개",
    "counterexample_or_failure_domain": "반례 또는 실패 영역", "production_architecture": "운영 아키텍처 관점",
    "reliability_or_observability": "신뢰성/관측 가능성", "capacity_or_security": "용량 또는 보안 영향",
    "operational_tradeoff": "운영 트레이드오프", "formal_model": "형식 모델(수식/상태전이/불변식) 1개",
}


def repair_instruction(missing: List[str], unsupported: List[str], duplicate_reason: str = "") -> str:
    items = [f"- {_MISSING_HINT.get(m, m)} 추가/수정" for m in missing]
    if unsupported:
        items.append("- 근거 자료에 없는 구체 수치/버전/논문 표기 삭제 또는 조건부 표현으로 수정: " + ", ".join(unsupported[:4]))
    if duplicate_reason:
        items.append("- 다른 교수 답변과 겹치는 문장을 새로운 내용으로 교체")
    return ("[REPAIR] 기존 답변의 내용과 말투를 최대한 유지한다. 다음 누락/위반 요소만 추가·수정한 전체 답변을 다시 출력한다:\n"
            + "\n".join(items))
