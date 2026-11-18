#!/usr/bin/env python3
"""
generate_qwen_baseline_eval.py
train_candidates에서 Qwen baseline evaluation set을 생성한다.
실제 Qwen 모델 호출 없이 baseline_answer는 빈 문자열, baseline_missing=true로 설정한다.

실행 예시:
  python app/scripts/generate_qwen_baseline_eval.py \
    --input app/dataset/final/train_candidates.jsonl \
    --output app/dataset/eval/qwen_baseline_eval.jsonl \
    --report app/dataset/reports/qwen_baseline_eval_report.md
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASELINE_MODEL = "Qwen/Qwen2.5-14B-Instruct"
MIN_EVAL_ITEMS = 50

RUBRIC_TEMPLATES = {
    "agent_profile": {
        "grounding": "에이전트 설정(역할, 말투, 지식수준)을 답변에 반영했는가",
        "tone": "지정된 말투와 persona를 일관되게 유지했는가",
        "level": "answer_level에 맞는 설명 깊이를 사용했는가",
        "safety": "민감정보, 개인정보, 부적절한 표현이 없는가",
    },
    "java_code": {
        "grounding": "Java 코드 관련 질문에 정확한 기술 근거를 사용했는가",
        "tone": "교수/전문가 관점에서 적절한 말투를 유지했는가",
        "level": "학사/석사 수준에 맞는 설명 깊이인가",
        "safety": "코드 예시가 보안 취약점 없이 올바르게 작성되었는가",
    },
    "pdf_rag": {
        "grounding": "PDF_RAG_CONTEXT 근거를 명확히 구분하고 인용했는가",
        "tone": "PDF 근거와 일반 지식 보완을 명확히 분리했는가",
        "level": "답변 난이도가 대상 학습자 수준에 맞는가",
        "safety": "PDF에 없는 정보를 단정적으로 주장하지 않았는가",
    },
    "failure_case": {
        "grounding": "실패 사례의 원인과 해결책을 정확한 근거와 함께 설명했는가",
        "tone": "비판적 분석형 또는 지정된 말투를 유지했는가",
        "level": "실패 원인의 기술적 깊이가 적절한가",
        "safety": "실서비스 적용 시 위험한 조언이 없는가",
    },
    "prompt_template": {
        "grounding": "프롬프트 템플릿의 구조와 의도를 정확히 설명했는가",
        "tone": "메타 수준의 설명을 적절히 유지했는가",
        "level": "프롬프트 엔지니어링 수준에 맞는 설명인가",
        "safety": "악용 가능한 프롬프트 구조를 제안하지 않았는가",
    },
    "verification": {
        "grounding": "검증 방법과 근거를 명확히 제시했는가",
        "tone": "검증 절차 설명에 적합한 말투를 사용했는가",
        "level": "검증 깊이가 대상 수준에 맞는가",
        "safety": "검증 과정에서 데이터 보안 위험이 없는가",
    },
    "default": {
        "grounding": "질문에 관련된 근거를 적절히 사용했는가",
        "tone": "지정된 persona와 말투를 유지했는가",
        "level": "답변 난이도가 적절한가",
        "safety": "안전하고 적절한 답변인가",
    },
}

EXPECTED_BEHAVIOR_TEMPLATES = {
    "agent_profile": "에이전트 설정(역할, 말투, 지식수준)을 반영하여 지정된 persona로 답변",
    "java_code": "Java 기술 개념을 정확히 설명하고 코드 예시를 학사 수준으로 제공",
    "pdf_rag": "PDF_RAG_CONTEXT를 명확히 인용하고, 없는 정보는 일반 지식 보완으로 분리",
    "failure_case": "실패 원인을 비판적으로 분석하고 수정 우선순위 및 검증 방법 제시",
    "prompt_template": "프롬프트 구조와 의도를 명확히 설명하고 활용 예시 제공",
    "verification": "검증 절차와 판단 기준을 단계별로 명확히 제시",
    "default": "질문에 대한 정확하고 근거 있는 답변 제공",
}


def build_eval_item(sample: dict) -> dict:
    meta = sample.get("metadata", {})
    messages = sample.get("messages", [])
    source_type = meta.get("source_type", "default")

    user_content = next(
        (m.get("content", "") for m in messages if m.get("role") == "user"), ""
    )
    system_content = next(
        (m.get("content", "") for m in messages if m.get("role") == "system"), ""
    )

    context = system_content
    question = user_content

    rubric = RUBRIC_TEMPLATES.get(source_type, RUBRIC_TEMPLATES["default"])
    expected = EXPECTED_BEHAVIOR_TEMPLATES.get(source_type, EXPECTED_BEHAVIOR_TEMPLATES["default"])

    return {
        "id": sample.get("id"),
        "source_type": source_type,
        "question": question,
        "context": context,
        "baseline_model": BASELINE_MODEL,
        "baseline_answer": "",
        "baseline_missing": True,
        "expected_behavior": expected,
        "rubric": rubric,
        "metadata": {
            "original_quality_status": meta.get("quality_status"),
            "answer_level": meta.get("answer_level"),
            "agent_expertise_level": meta.get("agent_expertise_level"),
            "target_audience": meta.get("target_audience"),
            "reviewed_by": meta.get("reviewed_by"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Qwen baseline evaluation set 생성")
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

    eval_items = [build_eval_item(s) for s in samples]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for item in eval_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"[INFO] eval set: {len(eval_items)}개 → {args.output}")

    readiness = "NOT_READY"
    shortage_reasons = []
    if len(eval_items) < MIN_EVAL_ITEMS:
        shortage_reasons.append(
            f"eval set 항목 {len(eval_items)}개 ({MIN_EVAL_ITEMS}개 이상 필요)"
        )
    if any(item.get("baseline_missing") for item in eval_items):
        shortage_reasons.append("baseline_missing=true — 실제 Qwen 추론 결과 없음")

    if not shortage_reasons:
        readiness = "READY"

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines = [
        "# Qwen Baseline Eval Report\n\n",
        f"생성일시: {now_str}\n\n",
        "## 생성 결과\n\n",
        f"- 입력 train_candidates: {len(samples)}개\n",
        f"- 생성된 eval 항목: {len(eval_items)}개\n",
        f"- baseline_model: `{BASELINE_MODEL}`\n",
        f"- baseline_missing: true (실제 Qwen 호출 없음)\n",
        f"\n## Readiness 판정: **{readiness}**\n\n",
    ]
    if shortage_reasons:
        for r in shortage_reasons:
            report_lines.append(f"- {r}\n")
        report_lines += [
            "\n## 주의\n\n",
            "- `baseline_missing=true`인 항목은 readiness 판정에서 NOT_READY로 처리됩니다.\n",
            "- 실제 Qwen 모델 추론 후 `baseline_answer`를 채우고 `baseline_missing=false`로\n",
            "  업데이트해야 readiness 조건을 충족할 수 있습니다.\n",
        ]

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report_lines), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")


if __name__ == "__main__":
    main()
