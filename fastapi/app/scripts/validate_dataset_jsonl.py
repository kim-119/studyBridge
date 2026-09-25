#!/usr/bin/env python3
"""
validate_dataset_jsonl.py
JSONL 데이터셋 구조와 내용을 검증하고 validate_dataset_report.md를 생성한다.

실행 예시:
  python app/scripts/validate_dataset_jsonl.py \
    --input app/dataset/review/normalized_dataset.jsonl \
    --report app/dataset/reports/validate_dataset_report.md
"""
import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone

VALID_SOURCE_TYPES = {
    "java_code", "pdf_rag", "user_log", "agent_profile",
    "verification", "prompt_template", "failure_case", "code_rag",
}

VALID_QUALITY_STATUSES = {
    "raw", "sanitized", "auto_generated", "needs_review",
    "reviewed", "approved", "rejected", "duplicate", "unsafe",
}

VALID_CORRECTION_TYPES = {
    "none", "tone_adjusted", "source_separation_fixed", "level_normalized",
    "pdf_metadata_hallucination", "persona_tone_mismatch", "",
}

REQUIRED_METADATA = [
    "source_type", "quality_status", "requires_human_review",
    "contains_code", "contains_personal_data", "contains_secret_candidate",
    "language", "project", "repo_branch", "created_by",
]

EXCLUDE_STATUSES = {"needs_review", "duplicate", "rejected", "unsafe"}

SECRET_PATTERNS = [
    re.compile(r'sk-[A-Za-z0-9]{48}'),
    re.compile(r'tvly-[A-Za-z0-9_\-]+'),
    re.compile(r'AKIA[0-9A-Z]{16}'),
    re.compile(r'hf_[A-Za-z0-9]{30,}'),
    re.compile(r'postgresql://[^\s"\'<>]+'),
    re.compile(r'jdbc:[a-z]+://[^\s"\'<>]+'),
    re.compile(r'-----BEGIN.*PRIVATE KEY-----'),
]

PERSONAL_DATA_PATTERNS = [
    re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'),
    re.compile(r'01[0-9][-\s]?\d{3,4}[-\s]?\d{4}'),
]

CHUNK_INDEX_RE = re.compile(r'chunk_index\s*[:=]?\s*\d+', re.IGNORECASE)
SIMILARITY_RE = re.compile(r'similarity\s*[:=]?\s*[\d.]+', re.IGNORECASE)

JAVA_CODE_RE = re.compile(r'```java|public\s+class\s+\w+|import\s+java\.')


def has_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def has_personal_data(text: str) -> bool:
    return any(p.search(text) for p in PERSONAL_DATA_PATTERNS)


def contains_java_code(text: str) -> bool:
    return bool(JAVA_CODE_RE.search(text))


def validate_sample(idx: int, raw_line: str, seen_ids: dict) -> dict:
    errors = []
    warnings = []
    info = []

    try:
        sample = json.loads(raw_line)
    except json.JSONDecodeError as e:
        return {"idx": idx, "id": None, "errors": [f"JSON 파싱 실패: {e}"],
                "warnings": [], "info": []}

    sid = sample.get("id", f"idx_{idx}")

    if not sample.get("id"):
        errors.append("id 없음")

    if sid in seen_ids:
        errors.append(f"id 중복 (이전: 라인 {seen_ids[sid]})")
    else:
        seen_ids[sid] = idx

    messages = sample.get("messages")
    full_text = ""
    assistant_content = ""
    user_content = ""

    if not messages or not isinstance(messages, list):
        errors.append("messages 배열 없음")
    else:
        roles = [m.get("role") for m in messages]
        for r in ("system", "user", "assistant"):
            if r not in roles:
                errors.append(f"{r} role 없음")

        assistant_content = next(
            (m.get("content", "") for m in messages if m.get("role") == "assistant"), ""
        )
        user_content = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"), ""
        )
        full_text = " ".join(m.get("content", "") for m in messages)

        if len(assistant_content.strip()) < 50:
            errors.append(f"assistant content 너무 짧음 ({len(assistant_content)}자)")
        elif len(assistant_content) > 5000:
            warnings.append(f"assistant content 매우 김 ({len(assistant_content)}자)")

        if has_secret(full_text):
            errors.append("민감정보 후보 발견 — 직접 제거 필요")
        if has_personal_data(full_text):
            warnings.append("개인정보 후보 발견 — 검토 필요")

        # PDF 환각 탐지
        if "PDF_RAG_CONTEXT" in user_content:
            if not CHUNK_INDEX_RE.search(user_content) and CHUNK_INDEX_RE.search(assistant_content):
                warnings.append("PDF 환각: chunk_index가 user에 없는데 assistant에 있음")
            if not SIMILARITY_RE.search(user_content) and SIMILARITY_RE.search(assistant_content):
                warnings.append("PDF 환각: similarity가 user에 없는데 assistant에 있음")

        # Java 코드 원문 500자 초과 검사
        if contains_java_code(assistant_content):
            java_blocks = re.findall(r'```java(.*?)```', assistant_content, re.DOTALL)
            for block in java_blocks:
                if len(block.strip()) > 500:
                    warnings.append(f"Java 코드 블록 500자 초과 ({len(block.strip())}자) — 원본 전체 포함 여부 확인")

    meta = sample.get("metadata")
    if not meta:
        errors.append("metadata 없음")
    else:
        for field in REQUIRED_METADATA:
            if field not in meta:
                errors.append(f"필수 metadata 누락: {field}")

        src = meta.get("source_type", "")
        if src not in VALID_SOURCE_TYPES:
            errors.append(f"유효하지 않은 source_type: {src}")

        qs = meta.get("quality_status", "")
        if qs not in VALID_QUALITY_STATUSES:
            errors.append(f"유효하지 않은 quality_status: {qs}")

        correction_type = meta.get("correction_type", "")
        if correction_type and correction_type not in VALID_CORRECTION_TYPES:
            warnings.append(f"알 수 없는 correction_type: {correction_type}")

        # contains_code 자동 추정과 metadata 비교
        inferred_contains_code = contains_java_code(full_text)
        if inferred_contains_code and not meta.get("contains_code"):
            warnings.append("코드 감지되었으나 contains_code=false — 확인 필요")

        if meta.get("contains_secret_candidate"):
            warnings.append("contains_secret_candidate=true — 사람 검토 필요")
        if meta.get("contains_personal_data"):
            warnings.append("contains_personal_data=true — 마스킹 확인 필요")

        if qs == "approved" and meta.get("requires_human_review"):
            warnings.append("approved이지만 requires_human_review=true — 불일치")

        if qs in {"reviewed", "approved"} and not meta.get("reviewed_by"):
            warnings.append(f"{qs} 샘플인데 reviewed_by 없음")

        if not meta.get("review_notes") and not meta.get("cleaned_review_notes"):
            info.append("review_notes 없음")

    return {"idx": idx, "id": sid, "errors": errors, "warnings": warnings, "info": info}


