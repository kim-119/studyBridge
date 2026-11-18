#!/usr/bin/env python3
"""
dataset_stats.py
JSONL 데이터셋 통계를 생성하고 dataset_statistics.md를 저장한다.

실행 예시:
  python app/scripts/dataset_stats.py \
    --input app/dataset/samples/sample_qlora_dataset.jsonl \
    --out app/reports/dataset_statistics.md
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

def compute_stats(jsonl_path: str) -> dict:
    path = Path(jsonl_path)
    if not path.exists():
        print(f"[ERROR] 파일 없음: {jsonl_path}", file=sys.stderr)
        return {}

    samples = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                samples.append(json.loads(line))
            except:
                pass

    if not samples:
        return {"total": 0}

    source_types = Counter()
    quality_statuses = Counter()
    knowledge_levels = Counter()
    contains_code = 0
    requires_review = 0
    secret_candidates = 0
    personal_data = 0
    user_lengths = []
    asst_lengths = []
    long_samples = []  # asst > 3000자

    for s in samples:
        meta = s.get("metadata", {})
        source_types[meta.get("source_type", "unknown")] += 1
        quality_statuses[meta.get("quality_status", "unknown")] += 1
        if meta.get("knowledge_level"):
            knowledge_levels[meta["knowledge_level"]] += 1
        if meta.get("contains_code"):
            contains_code += 1
        if meta.get("requires_human_review"):
            requires_review += 1
        if meta.get("contains_secret_candidate"):
            secret_candidates += 1
        if meta.get("contains_personal_data"):
            personal_data += 1

        messages = s.get("messages", [])
        for m in messages:
            if m.get("role") == "user":
                user_lengths.append(len(m.get("content", "")))
            elif m.get("role") == "assistant":
                l = len(m.get("content", ""))
                asst_lengths.append(l)
                if l > 3000:
                    long_samples.append(s.get("id", "?"))

    return {
        "total": len(samples),
        "source_types": dict(source_types),
        "quality_statuses": dict(quality_statuses),
        "knowledge_levels": dict(knowledge_levels),
        "contains_code": contains_code,
        "requires_review": requires_review,
        "secret_candidates": secret_candidates,
        "personal_data": personal_data,
        "avg_user_length": round(sum(user_lengths) / len(user_lengths)) if user_lengths else 0,
        "avg_asst_length": round(sum(asst_lengths) / len(asst_lengths)) if asst_lengths else 0,
        "max_asst_length": max(asst_lengths) if asst_lengths else 0,
        "long_samples": long_samples[:10],
        "long_count": len(long_samples),
    }

def generate_report(stats: dict, output_path: str):
    lines = [
        "# 데이터셋 통계 리포트\n\n",
        f"## 전체 샘플 수\n\n**{stats.get('total', 0)}개**\n\n",

        "## source_type 분포\n\n",
        "| source_type | 샘플 수 | 비율 |\n",
        "|---|---|---|\n",
    ]
    total = stats.get("total", 1)
    for k, v in sorted(stats.get("source_types", {}).items(), key=lambda x: -x[1]):
        lines.append(f"| `{k}` | {v} | {v/total*100:.1f}% |\n")

    lines += [
        "\n## quality_status 분포\n\n",
        "| quality_status | 샘플 수 |\n",
        "|---|---|\n",
    ]
    for k, v in sorted(stats.get("quality_statuses", {}).items(), key=lambda x: -x[1]):
        lines.append(f"| `{k}` | {v} |\n")

    kl = stats.get("knowledge_levels", {})
    if kl:
        lines += ["\n## knowledge_level 분포\n\n",
                  "| 수준 | 샘플 수 |\n", "|---|---|\n"]
        for k, v in kl.items():
            lines.append(f"| {k} | {v} |\n")

    lines += [
        f"\n## 기타 통계\n\n",
        f"- 코드 포함 샘플: {stats.get('contains_code', 0)}개\n",
        f"- 사람 검수 필요: {stats.get('requires_review', 0)}개\n",
        f"- 민감정보 후보: {stats.get('secret_candidates', 0)}개\n",
        f"- 개인정보 후보: {stats.get('personal_data', 0)}개\n",
        f"- 평균 user 길이: {stats.get('avg_user_length', 0)}자\n",
        f"- 평균 assistant 길이: {stats.get('avg_asst_length', 0)}자\n",
        f"- 최대 assistant 길이: {stats.get('max_asst_length', 0)}자\n",
        f"- 3000자 초과 샘플: {stats.get('long_count', 0)}개\n",
    ]

    if stats.get("long_samples"):
        lines.append(f"\n**3000자 초과 샘플 ID**: {', '.join(stats['long_samples'])}\n")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("".join(lines), encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(description="데이터셋 통계 생성")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    stats = compute_stats(args.input)
    if not stats:
        sys.exit(1)

    generate_report(stats, args.out)
    print(f"[INFO] 총 샘플: {stats['total']}개")
    print(f"[INFO] 리포트 저장: {args.out}")

if __name__ == "__main__":
    main()
