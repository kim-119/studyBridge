#!/usr/bin/env python3
"""
convert_jsonl_to_messages.py
기존 JSONL(messages 형식 또는 flat 형식)을 SFT/QLoRA용 messages 포맷으로 변환한다.
assistant 답변이 없는 샘플은 skipped_missing_answer.jsonl에 분리 저장한다.

실행 예시:
  python app/scripts/convert_jsonl_to_messages.py \
    --input app/dataset/review/normalized_dataset.jsonl \
    --output app/dataset/final/train_messages.jsonl \
    --skipped app/dataset/final/skipped_missing_answer.jsonl \
    --report app/dataset/reports/conversion_report.md \
    --synthetic app/dataset/review/synthetic_dummy_300_messages.jsonl \
    --merged app/dataset/final/final_train_messages_merged.jsonl
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SYSTEM = (
    "너는 StudyBridge의 AI 학습 에이전트다. "
    "제공된 근거를 우선 사용하고, 근거 없는 내용은 단정하지 않는다. "
    "에이전트 설정과 지식수준을 반영해 한국어로 답변한다."
)

MIN_ASSISTANT_LEN = 50

NON_ANSWER_FIELDS = {"expected_behavior", "rubric", "metadata", "context", "question"}


def validate_messages_item(item: dict) -> tuple[bool, str]:
    if not isinstance(item, dict):
        return False, "최상위가 dict가 아님"
    messages = item.get("messages")
    if not isinstance(messages, list):
        return False, "messages가 list가 아님"
    if len(messages) < 3:
        return False, f"messages 항목이 {len(messages)}개 (최소 3개 필요)"
    valid_roles = {"system", "user", "assistant"}
    roles_found = set()
    for msg in messages:
        if not isinstance(msg, dict):
            return False, "메시지가 dict가 아님"
        role = msg.get("role")
        content = msg.get("content")
        if role not in valid_roles:
            return False, f"유효하지 않은 role: {role}"
        if not isinstance(content, str) or not content.strip():
            return False, f"content 비어 있음 (role={role})"
        roles_found.add(role)
    for required in ("system", "user", "assistant"):
        if required not in roles_found:
            return False, f"{required} role 없음"
    asst_content = next(
        (m["content"] for m in messages if m.get("role") == "assistant"), ""
    )
    if len(asst_content.strip()) < MIN_ASSISTANT_LEN:
        return False, f"assistant content 너무 짧음 ({len(asst_content.strip())}자, 최소 {MIN_ASSISTANT_LEN}자 필요)"
    return True, "ok"


def find_assistant_answer(sample: dict) -> str | None:
    """우선순위: ideal_answer > reviewed_answer > final_answer > answer > baseline_answer(비어있지 않은 경우)"""
    for field in ("ideal_answer", "reviewed_answer", "final_answer", "answer"):
        val = sample.get(field, "")
        if isinstance(val, str) and val.strip() and field not in NON_ANSWER_FIELDS:
            return val.strip()
    baseline = sample.get("baseline_answer", "")
    if isinstance(baseline, str) and baseline.strip():
        return baseline.strip()
    if isinstance(sample.get("messages"), list):
        asst = next(
            (m.get("content", "") for m in sample["messages"] if m.get("role") == "assistant"),
            ""
        )
        if asst.strip() and len(asst.strip()) >= MIN_ASSISTANT_LEN:
            return asst.strip()
    return None


def convert_flat_to_messages(sample: dict) -> dict | None:
    context = sample.get("context", "")
    question = sample.get("question", "")
    system_content = context.strip() if context.strip() else DEFAULT_SYSTEM
    if not question.strip():
        return None
    answer = find_assistant_answer(sample)
    if not answer:
        return None
    meta = dict(sample.get("metadata") or {})
    meta["source"] = "original_converted"
    meta.setdefault("review_status", sample.get("metadata", {}).get("quality_status", "unknown"))
    return {
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
        "metadata": meta,
    }


def convert_messages_to_clean(sample: dict) -> dict | None:
    messages = sample.get("messages", [])
    answer = find_assistant_answer(sample)
    if not answer:
        return None
    cleaned_messages = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "assistant":
            content = answer
        if role in ("system", "user", "assistant") and content.strip():
            cleaned_messages.append({"role": role, "content": content})
    if len(cleaned_messages) < 3:
        return None
    roles = [m["role"] for m in cleaned_messages]
    for r in ("system", "user", "assistant"):
        if r not in roles:
            return None
    meta = dict(sample.get("metadata") or {})
    meta["source"] = "original_messages"
    meta.setdefault("review_status", meta.get("quality_status", "unknown"))
    return {"messages": cleaned_messages, "metadata": meta}


def load_jsonl(path: Path) -> tuple[list[dict], int]:
    samples = []
    parse_errors = 0
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            parse_errors += 1
    return samples, parse_errors


def write_jsonl(samples: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def merge_and_deduplicate(a: list[dict], b: list[dict]) -> tuple[list[dict], int]:
    seen_user_contents: set[str] = set()
    merged = []
    dup_count = 0
    for sample in a + b:
        messages = sample.get("messages", [])
        user_content = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"), ""
        )
        key = user_content.strip()
        if key in seen_user_contents:
            dup_count += 1
            continue
        seen_user_contents.add(key)
        merged.append(sample)
    return merged, dup_count


def main():
    parser = argparse.ArgumentParser(description="JSONL → messages 포맷 변환")
    parser.add_argument("--input", required=True, help="원본 JSONL 파일")
    parser.add_argument("--output", required=True, help="변환 성공 출력 (train_messages.jsonl)")
    parser.add_argument("--skipped", required=True, help="answer 누락 샘플 (skipped_missing_answer.jsonl)")
    parser.add_argument("--report", required=True, help="변환 리포트 (conversion_report.md)")
    parser.add_argument("--synthetic", default="", help="synthetic dummy JSONL (병합용, 선택사항)")
    parser.add_argument("--merged", default="", help="최종 병합 출력 (final_train_messages_merged.jsonl)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] 입력 파일 없음: {args.input}", file=sys.stderr)
        sys.exit(1)

    samples, parse_errors = load_jsonl(input_path)
    print(f"[INFO] 입력 샘플: {len(samples)}개, 파싱 실패: {parse_errors}개")

    converted: list[dict] = []
    skipped: list[dict] = []

    baseline_empty_count = 0
    expected_behavior_count = 0

    for sample in samples:
        if sample.get("baseline_answer") == "":
            baseline_empty_count += 1
        if "expected_behavior" in sample or "rubric" in sample:
            expected_behavior_count += 1

        if isinstance(sample.get("messages"), list):
            result = convert_messages_to_clean(sample)
        else:
            result = convert_flat_to_messages(sample)

        if result is None:
            skip_copy = dict(sample)
            skip_copy["skip_reason"] = "assistant answer missing"
            skipped.append(skip_copy)
        else:
            valid, reason = validate_messages_item(result)
            if valid:
                converted.append(result)
            else:
                skip_copy = dict(sample)
                skip_copy["skip_reason"] = f"validation failed: {reason}"
                skipped.append(skip_copy)

    write_jsonl(converted, Path(args.output))
    write_jsonl(skipped, Path(args.skipped))
    print(f"[INFO] 변환 성공: {len(converted)}개 → {args.output}")
    print(f"[INFO] 제외: {len(skipped)}개 → {args.skipped}")

    # 더미 데이터 로드 및 병합
    synthetic_count = 0
    merged_count = 0
    dup_count = 0
    synthetic_samples: list[dict] = []

    if args.synthetic and Path(args.synthetic).exists():
        synthetic_samples, _ = load_jsonl(Path(args.synthetic))
        synthetic_count = len(synthetic_samples)
        print(f"[INFO] synthetic dummy: {synthetic_count}개")

    if args.merged and (converted or synthetic_samples):
        merged, dup_count = merge_and_deduplicate(converted, synthetic_samples)
        merged_count = len(merged)
        write_jsonl(merged, Path(args.merged))
        print(f"[INFO] 병합 결과: {merged_count}개 → {args.merged} (중복 제거: {dup_count}개)")

    # 변환 리포트
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report = [
        "# JSONL 변환 및 더미 데이터 생성 보고서\n\n",
        f"생성일시: {now_str}\n\n",
        "## 입력 파일\n\n",
        f"- 원본 파일명: `{args.input}`\n",
        f"- 전체 라인 수: {len(samples) + parse_errors}\n",
        f"- JSON 파싱 실패: {parse_errors}개\n",
        f"- 유효 샘플: {len(samples)}개\n",
        "\n## 기존 데이터 변환 결과\n\n",
        f"- 변환 성공 수: {len(converted)}\n",
        f"- assistant 답변 누락으로 제외된 수: {len(skipped)}\n",
        f"- JSON 파싱 실패 수: {parse_errors}\n",
        "\n## 기존 JSONL 구조 문제\n\n",
        f"- baseline_answer 빈 문자열 존재: {baseline_empty_count}개\n",
        f"- expected_behavior/rubric은 assistant 답변으로 사용 불가: {expected_behavior_count}개\n",
        "\n## 더미 데이터 생성 결과\n\n",
        f"- synthetic dummy 파일: `{args.synthetic or '미지정'}`\n",
        f"- 실제 로드된 수: {synthetic_count}\n",
        "\n## 최종 병합 결과\n\n",
        f"- train_messages.jsonl 수: {len(converted)}\n",
        f"- synthetic_dummy_300_messages.jsonl 수: {synthetic_count}\n",
        f"- final_train_messages_merged.jsonl 수: {merged_count}\n",
        f"- 중복 제거 수: {dup_count}\n",
        "\n## 발견된 문제\n\n",
        "- 기존 JSONL에 messages 배열이 있더라도 assistant content가 빈 경우 학습 불가\n",
        "- baseline_answer 빈 문자열: assistant 답변으로 사용하지 않음\n",
        "- expected_behavior/rubric: 평가 기준이므로 assistant 답변으로 사용하지 않음\n",
        "\n## 최종 판단\n\n",
        f"- 기존 변환 데이터 {len(converted)}개 + synthetic dummy {synthetic_count}개 = 병합 {merged_count}개\n",
        "- synthetic dummy 데이터는 파이프라인 검증 및 초기 스타일 학습용으로 사용 가능\n",
        "- 실서비스 품질을 위해서는 synthetic_unreviewed 데이터를 사람이 검토하여 reviewed_answer 또는 approved 상태로 승격 필요\n",
    ]

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report), encoding="utf-8")
    print(f"[INFO] 리포트 저장: {args.report}")


if __name__ == "__main__":
    main()