def main():
    parser = argparse.ArgumentParser(description="JSONL 데이터셋 검증")
    parser.add_argument("--input", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 파일 없음: {args.input}", file=sys.stderr)
        sys.exit(1)

    lines = input_path.read_text(encoding="utf-8").strip().splitlines()
    print(f"[INFO] 검증 대상: {len(lines)}개 샘플")

    results = []
    seen_ids: dict[str, int] = {}
    status_counter = Counter()
    source_type_counter = Counter()

    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        r = validate_sample(idx + 1, line, seen_ids)
        results.append(r)

        try:
            s = json.loads(line)
            meta = s.get("metadata", {})
            status_counter[meta.get("quality_status", "unknown")] += 1
            source_type_counter[meta.get("source_type", "unknown")] += 1
        except Exception:
            pass

    total = len(results)
    error_count = sum(1 for r in results if r["errors"])
    warn_count = sum(1 for r in results if r["warnings"] and not r["errors"])
    pass_count = total - error_count - warn_count

    java_count = source_type_counter.get("java_code", 0)
    java_ratio = java_count / total if total else 0.0
    reviewed_approved = status_counter.get("reviewed", 0) + status_counter.get("approved", 0)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# JSONL 데이터셋 검증 리포트\n\n",
        f"생성일시: {now_str}\n\n",
        f"- 검증 파일: `{args.input}`\n",
        f"- 총 샘플: {total}개\n",
        f"- 통과: {pass_count}개\n",
        f"- 경고: {warn_count}개\n",
        f"- 오류: {error_count}개\n",
        "\n## quality_status 분포\n\n",
    ]
    for qs, cnt in sorted(status_counter.items()):
        report_lines.append(f"- {qs}: {cnt}\n")

    report_lines += [
        "\n## source_type 분포\n\n",
    ]
    for st, cnt in sorted(source_type_counter.items()):
        report_lines.append(f"- {st}: {cnt}\n")

    report_lines += [
        f"\n- Java 코드 비율: {java_ratio:.1%}\n",
        f"- reviewed + approved: {reviewed_approved}\n",
    ]

    if error_count > 0:
        report_lines.append("\n## 오류 샘플\n\n")
        for r in results:
            if r["errors"]:
                report_lines.append(f"### 라인 {r['idx']} (id: `{r['id']}`)\n\n")
                for e in r["errors"]:
                    report_lines.append(f"- 오류: {e}\n")
                report_lines.append("\n")

    if warn_count > 0:
        report_lines.append("\n## 경고 샘플\n\n")
        for r in results:
            if r["warnings"] and not r["errors"]:
                report_lines.append(f"### 라인 {r['idx']} (id: `{r['id']}`)\n\n")
                for w in r["warnings"]:
                    report_lines.append(f"- 경고: {w}\n")
                report_lines.append("\n")

    report_lines.append("\n## 최종 판정\n\n")
    if error_count == 0:
        report_lines.append("오류 없음 — 경고 항목 검토 후 학습 후보 파일 사용 가능\n")
    else:
        report_lines.append(f"오류 {error_count}개 발생 — 수정 후 재검증 필요\n")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")

    print(f"[INFO] 통과: {pass_count} / 경고: {warn_count} / 오류: {error_count}")
    print(f"[INFO] 리포트 저장: {args.report}")
    sys.exit(1 if error_count > 0 else 0)


if __name__ == "__main__":
    main()
