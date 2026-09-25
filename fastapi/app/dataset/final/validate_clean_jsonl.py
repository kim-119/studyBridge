#!/usr/bin/env python3
"""
validate_clean_jsonl.py
final_train_messages_clean.jsonl의 구조와 품질을 검증한다.

실행:
  python app/dataset/final/validate_clean_jsonl.py
  python app/dataset/final/validate_clean_jsonl.py --input <path>
"""
import argparse
import json
import sys
from pathlib import Path

VALID_ROLES       = {"system", "user", "assistant"}
MIN_ASSISTANT_LEN = 30
MIN_USER_LEN      = 5

DEFAULT_INPUT = Path(__file__).parent / "final_train_messages_clean.jsonl"


def check(condition: bool, label: str, fail_log: list, detail: str = "") -> bool:
    if condition:
        print(f"  [PASS] {label}")
    else:
        msg = f"  [FAIL] {label}" + (f" — {detail}" if detail else "")
        print(msg)
        fail_log.append(msg)
    return condition


def validate(input_path: Path) -> bool:
    if not input_path.exists():
        print(f"[ERROR] 파일 없음: {input_path}")
        return False

    raw_lines = [l for l in input_path.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    total = len(raw_lines)
    print(f"\n대상 파일: {input_path}")
    print(f"총 라인 수: {total}\n")

    fail_log: list[str] = []
    parse_failures      = []
    extra_field_lines   = []
    bad_role_lines      = []
    missing_content     = []
    missing_user        = []
    missing_assistant   = []
    short_assistant     = []
    extra_msg_fields    = []

    parsed: list[dict] = []

    # ── 줄별 검사 ────────────────────────────────────────────
    for i, line in enumerate(raw_lines, 1):
        # 1. JSON 파싱
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            parse_failures.append(f"  라인 {i}: {e}")
            continue
        parsed.append(obj)

        # 2. 최상위 필드가 messages 하나뿐인지
        if set(obj.keys()) != {"messages"}:
            extra_field_lines.append(
                f"  라인 {i}: top-level keys = {list(obj.keys())}"
            )

        # 3. messages가 list인지
        messages = obj.get("messages")
        if not isinstance(messages, list) or not messages:
            missing_user.append(f"  라인 {i}: messages 배열 없음")
            continue

        roles_found = set()
        for j, msg in enumerate(messages):
            # 4. 각 메시지에 role/content만 있는지
            msg_keys = set(msg.keys())
            if msg_keys != {"role", "content"}:
                extra_msg_fields.append(
                    f"  라인 {i}, msg[{j}]: keys={list(msg_keys)}"
                )

            role    = msg.get("role", "")
            content = msg.get("content", "")

            # 5. role 값 유효성
            if role not in VALID_ROLES:
                bad_role_lines.append(f"  라인 {i}, msg[{j}]: role='{role}'")

            # 6. content 비어 있지 않은지
            if not isinstance(content, str) or not content.strip():
                missing_content.append(f"  라인 {i}, msg[{j}] (role={role})")

            roles_found.add(role)

        # 7. user 존재 여부
        if "user" not in roles_found:
            missing_user.append(f"  라인 {i}: user role 없음")

        # 8. assistant 존재 여부
        if "assistant" not in roles_found:
            missing_assistant.append(f"  라인 {i}: assistant role 없음")

        # 9. assistant 내용 길이
        asst_content = next(
            (m["content"] for m in messages if m.get("role") == "assistant"), ""
        )
        if len(asst_content.strip()) < MIN_ASSISTANT_LEN:
            short_assistant.append(
                f"  라인 {i}: assistant {len(asst_content.strip())}자 "
                f"(최소 {MIN_ASSISTANT_LEN}자 필요)"
            )

    # ── 집계 검사 ─────────────────────────────────────────────
    print("=" * 55)
    print("검증 항목별 결과")
    print("=" * 55)

    check(not parse_failures,      "모든 줄이 JSON 파싱 가능",             fail_log,
          f"{len(parse_failures)}개 실패")
    check(len(parsed) == total - len(parse_failures),
          "파싱 성공 줄 수 일치",                                           fail_log)
    check(not extra_field_lines,   "최상위 필드가 messages 하나뿐",         fail_log,
          f"{len(extra_field_lines)}개 위반")
    check(not extra_msg_fields,    "메시지 내부가 role/content만 포함",      fail_log,
          f"{len(extra_msg_fields)}개 위반")
    check(not bad_role_lines,      "모든 role 값이 system/user/assistant",  fail_log,
          f"{len(bad_role_lines)}개 위반")
    check(not missing_content,     "content 빈 문자열 없음",                fail_log,
          f"{len(missing_content)}개 위반")
    check(not missing_user,        "모든 줄에 user role 존재",              fail_log,
          f"{len(missing_user)}개 위반")
    check(not missing_assistant,   "모든 줄에 assistant role 존재",         fail_log,
          f"{len(missing_assistant)}개 위반")
    check(not short_assistant,     f"assistant {MIN_ASSISTANT_LEN}자 이상", fail_log,
          f"{len(short_assistant)}개 위반")

    # 중복 검사
    dedup_keys = set()
    dups = 0
    for obj in parsed:
        msgs = obj.get("messages", [])
        user = next((m["content"] for m in msgs if m.get("role") == "user"),  "")[:200]
        asst = next((m["content"] for m in msgs if m.get("role") == "assistant"), "")[:200]
        key = user + "|||" + asst
        if key in dedup_keys:
            dups += 1
        else:
            dedup_keys.add(key)
    check(dups == 0, "중복 데이터 없음", fail_log, f"{dups}개 중복")

    # ── 최종 판정 ─────────────────────────────────────────────
    print("=" * 55)
    passed = len(fail_log) == 0
    verdict = "PASS — 학습 데이터로 사용 가능" if passed else f"FAIL — {len(fail_log)}개 항목 실패"
    print(f"최종 판정: {verdict}")
    print(f"검증 완료 라인 수: {len(parsed)} / {total}")
    print("=" * 55)

    if fail_log:
        print("\n실패 항목 상세:")
        for f in fail_log:
            print(f)
        # 상세 위반 목록 (최대 5개씩)
        for name, items in [
            ("파싱 실패", parse_failures),
            ("최상위 필드 위반", extra_field_lines),
            ("role 값 위반", bad_role_lines),
            ("content 비어 있음", missing_content),
            ("user 없음", missing_user),
            ("assistant 없음", missing_assistant),
            ("assistant 짧음", short_assistant),
        ]:
            if items:
                print(f"\n  [{name}] (최대 5개 표시)")
                for item in items[:5]:
                    print(item)

    return passed


def main():
    parser = argparse.ArgumentParser(description="JSONL 학습 데이터 검증")
    parser.add_argument("--input", default=str(DEFAULT_INPUT),
                        help=f"검증할 JSONL 파일 (기본: {DEFAULT_INPUT})")
    args = parser.parse_args()

    ok = validate(Path(args.input))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
