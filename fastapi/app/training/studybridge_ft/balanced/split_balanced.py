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
    for _, rows in sorted(strata.items(), key=lambda kv: str(kv[0])):
        rows = rows[:]
        rnd.shuffle(rows)
        n = len(rows)
        n_tr = max(1, int(n * ratios[0])) if n >= 3 else n
        n_va = 1 if n - n_tr >= 2 else 0
        train += rows[:n_tr]
        valid += rows[n_tr:n_tr + n_va]
        test += rows[n_tr + n_va:]
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
