#!/usr/bin/env python3
"""
check_qlora_readiness.py
QLoRA 학습 가능 조건을 자동 판정한다. 현재 데이터로는 반드시 NOT_READY를 반환한다.

실행 예시:
  python app/scripts/check_qlora_readiness.py \
    --dataset app/dataset/final/train_candidates.jsonl \
    --eval app/dataset/eval/qwen_baseline_eval.jsonl \
    --report app/dataset/reports/qlora_readiness_report.md
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

MIN_REVIEWED_APPROVED = 300
MIN_APPROVED = 1
MIN_ASSISTANT_LEN = 50
MAX_JAVA_RATIO = 0.30
MIN_PDF_RAG_RATIO = 0.10
MIN_EVAL_ITEMS = 50

REQUIRED_SOURCE_TYPES = {"pdf_rag", "agent_profile", "failure_case"}
EXCLUDE_STATUSES = {"needs_review", "duplicate", "rejected", "unsafe"}


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    samples = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return samples


def check_dataset(samples: list[dict], checks: list[tuple], failures: list[str]) -> None:
    if not samples:
        failures.append("JSONL 파일이 비어 있거나 파싱 불가")
        return

    ids = [s.get("id") for s in samples]
    seen: set[str] = set()
    dup_ids = []
    for sid in ids:
        if not sid:
            failures.append("id 없는 샘플 존재")
        elif sid in seen:
            dup_ids.append(sid)
        else:
            seen.add(sid)
    if dup_ids:
        failures.append(f"중복 id 존재: {dup_ids[:3]}")

    status_counter = Counter()
    source_counter = Counter()
    personal_data_samples = []
    secret_samples = []
    short_assistant_samples = []
    no_messages_samples = []

    for s in samples:
        meta = s.get("metadata", {})
        qs = meta.get("quality_status", "unknown")
        src = meta.get("source_type", "unknown")
        status_counter[qs] += 1
        source_counter[src] += 1

        messages = s.get("messages", [])
        if not messages:
            no_messages_samples.append(s.get("id"))
            continue

        roles = [m.get("role") for m in messages]
        for r in ("system", "user", "assistant"):
            if r not in roles:
                failures.append(f"{s.get('id')}: {r} role 없음")

        asst = next(
            (m.get("content", "") for m in messages if m.get("role") == "assistant"), ""
        )
        if len(asst.strip()) < MIN_ASSISTANT_LEN:
            short_assistant_samples.append(s.get("id"))

        if meta.get("contains_personal_data"):
            personal_data_samples.append(s.get("id"))
        if meta.get("contains_secret_candidate"):
            secret_samples.append(s.get("id"))

    total = len(samples)
    reviewed_approved = status_counter.get("reviewed", 0) + status_counter.get("approved", 0)
    approved_count = status_counter.get("approved", 0)
    java_count = source_counter.get("java_code", 0)
    java_ratio = java_count / total if total else 0.0

    if reviewed_approved < MIN_REVIEWED_APPROVED:
        failures.append(
            f"reviewed/approved 샘플 {reviewed_approved}개 — {MIN_REVIEWED_APPROVED}개 이상 필요"
        )

    if approved_count < MIN_APPROVED:
        failures.append(f"approved 샘플 {approved_count}개 — 최소 {MIN_APPROVED}개 이상 필요")

    for bad_status in EXCLUDE_STATUSES:
        cnt = status_counter.get(bad_status, 0)
        if cnt > 0:
            failures.append(f"{bad_status} 샘플 {cnt}개 존재 — 학습 후보에서 제외되어야 함")

    if java_ratio > MAX_JAVA_RATIO:
        failures.append(
            f"Java 코드 비율 {java_ratio:.1%} — {MAX_JAVA_RATIO:.0%} 이하 필요"
        )

    for missing_src in REQUIRED_SOURCE_TYPES:
        if source_counter.get(missing_src, 0) == 0:
            failures.append(f"source_type={missing_src} 샘플 없음")

    pdf_count = source_counter.get("pdf_rag", 0)
    pdf_ratio = pdf_count / total if total else 0.0
    if pdf_ratio < MIN_PDF_RAG_RATIO:
        failures.append(f"실제 PDF RAG 데이터 부족: {pdf_count}개 ({pdf_ratio:.1%})")

    if no_messages_samples:
        failures.append(f"messages 없는 샘플: {no_messages_samples[:3]}")

    if short_assistant_samples:
        failures.append(
            f"assistant content 너무 짧은 샘플 {len(short_assistant_samples)}개"
        )

    if personal_data_samples:
        failures.append(f"contains_personal_data=true 샘플: {personal_data_samples[:3]}")

    if secret_samples:
        failures.append(f"contains_secret_candidate=true 샘플: {secret_samples[:3]}")

    checks.append(("전체 샘플 수", str(total)))
    checks.append(("reviewed + approved", str(reviewed_approved)))
    checks.append(("approved", str(approved_count)))
    checks.append(("Java 코드 비율", f"{java_ratio:.1%}"))
    checks.append(("PDF RAG 비율", f"{pdf_ratio:.1%}"))
    checks.append(("source_type 분포", str(dict(source_counter))))
    checks.append(("quality_status 분포", str(dict(status_counter))))


def check_eval_set(eval_samples: list[dict], failures: list[str]) -> None:
    if not eval_samples:
        failures.append("Qwen baseline evaluation set 없음 또는 비어 있음")
        return

    if len(eval_samples) < MIN_EVAL_ITEMS:
        failures.append(
            f"Qwen baseline eval set 부족: {len(eval_samples)}개 ({MIN_EVAL_ITEMS}개 이상 필요)"
        )

    baseline_missing = sum(1 for s in eval_samples if s.get("baseline_missing"))
    if baseline_missing > 0:
        failures.append(
            f"baseline_missing=true인 eval 항목 {baseline_missing}개 — Qwen 실제 추론 필요"
        )


def main():
    parser = argparse.ArgumentParser(description="QLoRA 학습 readiness 판정")
    parser.add_argument("--dataset", required=True, help="train_candidates.jsonl")
    parser.add_argument("--eval", required=True, help="qwen_baseline_eval.jsonl")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    eval_path = Path(args.eval)

    dataset_samples = load_jsonl(dataset_path)
    eval_samples = load_jsonl(eval_path)

    failures: list[str] = []
    checks: list[tuple[str, str]] = []

    if not dataset_path.exists():
        failures.append(f"데이터셋 파일 없음: {args.dataset}")
    else:
        check_dataset(dataset_samples, checks, failures)

    if not eval_path.exists():
        failures.append(f"eval 파일 없음: {args.eval}")
    else:
        check_eval_set(eval_samples, failures)

    val_path = dataset_path.parent / "validation.jsonl"
    test_path = dataset_path.parent / "test.jsonl"
    if not val_path.exists() or val_path.stat().st_size == 0:
        failures.append("validation/test set 없음 — split_dataset.py 실행 필요")
    if not test_path.exists() or test_path.stat().st_size == 0:
        failures.append("test.jsonl 없음 또는 비어 있음")

    readiness = "NOT_READY" if failures else "READY"

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# QLoRA Readiness Report\n\n",
        f"생성일시: {now_str}\n\n",
        f"## 판정 결과: **{readiness}**\n\n",
    ]

    if checks:
        report_lines.append("## 검사 항목 결과\n\n")
        for k, v in checks:
            report_lines.append(f"- {k}: {v}\n")

    report_lines.append(f"\n## 실패 사유 ({len(failures)}건)\n\n")
    if failures:
        for f in failures:
            report_lines.append(f"- {f}\n")
    else:
        report_lines.append("- 없음 (모든 조건 충족)\n")

    if readiness == "NOT_READY":
        report_lines += [
            "\n## 결론\n\n",
            "현재 데이터셋은 QLoRA 학습 조건을 충족하지 못했습니다.\n",
            "학습은 실행하지 않았습니다.\n\n",
            "**학습 READY가 되기 위한 조건:**\n\n",
            "1. reviewed/approved 샘플 300개 이상\n",
            "2. 실제 PDF RAG 데이터 (더미 아닌 실제 PDF 근거 포함)\n",
            "3. 사람 검수 validation/test set 구성\n",
            "4. Qwen baseline evaluation set 50개 이상 (baseline_missing=false)\n",
            "5. validate_dataset_jsonl.py 오류 0건 통과\n",
            "6. needs_review/duplicate/rejected/unsafe 학습 후보에서 완전 제외\n",
            "7. Java 코드 비율 30% 이하\n",
        ]
    else:
        report_lines += [
            "\n## 결론\n\n",
            "모든 QLoRA 학습 조건을 충족했습니다. 학습을 실행할 수 있습니다.\n",
        ]

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")
    print(f"[RESULT] 판정: {readiness}")
    if failures:
        print(f"[INFO] 실패 사유 {len(failures)}건:")
        for f in failures[:5]:
            print(f"  - {f}")

    sys.exit(0 if readiness == "READY" else 1)


if __name__ == "__main__":
    main()
