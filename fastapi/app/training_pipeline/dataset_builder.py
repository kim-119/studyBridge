"""TRAIN_ELIGIBLE 후보 → train/validation/test 데이터셋(누출 방지 그룹 분할).

- 내보내기 직전에 자격을 다시 판정한다(동의 철회/삭제/PII/부정 피드백이 그 사이 생겼을 수 있음).
- 같은 사용자 · 같은 문서(materialId/documentId/revision) · 동일/유사 중복(SimHash ≤6)은 하나의 그룹(union-find)으로
  묶어 반드시 같은 split 에 넣는다. 기존 test 그룹(frozen)은 test 로 고정한다.
- 채팅 템플릿: 고정·버전된 학습용 system 프롬프트 + 질문(+PDF 근거 블록) + 검증된 답변(verified_answer).
  런타임 system prompt 나 모델 원 답변(candidate_answer)을 학습 정답으로 쓰지 않는다(자기증폭 차단).
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from app.training_pipeline.eligibility import PDF_KINDS, evaluate_eligibility
from app.training_pipeline.records import CandidateRecord
from app.utils.duplicate_checker import NEAR_DUP_MAX_HAMMING, hamming

TEMPLATE_VERSION = "sb-chat-v1"
TRAINING_SYSTEM_PROMPT_V1 = ("너는 StudyBridge 학습 도우미다. 제공된 근거가 있으면 근거와 일치하게, "
                             "근거가 없으면 확인된 사실만 한국어로 간결하게 답한다.")
SPLITS = ("train", "validation", "test")


class LeakageError(Exception):
    pass


@dataclass
class DatasetSample:
    candidate_id: str
    content_hash: str
    user_key: str
    doc_keys: Set[str]
    simhash: int
    messages: List[Dict[str, str]]
    record: CandidateRecord


@dataclass
class DatasetBuild:
    splits: Dict[str, List[DatasetSample]]
    excluded: Dict[str, int] = field(default_factory=dict)
    groups: int = 0

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.splits.values())


def _doc_keys(rec: CandidateRecord) -> Set[str]:
    keys = set()
    for e in rec.evidence or []:
        if e.get("materialId") is not None:
            keys.add(f"m:{e['materialId']}")
        if e.get("documentId"):
            keys.add(f"d:{e['documentId']}")
    if rec.source_revision_hash:
        keys.add(f"r:{rec.source_revision_hash}")
    return keys


def to_messages(rec: CandidateRecord) -> List[Dict[str, str]]:
    user = rec.question.strip()
    if rec.source_kind in PDF_KINDS:
        quotes = [f"[p.{e.get('page')} {e.get('chunkId')}] {str(e.get('quote') or '').strip()}"
                  for e in rec.evidence or [] if e.get("quote")]
        user = "<evidence>\n" + "\n".join(quotes) + "\n</evidence>\n\n" + user
    return [{"role": "system", "content": TRAINING_SYSTEM_PROMPT_V1},
            {"role": "user", "content": user},
            {"role": "assistant", "content": (rec.verified_answer or "").strip()}]


class _UF:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _bands(sim: int) -> List[Tuple[int, int]]:
    # 8개 밴드 × 8비트: 해밍거리 ≤7 이면 비둘기집 원리로 최소 한 밴드가 완전히 같다(≤6 near-dup 누락 없음).
    u = sim & ((1 << 64) - 1)
    return [(i, (u >> (8 * i)) & 0xFF) for i in range(8)]


def _bucket(seed: str, key: str, ratios: Tuple[float, float, float]) -> str:
    x = int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    if x < ratios[0]:
        return "train"
    return "validation" if x < ratios[0] + ratios[1] else "test"


def build_dataset(records: Iterable[CandidateRecord], *, ratios: Tuple[float, float, float] = (0.8, 0.1, 0.1),
                  seed: str = "sb-dataset-v1", frozen_test_hashes: Optional[Set[str]] = None,
                  max_sample_chars: int = 16000) -> DatasetBuild:
    excluded: Counter = Counter()
    samples: List[DatasetSample] = []
    seen_hash: Set[str] = set()
    for rec in records:
        res = evaluate_eligibility(rec)
        if not res.eligible:
            for r in res.reasons:
                excluded[r] += 1
            continue
        if rec.content_hash in seen_hash:
            excluded["EXACT_DUPLICATE"] += 1
            continue
        msgs = to_messages(rec)
        if sum(len(m["content"]) for m in msgs) > max_sample_chars:
            excluded["SAMPLE_TOO_LONG"] += 1
            continue
        seen_hash.add(rec.content_hash)
        samples.append(DatasetSample(candidate_id=rec.candidate_id, content_hash=rec.content_hash,
                                     user_key=rec.pseudonymous_user_key, doc_keys=_doc_keys(rec),
                                     simhash=rec.simhash, messages=msgs, record=rec))

    uf = _UF(len(samples))
    first_by_key: Dict[str, int] = {}
    for i, s in enumerate(samples):
        for k in [f"u:{s.user_key}"] + sorted(s.doc_keys):
            if k in first_by_key:
                uf.union(i, first_by_key[k])
            else:
                first_by_key[k] = i
    band_index: Dict[Tuple[int, int], List[int]] = {}
    for i, s in enumerate(samples):
        for b in _bands(s.simhash):
            for j in band_index.get(b, []):
                if hamming(s.simhash, samples[j].simhash) <= NEAR_DUP_MAX_HAMMING:
                    uf.union(i, j)
            band_index.setdefault(b, []).append(i)

    groups: Dict[int, List[int]] = {}
    for i in range(len(samples)):
        groups.setdefault(uf.find(i), []).append(i)
    frozen = frozen_test_hashes or set()
    splits: Dict[str, List[DatasetSample]] = {k: [] for k in SPLITS}
    assign: Dict[int, str] = {}
    for root, members in groups.items():
        if any(samples[m].content_hash in frozen for m in members):
            split = "test"
        else:
            split = _bucket(seed, min(samples[m].content_hash for m in members), ratios)
        for m in members:
            assign[m] = split
            splits[split].append(samples[m])

    verify_no_leakage(splits)
    return DatasetBuild(splits=splits, excluded=dict(excluded), groups=len(groups))


def verify_no_leakage(splits: Dict[str, List[DatasetSample]]) -> None:
    """split 간 사용자/문서/정확·유사 중복 공유가 하나라도 있으면 LeakageError."""
    owner: Dict[str, str] = {}
    for name, items in splits.items():
        for s in items:
            for k in [f"u:{s.user_key}", f"h:{s.content_hash}"] + sorted(s.doc_keys):
                prev = owner.setdefault(k, name)
                if prev != name:
                    raise LeakageError(f"key shared across {prev}/{name}: {k.split(':')[0]}")
    flat = [(name, s) for name, items in splits.items() for s in items]
    band_index: Dict[Tuple[int, int], List[Tuple[str, int]]] = {}
    for name, s in flat:
        for b in _bands(s.simhash):
            for other_name, other_sim in band_index.get(b, []):
                if other_name != name and hamming(s.simhash, other_sim) <= NEAR_DUP_MAX_HAMMING:
                    raise LeakageError(f"near-duplicate across {other_name}/{name}")
            band_index.setdefault(b, []).append((name, s.simhash))


def split_hash(items: List[DatasetSample]) -> str:
    return hashlib.sha256("\n".join(sorted(s.content_hash for s in items)).encode()).hexdigest()
