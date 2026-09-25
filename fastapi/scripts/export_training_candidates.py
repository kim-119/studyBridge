#!/usr/bin/env python3
"""
학습 후보 JSONL 내보내기 CLI.

사용:
  python scripts/export_training_candidates.py
  python scripts/export_training_candidates.py --output my_data.jsonl --min-score 85
  python scripts/export_training_candidates.py --dry-run

주의:
  - AI_DATABASE_URL이 설정되어 있어야 한다.
  - auto_approved + is_duplicate=FALSE + is_unsafe=FALSE 샘플만 내보낸다.
  - 내보낸 JSONL은 id/user_id/quality_score/metadata를 포함하지 않는다.
"""
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def build_output_path(base: str) -> str:
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = Path(base)
    return str(p.parent / f"{p.stem}_{date_str}{p.suffix}")


async def _run(output_path: str, min_score: int, dry_run: bool) -> None:
    # .env 로드
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass

    import os
    url = os.getenv("AI_DATABASE_URL")
    if not url:
        print("[오류] AI_DATABASE_URL이 설정되지 않았습니다.")
        sys.exit(1)

    if dry_run:
        print(f"[DRY-RUN] 출력 경로: {output_path}")
        print(f"[DRY-RUN] 최소 점수: {min_score}")
        print("[DRY-RUN] 실제 내보내기를 실행하려면 --dry-run 옵션을 제거하세요.")
        return

    try:
        from app.services.jsonl_export_service import export_approved_candidates
        result = await export_approved_candidates(
            output_path=output_path,
            min_score=min_score,
        )
        count = result.get("exported_count", 0)
        status = result.get("status", "unknown")
        print(f"내보내기 완료: {count}개 → {output_path} (status={status})")

        if count > 0:
            from app.utils.jsonl_validator import validate_jsonl_file
            validation = validate_jsonl_file(output_path)
            print(f"검증: {validation.valid}/{validation.total} 유효")
            if validation.errors:
                print(f"경고: {len(validation.errors)}개 오류 발견")
                for e in validation.errors[:5]:
                    print(f"  - {e}")
    except Exception as e:
        print(f"[오류] {e}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="학습 후보 JSONL 내보내기")
    parser.add_argument("--output", default="exported_training_data.jsonl", help="출력 파일 경로")
    parser.add_argument("--min-score", type=int, default=90, help="최소 quality_score (기본: 90)")
    parser.add_argument("--dry-run", action="store_true", help="실제 내보내기 없이 설정만 확인")
    args = parser.parse_args()

    output = build_output_path(args.output)
    asyncio.run(_run(output, args.min_score, args.dry_run))


if __name__ == "__main__":
    main()
