#!/usr/bin/env python3
"""
clean_train_jsonl.py
final_train_messages_merged.jsonl을 QLoRA/SFT 학습용으로 정리한다.

실행:
  python app/scripts/clean_train_jsonl.py \
    --input  app/dataset/final/final_train_messages_merged.jsonl \
    --output app/dataset/final/final_train_messages_clean.jsonl \
    --report app/dataset/final/final_train_messages_clean_report.txt \
    --supplement-a app/dataset/review/normalized_dataset.jsonl \
    --supplement-b app/dataset/review/synthetic_dummy_300_messages.jsonl \
    --min-total 300
"""
import argparse
import json
import re
import sys
from pathlib import Path

# ─── 기준 상수 ────────────────────────────────────────────────
VALID_ROLES       = {"system", "user", "assistant"}
MIN_ASSISTANT     = 30      # 글자 수 기준 (학습 의미 없는 짧은 답변 제거)
MIN_USER          = 5
DEFAULT_SYSTEM    = "너는 학습자를 돕는 전문적인 AI 튜터다."
TARGET_MIN        = 300     # 최소 학습 샘플 수

# ─── 민감정보 패턴 ────────────────────────────────────────────
_SENSITIVE = [
    re.compile(r'sk-[A-Za-z0-9]{10,}'),
    re.compile(r'tvly-[A-Za-z0-9_\-]+'),
    re.compile(r'AKIA[0-9A-Z]{16}'),
    re.compile(r'hf_[A-Za-z0-9]{30,}'),
    re.compile(r'postgresql://[^\s"\'<>]+'),
    re.compile(r'jdbc:[a-z]+://[^\s"\'<>]+', re.I),
    re.compile(r'-----BEGIN\s+(RSA\s+)?PRIVATE KEY-----'),
    re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'),
    re.compile(r'01[016789][-\s]?\d{3,4}[-\s]?\d{4}'),
    re.compile(r'\bpassword\s*[:=]\s*\S+', re.I),
    re.compile(r'\bapi[_-]?key\s*[:=]\s*\S+', re.I),
    re.compile(r'\btoken\s*[:=]\s*[A-Za-z0-9_\-\.]{20,}', re.I),
    re.compile(r'eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}'),  # JWT
]

# 마스킹 가능 패턴 (제거 대신 마스킹)
_MASKABLE = [
    (re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'),
     "[EMAIL_MASKED]"),
    (re.compile(r'01[016789][-\s]?\d{3,4}[-\s]?\d{4}'),
     "[PHONE_MASKED]"),
]

# 삭제가 필요한 고위험 패턴 (마스킹 불가)
_HIGH_RISK = [
    re.compile(r'sk-[A-Za-z0-9]{10,}'),
    re.compile(r'tvly-[A-Za-z0-9_\-]+'),
    re.compile(r'AKIA[0-9A-Z]{16}'),
    re.compile(r'hf_[A-Za-z0-9]{30,}'),
    re.compile(r'postgresql://[^\s"\'<>]+'),
    re.compile(r'jdbc:[a-z]+://[^\s"\'<>]+', re.I),
    re.compile(r'-----BEGIN\s+(RSA\s+)?PRIVATE KEY-----'),
    re.compile(r'\bpassword\s*[:=]\s*\S+', re.I),
    re.compile(r'\bapi[_-]?key\s*[:=]\s*\S+', re.I),
    re.compile(r'\btoken\s*[:=]\s*[A-Za-z0-9_\-\.]{20,}', re.I),
    re.compile(r'eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}'),
]


def has_high_risk(text: str) -> bool:
    return any(p.search(text) for p in _HIGH_RISK)


def mask_low_risk(text: str) -> tuple[str, bool]:
    masked = False
    for pattern, replacement in _MASKABLE:
        new_text, n = pattern.subn(replacement, text)
        if n:
            text = new_text
            masked = True
    return text, masked


# ─── 메시지 정리 ──────────────────────────────────────────────

