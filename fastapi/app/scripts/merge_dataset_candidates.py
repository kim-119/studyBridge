#!/usr/bin/env python3
"""
merge_dataset_candidates.py
source_type별 JSONL 파일을 하나로 병합하고 ID를 재부여한다.

실행 예시:
  python app/scripts/merge_dataset_candidates.py \
    --input-dir app/dataset/samples \
    --out app/dataset/samples/sample_qlora_dataset.jsonl
"""
import argparse
import json
import sys
from pathlib import Path
from collections import Counter

def merge_jsonl_files(input_dir: str, output_path: str, exclude_files: list = None) -> dict:
    """JSONL 파일들을 병합하고 ID를 재부여."""
    input_path = Path(input_dir)
    exclude = set(exclude_files or ["sample_qlora_dataset.jsonl"])

    # sample_*.jsonl 파일 수집 (통합 파일 제외)
    jsonl_files = sorted([
        f for f in input_path.glob("sample_*.jsonl")
        if f.name not in exclude
    ])

    if not jsonl_files:
        print(f"[WARN] {input_dir}에서 sample_*.jsonl 파일을 찾을 수 없습니다.", file=sys.stderr)
        return {"total": 0, "files": 0}

    all_samples = []
    seen_originals = set()
    source_counts = Counter()
    dup_count = 0

    for jsonl_file in jsonl_files:
        print(f"[INFO] 읽는 중: {jsonl_file.name}")
        for line in jsonl_file.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError:
                print(f"[WARN] JSON 파싱 실패: {line[:50]}", file=sys.stderr)
                continue

            # 중복 제거: user content 기준
            messages = sample.get("messages", [])
            user_content = next(
                (m.get("content", "") for m in messages if m.get("role") == "user"), ""
            )
            dedup_key = user_content[:200].strip()

            if dedup_key in seen_originals:
                dup_count += 1
                continue

            seen_originals.add(dedup_key)
            src = sample.get("metadata", {}).get("source_type", "unknown")
            source_counts[src] += 1
            all_samples.append(sample)

    # ID 재부여
    for i, sample in enumerate(all_samples, 1):
        src = sample.get("metadata", {}).get("source_type", "unknown")
        prefix = {
            "java_code": "sb_java", "pdf_rag": "sb_pdf",
            "agent_profile": "sb_agent", "verification": "sb_verify",
            "failure_case": "sb_fail", "prompt_template": "sb_prompt",
            "user_log": "sb_log",
        }.get(src, "sb_data")
        sample["id"] = f"{prefix}_{i:06d}"

    # 저장
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for sample in all_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"\n[INFO] 병합 완료: 총 {len(all_samples)}개 (중복 제거: {dup_count}개)")
    print("[INFO] source_type 분포:")
    for src, cnt in source_counts.most_common():
        pct = cnt / len(all_samples) * 100 if all_samples else 0
        print(f"  {src}: {cnt}개 ({pct:.1f}%)")
    print(f"[INFO] 저장: {output_path}")

    return {
        "total": len(all_samples),
        "files": len(jsonl_files),
        "duplicates_removed": dup_count,
        "source_counts": dict(source_counts),
    }

def main():
    parser = argparse.ArgumentParser(description="JSONL 파일 병합")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    merge_jsonl_files(args.input_dir, args.out)

if __name__ == "__main__":
    main()
