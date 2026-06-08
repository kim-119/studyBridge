"""
CLI: QLoRA 학습 준비 상태 점검

사용법:
  python -m scripts.check_training_readiness [옵션]

옵션:
  --json    결과를 JSON으로 출력 (CI/스크립트 파싱용)

출력 상태:
  not_ready : 검증 통과 데이터 부족 또는 품질 기준 미달
  ready     : 학습 실행 가능 (관리자 승인 후 수동 실행 필요)
  blocked   : PII/보안키/위험 내용 감지 — export/학습 금지
  trained   : 실제 학습 완료 모델 파일 존재

주의:
  이 스크립트는 상태 점검만 수행한다.
  학습 실행 기능은 포함하지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="QLoRA 학습 준비 상태 점검 CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="결과를 JSON으로 출력",
    )
    return p.parse_args()


async def _run(args: argparse.Namespace) -> None:
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from app.db.postgres import init_pool, close_pool
    from app.training.qlora_readiness_checker import check_readiness, report_to_dict

    if not args.json:
        print("=" * 60)
        print(" StudyBridge — QLoRA 학습 준비 상태 점검")
        print("=" * 60)

    print("DB 연결 초기화 중...", end="", flush=True)
    try:
        await init_pool()
        print(" 완료")
    except Exception as e:
        if args.json:
            print(json.dumps({"status": "error", "message": f"DB 연결 실패: {e}"}, ensure_ascii=False))
        else:
            print(f"\n[오류] DB 연결 실패: {e}")
        sys.exit(1)

    report = await check_readiness()
    await close_pool()

    result = report_to_dict(report)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        _exit_by_status(report.status)
        return

    # 사람이 읽을 수 있는 출력
    _STATUS_EMOJI = {
        "not_ready": "⏳",
        "ready":     "✅",
        "blocked":   "🚫",
        "trained":   "🎓",
    }
    emoji = _STATUS_EMOJI.get(report.status, "?")

    print()
    print(f"  상태             : {emoji} {report.status.upper()}")
    print(f"  전체 후보        : {report.total_candidates}건")
    print(f"  검증 통과 수     : {report.validated_samples}건 (최소: {report.required_samples}건)")
    print(f"  평균 품질 점수   : {report.average_quality_score:.4f}")
    print(f"  중복률 추정      : {report.duplication_rate:.2%}")
    print(f"  안전성 차단      : {'예 — ' + report.safety_blocked_reason if report.safety_blocked else '아니오'}")
    print(f"  모델 파일 존재   : {'예' if report.model_file_exists else '아니오'}")
    if report.last_exported_file:
        print(f"  최근 export      : {report.last_exported_file} ({report.last_export_count}건)")
    print()
    print(f"  {report.message}")
    print("─" * 60)

    if report.status == "not_ready":
        reasons = result.get("detail", {}).get("reasons_not_ready", [])
        if reasons:
            print()
            print("  [미충족 조건]")
            for r in reasons:
                print(f"    • {r}")
        print()
        print("  데이터 수집을 계속하거나 강의 PDF를 더 추가하세요.")
        print("  export 명령어: python -m scripts.export_training_jsonl_from_db")

    elif report.status == "ready":
        print()
        print("  학습 실행 명령어 (관리자 전용):")
        print("  python -m scripts.run_qlora_training \\")
        print("    --data-file training_exports/<export-파일>.jsonl \\")
        print("    --base-model Qwen2.5-14B-Instruct \\")
        print("    --output-dir adapters/qwen25_14b_studybridge")

    elif report.status == "blocked":
        print()
        print("  [경고] 안전 위반 데이터가 감지되어 학습이 차단되었습니다.")
        print("  validate-candidates API로 어떤 데이터가 문제인지 확인하세요.")

    elif report.status == "trained":
        print()
        print("  실제 학습 완료 모델이 존재합니다.")
        print("  FINETUNED_ADAPTER_PATH 또는 ollama list로 확인하세요.")

    _exit_by_status(report.status)


def _exit_by_status(status: str) -> None:
    """CI에서 상태별 exit code를 구분할 수 있도록 한다."""
    codes = {"not_ready": 1, "ready": 0, "blocked": 2, "trained": 0}
    sys.exit(codes.get(status, 1))


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
