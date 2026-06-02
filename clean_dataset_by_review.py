#!/usr/bin/env python3
"""
검수 보고서 기반 학습 데이터 정리 스크립트
입력: raw JSONL + human_review_report.md
출력: clean_training_dataset.jsonl, cleaning_report.md
"""
import json
import re
import sys
from pathlib import Path

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/ai07/capstoneLLM/fastapi/app/dataset/final")
JSONL_PATH = BASE_DIR / "final_train_messages_clean.jsonl"
REPORT_PATH = BASE_DIR / "human_review_report.md"
OUT_JSONL = Path("/home/ai07/capstoneLLM/clean_training_dataset.jsonl")
OUT_REPORT = Path("/home/ai07/capstoneLLM/cleaning_report.md")

# ── 검수 보고서 파싱 ──────────────────────────────────────────────────────────
def parse_review_table(md_path: Path) -> list[dict]:
    """
    '샘플별 검수 메모' 테이블을 파싱해 행 순서대로 반환.
    각 행: {quality_status, review_notes}
    """
    text = md_path.read_text(encoding="utf-8")
    # 테이블 헤더 이후 데이터 행만 추출
    # 헤더: | id | source_type | quality_status | reviewed_by | review_notes |
    in_table = False
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        # 헤더 감지
        if "quality_status" in stripped and "reviewed_by" in stripped:
            in_table = True
            continue
        # 구분선 건너뜀
        if re.match(r"\|[-| ]+\|", stripped):
            continue
        if not in_table:
            continue
        # 데이터 행 파싱: | id | source_type | quality_status | reviewed_by | review_notes |
        parts = [p.strip() for p in stripped.strip("|").split("|")]
        if len(parts) < 4:
            continue
        rows.append({
            "quality_status": parts[2].strip().lower(),
            "review_notes": parts[4].strip() if len(parts) > 4 else "",
        })
    return rows


# ── messages 구조 검증 ────────────────────────────────────────────────────────
# reviewed/approved 상태인데도 notes에 명확한 제외 근거가 있는 경우만 걸러냄.
# "중복" 단독 키워드는 "중복 아님" 같은 긍정 문구에 오매칭되므로 제외.
EXCLUDE_KEYWORDS = [
    "학습 제외",
]

QUIZ_PATTERNS = [
    r"^[①②③④⑤]",
    r"^[1-4]\)",
    r"^답안\s*:",
    r"^정답\s*:",
    r"^선택지",
    r"^문제\s*:",
]

def is_quiz_style(assistant_content: str) -> bool:
    lines = assistant_content.strip().splitlines()
    quiz_line_count = 0
    for line in lines[:10]:
        for pat in QUIZ_PATTERNS:
            if re.search(pat, line.strip()):
                quiz_line_count += 1
                break
    return quiz_line_count >= 2


def validate_messages(messages: list) -> tuple[bool, str]:
    """True = 통과, False = 제외 + 사유"""
    if not isinstance(messages, list) or len(messages) == 0:
        return False, "messages 배열 없음"

    roles = [m.get("role", "") for m in messages]
    if "assistant" not in roles:
        return False, "assistant role 없음"
    if "user" not in roles:
        return False, "user role 없음"

    for m in messages:
        if not m.get("role"):
            return False, "role 누락"
        if m["role"] not in ("system", "user", "assistant"):
            return False, f"허용되지 않는 role: {m['role']}"
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            return False, f"{m['role']} content 비어 있음"

    assistant_content = next(
        (m["content"] for m in reversed(messages) if m["role"] == "assistant"), ""
    )
    if len(assistant_content.strip()) < 10:
        return False, "assistant 답변 너무 짧음"

    if is_quiz_style(assistant_content):
        return False, "문제 출제형 답변"

    return True, ""


def extract_clean_sample(raw: dict) -> dict:
    """messages 필드만 남기고 허용 role만 유지"""
    messages = raw.get("messages", [])
    clean_messages = []
    # system → user → assistant 순서 보장을 위해 역할별 수집 후 정렬
    order = {"system": 0, "user": 1, "assistant": 2}
    for m in messages:
        if m.get("role") in order:
            clean_messages.append({"role": m["role"], "content": m["content"]})
    clean_messages.sort(key=lambda x: order.get(x["role"], 99))
    return {"messages": clean_messages}


