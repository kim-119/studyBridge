"""stratified train/valid/test split. domain×task×difficulty 층화로 분포 보존 (스펙 97)."""
from __future__ import annotations
import random
from collections import defaultdict
from pathlib import Path

from .. import paths
from ..utils import jsonl_io
from ..utils.dedup import sample_hash


def _stratum(s: dict) -> tuple:
    md = s.get("metadata", {})
    return (md.get("domain"), md.get("task_type"), md.get("difficulty"))


def split(samples: list[dict], ratios=(0.90, 0.05, 0.05), seed: int = 0) -> dict:
    rnd = random.Random(seed)
    # dedup 먼저
    seen, uniq = set(), []
    for s in samples:
        h = sample_hash(s)
        if h in seen:
            continue
        seen.add(h)
        uniq.append(s)

    strata = defaultdict(list)
    for s in uniq:
        strata[_stratum(s)].append(s)

    train, valid, test = [], [], []
    # 분수 잔여를 strata 간 이월(largest-remainder)해서 작은 stratum도 valid/test에
    # 기여하게 한다. per-stratum 독립 반올림은 5%(valid)를 항상 0으로 굶긴다(회귀 버그).
    carry = [0.0, 0.0, 0.0]
    for _, rows in sorted(strata.items(), key=lambda kv: str(kv[0])):
        rows = rows[:]
        rnd.shuffle(rows)
        n = len(rows)
        want = [carry[i] + n * ratios[i] for i in range(3)]
        counts = [int(w) for w in want]
        leftover = n - sum(counts)
        order = sorted(range(3), key=lambda i: want[i] - counts[i], reverse=True)
        for k in range(leftover):
            counts[order[k % 3]] += 1
        carry = [want[i] - counts[i] for i in range(3)]
        i0, i1 = counts[0], counts[0] + counts[1]
        train += rows[:i0]
        valid += rows[i0:i1]
        test += rows[i1:]
    rnd.shuffle(train); rnd.shuffle(valid); rnd.shuffle(test)
    return {"train": train, "valid": valid, "test": test}


def run(cleaned_file: Path | None = None, out_dir: Path | None = None, seed: int = 0) -> dict:
    src = cleaned_file or (paths.BASE / "cleaned" / "balanced.jsonl")
    odir = out_dir or paths.SUBDIRS["data"]
    paths.assert_outside_repo(odir)
    samples = jsonl_io.read_jsonl(src)
    sp = split(samples, seed=seed)
    counts = {}
    for name in ("train", "valid", "test"):
        counts[name] = jsonl_io.write_jsonl(odir / f"{name}_balanced.jsonl", sp[name])
    return {"input": len(samples), **counts}


def main():
    print(run())


if __name__ == "__main__":
    main()
