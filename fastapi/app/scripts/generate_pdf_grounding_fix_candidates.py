#!/usr/bin/env python3
"""
generate_pdf_grounding_fix_candidates.py
PDF_RAG_CONTEXT에 없는 메타데이터를 assistant가 생성하는 환각을 탐지한다.

실행 예시:
  python app/scripts/generate_pdf_grounding_fix_candidates.py \
    --input app/dataset/review/normalized_dataset.jsonl \
    --output app/dataset/review/pdf_grounding_fix_candidates.jsonl \
    --report app/dataset/reports/pdf_grounding_fix_candidates_report.md
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CHUNK_INDEX_RE = re.compile(r'chunk_index\s*[:=]?\s*\d+', re.IGNORECASE)
SIMILARITY_RE = re.compile(r'similarity\s*[:=]?\s*[\d.]+', re.IGNORECASE)
DOC_TITLE_RE = re.compile(r'document_title\s*[:=]?\s*\S+', re.IGNORECASE)

PDF_CONTEXT_MARKER = "PDF_RAG_CONTEXT"


def user_has_field(user_content: str, field_re: re.Pattern) -> bool:
    return bool(field_re.search(user_content))


def assistant_has_field(assistant_content: str, field_re: re.Pattern) -> bool:
    return bool(field_re.search(assistant_content))


def build_proposed_rewrite(assistant_content: str, hallucinations: list[str]) -> str:
    rewrite = assistant_content
    for h in hallucinations:
        rewrite = re.sub(re.escape(h), "[출처: 제공된 PDF_RAG_CONTEXT]", rewrite)
    note = (
        "\n\n[보정 제안]\n"
        "- 위 항목은 PDF_RAG_CONTEXT에 없는 메타데이터를 임의 생성한 것으로 판단됩니다.\n"
        "- '출처: 제공된 PDF_RAG_CONTEXT'로 수정하거나 해당 항목을 제거하세요.\n"
        "- 일반 지식은 '일반 지식 보완:' 접두사로 분리하세요.\n"
        "[주의: 이 내용은 제안이며 사람이 검토해야 합니다.]"
    )
    return rewrite + note


def detect_hallucinations(user_content: str, assistant_content: str) -> list[str]:
    issues = []
    found_hallucinations = []

    if not user_has_field(user_content, CHUNK_INDEX_RE):
        matches = CHUNK_INDEX_RE.findall(assistant_content)
        if matches:
            issues.append(f"chunk_index 환각: {matches}")
            found_hallucinations.extend(matches)

    if not user_has_field(user_content, SIMILARITY_RE):
        matches = SIMILARITY_RE.findall(assistant_content)
        if matches:
            issues.append(f"similarity 환각: {matches}")
            found_hallucinations.extend(matches)

    if not user_has_field(user_content, DOC_TITLE_RE):
        matches = DOC_TITLE_RE.findall(assistant_content)
        if matches:
            issues.append(f"document_title 환각: {matches}")
            found_hallucinations.extend(matches)

    return issues, found_hallucinations


def main():
    parser = argparse.ArgumentParser(description="PDF 메타데이터 환각 보정 후보 생성")
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

    candidates = []
    for sample in samples:
        messages = sample.get("messages", [])
        user_content = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"), ""
        )
        assistant_content = next(
            (m.get("content", "") for m in messages if m.get("role") == "assistant"), ""
        )

        if PDF_CONTEXT_MARKER not in user_content:
            continue

        issues, found_hallucinations = detect_hallucinations(user_content, assistant_content)

        if not issues:
            meta = sample.get("metadata", {})
            issue_types = meta.get("issue_types", [])
            if "pdf_metadata_hallucination" not in issue_types:
                continue

        sample_copy = json.loads(json.dumps(sample))
        m = sample_copy.setdefault("metadata", {})
        m["fix_required"] = True
        m["fix_type"] = "pdf_metadata_hallucination"
        m["correction_type"] = "source_separation_fixed"
        m["hallucination_details"] = issues if issues else ["issue_type에 의해 탐지됨"]
        m["proposed_assistant_rewrite"] = build_proposed_rewrite(
            assistant_content, found_hallucinations
        )
        m["human_approval_required"] = True
        m["pdf_grounding_fix_flagged_at"] = datetime.now(timezone.utc).isoformat()

        candidates.append(sample_copy)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for s in candidates:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[INFO] pdf_grounding_fix_candidates: {len(candidates)}개 → {args.output}")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# PDF Grounding Fix Candidates Report\n\n",
        f"생성일시: {now_str}\n\n",
        "## 탐지 결과\n\n",
        f"- 전체 입력 샘플: {len(samples)}\n",
        f"- PDF 환각 보정 후보 수: {len(candidates)}\n",
        "\n## 탐지 항목 종류\n\n",
        "- `chunk_index`: user PDF_RAG_CONTEXT에 없는데 assistant가 생성\n",
        "- `similarity`: user PDF_RAG_CONTEXT에 없는데 assistant가 생성\n",
        "- `document_title`: user PDF_RAG_CONTEXT에 없는데 assistant가 생성\n",
        "\n## 주의사항\n\n",
        "- `proposed_assistant_rewrite`는 제안 초안이며 원본 assistant를 덮어쓰지 않습니다.\n",
        "- 사람이 확인하기 전까지 `quality_status`는 `needs_review`를 유지합니다.\n",
    ]

    if candidates:
        report_lines.append("\n## 후보 샘플 목록\n\n")
        for s in candidates:
            sid = s.get("id", "unknown")
            details = s.get("metadata", {}).get("hallucination_details", [])
            report_lines.append(f"- `{sid}`: {', '.join(str(d) for d in details[:2])}\n")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")


if __name__ == "__main__":
    main()