# ── 메인 처리 ─────────────────────────────────────────────────────────────────
def main():
    # 1. 원본 JSONL 읽기
    raw_lines = JSONL_PATH.read_text(encoding="utf-8").splitlines()
    raw_samples = []
    parse_errors = 0
    for i, line in enumerate(raw_lines):
        line = line.strip()
        if not line:
            continue
        try:
            raw_samples.append(json.loads(line))
        except json.JSONDecodeError:
            raw_samples.append(None)
            parse_errors += 1

    # 2. 검수 보고서 파싱
    review_rows = parse_review_table(REPORT_PATH)

    # 3. 개수 비교
    n_raw = len(raw_samples)
    n_review = len(review_rows)

    if n_raw != n_review:
        msg = (
            f"매칭 실패: 원본 JSONL 샘플 수({n_raw}) ≠ "
            f"검수 보고서 행 수({n_review}). "
            "clean_training_dataset.jsonl을 생성하지 않습니다."
        )
        print(msg)
        OUT_REPORT.write_text(
            f"# Cleaning Report\n\n## 매칭 실패\n\n{msg}\n",
            encoding="utf-8",
        )
        sys.exit(1)

    # 4. 상태별 통계 초기화
    status_counts: dict[str, int] = {
        "reviewed": 0, "approved": 0, "needs_review": 0,
        "duplicate": 0, "rejected": 0, "unsafe": 0, "unknown": 0,
    }
    kept_samples = []
    needs_review_list = []
    excluded_reasons: dict[str, int] = {}

    def bump_reason(reason: str):
        excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1

    # 5. 줄 순서 기준 매칭 + 필터링
    for idx, (raw, review) in enumerate(zip(raw_samples, review_rows)):
        status = review["quality_status"]
        notes = review["review_notes"]

        # 상태 카운트
        if status in status_counts:
            status_counts[status] += 1
        else:
            status_counts["unknown"] += 1

        # --- 제외 판정 ---
        if status in ("duplicate", "rejected", "unsafe"):
            bump_reason(f"status={status}")
            continue

        if status == "needs_review":
            needs_review_list.append(idx + 1)
            continue

        # reviewed / approved 이하 처리
        if raw is None:
            bump_reason("JSON 파싱 실패")
            continue

        # review_notes 기반 추가 제외
        exclude_by_notes = False
        for kw in EXCLUDE_KEYWORDS:
            if kw in notes:
                bump_reason(f"review_notes 제외 키워드: {kw}")
                exclude_by_notes = True
                break
        if exclude_by_notes:
            continue

        # messages 구조 검증
        messages = raw.get("messages", [])
        ok, reason = validate_messages(messages)
        if not ok:
            bump_reason(f"구조 오류: {reason}")
            continue

        kept_samples.append(extract_clean_sample(raw))

    # 6. clean_training_dataset.jsonl 저장
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for sample in kept_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    # 7. 통계 계산
    n_kept = len(kept_samples)
    n_needs_review = status_counts["needs_review"]
    n_duplicate = status_counts["duplicate"]
    n_rejected = status_counts["rejected"]
    n_unsafe = status_counts["unsafe"]
    n_excluded = n_raw - n_kept - n_needs_review
    n_struct_error = sum(
        v for k, v in excluded_reasons.items() if k.startswith("구조 오류")
    )

    if n_kept < 100:
        readiness = "NOT_READY"
    elif n_kept < 500:
        readiness = "SMOKE_TEST_ONLY"
    else:
        readiness = "READY_CANDIDATE"

    # 8. cleaning_report.md 작성
    excluded_summary = "\n".join(
        f"  - {k}: {v}건" for k, v in sorted(excluded_reasons.items(), key=lambda x: -x[1])
    )

    needs_review_sample = (
        ", ".join(str(i) for i in needs_review_list[:10])
        + (" ..." if len(needs_review_list) > 10 else "")
    )

    report_lines = [
        "# Cleaning Report",
        "",
        "## 1. 입력 파일",
        f"- 원본 JSONL 파일: `{JSONL_PATH.name}`",
        f"- 검수 보고서 파일: `{REPORT_PATH.name}`",
        "",
        "## 2. 전체 처리 결과",
        "",
        f"| 항목 | 수치 |",
        f"|---|---:|",
        f"| 원본 샘플 수 | {n_raw} |",
        f"| 검수 보고서 행 수 | {n_review} |",
        f"| 최종 학습 JSONL 샘플 수 | {n_kept} |",
        f"| 제외 샘플 수 (needs_review 제외) | {n_excluded} |",
        f"| 수정 필요(needs_review) 샘플 수 | {n_needs_review} |",
        f"| 구조 오류 제외 샘플 수 | {n_struct_error} |",
        f"| 중복(duplicate) 제외 샘플 수 | {n_duplicate} |",
        f"| rejected 제외 샘플 수 | {n_rejected} |",
        f"| unsafe 제외 샘플 수 | {n_unsafe} |",
        "",
        "## 3. 상태별 처리 결과",
        "",
        "| quality_status | 개수 | 처리 |",
        "|---|---:|---|",
        f"| reviewed | {status_counts['reviewed']} | 구조 검증 후 유지 |",
        f"| approved | {status_counts['approved']} | 구조 검증 후 유지 |",
        f"| needs_review | {status_counts['needs_review']} | 최종 학습 제외, 재검수 필요 |",
        f"| duplicate | {status_counts['duplicate']} | 제외 |",
        f"| rejected | {status_counts['rejected']} | 제외 |",
        f"| unsafe | {status_counts['unsafe']} | 제외 |",
        "",
        "## 4. 최종 학습 가능 여부",
        "",
        f"**{readiness}**",
        "",
        f"- 최종 학습 JSONL 샘플 수: {n_kept}개",
    ]

    if readiness == "NOT_READY":
        report_lines.append("- 판단 근거: 100개 미만이므로 실질적 SFT 학습 불가. Dry-run 또는 파이프라인 검증 수준으로만 활용 가능.")
    elif readiness == "SMOKE_TEST_ONLY":
        report_lines.append("- 판단 근거: 100개 이상이나 500개 미만. Smoke test 수준 학습은 가능하나 실제 파인튜닝 품질 보장 불가.")
    else:
        report_lines.append("- 판단 근거: 500개 이상 확보. 데이터 품질 및 다양성 추가 확인 후 학습 진입 검토 가능.")

    report_lines += [
        "",
        "## 5. 제외 사유 요약",
        "",
    ]

    if excluded_reasons:
        for k, v in sorted(excluded_reasons.items(), key=lambda x: -x[1]):
            report_lines.append(f"- {k}: {v}건")
    else:
        report_lines.append("- 없음")

    report_lines += [
        "",
        "### 주요 제외 원인",
        "- 중복 데이터 과다 (동일 주제를 성격/말투만 바꿔 반복 생성)",
        "- 문제 출제형 데이터 제외 (자료보관함 퀴즈 기능과 역할 중복)",
        "- 질문 의도 불일치 (설명 요청 → 객관식 문제로 대체)",
        "- 성격/말투 반영 부족",
        "- 지식수준 반영 부족",
        "- 예시 및 답변 깊이 부족",
        "",
        "## 6. needs_review 샘플 목록 (재검수 대상)",
        "",
        f"- 총 {n_needs_review}개",
        f"- 행 번호(1-indexed): {needs_review_sample}",
        "",
        "## 7. 다음 작업",
        "",
        "1. `needs_review` 샘플은 원본 질문 의도와 review_notes를 보고 사람이 직접 수정해야 한다.",
        "2. `duplicate` 샘플은 복구하지 않는다.",
        "3. `rejected` 샘플은 학습 제외한다.",
        "4. 현재 reviewed 샘플만으로는 실제 학습보다 dry-run/smoke test에 적합하다.",
        "5. 6단계 QLoRA/SFT 진입 전 최소 300개 이상의 고품질 reviewed 샘플을 확보해야 한다.",
        "6. needs_review 샘플 수정·재검수 후 다시 이 스크립트를 실행해 clean_training_dataset.jsonl을 갱신하라.",
        "",
        f"---",
        f"*생성일: 2026-06-02 | 스크립트: clean_dataset_by_review.py*",
    ]

    OUT_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    # 9. 콘솔 출력
    print("처리 완료")
    print(f"- 원본 샘플 수: {n_raw}")
    print(f"- 최종 학습 샘플 수: {n_kept}")
    print(f"- 제외 샘플 수: {n_excluded}")
    print(f"- 수정 필요 샘플 수: {n_needs_review}")
    print(f"- 최종 판단: {readiness}")


if __name__ == "__main__":
    main()
