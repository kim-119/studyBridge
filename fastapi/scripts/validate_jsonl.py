#!/usr/bin/env python3
"""
JSONL 파일 구조 검증 CLI.

사용:
  python scripts/validate_jsonl.py exported_training_data.jsonl
  python scripts/validate_jsonl.py data.jsonl --strict

검증 항목:
  - JSON 파싱 가능 여부
  - messages 배열 구조 (user/assistant role 필수)
  - 빈 content 없음
  - 금지 필드 없음 (id, user_id, quality_score, metadata)
  - PII 패턴 감지 (이메일, 전화번호 등)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="JSONL 파일 구조 검증")
    parser.add_argument("file", help="검증할 JSONL 파일 경로")
    parser.add_argument("--strict", action="store_true", help="경고도 오류로 처리")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"[오류] 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)

    try:
        from app.utils.jsonl_validator import validate_jsonl_file
        result = validate_jsonl_file(str(path))
    except ImportError as e:
        print(f"[오류] 모듈 import 실패: {e}")
        sys.exit(1)

    print(f"파일: {path}")
    print(f"전체: {result.total}줄 / 유효: {result.valid}줄 / 오류: {result.total - result.valid}줄")

    if result.errors:
        print(f"\n오류 목록 (최대 20개):")
        for e in result.errors[:20]:
            print(f"  - {e}")
        if len(result.errors) > 20:
            print(f"  ... 외 {len(result.errors) - 20}개")

    if result.is_valid:
        print("\n[OK] 유효한 JSONL 파일입니다.")
        sys.exit(0)
    else:
        print(f"\n[실패] {len(result.errors)}개 오류가 있습니다.")
        sys.exit(1 if args.strict else 0)


if __name__ == "__main__":
    main()
