#!/usr/bin/env python3
"""
apply_human_review_report.py
Markdown 리포트의 샘플별 검수 메모 표를 파싱하여 원본 JSONL metadata에 반영한다.

실행 예시:
  python app/scripts/apply_human_review_report.py \
    --input-jsonl app/dataset/review/ai_reviewed_candidates.jsonl \
    --review-reports app/dataset/reports/human_review_report.md \
                     app/dataset/reports/human_review_report_1.md \
    --output-jsonl app/dataset/review/human_review_applied_dataset.jsonl \
    --report app/dataset/reports/apply_human_review_report.md
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

VALID_QUALITY_STATUSES = {
    "reviewed", "approved", "needs_review", "duplicate",
    "rejected", "unsafe", "auto_generated", "raw", "sanitized",
}

STATUS_REQUIRES_HUMAN_REVIEW = {
    "reviewed": True,
    "approved": False,
    "needs_review": True,
    "duplicate": False,
    "rejected": False,
    "unsafe": True,
    "auto_generated": True,
    "raw": True,
    "sanitized": True,
}


def parse_markdown_table(md_text: str, report_filename: str) -> list[dict]:
    """## 샘플별 검수 메모 섹션 아래 Markdown 표를 파싱한다."""
    rows = []
    in_section = False
    header_found = False
    col_names = []

    for line in md_text.splitlines():
        stripped = line.strip()

        if re.match(r'^##\s+샘플별\s+검수\s+메모', stripped):
            in_section = True
            header_found = False
            continue

        if in_section and stripped.startswith("##"):
            break

        if not in_section or not stripped.startswith("|"):
            continue

        cells = [c.strip() for c in stripped.strip("|").split("|")]

        if not header_found:
            col_names = [c.lower().replace(" ", "_") for c in cells]
            header_found = True
            continue

        if re.match(r"^[\s\-|:]+$", stripped):
            continue

        if len(cells) < len(col_names):
            cells += [""] * (len(col_names) - len(cells))

        row = dict(zip(col_names, cells[:len(col_names)]))
        row["_source_report"] = report_filename
        rows.append(row)

    return rows


def apply_status_rules(meta: dict, status: str, report_filename: str,
                       reviewed_by: str, review_notes: str,
                       original_status: str, original_notes: str) -> None:
    meta["original_quality_status"] = original_status
    meta["original_review_notes"] = original_notes

    meta["quality_status"] = status
    meta["reviewed_by"] = reviewed_by
    meta["review_notes"] = review_notes
    meta["human_review_applied"] = True
    meta["human_review_source"] = report_filename
    meta["human_review_applied_at"] = datetime.now(timezone.utc).isoformat()
    meta["requires_human_review"] = STATUS_REQUIRES_HUMAN_REVIEW.get(status, True)


