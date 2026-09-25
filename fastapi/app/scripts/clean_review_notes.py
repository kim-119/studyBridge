#!/usr/bin/env python3
"""
clean_review_notes.py
review_notes의 부적절한 표현을 정리하고 issue_type을 추가한다.

실행 예시:
  python app/scripts/clean_review_notes.py \
    --input app/dataset/review/human_review_applied_dataset.jsonl \
    --output app/dataset/review/cleaned_human_reviewed_dataset.jsonl \
    --report app/dataset/reports/clean_review_notes_report.md
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_NOTES = {
    "reviewed": "사람 검수 결과 통과. 단, 최종 approved 전 실제 근거 재확인 권장.",
    "approved": "사람 검수 결과 최종 승인됨.",
    "needs_review": "추가 검토 필요. 답변 품질, 근거 일치, 말투 또는 메타데이터 문제 확인 필요.",
    "duplicate": "중복 후보로 판단되어 학습 데이터에서 제외 필요.",
    "rejected": "학습 제외 대상으로 판단됨.",
    "unsafe": "민감정보 또는 개인정보 위험으로 학습 제외 필요.",
}

INAPPROPRIATE_REPLACEMENTS = [
    ("꺼져", "중복 후보로 판단되어 학습 데이터에서 제외 필요."),
    ("닥쳐", "검수 메모 재작성 필요."),
]

ISSUE_PATTERNS = [
    (re.compile(r"지식수준이 에이전트의 전문성인지 답변 난이도인지 구분"), "answer_level_ambiguity"),
    (re.compile(r"비판적 분석형"), "persona_tone_mismatch"),
    (re.compile(r"chunk_index"), "pdf_metadata_hallucination"),
    (re.compile(r"중복"), "duplicate_candidate"),
    (re.compile(r"민감정보|개인정보"), "safety_review_required"),
]


def deduplicate_sentences(text: str) -> str:
    """중복 문장을 제거한다."""
    sentences = re.split(r'(?<=[.!?。])\s+', text.strip())
    seen = []
    for s in sentences:
        s = s.strip()
        if s and s not in seen:
            seen.append(s)
    return " ".join(seen)


def clean_note(notes: str, status: str) -> tuple[str, list[str], list[str]]:
    """
    notes를 정리하고 (cleaned_notes, issue_types, change_log)를 반환한다.
    """
    change_log = []
    issue_types = []

    cleaned = notes.strip()

    for bad_expr, replacement in INAPPROPRIATE_REPLACEMENTS:
        if bad_expr in cleaned:
            cleaned = cleaned.replace(bad_expr, replacement)
            change_log.append(f"부적절한 표현 교체: '{bad_expr}' → '{replacement}'")

    deduped = deduplicate_sentences(cleaned)
    if deduped != cleaned:
        change_log.append("반복 문장 제거")
        cleaned = deduped

    if not cleaned:
        default = DEFAULT_NOTES.get(status, "검수 메모 없음.")
        cleaned = default
        change_log.append(f"빈 메모 → 기본 메모 채움: '{default}'")

    for pattern, issue_type in ISSUE_PATTERNS:
        if pattern.search(cleaned):
            issue_types.append(issue_type)

    return cleaned, issue_types, change_log


def main():
    parser = argparse.ArgumentParser(description="review_notes 정리")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
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

    changed_count = 0
    inappropriate_fixed = 0
    repeat_removed = 0
    needs_human_check: list[str] = []
    issue_type_counts: dict[str, int] = {}
    all_change_details: list[dict] = []

    for sample in samples:
        meta = sample.setdefault("metadata", {})
        status = meta.get("quality_status", "")
        notes = meta.get("review_notes", "")

        meta["original_review_notes"] = notes

        cleaned, issue_types, change_log = clean_note(notes, status)

        if change_log:
            changed_count += 1
            for c in change_log:
                if "부적절한 표현" in c:
                    inappropriate_fixed += 1
                if "반복 문장" in c:
                    repeat_removed += 1
            all_change_details.append({
                "id": sample.get("id"),
                "changes": change_log,
            })

        meta["cleaned_review_notes"] = cleaned

        if issue_types:
            meta["issue_types"] = list(set(issue_types))
            meta["review_note_needs_human_check"] = True
            needs_human_check.append(sample.get("id", "unknown"))
            for it in set(issue_types):
                issue_type_counts[it] = issue_type_counts.get(it, 0) + 1
        else:
            meta["review_note_needs_human_check"] = False

        meta["review_notes_cleaned_at"] = datetime.now(timezone.utc).isoformat()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[INFO] 저장: {args.output} ({len(samples)}개)")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# Clean Review Notes Report\n\n",
        f"생성일시: {now_str}\n\n",
        "## 정리 결과\n\n",
        f"- 전체 샘플 수: {len(samples)}\n",
        f"- review_notes 변경된 샘플 수: {changed_count}\n",
        f"- 부적절 표현 수정 수: {inappropriate_fixed}\n",
        f"- 반복 문장 제거 수: {repeat_removed}\n",
        f"- 사람 재검토 필요 샘플 수: {len(needs_human_check)}\n",
        "\n## issue_type별 샘플 수\n\n",
    ]
    if issue_type_counts:
        for it, cnt in sorted(issue_type_counts.items()):
            report_lines.append(f"- {it}: {cnt}\n")
    else:
        report_lines.append("- 없음\n")

    if needs_human_check:
        report_lines.append("\n## 사람이 다시 봐야 할 샘플 id\n\n")
        for sid in needs_human_check:
            report_lines.append(f"- `{sid}`\n")

    if all_change_details:
        report_lines.append("\n## 상세 변경 내역\n\n")
        for d in all_change_details:
            report_lines.append(f"### `{d['id']}`\n\n")
            for c in d["changes"]:
                report_lines.append(f"- {c}\n")
            report_lines.append("\n")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")


if __name__ == "__main__":
    main()
