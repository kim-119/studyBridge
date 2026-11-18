"""
CLI: DB 학습 후보 → 검증 → JSONL 내보내기

사용법:
  python -m scripts.export_training_jsonl_from_db [옵션]

옵션:
  --min-db-score INT          DB 조회 최소 quality_score (기본: 70)
  --min-quality FLOAT         검증 최소 overall_quality_score (기본: 0.80)
  --min-knowledge FLOAT       검증 최소 knowledge_level_score (기본: 0.75)
  --min-personality FLOAT     검증 최소 personality_score (기본: 0.75)
  --output FILENAME           저장할 파일명 (기본: 자동 생성)
  --dry-run                   파일 저장 없이 통계만 출력
  --yes                       확인 프롬프트 건너뜀

주의:
  - 이 스크립트는 JSONL export만 수행한다.
  - QLoRA 학습 실행은 포함하지 않는다. (관리자 승인 후 수동 실행)
  - 개인정보, 보안키, 비밀번호가 포함된 데이터는 자동으로 제외된다.
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="DB 학습 후보 → 검증 → JSONL 내보내기 CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--min-db-score",     type=int,   default=70)
    p.add_argument("--min-quality",      type=float, default=0.80)
    p.add_argument("--min-knowledge",    type=float, default=0.75)
    p.add_argument("--min-personality",  type=float, default=0.75)
    p.add_argument("--output",           type=str,   default=None)
    p.add_argument("--dry-run",          action="store_true")
    p.add_argument("--yes", "-y",        action="store_true")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> None:
    # 환경 초기화
    import os, sys
    # 스크립트를 fastapi/ 에서 실행한다고 가정
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from app.db.postgres import init_pool, close_pool
    from app.training.training_data_validator import ValidationCriteria
    from app.training.jsonl_exporter import export_validated_jsonl

    print("=" * 60)
    print(" StudyBridge — QLoRA 학습 데이터 JSONL 내보내기")
    print("=" * 60)
    print(f"  DB 최소 점수   : {args.min_db_score}")
    print(f"  전체 품질 기준 : {args.min_quality}")
    print(f"  지식수준 기준  : {args.min_knowledge}")
    print(f"  성격 기준      : {args.min_personality}")
    print(f"  출력 파일      : {args.output or '(자동 생성)'}")
    print(f"  Dry-run 모드   : {args.dry_run}")
    print()

    if not args.yes and not args.dry_run:
        answer = input("위 설정으로 JSONL을 내보내시겠습니까? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("취소되었습니다.")
            return

    print("DB 연결 초기화 중...")
    try:
        await init_pool()
    except Exception as e:
        print(f"[오류] DB 연결 실패: {e}")
        sys.exit(1)

    criteria = ValidationCriteria(
        min_overall_quality_score=args.min_quality,
        min_knowledge_level_score=args.min_knowledge,
        min_personality_score=args.min_personality,
    )

    print("내보내기 실행 중...")
    result = await export_validated_jsonl(
        output_filename=args.output,
        criteria=criteria,
        min_db_score=args.min_db_score,
        dry_run=args.dry_run,
    )

    await close_pool()

    # 결과 출력
    print()
    print("─" * 60)
    print(f"  상태             : {result['status']}")
    print(f"  전체 후보        : {result['total_candidates']}건")
    print(f"  검증 통과        : {result['passed_count']}건")
    print(f"  검증 탈락        : {result['failed_count']}건")
    print(f"  실제 내보낸 수   : {result['exported_count']}건")
    print(f"  데이터셋 버전    : {result.get('dataset_version', '-')}")
    if result.get("output_file"):
        print(f"  저장 위치        : {result['output_file']}")
    print(f"  메시지           : {result.get('message', '')}")

    if result.get("failure_summary"):
        print()
        print("  [탈락 이유 집계]")
        for reason, cnt in sorted(result["failure_summary"].items(), key=lambda x: -x[1]):
            print(f"    {reason}: {cnt}건")
    print("─" * 60)

    if result["status"] == "completed":
        print()
        print("★ JSONL export 완료.")
        print("  QLoRA 학습은 아래 스크립트로 별도 실행하세요:")
        print("  python -m scripts.run_qlora_training --data-file <위 저장 위치>")
        print("  (학습 실행은 관리자 승인 또는 CLI 전용입니다.)")
    elif result["status"] == "dry_run":
        print()
        print("  Dry-run 완료. 실제 저장하려면 --dry-run 없이 재실행하세요.")
    else:
        print()
        print("  export 할 데이터가 없습니다. 데이터 수집을 계속하세요.")
        sys.exit(0)


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
