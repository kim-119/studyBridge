#!/usr/bin/env python3
"""
split_dataset.py
JSONL 데이터셋을 train/validation/test로 분리한다.

규칙:
- group_id가 같은 샘플은 같은 split에 배치
- test에는 reviewed/approved만 허용
- validation도 reviewed/approved 우선
- needs_review, rejected, unsafe, duplicate는 학습 데이터에서 제외
- Java 코드 비율 30% 이하
- pdf_rag 40% 이상 권장, agent_profile 25% 이상 권장, failure_case 10% 이상 권장
- 총 샘플이 300 미만이면 split partial + NOT_READY 리포트 출력

실행 예시:
  python app/scripts/split_dataset.py \
    --input app/dataset/final/train_candidates.jsonl \
    --out-dir app/dataset/final \
    --train-ratio 0.8 \
    --val-ratio 0.1 \
    --test-ratio 0.1 \
    --group-by group_id \
    --approved-only-test
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REVIEWED_STATUSES = {"approved", "reviewed"}
EXCLUDE_STATUSES = {"needs_review", "duplicate", "rejected", "unsafe"}
MIN_SAMPLES_FOR_FULL_SPLIT = 300
MAX_JAVA_RATIO = 0.30


def load_samples(path: str) -> list:
    samples = []
    for line in Path(path).read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                samples.append(json.loads(line))
            except Exception:
                pass
    return samples


def get_status(sample: dict) -> str:
    return sample.get("metadata", {}).get("quality_status", "")


def write_split(samples: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def check_ratios(samples: list, split_name: str) -> list[str]:
    warnings = []
    if not samples:
        return warnings
    total = len(samples)
    java_count = sum(
        1 for s in samples if s.get("metadata", {}).get("source_type") == "java_code"
    )
    java_ratio = java_count / total
    if java_ratio > MAX_JAVA_RATIO:
        warnings.append(
            f"[{split_name}] Java 코드 비율 {java_ratio:.1%} > 30% 권장 상한"
        )
    return warnings


def main():
    parser = argparse.ArgumentParser(description="데이터셋 train/val/test 분리")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--group-by", default="group_id")
    parser.add_argument("--approved-only-test", action="store_true", default=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    assert abs(args.train_ratio + args.val_ratio + args.test_ratio - 1.0) < 0.01, \
        "비율 합계가 1.0이 아닙니다."

    random.seed(args.seed)

    all_samples = load_samples(args.input)
    samples = [s for s in all_samples if get_status(s) not in EXCLUDE_STATUSES]
    excluded_count = len(all_samples) - len(samples)

    if excluded_count:
        print(f"[INFO] 제외 대상 {excluded_count}개 (needs_review/duplicate/rejected/unsafe)")

    total = len(samples)
    print(f"[INFO] 학습 가능 샘플: {total}개")

    out_path = Path(args.out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    report_lines = [
        "# Split Dataset Report\n\n",
        f"생성일시: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n",
        f"- 전체 입력 샘플: {len(all_samples)}\n",
        f"- 제외 샘플 (학습 부적합): {excluded_count}\n",
        f"- 학습 가능 샘플: {total}\n",
    ]

    if total < MIN_SAMPLES_FOR_FULL_SPLIT:
        msg = (
            f"[WARN] 학습 가능 샘플 {total}개 — "
            f"{MIN_SAMPLES_FOR_FULL_SPLIT}개 이상 필요 → NOT_READY (partial split만 생성)"
        )
        print(msg)
        report_lines += [
            f"\n## 판정: **NOT_READY**\n\n",
            f"- 이유: reviewed/approved 샘플 {total}개 ({MIN_SAMPLES_FOR_FULL_SPLIT}개 미만)\n",
            "- partial split 파일을 생성하지만 QLoRA 학습에 사용하면 안 됩니다.\n",
        ]

    # group_id 기준 그룹핑
    groups: dict[str, list] = defaultdict(list)
    for s in samples:
        gid = (
            s.get("metadata", {}).get(args.group_by)
            or s.get("id", "")
        )
        groups[gid].append(s)

    group_ids = list(groups.keys())
    random.shuffle(group_ids)

    # reviewed/approved 그룹과 나머지 분리
    reviewed_groups = [
        gid for gid in group_ids
        if any(get_status(s) in REVIEWED_STATUSES for s in groups[gid])
    ]
    other_groups = [g for g in group_ids if g not in reviewed_groups]

    if not reviewed_groups:
        print("[WARN] reviewed/approved 샘플 없음 — test set 구성 불가")
        report_lines.append("- 경고: reviewed/approved 샘플 없어 test set 구성 불가\n")

    n_test = max(1, int(total * args.test_ratio))
    n_val = max(1, int(total * args.val_ratio))

    # test: reviewed/approved 우선
    test_samples: list = []
    used_groups: set[str] = set()
    for gid in reviewed_groups:
        if len(test_samples) >= n_test:
            break
        test_samples.extend(groups[gid])
        used_groups.add(gid)

    # validation: 나머지 reviewed/approved 우선, 그 다음 other
    val_samples: list = []
    for gid in reviewed_groups + other_groups:
        if gid in used_groups:
            continue
        if len(val_samples) >= n_val:
            break
        val_samples.extend(groups[gid])
        used_groups.add(gid)

    # train: 나머지
    test_ids = {s.get("id") for s in test_samples}
    val_ids = {s.get("id") for s in val_samples}
    train_samples = [
        s for s in samples
        if s.get("id") not in test_ids and s.get("id") not in val_ids
    ]

    warnings: list[str] = []
    for split_name, split_samples in [
        ("train", train_samples), ("validation", val_samples), ("test", test_samples)
    ]:
        warnings.extend(check_ratios(split_samples, split_name))

    for split_name, split_samples in [
        ("train", train_samples), ("validation", val_samples), ("test", test_samples)
    ]:
        fpath = out_path / f"{split_name}.jsonl"
        write_split(split_samples, fpath)
        print(f"[INFO] {split_name}: {len(split_samples)}개 → {fpath}")

    for w in warnings:
        print(f"[WARN] {w}")

    report_lines += [
        "\n## Split 결과\n\n",
        f"- train: {len(train_samples)}개\n",
        f"- validation: {len(val_samples)}개\n",
        f"- test: {len(test_samples)}개\n",
    ]
    if warnings:
        report_lines.append("\n## 경고\n\n")
        for w in warnings:
            report_lines.append(f"- {w}\n")

    readiness = "READY" if total >= MIN_SAMPLES_FOR_FULL_SPLIT else "NOT_READY"
    report_lines.append(f"\n## 최종 판정: **{readiness}**\n")

    report_path = out_path / "split_report.md"
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {report_path}")

    sys.exit(0 if readiness == "READY" else 1)


if __name__ == "__main__":
    main()
