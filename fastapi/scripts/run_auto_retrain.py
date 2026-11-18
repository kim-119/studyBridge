"""
CLI: 자동 재학습 파이프라인 수동 실행

사용법:
  python -m scripts.run_auto_retrain [옵션]

옵션:
  --dry-run              학습/배포 없이 dataset 생성 + readiness check만 실행
  --force-train          autoTrain=false이어도 강제로 학습 실행
  --force-deploy         autoDeploy=false이어도 평가 통과 시 production 배포
  --yes, -y              확인 프롬프트 건너뜀
  --json                 결과를 JSON으로 출력

주의:
  - 기본 설정은 autoTrain=false, autoDeploy=false이다.
  - 실제 QLoRA 학습을 원하면 --force-train 을 명시적으로 사용하거나
    auto_retrain_config.json에서 autoTrain=true로 변경한다.
  - production 자동 반영은 --force-deploy 또는 autoDeploy=true일 때만 실행된다.
  - GPU가 없으면 학습 단계는 자동으로 건너뛴다.
  - 개인정보/보안키가 포함된 데이터는 안전성 게이트에서 자동 차단된다.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="자동 QLoRA 재학습 파이프라인 CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--dry-run",      action="store_true", help="학습/배포 없이 dataset까지만 실행")
    p.add_argument("--force-train",  action="store_true", help="autoTrain 무시하고 학습 강제 실행")
    p.add_argument("--force-deploy", action="store_true", help="autoDeploy 무시하고 배포 강제 실행")
    p.add_argument("--yes", "-y",    action="store_true", help="확인 프롬프트 건너뜀")
    p.add_argument("--json",         action="store_true", help="결과 JSON 출력")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> None:
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from app.training.auto_retrain_runner import load_config, run_auto_retrain
    from app.db.postgres import init_pool, close_pool

    config = load_config()
    if args.force_train:
        config.auto_train = True
    if args.force_deploy:
        config.auto_deploy = True

    if not args.json:
        print("=" * 65)
        print(" StudyBridge — 자동 QLoRA 재학습 파이프라인")
        print("=" * 65)
        print(f"  dry-run      : {args.dry_run}")
        print(f"  autoTrain    : {config.auto_train}")
        print(f"  autoDeploy   : {config.auto_deploy}")
        print(f"  canaryDeploy : {config.canary_deploy}")
        print(f"  rollback     : {config.rollback_on_failure}")
        print()
        _print_safety_notice()

    if not args.yes and not args.dry_run:
        answer = input("위 설정으로 파이프라인을 실행하시겠습니까? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("취소되었습니다.")
            return
    elif not args.yes and args.dry_run:
        if not args.json:
            print("dry-run 실행 중...\n")

    print("DB 연결 초기화 중...")
    try:
        await init_pool()
    except Exception as e:
        print(f"[오류] DB 연결 실패: {e}")
        sys.exit(1)

    result = await run_auto_retrain(
        config=config,
        dry_run=args.dry_run,
        force_train=args.force_train,
    )

    await close_pool()

    if args.json:
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2, default=str))
        _exit_by_status(result.status)
        return

    # 사람이 읽을 수 있는 출력
    _STATUS_EMOJI = {
        "completed": "✅",
        "dry_run":   "🔍",
        "skipped":   "⏭",
        "blocked":   "🚫",
        "failed":    "❌",
    }
    emoji = _STATUS_EMOJI.get(result.status, "?")
    print()
    print("─" * 65)
    print(f"  상태          : {emoji} {result.status.upper()}")
    print(f"  run ID        : {result.run_id}")
    print(f"  dataset       : {result.dataset_version or '(생성 안 됨)'}")
    print(f"  검증 통과     : {result.validated_samples}건")
    print(f"  안전 차단     : {result.safety_blocked}건")
    print()
    print("  [단계별 상태]")
    steps = [
        ("1. 데이터 수집",  result.step_data_collect),
        ("2. 검증",         result.step_validate),
        ("3. dataset 생성", result.step_dataset),
        ("4. readiness",    result.step_readiness),
        ("5. 학습",         result.step_train),
        ("6. 평가",         result.step_evaluate),
        ("7. 등록",         result.step_register),
        ("8. 배포",         result.step_deploy),
    ]
    for name, status_str in steps:
        icon = "✅" if status_str.startswith("ok") else ("⏭" if "skipped" in status_str else "❌" if "failed" in status_str else "🔄")
        print(f"  {icon} {name:15s}: {status_str}")

    if result.eval_scores:
        print()
        print("  [평가 점수]")
        for k, v in result.eval_scores.items():
            print(f"    {k}: {v}")

    if result.errors:
        print()
        print("  [오류]")
        for e in result.errors:
            print(f"    • {e}")

    print()
    print(f"  {result.message}")
    print("─" * 65)

    if result.status == "completed" and not result.production_updated:
        print()
        print("  candidate 모델 배포는 아래 API로 수동 진행하세요:")
        print("  POST /api/ai/training/auto-retrain/enable (스케줄러 활성화)")
        print("  또는 auto_retrain_config.json에서 autoDeploy=true 설정")

    _exit_by_status(result.status)


def _print_safety_notice():
    print("  [안전 조건]")
    print("  • 개인정보 / 보안키 / 위험 내용 포함 데이터는 자동 차단됩니다.")
    print("  • readiness gate를 통과하지 못하면 학습을 실행하지 않습니다.")
    print("  • 기존 모델보다 품질이 떨어지면 자동 배포하지 않습니다.")
    print("  • autoDeploy=false이면 production 모델은 변경되지 않습니다.")
    print()


def _exit_by_status(status: str) -> None:
    codes = {"completed": 0, "dry_run": 0, "skipped": 0, "blocked": 2, "failed": 1}
    sys.exit(codes.get(status, 1))


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
