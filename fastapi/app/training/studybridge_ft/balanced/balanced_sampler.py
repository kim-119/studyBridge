"""domain × task_type × difficulty stratified 샘플링 계획기.

스펙 72-76, 97. 같은 (total, seed)에서 동일 계획 재현. 상·하한 캡 보장.
페르소나는 professor 태스크에서만 순회, 그 외 'default'.
"""
from __future__ import annotations
import random
from collections import Counter
from dataclasses import dataclass
from . import taxonomy as tx


@dataclass(frozen=True)
class Cell:
    domain: str
    subdomain: str
    task_type: str
    difficulty: str
    persona: str


def _largest_remainder(total: int, keys: list[str]) -> dict[str, int]:
    """total을 keys 개수로 균등 배분(최대잉여법) — 합이 정확히 total."""
    n = len(keys)
    base = total // n
    rem = total - base * n
    alloc = {k: base for k in keys}
    # 잉여는 앞에서부터(결정론적) 1개씩
    for k in keys[:rem]:
        alloc[k] += 1
    return alloc


def build_plan(total: int, seed: int = 42) -> list[Cell]:
    """균형 계획 생성. domain→task→difficulty 3중 균등 배분, subdomain/persona 순회."""
    domains = tx.all_domains()
    tasks = tx.TASK_TYPES
    diffs = tx.DIFFICULTIES

    plan: list[Cell] = []
    sub_idx = {d: 0 for d in domains}      # 학문별 subdomain 라운드로빈 포인터
    persona_idx = 0

    dom_alloc = _largest_remainder(total, domains)
    for d in domains:
        task_alloc = _largest_remainder(dom_alloc[d], tasks)
        for t in tasks:
            diff_alloc = _largest_remainder(task_alloc[t], diffs)
            for diff in diffs:
                for _ in range(diff_alloc[diff]):
                    subs = tx.subdomains(d)
                    sub = subs[sub_idx[d] % len(subs)]
                    sub_idx[d] += 1
                    if t == "professor":
                        persona = tx.PERSONAS[persona_idx % len(tx.PERSONAS)]
                        persona_idx += 1
                    else:
                        persona = "default"
                    plan.append(Cell(d, sub, t, diff, persona))

    # 결정론적 셔플(생성 순서 다양화, 분포는 보존)
    random.Random(seed).shuffle(plan)
    return plan


def distribution(cells: list[Cell]) -> dict:
    """계획/데이터의 축별 분포 비율 반환."""
    n = max(1, len(cells))
    dom = Counter(c.domain for c in cells)
    task = Counter(c.task_type for c in cells)
    diff = Counter(c.difficulty for c in cells)
    return {
        "total": len(cells),
        "domain": {k: dom[k] / n for k in tx.all_domains()},
        "task": {k: task[k] / n for k in tx.TASK_TYPES},
        "difficulty": {k: diff[k] / n for k in tx.DIFFICULTIES},
        "_counts": {"domain": dict(dom), "task": dict(task), "difficulty": dict(diff)},
    }


def check_distribution(cells: list[Cell]) -> tuple[bool, list[str]]:
    """분포 게이트 — 상·하한 캡 위반 목록 반환. (통과여부, 위반사유)."""
    dist = distribution(cells)
    n = dist["total"]
    issues: list[str] = []
    if n == 0:
        return False, ["empty"]
    # 모든 학문 최소 1회 (스펙 23)
    for d in tx.all_domains():
        if dist["_counts"]["domain"].get(d, 0) == 0:
            issues.append(f"domain_missing:{d}")
    # 학문 상·하한
    for d, r in dist["domain"].items():
        if r > tx.DOMAIN_CAP_HIGH + 1e-9:
            issues.append(f"domain_over:{d}={r:.3f}")
        if 0 < r < tx.DOMAIN_CAP_LOW - 1e-9:
            issues.append(f"domain_under:{d}={r:.3f}")
    # 태스크 상·하한
    for t, r in dist["task"].items():
        if r > tx.TASK_CAP_HIGH + 1e-9:
            issues.append(f"task_over:{t}={r:.3f}")
        if 0 < r < tx.TASK_CAP_LOW - 1e-9:
            issues.append(f"task_under:{t}={r:.3f}")
    return (not issues), issues
