#!/usr/bin/env python3
"""
SFT 데이터셋 JSONL 유효성 검증 스크립트.

확인 항목:
- JSON 파싱 가능 여부
- messages 배열 구조 (system/user/assistant 순서)
- 빈 content 없음
- 최소 길이 조건
- 욕설/비하 패턴 없음 (기본 필터)
- 중복 비율 경고

실행 예시:
  python validate_sft_dataset.py --input ./data/sft_train.jsonl
  python validate_sft_dataset.py --input ./data/sft_train.jsonl --strict
"""
import argparse
import json
import sys
from pathlib import Path

MIN_ASSISTANT_LEN = 30
WARN_DUPLICATE_RATIO = 0.1  # 중복이 10% 이상이면 경고

BAD_PATTERNS = ["욕설샘플", "비하샘플"]  # 실제 필터 패턴은 팀 정책에 맞게 추가


def validate_record(idx: int, rec: dict) -> list[str]:
    errors = []
    messages = rec.get("messages", [])
    if not isinstance(messages, list) or len(messages) < 2:
        errors.append(f"[{idx}] messages 배열 길이 부족 ({len(messages)})")
        return errors

    roles = [m.get("role") for m in messages]
    if roles[-1] != "assistant":
        errors.append(f"[{idx}] 마지막 role이 'assistant'가 아님: {roles[-1]}")

    for m in messages:
        content = m.get("content", "")
        if not content or not content.strip():
            errors.append(f"[{idx}] 빈 content 발견 (role={m.get('role')})")
        for bad in BAD_PATTERNS:
            if bad in content:
                errors.append(f"[{idx}] 금지 패턴 발견: '{bad}' (role={m.get('role')})")

    assistant_content = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "assistant"), ""
    )
    if len(assistant_content.strip()) < MIN_ASSISTANT_LEN:
        errors.append(f"[{idx}] assistant 답변이 너무 짧음 ({len(assistant_content.strip())}자 < {MIN_ASSISTANT_LEN}자)")

    return errors


def main():
    parser = argparse.ArgumentParser(description="SFT 데이터셋 검증")
    parser.add_argument("--input", required=True, help="검증할 JSONL 파일 경로")
    parser.add_argument("--strict", action="store_true", help="오류 시 exit(1)")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"파일 없음: {path}")
        sys.exit(1)

    records = []
    parse_errors = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append((i, json.loads(line)))
            except json.JSONDecodeError as e:
                parse_errors.append(f"[{i}] JSON 파싱 실패: {e}")

    all_errors = list(parse_errors)
    seen_keys: set[str] = set()
    duplicates = 0

    for idx, rec in records:
        errors = validate_record(idx, rec)
        all_errors.extend(errors)

        # 중복 체크 (assistant 답변 앞 50자 기준)
        assistant = next(
            (m.get("content", "")[:50] for m in reversed(rec.get("messages", []))
             if m.get("role") == "assistant"), ""
        )
        if assistant in seen_keys:
            duplicates += 1
        else:
            seen_keys.add(assistant)

    total = len(records)
    dup_ratio = duplicates / total if total else 0

    print(f"\n검증 결과: 총 {total}건")
    print(f"  오류: {len(all_errors)}건")
    print(f"  중복 의심: {duplicates}건 ({dup_ratio:.1%})")

    if all_errors:
        print("\n[오류 목록]")
        for e in all_errors[:20]:
            print(f"  {e}")
        if len(all_errors) > 20:
            print(f"  ... 외 {len(all_errors) - 20}건")

    if dup_ratio >= WARN_DUPLICATE_RATIO:
        print(f"\n[경고] 중복 비율 {dup_ratio:.1%}이 {WARN_DUPLICATE_RATIO:.0%}를 초과합니다.")

    if all_errors and args.strict:
        sys.exit(1)

    if not all_errors:
        print("\n✓ 검증 통과")


if __name__ == "__main__":
    main()
