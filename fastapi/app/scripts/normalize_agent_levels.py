#!/usr/bin/env python3
"""
normalize_agent_levels.py
knowledge_level 모호성 해결: agent_expertise_level / answer_level / target_audience 분리.

실행 예시:
  python app/scripts/normalize_agent_levels.py \
    --input app/dataset/review/cleaned_human_reviewed_dataset.jsonl \
    --output app/dataset/review/normalized_dataset.jsonl \
    --report app/dataset/reports/normalize_agent_levels_report.md
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROLE_EXPERTISE_MAP = {
    "교수": "전문가",
    "professor": "전문가",
    "아키텍트": "전문가",
    "architect": "전문가",
    "연구자": "전문가",
    "researcher": "전문가",
    "전문가": "전문가",
    "expert": "전문가",
    "강사": "중급",
    "developer": "중급",
    "개발자": "중급",
    "튜터": "중급",
    "학생": "입문",
    "student": "입문",
    "도우미": "입문",
    "봇": "입문",
}

LEVEL_AUDIENCE_MAP = {
    "입문": "프로그래밍 입문자",
    "학사": "컴퓨터공학 학부생",
    "석사": "대학원생 / 연구자",
    "박사": "박사 과정 / 연구자",
    "전문가": "현업 개발자 / 아키텍트",
    "intermediate": "컴퓨터공학 학부생",
    "advanced": "대학원생 / 연구자",
    "beginner": "프로그래밍 입문자",
}

ANSWER_LEVEL_KEYWORDS = {
    "입문": ["비유", "쉽게", "초보", "간단"],
    "학사": ["학사", "전공", "기본 개념", "예시", "코드"],
    "석사": ["석사", "장단점", "한계", "적용 조건", "세부 구현"],
    "박사": ["박사", "아키텍처", "비교 분석", "연구"],
    "전문가": ["운영", "배포", "모니터링", "실서비스", "비용"],
}

AMBIGUITY_PATTERN = re.compile(
    r"지식수준이 에이전트의 전문성인지 답변 난이도인지 구분"
)


def infer_expertise_level(role: str) -> str:
    if not role:
        return "중급"
    role_lower = role.lower()
    for keyword, level in ROLE_EXPERTISE_MAP.items():
        if keyword in role_lower:
            return level
    return "중급"


def infer_answer_level(knowledge_level: str, assistant_content: str) -> str:
    kl = (knowledge_level or "").strip()
    known = {"입문", "학사", "석사", "박사", "전문가"}
    if kl in known:
        return kl

    content_lower = (assistant_content or "").lower()
    for level, keywords in ANSWER_LEVEL_KEYWORDS.items():
        if any(kw in content_lower for kw in keywords):
            return level
    return "학사"


def check_level_mismatch(answer_level: str, assistant_content: str) -> bool:
    content = (assistant_content or "").lower()
    if answer_level == "박사" and "연구" not in content and "아키텍처" not in content:
        return True
    if answer_level == "입문" and len(re.findall(r'[A-Z]{3,}', assistant_content or "")) > 5:
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="answer_level / agent_expertise_level 정규화")
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

    normalized_count = 0
    mismatch_candidates: list[str] = []
    schema_normalized: list[str] = []

    for sample in samples:
        meta = sample.setdefault("metadata", {})
        messages = sample.get("messages", [])
        assistant_content = next(
            (m.get("content", "") for m in messages if m.get("role") == "assistant"), ""
        )

        knowledge_level = meta.get("knowledge_level", "")
        agent_role = meta.get("agent_name") or meta.get("role", "")

        cleaned_notes = meta.get("cleaned_review_notes", meta.get("review_notes", ""))
        is_ambiguous = bool(AMBIGUITY_PATTERN.search(cleaned_notes))

        expertise_level = infer_expertise_level(agent_role)
        answer_level = infer_answer_level(knowledge_level, assistant_content)
        target_audience = LEVEL_AUDIENCE_MAP.get(answer_level, "학부생")

        meta["agent_role"] = agent_role
        meta["agent_expertise_level"] = expertise_level
        meta["answer_level"] = answer_level
        meta["target_audience"] = target_audience

        if is_ambiguous:
            meta["level_schema_normalized"] = True
            schema_normalized.append(sample.get("id", ""))
            normalized_count += 1

        if check_level_mismatch(answer_level, assistant_content):
            meta["level_mismatch_candidate"] = True
            mismatch_candidates.append(sample.get("id", ""))

        meta["level_normalized_at"] = datetime.now(timezone.utc).isoformat()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[INFO] 저장: {args.output} ({len(samples)}개)")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# Normalize Agent Levels Report\n\n",
        f"생성일시: {now_str}\n\n",
        "## 정규화 결과\n\n",
        f"- 전체 샘플 수: {len(samples)}\n",
        f"- level_schema_normalized 적용 샘플 수: {normalized_count}\n",
        f"- level_mismatch_candidate 샘플 수: {len(mismatch_candidates)}\n",
        "\n## 정규화 개요\n\n",
        "| 필드 | 의미 |\n",
        "|---|---|\n",
        "| `agent_expertise_level` | 에이전트 자체의 전문성 수준 (교수=전문가) |\n",
        "| `answer_level` | 답변 난이도 (학부생 대상=학사) |\n",
        "| `target_audience` | 답변이 설계된 대상 학습자 |\n",
        "| `knowledge_level` | 기존 값 유지 |\n",
        "\n## level_schema_normalized 샘플\n\n",
    ]
    if schema_normalized:
        for sid in schema_normalized:
            report_lines.append(f"- `{sid}`\n")
    else:
        report_lines.append("- 없음\n")

    if mismatch_candidates:
        report_lines.append("\n## level_mismatch_candidate 샘플\n\n")
        for sid in mismatch_candidates:
            report_lines.append(f"- `{sid}`\n")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")


if __name__ == "__main__":
    main()
