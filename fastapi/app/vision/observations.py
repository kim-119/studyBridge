"""화면 판독 관측 근거(vision-observation.v1) — EC2 Phase D 요청 R1·R5-2.

Spring 이 비전 답변을 품질 평가할 때 '답변이 화면에서 실제로 읽힌 내용에 근거했는가'를 확인할 수 있도록, 응답에
마스킹된 판독 관측 목록과 답변이 참조한 관측 id 를 싣는다(VISION_RETURN_OBSERVATIONS=true 일 때만, 기본 꺼짐).

    "observationSchemaVersion": "vision-observation.v1",
    "observations": [{"observationId": "obs-1", "kind": "TEXT", "text": "(마스킹된 판독 텍스트)", "confidence": "OBSERVED"}],
    "answerObservationIds": ["obs-1"], "uncertainObservationIds": ["obs-4"], "legible": true, "screenType": "code"

- text 는 mask_obj 를 거친 판독 결과에서만 만든다(마스킹 전 원문·이미지는 응답에 없다).
- confidence 는 판독 모델이 '불확실' 목록에 넣었거나 화면이 판독 불가(legible=false)면 UNCERTAIN, 아니면 OBSERVED.
  VLM 은 숫자 확률도 좌표도 내지 않으므로 숫자 confidence·bbox 는 만들지 않는다(추측 금지 — bbox 는 생략).
- answerObservationIds 는 결정적 대조(답변에 관측 텍스트의 12자 이상 조각이 그대로 나타남)로 정한다.
- 평가기 입력 변환: evidenceId=observationId, sourceType=VISION_OBSERVATION(_UNCERTAIN), text=관측 텍스트.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

SCHEMA_VERSION = "vision-observation.v1"
MAX_OBSERVATIONS = 24
MAX_TEXT_CHARS = 400
MAX_TOTAL_CHARS = 6000
OBSERVED, UNCERTAIN = "OBSERVED", "UNCERTAIN"
SOURCE_TYPES = {OBSERVED: "VISION_OBSERVATION", UNCERTAIN: "VISION_OBSERVATION_UNCERTAIN"}

_LIST_KINDS = (("errors", "ERROR"), ("math", "MATH"), ("charts", "CHART"), ("visualElements", "VISUAL"),
               ("questionEvidence", "QUESTION_EVIDENCE"), ("embeddedInstructions", "EMBEDDED_INSTRUCTION"))


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _clip(s: Any) -> str:
    return str(s or "").replace("\x00", "").strip()[:MAX_TEXT_CHARS]


def build_observations(masked: Dict[str, Any]) -> List[Dict[str, Any]]:
    """마스킹된 판독 dict → 관측 목록(순서 고정: 본문 줄 → 코드 → 오류·수식·차트·시각요소·질문근거·내장지시 → 불확실)."""
    if not isinstance(masked, dict):
        return []
    legible = masked.get("legible") is True
    uncertain = [_clip(u) for u in (masked.get("uncertain") or []) if _clip(u)]
    unc_norm = [_norm(u) for u in uncertain]
    raw: List[tuple] = []
    for line in str(masked.get("readableText") or "").splitlines():
        if _clip(line):
            raw.append(("TEXT", _clip(line)))
    for c in masked.get("code") or []:
        if isinstance(c, dict) and _clip(c.get("content")):
            raw.append(("CODE", _clip(c.get("content"))))
    for field, kind in _LIST_KINDS:
        for item in masked.get(field) or []:
            if _clip(item):
                raw.append((kind, _clip(item)))
    out: List[Dict[str, Any]] = []
    total = 0
    seen = set()

    def add(kind: str, text: str, conf: str) -> bool:
        nonlocal total
        key = (kind, _norm(text))
        if key in seen or not text:
            return True
        if len(out) >= MAX_OBSERVATIONS or total + len(text) > MAX_TOTAL_CHARS:
            return False
        seen.add(key)
        total += len(text)
        out.append({"observationId": f"obs-{len(out) + 1}", "kind": kind, "text": text, "confidence": conf})
        return True

    for kind, text in raw:
        n = _norm(text)
        conf = UNCERTAIN if (not legible or any(u and (u in n or n in u) for u in unc_norm)) else OBSERVED
        if not add(kind, text, conf):
            break
    for u in uncertain:
        if not add("UNCERTAIN", u, UNCERTAIN):
            break
    return out


def referenced_ids(answer: str, observations: List[Dict[str, Any]], min_overlap: int = 12) -> List[str]:
    """답변이 실제로 기대는 관측 id. 관측 텍스트(공백 제거)의 min_overlap 자 조각이 답변에 그대로 나오면 참조로 본다.
    짧은 관측(min_overlap 미만)은 통째로 나와야 한다. 답변 안의 [근거:obs-N] 표기도 인정한다(목록에 있는 id 만)."""
    na = _norm(answer)
    ids = {o["observationId"] for o in observations}
    out: List[str] = []
    for o in observations:
        q = _norm(o.get("text") or "")
        if not q:
            continue
        hit = (q in na) if len(q) < min_overlap else any(
            q[i:i + min_overlap] in na for i in range(0, len(q) - min_overlap + 1, max(1, min_overlap // 2)))
        if hit:
            out.append(o["observationId"])
    for m in re.finditer(r"\[(?:근거|출처|evidence)\s*[:：]\s*(obs-\d{1,3})\]", answer or "", re.IGNORECASE):
        if m.group(1) in ids and m.group(1) not in out:
            out.append(m.group(1))
    return out


def observation_payload(masked: Dict[str, Any], answer: str) -> Dict[str, Any]:
    obs = build_observations(masked)
    return {
        "observationSchemaVersion": SCHEMA_VERSION,
        "observations": obs,
        "answerObservationIds": referenced_ids(answer, obs),
        "uncertainObservationIds": [o["observationId"] for o in obs if o["confidence"] == UNCERTAIN],
        "legible": bool(masked.get("legible")) if isinstance(masked, dict) else False,
        "screenType": (masked.get("screenType") if isinstance(masked, dict) else None) or "other",
    }


def to_quality_evidence(observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """관측 → response-quality.v1 groundingEvidence(Spring 이 평가기에 넘길 형태, 32개 상한)."""
    return [{"evidenceId": o["observationId"], "sourceType": SOURCE_TYPES.get(o["confidence"], "VISION_OBSERVATION_UNCERTAIN"),
             "text": o["text"]} for o in observations[:32]]
