"""시드/전량 생성 오케스트레이터. dry-run, 중단 임계값, manifest, git 안전장치."""
import argparse
import uuid
import yaml
from pathlib import Path
from . import paths
from .utils import git_guard
from .utils.dedup import Deduper
from .utils.manifest import Manifest
from .utils.ollama_client import OllamaClient
from .generators import REGISTRY


def load_config(path=None) -> dict:
    p = Path(path) if path else (paths.PKG_DIR / "config.example.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def check_abort(totals: dict, cfg: dict) -> str | None:
    t = cfg["abort_thresholds"]
    if totals["reject_reasons"].get("pii_secret", 0) > t["secret_pii_count"]:
        return "secret/PII detected → 즉시 중단"
    done = totals["accepted"] + totals["rejected"]
    if done >= 50:  # 표본 충분할 때만 비율 적용
        if totals["rejected"] / max(1, done) > t["total_reject_ratio"]:
            return "total reject ratio 초과"
        if totals["quiz_total"] >= 20 and totals["quiz_invalid"] / totals["quiz_total"] > t["quiz_invalid_ratio"]:
            return "quiz invalid ratio 초과"
        if totals["empty"] / max(1, done) > t["empty_assistant_ratio"]:
            return "empty assistant ratio 초과"
    return None


def run(profile="seed", dry_run=False, per_category=None, config=None, client=None) -> dict:
    git_guard.assert_safe()
    cfg = config or load_config()
    paths.ensure_dirs()
    counts = ({c: (per_category or 5) for c in REGISTRY} if dry_run
              else cfg[f"{profile}_counts"])
    oc = cfg["ollama"]
    client = client or OllamaClient(oc["base_url"], oc["model"], think=oc["think"],
        num_predict=oc["num_predict"], temperature=oc["temperature"],
        timeout_s=oc["timeout_s"], vram_guard_mib=oc["vram_guard_mib"])
    base = (paths.SUBDIRS["cache"] / "dryrun") if dry_run else paths.BASE
    raw_d, clean_d, rej_d = base / "raw", base / "cleaned", base / "rejected"
    deduper = Deduper()
    run_id = uuid.uuid4().hex[:12]
    digest = client.model_digest() if hasattr(client, "model_digest") else "unknown"
    man = Manifest.new(run_id, git_guard.current_commit(), oc["model"], digest,
                       generation_config=oc, input_seed=cfg.get("seed", 0))
    totals = {"accepted": 0, "rejected": 0, "repaired": 0, "deduped": 0,
              "quiz_total": 0, "quiz_invalid": 0, "empty": 0, "reject_reasons": {}}
    aborted = None
    for cat, n in counts.items():
        gen = REGISTRY[cat]()
        shard = "0001"
        res = gen.generate(n, client, deduper,
            raw_d / f"{cat}_{shard}.jsonl", clean_d / f"{cat}_{shard}.clean.jsonl", rej_d)
        totals["accepted"] += res.accepted
        totals["rejected"] += res.rejected
        totals["repaired"] += res.repaired
        totals["deduped"] += res.deduped
        for k, v in res.reject_reasons.items():
            totals["reject_reasons"][k] = totals["reject_reasons"].get(k, 0) + v
            if k.startswith("quiz_"):
                totals["quiz_invalid"] += v
            if k == "empty_answer":
                totals["empty"] += v
        if cat == "quiz":
            totals["quiz_total"] += n
        man.record(res.accepted, res.rejected, res.repaired, res.deduped, category=cat)
        aborted = check_abort(totals, cfg)
        if aborted:
            break
    man.finish()
    man.save()
    return {"dry_run": dry_run, "run_id": run_id, "aborted": aborted, **totals}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--per-category", type=int, default=None)
    ap.add_argument("--profile", default="seed", choices=["seed", "full"])
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    cfg = load_config(a.config)
    s = run(profile=a.profile, dry_run=a.dry_run, per_category=a.per_category, config=cfg)
    print(s)


if __name__ == "__main__":
    main()