def extract_messages(raw: dict) -> list[dict] | None:
    """raw dict에서 messages 배열을 추출하고 role/content만 남긴다."""
    messages = raw.get("messages")

    # flat 형식 (instruction/output) → messages 변환
    if not messages:
        instr = raw.get("instruction") or raw.get("question") or raw.get("input") or ""
        out   = raw.get("output") or raw.get("answer") or raw.get("response") or ""
        if instr.strip() and out.strip():
            messages = [
                {"role": "user",      "content": instr.strip()},
                {"role": "assistant", "content": out.strip()},
            ]
        else:
            return None

    if not isinstance(messages, list):
        return None

    cleaned = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role    = str(msg.get("role", "")).strip().lower()
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        if role not in VALID_ROLES or not content:
            continue
        cleaned.append({"role": role, "content": content})

    return cleaned if cleaned else None


def validate_and_clean(messages: list[dict], log: list[str]) -> list[dict] | None:
    """구조 검증 + 민감정보 처리. 통과하면 정리된 messages, 실패하면 None."""
    roles = {m["role"] for m in messages}
    if "user" not in roles or "assistant" not in roles:
        log.append("user/assistant 없음 → 삭제")
        return None

    asst = next(m["content"] for m in messages if m["role"] == "assistant")
    user = next(m["content"] for m in messages if m["role"] == "user")

    if len(asst) < MIN_ASSISTANT:
        log.append(f"assistant 너무 짧음({len(asst)}자) → 삭제")
        return None
    if len(user) < MIN_USER:
        log.append(f"user 너무 짧음({len(user)}자) → 삭제")
        return None

    # system이 없으면 추가
    if "system" not in roles:
        messages = [{"role": "system", "content": DEFAULT_SYSTEM}] + messages

    # 민감정보 처리
    full_text = " ".join(m["content"] for m in messages)
    if has_high_risk(full_text):
        log.append("고위험 민감정보 발견 → 삭제")
        return None

    # 저위험 마스킹
    new_messages = []
    any_masked = False
    for m in messages:
        content, masked = mask_low_risk(m["content"])
        new_messages.append({"role": m["role"], "content": content})
        if masked:
            any_masked = True
    if any_masked:
        log.append("저위험 정보 마스킹 처리")

    return new_messages


def dedup_key(messages: list[dict]) -> str:
    user  = next((m["content"] for m in messages if m["role"] == "user"),  "")
    asst  = next((m["content"] for m in messages if m["role"] == "assistant"), "")
    return (user.strip()[:200] + "|||" + asst.strip()[:200])


# ─── JSONL 로드 ───────────────────────────────────────────────

def load_jsonl(path: Path) -> tuple[list[dict], int]:
    """(파싱된 샘플 리스트, 파싱 실패 수) 반환"""
    samples, errors = [], 0
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            errors += 1
    return samples, errors


