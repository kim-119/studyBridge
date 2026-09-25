"""균형 데이터 생성 오케스트레이터. stratified plan을 따라 셀별 1샘플 생성.

스펙 72-89. resume(cursor), 100개마다 중간 분포(채팅/stdout), abort 임계값, 최종 분포 게이트.
출력은 repo 밖(~/studybridge-ft). 리포트는 파일 아닌 stdout.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .. import paths
from ..utils import jsonl_io
from ..utils.dedup import Deduper
from ..utils.ollama_client import OllamaClient
from . import balanced_sampler as bs
from . import prompt_builder_balanced as pb
from . import validate_balanced as vb
from . import taxonomy as tx

OUT = lambda: paths.BASE / "cleaned" / "balanced.jsonl"          # noqa: E731
CURSOR = lambda: paths.BASE / "cleaned" / "balanced.cursor"      # noqa: E731
REJECT_DIR = lambda: paths.BASE / "rejected"                     # noqa: E731

ABORT = {"reject_ratio": 0.30, "empty_ratio": 0.01}


def _print_distribution(samples: list[dict], header: str):
    ok, issues = vb.gate_distribution(samples)
    from collections import Counter
    dom = Counter(s["metadata"]["domain"] for s in samples)
    n = max(1, len(samples))
    print(f"\n[{header}] 수집 {len(samples)}")
    top = ", ".join(f"{k} {v}({v/n*100:.0f}%)" for k, v in dom.most_common(4))
    print(f"  상위학문: {top}")
    print(f"  분포게이트: {'OK' if ok else '위반 ' + str(issues[:4])}")
    sys.stdout.flush()


def generate(total: int, seed: int = 42, resume: bool = True,
             base_url="http://localhost:11434", model="qwen3:14b") -> dict:
    paths.ensure_dirs()
    plan = bs.build_plan(total, seed)
    out, cursor_f, rej = OUT(), CURSOR(), REJECT_DIR()
    rej.mkdir(parents=True, exist_ok=True)

    start = 0
    samples: list[dict] = []
    deduper = Deduper()
    if resume and out.exists():
        samples = jsonl_io.read_jsonl(out)
        for s in samples:
            deduper.is_dup(s)
        if cursor_f.exists():
            start = int(cursor_f.read_text().strip() or "0")
    print(f"=== 균형 생성 시작: 계획 {len(plan)} / 재개 인덱스 {start} / 기존 {len(samples)} ===")

    client = OllamaClient(base_url, model, think=False, num_predict=1024)
    stats = {"accepted": len(samples), "rejected": 0, "repaired": 0,
             "deduped": 0, "empty": 0, "reject_reasons": {}, "aborted": None}
    processed = start

    for i in range(start, len(plan)):
        cell = plan[i]
        sysp, userp = pb.build(cell)
        raw = client.chat(sysp, userp)
        sample = pb.make_sample(cell, raw)
        ok, reason, tags = vb.validate_sample(sample)
        if not ok:  # repair 1회
            raw2 = client.chat(sysp, userp)
            sample2 = pb.make_sample(cell, raw2)
            ok2, reason2, tags2 = vb.validate_sample(sample2)
            if ok2:
                sample, ok, tags = sample2, True, tags2
                stats["repaired"] += 1
            else:
                stats["rejected"] += 1
                if reason2 == "empty":
                    stats["empty"] += 1
                stats["reject_reasons"][reason2] = stats["reject_reasons"].get(reason2, 0) + 1
                jsonl_io.append_jsonl(rej / f"{reason2}.jsonl", sample2)
                processed = i + 1
                cursor_f.write_text(str(processed))
                continue
        if deduper.is_dup(sample):
            stats["deduped"] += 1
            processed = i + 1
            cursor_f.write_text(str(processed))
            continue
        sample["metadata"]["quality_tags"] = tags
        jsonl_io.append_jsonl(out, sample)
        samples.append(sample)
        stats["accepted"] += 1
        processed = i + 1
        cursor_f.write_text(str(processed))

        done = i + 1 - start
        if done > 0 and stats["accepted"] % 100 == 0:
            _print_distribution(samples, f"중간 {stats['accepted']}")
            # abort 체크: reject / (reject+accepted)
            total_tried = max(1, stats["rejected"] + stats["accepted"])
            if stats["rejected"] / total_tried > ABORT["reject_ratio"]:
                stats["aborted"] = "reject_ratio"
                break

    _print_distribution(samples, "최종")
    gate_ok, gate_issues = vb.gate_distribution(samples)
    stats["distribution_gate"] = {"ok": gate_ok, "issues": gate_issues}
    stats["total_samples"] = len(samples)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=2400)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--model", default="qwen3:14b")
    a = ap.parse_args()
    res = generate(a.total, a.seed, resume=not a.no_resume, model=a.model)
    print("\n=== 생성 요약 ===")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
