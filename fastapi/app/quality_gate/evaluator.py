"""단일 재사용 Response Quality Evaluator (response-quality.v1).

승인 = verified AND score>=80 AND !hardFail AND 필수 검증기 통과. 점수는 rubric 점수(정답 확률 아님).
- 사실 차원은 (1) 결정적 gold/수식 → (2) 근거 대조 → (3) 허용된 프로파일에서만 judge 순으로 검증한다.
  셋 다 불가하면 score=None, verified=False(근거 없는 단정은 승인 불가). 정직한 '근거 없음' 고지는 예외적으로 검증 가능.
- 평가기 예외/timeout/judge 불능 → VALIDATION_ERROR(success=False). 어떤 실패도 APPROVED 로 바뀌지 않는다.
- 원문(질문/답변/PDF)은 로그에 남기지 않는다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.response_quality_v1 import (MINIMUM_SCORE, SCHEMA_VERSION, Dimension, OutputKind, QualityInput, QualityOutput,
                                               QualityStatus, Severity, TaskType, Violation)
from app.quality_gate import checks as C
from app.quality_gate.judge import JudgeUnavailable, model_family
from app.quality_gate.profiles import get_profile

logger = logging.getLogger(__name__)

EVALUATOR_VERSION = "rqg-1.0.0"
_FACTUAL_DIMS = {"factual_correctness", "answer_key", "solution_reverification", "concept_consistency",
                 "observation_grounding", "source_fidelity", "grounding"}
_QUERY_TASKS = {TaskType.GENERAL_EXPLANATION, TaskType.STUDYMATE_BASIC, TaskType.STUDYMATE_SOCRATIC,
                TaskType.STUDYMATE_DEBATE, TaskType.PDF_QA, TaskType.WRONG_NOTE_EXPLANATION, TaskType.MATH_SOLUTION,
                TaskType.GROUP_STUDY_MESSAGE}
_GENERIC_MAJOR_PENALTY = 3
_GENERIC_MAJOR_CAP = 15

from app.quality_gate.hints import HINTS  # noqa: E402  (재생성 지침 표는 생성 경로와 공유)
NON_REGENERABLE = {"SOURCE_SCOPE_VIOLATION", "SOURCE_SCOPE_UNVERIFIED", "FALLBACK_CONTENT", "PII_SCAN_ERROR"}

_cache: "OrderedDict[str, QualityOutput]" = OrderedDict()
_CACHE_MAX = 512


def _offload_min_chars() -> int:
    try:
        return max(0, int(os.getenv("AI_QUALITY_EVAL_OFFLOAD_MIN_CHARS", "8000")))
    except ValueError:
        return 8000


def _input_chars(inp: QualityInput) -> int:
    po = inp.proposedOutput
    if po is None:
        return 0
    return len(po) if isinstance(po, str) else len(json.dumps(po, ensure_ascii=False, separators=(",", ":"), default=str))


def _latency_ms(started: float) -> int:
    # Java Integer 범위로 고정(EC2 는 범위 밖 latencyMs 를 EVALUATOR_OUTPUT_CONTRACT_INVALID 로 거부한다).
    return max(0, min(2 ** 31 - 1, int((time.time() - started) * 1000)))


def _cache_key(inp: QualityInput) -> str:
    body = json.dumps({"t": inp.taskType.value, "k": inp.outputKind.value, "o": inp.proposedOutput,
                       "q": inp.originalRequest, "e": [e.model_dump(mode="json") for e in inp.groundingEvidence],
                       "c": inp.constraints.model_dump(mode="json"), "v": EVALUATOR_VERSION,
                       "j": os.getenv("AI_QUALITY_JUDGE", "")}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _error_output(inp: QualityInput, code: str, started: float) -> QualityOutput:
    return QualityOutput(schemaVersion=SCHEMA_VERSION, requestId=inp.requestId, taskType=inp.taskType, success=False,
                         verified=False, qualityStatus=QualityStatus.VALIDATION_ERROR, score=None,
                         minimumScore=MINIMUM_SCORE, hardFail=False,
                         violations=[Violation(code=code, severity=Severity.MAJOR, reason="평가를 완료하지 못함 — 승인 불가")],
                         evaluatorVersion=EVALUATOR_VERSION, modelDigest=inp.modelDigest,
                         latencyMs=_latency_ms(started),
                         mandatoryValidatorsPassed=False)  # 검증기를 끝까지 돌리지 못함 = 통과 아님(C-RQ-1)


async def evaluate(inp: QualityInput, *, judge=None, timeout_s: Optional[float] = None) -> QualityOutput:
    started = time.time()
    timeout_s = timeout_s if timeout_s is not None else float(os.getenv("AI_QUALITY_EVAL_TIMEOUT_SECONDS", "25"))
    key = _cache_key(inp)
    hit = _cache.get(key)
    if hit is not None:
        _cache.move_to_end(key)
        return hit.model_copy(update={"requestId": inp.requestId, "latencyMs": _latency_ms(started)})
    try:
        if judge is None and _input_chars(inp) >= _offload_min_chars():
            # judge 없는 평가는 순수 CPU(정규식/토큰 비교) — 큰 본문은 워커 스레드에서 돌려 이벤트 루프(다른 사용자 SSE)를
            # 막지 않는다(실측: 60k자 27ms 점유 → 스레드 전환 간격 수준). judge 가 있으면 GPU 슬롯/httpx 가 루프에 묶여 있어 제외.
            out = await asyncio.wait_for(asyncio.to_thread(lambda: asyncio.run(_evaluate(inp, None, started))),
                                         timeout=timeout_s)
        else:
            out = await asyncio.wait_for(_evaluate(inp, judge, started), timeout=timeout_s)
    except asyncio.TimeoutError:
        out = _error_output(inp, "EVALUATION_TIMEOUT", started)
    except JudgeUnavailable:
        out = _error_output(inp, "JUDGE_UNAVAILABLE", started)
    except Exception as e:  # noqa: BLE001
        logger.warning("[quality] evaluator error requestId=%s type=%s", inp.requestId, type(e).__name__)
        out = _error_output(inp, "EVALUATOR_ERROR", started)
    if out.success:
        _cache[key] = out
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    logger.info("[quality] requestId=%s task=%s status=%s score=%s hard=%s latencyMs=%d v=%s",
                inp.requestId, inp.taskType.value, out.qualityStatus.value, out.score, out.hardFail,
                out.latencyMs, EVALUATOR_VERSION)
    return out


def clear_cache() -> None:
    _cache.clear()


async def _evaluate(inp: QualityInput, judge, started: float) -> QualityOutput:
    prof = get_profile(inp.taskType)
    text = C.text_of(inp.proposedOutput)
    cons = inp.constraints
    ev = [e.model_dump(mode="json") for e in inp.groundingEvidence]
    ev_texts = [e.text for e in inp.groundingEvidence if e.text and e.text.strip()]
    vs: List[Tuple] = []

    vs += C.check_empty_truncated(text, finish_reason=cons.finishReason, max_chars=cons.maxChars)
    if any(x[0] == "EMPTY_OUTPUT" for x in vs):
        return _finalize(inp, prof, vs, {}, started, verified=False)
    vs += C.check_failure_markers(text)
    vs += C.check_secret_pii(text, inp.originalRequest, allow_echo=cons.allowPiiEcho)
    vs += C.check_prompt_injection(text, ev_texts, inp.originalRequest)
    vs += C.check_citations(text, ev, require=cons.requireCitations)
    vs += C.check_scope(ev, cons.allowedMaterialIds, cons.allowedDocumentIds, pdf_task=prof.requires_evidence)

    quiz_stats = None
    if "quiz" in prof.validators or inp.outputKind == OutputKind.QUIZ_JSON:
        qv, quiz_stats = C.check_quiz(inp.proposedOutput, expected_count=cons.expectedQuestionCount,
                                      expected_options=cons.expectedOptionCount, evidence_texts=ev_texts,
                                      pdf_task=prof.requires_evidence)
        vs += qv
    if "graph" in prof.validators:
        vs += C.check_graph(inp.proposedOutput)
    # 계획 구조 검증은 구조화된 계획(plan_json 또는 객체)에만 적용한다. 서술형 코칭(text)은 일정 JSON 이 아니므로
    # 예전처럼 JSON_SCHEMA_INVALID(HARD)로 무조건 거절하지 않고, 대신 feasibility 를 '검증 불가'로 두어 점수에 넣지 않는다.
    plan_structured = inp.outputKind == OutputKind.PLAN_JSON or not isinstance(inp.proposedOutput, str)
    if "plan" in prof.validators and plan_structured:
        vs += C.check_plan(inp.proposedOutput, max_daily_hours=cons.maxDailyHours, deadline=cons.deadline,
                           known_prereqs=cons.knownPrerequisites)
    if "vision" in prof.validators:
        vs += C.check_vision(text, ev)
    if "socratic" in prof.validators:
        vs += C.check_socratic(text)
    if "debate" in prof.validators:
        vs += C.check_debate(text)
    if "group" in prof.validators:
        vs += C.check_group_scope(text, cons.participants)
    math_checked, final_ok = 0, None
    if "math" in prof.validators or cons.expectedAnswer is not None:
        mv, math_checked, final_ok = C.check_math(text, cons.expectedAnswer)
        vs += mv
    if "source_fidelity" in prof.validators and ev_texts:
        vs += C.source_fidelity_violations(text, ev_texts)

    codes = {x[0] for x in vs}
    support, n_claims = C.claim_support_ratio(text, ev_texts) if ev_texts else (None, 0)
    if support is not None and n_claims and support < 0.5:
        vs.append(C.v("UNSUPPORTED_CLAIMS", "MAJOR", f"근거 미지지 문장 비율 {round(1 - support, 2)}"))
    rel = C.relevance(inp.originalRequest, text)
    disclosure = C.is_no_claim_disclosure(text)
    # 요청-답변 어휘 관련성은 '질의형' 작업에만 의미가 있다("자료를 요약하라" 같은 요청에는 오탐 — 2026-11-04 실측).
    if inp.taskType in _QUERY_TASKS and rel == 0 and len(C.stems(inp.originalRequest)) >= 2 and not disclosure:
        vs.append(C.v("OFF_TOPIC", "MAJOR", "질문 핵심어가 답변에 없음"))
    contra = C.internal_contradictions(text)
    rep = C.repetition_count(text)
    if rep >= 2:
        vs.append(C.v("REPETITION", "MAJOR", f"반복 문장 {rep}"))
    codes = {x[0] for x in vs}
    hard_codes = {x[0] for x in vs if x[1] == "HARD"}

    judge_res = None
    judge_needed = False

    def fidelity_frac() -> Optional[float]:
        if not ev_texts:
            return None
        return 0.0 if codes & {"NUMERIC_UNSUPPORTED_BY_SOURCE", "SOURCE_CONTRADICTION"} else 1.0

    def evidence_frac() -> Optional[float]:
        if not ev_texts:
            return None
        if codes & {"SOURCE_CONTRADICTION", "NUMERIC_UNSUPPORTED_BY_SOURCE"}:
            return 0.0
        if not n_claims:
            return None        # 대조할 주장이 없으면 근거 일치를 '증명'한 것이 아니다
        return min(1.0, (support or 0.0) / 0.6)

    # 1차: 판정 가능한 사실 차원을 결정적/근거로 채운다.
    dims: Dict[str, Tuple[Optional[float], str]] = {}
    for name, _w in prof.weights:
        if name == "factual_correctness":
            if final_ok is not None:
                dims[name] = (1.0 if final_ok else 0.0, "deterministic:gold")
            elif "MATH_INCORRECT" in codes:
                dims[name] = (0.0, "deterministic:arithmetic")
            elif disclosure:
                dims[name] = (1.0, "deterministic:no_claims")
            elif ev_texts and evidence_frac() is not None:
                dims[name] = (evidence_frac(), "evidence")
            else:
                dims[name] = (None, "unverified")
                judge_needed = True
        elif name == "grounding":
            if disclosure:
                dims[name] = (1.0, "deterministic:no_claims")
            elif ev_texts:
                f = evidence_frac()
                dims[name] = (f, "evidence" if f is not None else "unverified")
            elif prof.requires_evidence:
                dims[name] = (None, "unverified")
            else:
                dims[name] = (None, "not_applicable")
        elif name == "source_fidelity":
            dims[name] = (fidelity_frac(), "evidence" if ev_texts else "unverified")
        elif name == "coverage":
            if ev_texts:
                freq: Dict[str, int] = {}
                for t in ev_texts:
                    for s in C.stems(t):
                        freq[s] = freq.get(s, 0) + 1
                top = [k for k, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:15]]
                cov = len(set(top) & C.stems(text)) / max(1, len(top))
                dims[name] = (min(1.0, cov / 0.5), "evidence")
            else:
                dims[name] = (None, "unverified")
        elif name == "citation":
            if codes & {"UNVERIFIED_CITATION", "UNVERIFIED_SOURCE_CLAIM"}:
                dims[name] = (0.0, "deterministic")
            elif "CITATION_MISSING" in codes:
                dims[name] = (0.4, "deterministic")
            else:
                has_cite = bool(C._CITE_PAGE_RE.search(text) or C._CITE_ID_RE.search(text))
                dims[name] = (1.0 if has_cite else 0.6, "deterministic")
        elif name == "request_fulfillment":
            frac = 0.5 + 0.5 * min(1.0, rel * 1.5)
            if "OFF_TOPIC" in codes:
                frac = 0.3
            if disclosure:
                frac = min(frac, 0.6)
            if "QUIZ_COUNT_MISMATCH" in codes:
                frac *= 0.6
            dims[name] = (frac, "deterministic:lexical")
        elif name in ("logical_consistency", "scenario_consistency", "context_consistency"):
            dims[name] = (max(0.0, 1.0 - 0.35 * (contra + (1 if rep >= 2 else 0))), "deterministic")
        elif name == "format":
            frac = 1.0
            if codes & {"JSON_SCHEMA_INVALID", "REASONING_TAG_LEAK", "TRUNCATED_OUTPUT"}:
                frac -= 0.6
            if codes & {"OVER_LENGTH", "POSSIBLY_TRUNCATED"}:
                frac -= 0.3
            dims[name] = (max(0.0, frac), "deterministic")
        elif name == "persona_level":
            dims[name] = (None, "not_applicable")   # 성격/수준 일치는 결정적으로 증명 불가 → 점수 부여하지 않음
        elif name == "question_quality":
            k = len(codes & {"SOCRATIC_NO_QUESTION", "SOCRATIC_MULTIPLE_QUESTIONS", "SOCRATIC_ANSWER_REVEAL"})
            dims[name] = (max(0.0, 1.0 - 0.5 * k), "deterministic")
        elif name == "argument_evidence":
            base = 0.3 if "DEBATE_NO_REASONING" in codes else 1.0
            dims[name] = (base * (evidence_frac() if ev_texts else 1.0), "deterministic+evidence" if ev_texts else "deterministic")
        elif name == "structure":
            if quiz_stats is not None:
                dims[name] = ((quiz_stats["valid"] / quiz_stats["items"]) if quiz_stats["items"] else 0.0, "deterministic")
            else:
                dims[name] = (0.0 if codes & {"JSON_SCHEMA_INVALID", "GRAPH_DUPLICATE_NODE", "GRAPH_DANGLING_EDGE"} else 1.0, "deterministic")
        elif name == "answer_key":
            if quiz_stats is None or not quiz_stats["items"]:
                dims[name] = (0.0, "deterministic")
            elif ev_texts:
                valid = quiz_stats["valid"] / quiz_stats["items"]
                grounded = (quiz_stats["grounded"] / quiz_stats["valid"]) if quiz_stats["valid"] else 0.0
                dims[name] = (valid * (0.4 + 0.6 * grounded), "deterministic+evidence")
            elif final_ok is not None:
                dims[name] = (1.0 if final_ok else 0.0, "deterministic:gold")
            else:
                dims[name] = (None, "unverified")      # 근거·gold 없는 정답 키는 증명 불가
                judge_needed = True
        elif name == "solution_reverification":
            if final_ok is not None:
                dims[name] = (1.0 if final_ok and "MATH_INCORRECT" not in codes else 0.0, "deterministic:gold")
            elif "MATH_INCORRECT" in codes:
                dims[name] = (0.0, "deterministic:arithmetic")
            else:
                dims[name] = (None, "unverified")
                judge_needed = True
        elif name == "concept_consistency":
            if ev_texts:
                dims[name] = (evidence_frac(), "evidence")
            elif final_ok is not None:
                dims[name] = (1.0 if final_ok else 0.0, "deterministic:gold")
            else:
                dims[name] = (None, "unverified")
                judge_needed = True
        elif name in ("feasibility", "rule_consistency"):
            plan_hard = {c for c in hard_codes if c.startswith("PLAN_") or c == "JSON_SCHEMA_INVALID"}
            if "plan" in prof.validators and not plan_structured:
                dims[name] = (None, "not_applicable")       # 서술형 코칭: 일정 실현 가능성을 결정적으로 증명할 수 없음
            elif name == "rule_consistency" and cons.maxDailyHours is None and cons.deadline is None:
                dims[name] = (None, "not_applicable")
            else:
                major = any(x[0].startswith("PLAN_") and x[1] == "MAJOR" for x in vs)
                dims[name] = (0.0 if plan_hard else (0.6 if major else 1.0), "deterministic")
        elif name == "relation_validity":
            gh = any(x[0].startswith("GRAPH_") and x[1] == "HARD" for x in vs)
            gm = sum(1 for x in vs if x[0].startswith("GRAPH_") and x[1] == "MAJOR")
            dims[name] = (0.0 if gh else max(0.0, 1.0 - 0.3 * gm), "deterministic")
        elif name == "observation_grounding":
            if any(x[0].startswith("VISION_") for x in vs):
                dims[name] = (0.0, "evidence")
            elif ev_texts:
                dims[name] = (1.0, "evidence")
            else:
                dims[name] = (None, "unverified")
        elif name == "uncertainty_honesty":
            dims[name] = (1.0 if C.has_uncertainty(text) or disclosure else 0.6, "deterministic")
        elif name == "privacy":
            dims[name] = (0.0 if codes & {"PII_LEAK", "SECRET_LEAK", "INTERNAL_INFO_LEAK"} else 1.0, "deterministic")
        elif name == "scope":
            dims[name] = (0.0 if codes & {"SOURCE_SCOPE_VIOLATION", "SOURCE_SCOPE_UNVERIFIED"}
                          else (0.4 if "GROUP_PARTICIPANT_SCOPE" in codes else 1.0), "deterministic")
        else:
            dims[name] = (None, "not_applicable")

    # 2차: 증명 안 된 사실 차원만 judge 로(허용 프로파일 + 하드 실패 없을 때만 — GPU 낭비 방지).
    if judge_needed and judge is not None and prof.judge_may_replace_evidence and not hard_codes:
        judge_res = await judge.judge(request_text=inp.originalRequest, output_text=text, evidence_texts=ev_texts)
        gen_family = model_family(os.getenv("AI_QUALITY_GENERATOR_MODEL") or os.getenv("OLLAMA_MODEL") or "qwen3:14b")
        same = judge_res.family and judge_res.family == gen_family
        if same:
            vs.append(C.v("JUDGE_SAME_FAMILY_BIAS", "INFO", f"judge 와 생성 모델이 같은 계열({gen_family}) — 편향 가능"))
        if judge_res.verdict == "CONTRADICTED":
            vs.append(C.v("JUDGE_CONTRADICTION", "MAJOR", "judge 가 사실 오류를 지적(근거 없으면 judge 오류 가능)"))
        for name, (val, method) in list(dims.items()):
            if val is None and method == "unverified" and name in _FACTUAL_DIMS:
                f = judge_res.factual
                if f is not None and same:
                    f = min(f, 0.9)   # 동일 계열 judge 단독으로 만점 불가
                dims[name] = (f, "judge" if f is not None else "unverified")

    verified = True
    for name, (val, method) in dims.items():
        if val is None and method == "unverified" and (name in _FACTUAL_DIMS and prof.factual_required
                                                         or prof.requires_evidence):
            verified = False
    if not verified and "FACTUALITY_UNVERIFIABLE" not in {x[0] for x in vs}:
        vs.append(C.v("FACTUALITY_UNVERIFIABLE", "MAJOR", "결정적 검증/근거/허용된 judge 로 사실성을 확인할 수 없음"))
    return _finalize(inp, prof, vs, dims, started, verified=verified)


def _finalize(inp: QualityInput, prof, vs: List[Tuple], dims: Dict[str, Tuple[Optional[float], str]],
              started: float, *, verified: bool) -> QualityOutput:
    violations = [Violation(code=c, severity=Severity(s), reason=r, evidenceId=e) for (c, s, r, e) in vs]
    hard = any(x.severity == Severity.HARD for x in violations)
    dim_models: List[Dimension] = []
    num = den = 0.0
    for name, w in prof.weights:
        val, method = dims.get(name, (None, "unverified"))
        dim_models.append(Dimension(name=name, score=None if val is None else round(val * w, 2), maxScore=float(w),
                                    method=method))
        if val is not None:
            num += val * w
            den += w
    score: Optional[float] = None
    if verified and den > 0:
        majors = sum(1 for x in violations if x.severity == Severity.MAJOR)
        penalty = min(_GENERIC_MAJOR_CAP, _GENERIC_MAJOR_PENALTY * majors)
        score = round(max(0.0, 100.0 * num / den - penalty), 1)
    if not dims:  # EMPTY_OUTPUT 조기 종료
        score = 0.0
        verified = False
    if hard or not verified or score is None or score < MINIMUM_SCORE:
        status = QualityStatus.REJECTED
    else:
        status = QualityStatus.APPROVED
    hints = None
    if status != QualityStatus.APPROVED:
        hints = list(dict.fromkeys(HINTS[x.code] for x in violations if x.code in HINTS))[:8] or None
    # C-RQ-1: 필수 검증기(빈 출력/잘림/비밀·PII/주입/범위/스키마/수식/인용 위조 등)의 실패는 전부 HARD 로 보고된다.
    return QualityOutput(schemaVersion=SCHEMA_VERSION, requestId=inp.requestId, taskType=inp.taskType, success=True,
                         verified=verified, qualityStatus=status, score=score, minimumScore=MINIMUM_SCORE, hardFail=hard,
                         violations=violations, dimensions=dim_models, regenerationHints=hints,
                         evaluatorVersion=EVALUATOR_VERSION, modelDigest=inp.modelDigest,
                         latencyMs=_latency_ms(started), mandatoryValidatorsPassed=not hard)