def main():
    parser = argparse.ArgumentParser(description="Markdown 검수 리포트 → JSONL metadata 반영")
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--review-reports", nargs="+", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    input_path = Path(args.input_jsonl)
    if not input_path.exists():
        print(f"[ERROR] 입력 JSONL 없음: {args.input_jsonl}", file=sys.stderr)
        sys.exit(1)

    # 1. JSONL 로드
    samples = []
    for line in input_path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] JSON 파싱 실패: {e}", file=sys.stderr)

    jsonl_by_id = {s["id"]: s for s in samples if "id" in s}
    print(f"[INFO] JSONL 샘플 수: {len(samples)}")

    # 2. Markdown 리포트 파싱
    all_review_rows: dict[str, dict] = {}
    duplicate_ids_in_report: list[str] = []
    source_map: dict[str, str] = {}

    for report_path_str in args.review_reports:
        rp = Path(report_path_str)
        if not rp.exists():
            print(f"[WARN] 리포트 파일 없음: {report_path_str}", file=sys.stderr)
            continue
        md_text = rp.read_text(encoding="utf-8")
        rows = parse_markdown_table(md_text, rp.name)
        print(f"[INFO] {rp.name}: {len(rows)}행 파싱")

        for row in rows:
            rid = row.get("id", "").strip()
            if not rid:
                continue
            if rid in all_review_rows:
                duplicate_ids_in_report.append(rid)
                print(f"[WARN] 중복 id in report: {rid}")
            all_review_rows[rid] = row
            source_map[rid] = rp.name

    # 3. 매칭 및 반영
    applied_ids: list[str] = []
    missing_in_jsonl: list[str] = []
    not_reviewed: list[str] = []
    source_type_mismatches: list[str] = []
    empty_notes: list[str] = []
    status_counts = defaultdict(int)
    warnings_log: list[str] = []

    for sid, row in all_review_rows.items():
        if sid not in jsonl_by_id:
            missing_in_jsonl.append(sid)
            continue

        sample = jsonl_by_id[sid]
        meta = sample.setdefault("metadata", {})

        orig_status = meta.get("quality_status", "")
        orig_notes = meta.get("review_notes", "")
        orig_source_type = meta.get("source_type", "")

        report_source_type = row.get("source_type", "").strip()
        quality_status = row.get("quality_status", "").strip()
        reviewed_by = row.get("reviewed_by", "").strip()
        review_notes = row.get("review_notes", "").strip()

        if quality_status not in VALID_QUALITY_STATUSES:
            w = f"유효하지 않은 quality_status '{quality_status}' for {sid}"
            warnings_log.append(w)
            print(f"[WARN] {w}")
            quality_status = "needs_review"

        if report_source_type and orig_source_type and report_source_type != orig_source_type:
            meta["source_type_mismatch"] = True
            msg = (f"source_type 불일치: {sid} "
                   f"(JSONL={orig_source_type}, report={report_source_type})")
            source_type_mismatches.append(msg)
            warnings_log.append(msg)
            print(f"[WARN] {msg}")

        if not review_notes:
            empty_notes.append(sid)

        apply_status_rules(
            meta, quality_status, source_map.get(sid, "unknown"),
            reviewed_by, review_notes, orig_status, orig_notes
        )

        status_counts[quality_status] += 1
        applied_ids.append(sid)

    for sid in jsonl_by_id:
        if sid not in all_review_rows:
            not_reviewed.append(sid)

    # 4. 출력 JSONL 저장
    out_path = Path(args.output_jsonl)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[INFO] 저장 완료: {args.output_jsonl} ({len(samples)}개)")

    # 5. 리포트 생성
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Apply Human Review Report\n\n",
        f"생성일시: {now_str}\n\n",
        "## 입력 파일\n\n",
        f"- input jsonl: `{args.input_jsonl}`\n",
    ]
    for rp in args.review_reports:
        lines.append(f"- review report: `{rp}`\n")

    lines += [
        "\n## 반영 결과\n\n",
        f"- 전체 JSONL 샘플 수: {len(samples)}\n",
        f"- Markdown에서 파싱한 검수 row 수: {len(all_review_rows)}\n",
        f"- JSONL에 반영된 샘플 수: {len(applied_ids)}\n",
        f"- Markdown에는 있으나 JSONL에는 없는 id 수: {len(missing_in_jsonl)}\n",
        f"- JSONL에는 있으나 Markdown에는 없는 id 수: {len(not_reviewed)}\n",
    ]

    if missing_in_jsonl:
        lines.append("\n### missing_in_jsonl\n\n")
        for sid in missing_in_jsonl:
            lines.append(f"- `{sid}`\n")

    if not_reviewed:
        lines.append("\n### not_reviewed_by_report\n\n")
        for sid in not_reviewed:
            lines.append(f"- `{sid}`\n")

    lines += [
        "\n## quality_status 반영 결과\n\n",
        f"- reviewed: {status_counts.get('reviewed', 0)}\n",
        f"- approved: {status_counts.get('approved', 0)}\n",
        f"- needs_review: {status_counts.get('needs_review', 0)}\n",
        f"- duplicate: {status_counts.get('duplicate', 0)}\n",
        f"- rejected: {status_counts.get('rejected', 0)}\n",
        f"- unsafe: {status_counts.get('unsafe', 0)}\n",
        f"- auto_generated: {status_counts.get('auto_generated', 0)}\n",
        f"- (미반영/not_reviewed): {len(not_reviewed)}\n",
    ]

    lines.append("\n## 경고\n\n")
    if source_type_mismatches:
        lines.append("### source_type mismatch\n\n")
        for m in source_type_mismatches:
            lines.append(f"- {m}\n")
    else:
        lines.append("- source_type mismatch: 없음\n")

    if empty_notes:
        lines.append("\n### review_notes 비어 있음\n\n")
        for sid in empty_notes:
            lines.append(f"- `{sid}`\n")
    else:
        lines.append("- review_notes 비어 있음: 없음\n")

    if duplicate_ids_in_report:
        lines.append("\n### 중복된 id (report 내)\n\n")
        for sid in duplicate_ids_in_report:
            lines.append(f"- `{sid}`\n")
    else:
        lines.append("- 중복된 id: 없음\n")

    if warnings_log:
        lines.append("\n### 기타 경고\n\n")
        for w in warnings_log:
            lines.append(f"- {w}\n")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")

    reviewed_approved = status_counts.get("reviewed", 0) + status_counts.get("approved", 0)
    print(f"[INFO] reviewed+approved: {reviewed_approved} / 300 필요 → "
          f"{'READY 조건 미충족' if reviewed_approved < 300 else 'OK'}")


if __name__ == "__main__":
    main()
