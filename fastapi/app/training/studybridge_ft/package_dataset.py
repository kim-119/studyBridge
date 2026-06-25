"""cleaned shard → dedup → bucket cap → 90/5/5 split → ChatML data/*.jsonl."""
import random
from pathlib import Path
from . import paths
from .utils import jsonl_io
from .utils.dedup import sample_hash
from .utils.token_bucket import assign_buckets


def split_rows(rows, ratios, seed=0) -> dict:
    rnd = random.Random(seed)
    rows = rows[:]
    rnd.shuffle(rows)
    n = len(rows)
    n_tr = int(n * ratios["train"])
    n_va = int(n * ratios["valid"])
    train = rows[:n_tr]
    rest = rows[n_tr:]
    tr_hashes = {sample_hash(x) for x in train}
    rest = [x for x in rest if sample_hash(x) not in tr_hashes]
    valid = rest[:n_va]
    test = rest[n_va:]
    return {"train": train, "valid": valid, "test": test}


def package(cleaned_dir=None, out_dir=None, cfg=None) -> dict:
    import yaml
    cfg = cfg or yaml.safe_load((paths.PKG_DIR / "config.example.yaml").read_text(encoding="utf-8"))
    cdir = Path(cleaned_dir) if cleaned_dir else paths.BASE / "cleaned"
    odir = Path(out_dir) if out_dir else paths.SUBDIRS["data"]
    paths.assert_outside_repo(odir)
    rows = []
    seen = set()
    for f in sorted(cdir.glob("*.clean.jsonl")):
        for s in jsonl_io.read_jsonl(f):
            h = sample_hash(s)
            if h in seen:
                continue
            seen.add(h)
            rows.append(s)
    buckets = assign_buckets(rows, cfg["buckets"])
    kept = buckets["512"] + buckets["1024"] + buckets["2048"]
    sp = split_rows(kept, cfg["split"], seed=cfg.get("seed", 0))
    counts = {}
    for name in ("train", "valid", "test"):
        counts[name] = jsonl_io.write_jsonl(odir / f"{name}.jsonl", sp[name])
    return {"total": len(kept), "dropped_xlong": buckets["dropped_xlong"],
            "buckets": {k: len(buckets[k]) for k in ("512", "1024", "2048")}, **counts}


def main():
    print(package())


if __name__ == "__main__":
    main()
