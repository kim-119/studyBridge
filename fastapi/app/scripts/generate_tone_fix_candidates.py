#!/usr/bin/env python3
"""
generate_tone_fix_candidates.py
비판적 분석형 persona/tone 불일치 샘플을 탐지하고 보정 후보를 생성한다.

실행 예시:
  python app/scripts/generate_tone_fix_candidates.py \
    --input app/dataset/review/normalized_dataset.jsonl \
    --output app/dataset/review/tone_fix_candidates.jsonl \
    --report app/dataset/reports/tone_fix_candidates_report.md
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CRITICAL_KEYWORDS = ["비판적 분석형", "critical_analysis", "비판적분석형"]

REQUIRED_SECTIONS = [
    "핵심 진단",
    "문제점",
    "위험",
    "우선순위",
    "검증",
    "결론",
]

REWRITE_TEMPLATE = """\
[에이전트 설정 기반 비판적 분석 답변 구조]

**핵심 진단**
현재 구조 또는 접근 방식의 핵심 문제를 한 문장으로 진단합니다.

**현재 구조의 문제점**
- 문제 1: (구체적 설명)
- 문제 2: (구체적 설명)

**방치 시 위험**
- 리스크 1: (발생 가능한 장애 또는 품질 저하)
- 리스크 2:

**수정 우선순위**
1. 즉시 수정 필요: (이유)
2. 단기 수정: (이유)
3. 중장기 개선: (이유)

**검증 방법**
- 수정 후 확인해야 할 체크리스트 또는 테스트 방법

**결론**
비판적 관점에서의 최종 권고 사항.

[주의: 이 구조는 제안 초안입니다. 실제 assistant 내용을 바탕으로 사람이 검토 후 확정해야 합니다.]
"""


def is_critical_tone(meta: dict) -> bool:
    persona = str(meta.get("persona", "")).lower()
    tone = str(meta.get("tone", "")).lower()
    return any(kw.lower() in persona or kw.lower() in tone for kw in CRITICAL_KEYWORDS)


def note_has_critical_flag(meta: dict) -> bool:
    notes = meta.get("cleaned_review_notes", meta.get("review_notes", ""))
    issue_types = meta.get("issue_types", [])
    return (
        any(kw in notes for kw in CRITICAL_KEYWORDS)
        or "persona_tone_mismatch" in issue_types
    )


def assistant_lacks_critical_content(content: str) -> bool:
    score = 0
    for section in REQUIRED_SECTIONS:
        if section in content:
            score += 1
    return score < 3


def main():
    parser = argparse.ArgumentParser(description="persona/tone 불일치 보정 후보 생성")
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
        meta = sample.get("metadata", {})
        messages = sample.get("messages", [])
        assistant_content = next(
            (m.get("content", "") for m in messages if m.get("role") == "assistant"), ""
        )

        if not (is_critical_tone(meta) or note_has_critical_flag(meta)):
            continue

        if not assistant_lacks_critical_content(assistant_content):
            continue

        sample_copy = json.loads(json.dumps(sample))
        m = sample_copy.setdefault("metadata", {})
        m["fix_required"] = True
        m["fix_type"] = "persona_tone_mismatch"
        m["correction_type"] = "tone_adjusted"
        m["proposed_assistant_rewrite"] = REWRITE_TEMPLATE
        m["human_approval_required"] = True
        m["tone_fix_flagged_at"] = datetime.now(timezone.utc).isoformat()

        candidates.append(sample_copy)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for s in candidates:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[INFO] tone_fix_candidates: {len(candidates)}개 → {args.output}")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# Tone Fix Candidates Report\n\n",
        f"생성일시: {now_str}\n\n",
        "## 탐지 결과\n\n",
        f"- 전체 입력 샘플: {len(samples)}\n",
        f"- tone_fix 후보 수: {len(candidates)}\n",
        "\n## 주의사항\n\n",
        "- `proposed_assistant_rewrite`는 제안 초안이며 원본 assistant를 덮어쓰지 않습니다.\n",
        "- 사람이 확인하기 전까지 `quality_status`는 `needs_review`를 유지합니다.\n",
        "- 자동으로 `reviewed` 또는 `approved`로 승격하지 않습니다.\n",
    ]

    if candidates:
        report_lines.append("\n## 후보 샘플 목록\n\n")
        for s in candidates:
            sid = s.get("id", "unknown")
            note = s.get("metadata", {}).get("cleaned_review_notes", "")[:80]
            report_lines.append(f"- `{sid}`: {note}...\n")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")


if __name__ == "__main__":
    main()
