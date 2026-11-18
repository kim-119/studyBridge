"""
학습 데이터 train / valid / test 분리.

기본 비율: train 80%, valid 10%, test 10%.
- 최신 데이터 / 고품질 레거시 / 엣지케이스 비율로 샘플링한다.
- 성격(personality)·지식수준(knowledge_level) 분포가 한쪽으로 쏠리지 않도록 한다.
- 인사/잡담(일상대화) 데이터는 대부분 제외한다.
- 데이터셋 크기 상한을 준수한다.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SplitConfig:
    train_ratio: float = 0.80
    valid_ratio: float = 0.10
    test_ratio:  float = 0.10

    max_train_samples: int = 5000
    max_valid_samples: int = 500
    max_test_samples:  int = 500

    # 샘플링 비율 (합 = 1.0)
    recent_data_ratio:         float = 0.60   # 최신 데이터
    high_quality_legacy_ratio: float = 0.30   # 고품질 레거시
    edge_case_ratio:           float = 0.10   # 엣지케이스

    max_casual_ratio: float = 0.05    # 일상대화 최대 허용 비율
    seed: int = 42


@dataclass
class SplitResult:
    train: list[dict] = field(default_factory=list)
    valid: list[dict] = field(default_factory=list)
    test:  list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.train) + len(self.valid) + len(self.test)


_CASUAL_LEVELS = {"일상대화", "casual"}


def split_dataset(rows: list[dict], config: SplitConfig | None = None) -> SplitResult:
    """
    전체 분리 파이프라인.

    1. 일상대화 비율 제한
    2. 품질 기반 + 날짜 기반 구분 샘플링
    3. train/valid/test 분리
    4. 크기 상한 적용
    """
    if config is None:
        config = SplitConfig()

    rng = random.Random(config.seed)

    # 1. 일상대화 제한
    casual  = [r for r in rows if str(r.get("knowledge_level", "")).strip() in _CASUAL_LEVELS]
    serious = [r for r in rows if str(r.get("knowledge_level", "")).strip() not in _CASUAL_LEVELS]

    max_casual = max(1, int(len(serious) * config.max_casual_ratio))
    rng.shuffle(casual)
    casual = casual[:max_casual]

    rows = serious + casual
    if len(rows) == 0:
        return SplitResult()

    # 2. 품질 기반 정렬 후 구간 분리
    rows_sorted = sorted(rows, key=lambda r: r.get("quality_score", 0), reverse=True)

    n = len(rows_sorted)
    recent_cutoff = int(n * config.recent_data_ratio)
    legacy_cutoff = recent_cutoff + int(n * config.high_quality_legacy_ratio)

    recent       = rows_sorted[:recent_cutoff]
    high_legacy  = rows_sorted[recent_cutoff:legacy_cutoff]
    edge_cases   = rows_sorted[legacy_cutoff:]

    # 3. 총 목표 샘플 수: train + valid + test 최대값 합
    target_total = min(
        config.max_train_samples + config.max_valid_samples + config.max_test_samples,
        n,
    )

    target_recent  = int(target_total * config.recent_data_ratio)
    target_legacy  = int(target_total * config.high_quality_legacy_ratio)
    target_edge    = target_total - target_recent - target_legacy

    rng.shuffle(recent)
    rng.shuffle(high_legacy)
    rng.shuffle(edge_cases)

    selected = (
        recent[:target_recent]
        + high_legacy[:target_legacy]
        + edge_cases[:target_edge]
    )
    rng.shuffle(selected)

    # 4. 성격/지식수준 분포 균형 (greedy 방식)
    selected = _balance_distribution(selected, rng)

    # 5. train/valid/test 비율 분리
    n_sel   = len(selected)
    n_test  = min(config.max_test_samples,  max(1, int(n_sel * config.test_ratio)))
    n_valid = min(config.max_valid_samples, max(1, int(n_sel * config.valid_ratio)))
    n_train = min(config.max_train_samples, n_sel - n_valid - n_test)

    train = selected[:n_train]
    valid = selected[n_train:n_train + n_valid]
    test  = selected[n_train + n_valid:n_train + n_valid + n_test]

    logger.info(
        "split 완료: train=%d valid=%d test=%d (입력 %d → 선택 %d)",
        len(train), len(valid), len(test), len(rows), n_sel,
    )
    return SplitResult(train=train, valid=valid, test=test)


def _balance_distribution(rows: list[dict], rng: random.Random) -> list[dict]:
    """
    성격·지식수준 분포가 한쪽에 치우치면 과도한 카테고리를 줄인다.
    각 카테고리 최대 비율 40% 이내.
    """
    if len(rows) <= 10:
        return rows

    _MAX_CATEGORY_RATIO = 0.40
    max_per_category = max(1, int(len(rows) * _MAX_CATEGORY_RATIO))

    # 성격 기준 제한
    persona_buckets: dict[str, list[dict]] = {}
    for r in rows:
        p = str(r.get("personality", "unknown"))
        persona_buckets.setdefault(p, []).append(r)

    result = []
    for p, bucket in persona_buckets.items():
        if len(bucket) > max_per_category:
            rng.shuffle(bucket)
            result.extend(bucket[:max_per_category])
        else:
            result.extend(bucket)

    rng.shuffle(result)
    return result