# ─── 메인 ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",        required=True)
    parser.add_argument("--output",       required=True)
    parser.add_argument("--report",       required=True)
    parser.add_argument("--supplement-a", default="")
    parser.add_argument("--supplement-b", default="")
    parser.add_argument("--min-total",    type=int, default=TARGET_MIN)
    args = parser.parse_args()

    # ── 1. 원본 로드 ──────────────────────────────────────────
    src_path = Path(args.input)
    raw_samples, parse_errors = load_jsonl(src_path)
    total_input = len(raw_samples) + parse_errors
    print(f"[INFO] 원본: {total_input}줄 (파싱실패: {parse_errors})")

    # ── 2. 정리 ───────────────────────────────────────────────
    clean_results: list[list[dict]] = []
    deleted_short   = 0
    deleted_no_qa   = 0
    deleted_sensitive = 0
    masked_count    = 0
    deleted_parse   = parse_errors
    detail_log: list[str] = []

    for raw in raw_samples:
        msgs = extract_messages(raw)
        if msgs is None:
            deleted_no_qa += 1
            continue

        item_log: list[str] = []
        cleaned = validate_and_clean(msgs, item_log)

        for entry in item_log:
            detail_log.append(entry)
            if "짧음" in entry:
                deleted_short += 1
            elif "민감정보" in entry or "고위험" in entry:
                deleted_sensitive += 1
            elif "마스킹" in entry:
                masked_count += 1
            elif "user/assistant" in entry:
                deleted_no_qa += 1

        if cleaned is not None:
            clean_results.append(cleaned)

    print(f"[INFO] 정리 후: {len(clean_results)}개")

    # ── 3. 중복 제거 ──────────────────────────────────────────
    seen: set[str] = set()
    deduped: list[list[dict]] = []
    dup_count = 0

    for msgs in clean_results:
        key = dedup_key(msgs)
        if key in seen:
            dup_count += 1
        else:
            seen.add(key)
            deduped.append(msgs)

    print(f"[INFO] 중복 제거 후: {len(deduped)}개 (중복 {dup_count}개 제거)")

    # ── 4. 보충 (300개 미만인 경우) ───────────────────────────
    supplemented_a = 0
    supplemented_b = 0

    if len(deduped) < args.min_total:
        for sup_path_str, label in [
            (args.supplement_a, "supplement-a"),
            (args.supplement_b, "supplement-b"),
        ]:
            if not sup_path_str or len(deduped) >= args.min_total:
                break
            sup_path = Path(sup_path_str)
            if not sup_path.exists():
                continue
            sup_raw, _ = load_jsonl(sup_path)
            added = 0
            for raw in sup_raw:
                if len(deduped) >= args.min_total:
                    break
                msgs = extract_messages(raw)
                if msgs is None:
                    continue
                cleaned = validate_and_clean(msgs, [])
                if cleaned is None:
                    continue
                key = dedup_key(cleaned)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(cleaned)
                added += 1
            print(f"[INFO] {label}에서 {added}개 보충")
            if label == "supplement-a":
                supplemented_a = added
            else:
                supplemented_b = added

    final = deduped
    print(f"[INFO] 최종: {len(final)}개")

    # ── 5. 출력 ───────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for msgs in final:
            obj = {"messages": msgs}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    # ── 6. 최종 검증 ──────────────────────────────────────────
    parse_ok  = True
    struct_ok = True
    qa_ok     = True
    extra_field_ok = True

    with out_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                parse_ok = False
                continue
            if set(obj.keys()) != {"messages"}:
                extra_field_ok = False
            msgs = obj.get("messages", [])
            if not isinstance(msgs, list):
                struct_ok = False
                continue
            for m in msgs:
                if set(m.keys()) != {"role", "content"}:
                    struct_ok = False
                if m.get("role") not in VALID_ROLES:
                    struct_ok = False
            roles = {m.get("role") for m in msgs}
            if "user" not in roles or "assistant" not in roles:
                qa_ok = False

    # ── 7. 리포트 ─────────────────────────────────────────────
    deleted_total = (parse_errors + deleted_no_qa + deleted_short
                     + deleted_sensitive + dup_count)

    report_lines = [
        "=" * 60,
        "  JSONL 정리 리포트",
        "=" * 60,
        f"원본 파일         : {args.input}",
        f"출력 파일         : {args.output}",
        "-" * 60,
        f"원본 라인 수      : {total_input}",
        f"  JSON 파싱 실패  : {parse_errors}",
        f"  user/assistant 없음 (구조 불가): {deleted_no_qa}",
        f"  내용 너무 짧음  : {deleted_short}",
        f"  민감정보 삭제   : {deleted_sensitive}",
        f"  중복 제거       : {dup_count}",
        f"  마스킹 처리 수  : {masked_count}",
        f"삭제된 라인 수    : {deleted_total}",
        "-" * 60,
        f"보충 (supplement-a): {supplemented_a}",
        f"보충 (supplement-b): {supplemented_b}",
        "-" * 60,
        f"최종 라인 수      : {len(final)}",
        "=" * 60,
        "검증 결과",
        "-" * 60,
        f"JSON 파싱 성공      : {'PASS' if parse_ok else 'FAIL'}",
        f"messages 구조 검증  : {'PASS' if struct_ok else 'FAIL'}",
        f"user/assistant 검증 : {'PASS' if qa_ok else 'FAIL'}",
        f"최상위 필드 순수성  : {'PASS' if extra_field_ok else 'FAIL'}",
        "=" * 60,
        "전체 판정: " + ("PASS — 학습 데이터로 사용 가능"
                         if all([parse_ok, struct_ok, qa_ok, extra_field_ok])
                         else "FAIL — 수동 확인 필요"),
        "=" * 60,
    ]
    if detail_log:
        report_lines += ["", "상세 로그:"] + detail_log[:50]

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("\n".join(report_lines))
    print(f"\n[INFO] 리포트 저장: {args.report}")


if __name__ == "__main__":
    main()
