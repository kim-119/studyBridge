#!/usr/bin/env python3
"""
filter_training_candidates.py
학습 후보와 제외 대상을 분리한다.

실행 예시:
  python app/scripts/filter_training_candidates.py \
    --input app/dataset/review/normalized_dataset.jsonl \
    --output app/dataset/final/train_candidates.jsonl \
    --excluded app/dataset/final/excluded_samples.jsonl \
    --report app/dataset/reports/filter_training_candidates_report.md
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

INCLUDE_STATUSES = {"reviewed", "approved"}
EXCLUDE_STATUSES = {"needs_review", "duplicate", "rejected", "unsafe", "auto_generated"}
VALID_SOURCE_TYPES = {
    "java_code", "pdf_rag", "user_log", "agent_profile",
    "verification", "prompt_template", "failure_case", "code_rag",
}
MIN_ASSISTANT_LEN = 50


def get_exclusion_reason(sample: dict, seen_ids: set) -> list[str]:
    reasons = []
    meta = sample.get("metadata", {})
    messages = sample.get("messages", [])
    sid = sample.get("id", "")

    qs = meta.get("quality_status", "")
    if qs in EXCLUDE_STATUSES:
        reasons.append(f"quality_status={qs}")

    if meta.get("contains_personal_data"):
        reasons.append("contains_personal_data=true")
    if meta.get("contains_secret_candidate"):
        reasons.append("contains_secret_candidate=true")

    src = meta.get("source_type", "")
    if src not in VALID_SOURCE_TYPES:
        reasons.append(f"유효하지 않은 source_type={src}")

    if not messages or not isinstance(messages, list):
        reasons.append("messages 구조 오류")
    else:
        roles = [m.get("role") for m in messages]
        for r in ("system", "user", "assistant"):
            if r not in roles:
                reasons.append(f"{r} role 없음")

        asst = next(
            (m.get("content", "") for m in messages if m.get("role") == "assistant"), ""
        )
        if len(asst.strip()) < MIN_ASSISTANT_LEN:
            reasons.append(f"assistant content 너무 짧음 ({len(asst.strip())}자)")

    if sid in seen_ids:
        reasons.append(f"id 중복: {sid}")

    if not sid:
        reasons.append("id 없음")

    return reasons


def main():
    parser = argparse.ArgumentParser(description="학습 후보 필터링")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--excluded", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 입력 파일 없음: {args.input}", file=sys.stderr)
        sys.exit(1)

    samples = []
    for line in input_path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    included = []
    excluded = []
    seen_ids: set[str] = set()
    exclusion_reasons: list[dict] = []
    status_counts = defaultdict(int)

    for sample in samples:
        meta = sample.get("metadata", {})
        qs = meta.get("quality_status", "")
        status_counts[qs] += 1

        sid = sample.get("id", "")
        reasons = get_exclusion_reason(sample, seen_ids)

        if qs in INCLUDE_STATUSES and not reasons:
            included.append(sample)
            if sid:
                seen_ids.add(sid)
        else:
            if not reasons:
                reasons = [f"quality_status={qs} (include 조건 미충족)"]
            excluded.append(sample)
            exclusion_reasons.append({"id": sid, "reasons": reasons})
            if sid:
                seen_ids.add(sid)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for s in included:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[INFO] train_candidates: {len(included)}개 → {args.output}")

    exc_path = Path(args.excluded)
    exc_path.parent.mkdir(parents=True, exist_ok=True)
    with exc_path.open("w", encoding="utf-8") as f:
        for s in excluded:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[INFO] excluded_samples: {len(excluded)}개 → {args.excluded}")

    java_count = sum(
        1 for s in included
        if s.get("metadata", {}).get("source_type") == "java_code"
    )
    java_ratio = java_count / len(included) if included else 0.0

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# Filter Training Candidates Report\n\n",
        f"생성일시: {now_str}\n\n",
        "## 결과 요약\n\n",
        f"- 전체 입력 샘플: {len(samples)}\n",
        f"- 학습 후보 포함: {len(included)}\n",
        f"- 학습 제외: {len(excluded)}\n",
        f"- Java 코드 비율 (학습 후보 내): {java_ratio:.1%}\n",
        "\n## quality_status별 입력 통계\n\n",
    ]
    for qs, cnt in sorted(status_counts.items()):
        report_lines.append(f"- {qs}: {cnt}\n")

    if exclusion_reasons:
        report_lines.append("\n## 제외된 샘플 상세\n\n")
        for r in exclusion_reasons:
            report_lines.append(f"- `{r['id']}`: {', '.join(r['reasons'])}\n")

    reviewed_approved = sum(
        1 for s in included
        if s.get("metadata", {}).get("quality_status") in INCLUDE_STATUSES
    )
    readiness = "READY" if reviewed_approved >= 300 else "NOT_READY"
    report_lines += [
        "\n## 현재 readiness 판정\n\n",
        f"- reviewed + approved 학습 후보: {reviewed_approved}\n",
        f"- 판정: **{readiness}**\n",
    ]
    if readiness == "NOT_READY":
        report_lines += [
            "\n### 미충족 이유\n\n",
            f"- reviewed/approved 샘플 {reviewed_approved}개 (300개 이상 필요)\n",
            "- 학습을 실행하지 마십시오.\n",
        ]

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")


if __name__ == "__main__":
    main()
