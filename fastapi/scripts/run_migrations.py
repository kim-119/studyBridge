#!/usr/bin/env python3
"""
AI 전용 DB 마이그레이션 실행 스크립트.

기본: dry-run (SQL 파일 목록만 출력, 실제 실행 안 함)
실행: --apply 옵션 필요

안전장치:
  - AI_DATABASE_URL에 'ai-db', 'studybridge_ai', 'localhost:5433'이 없으면 차단
  - URL에 'capstone', 'localhost:5432', 'db:5432'가 보이면 차단
  - 위 검사를 통과해도 사용자 확인 없이 --apply 불가
"""
import argparse
import os
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "app" / "db" / "migrations"

# ── 허용 패턴: URL에 이 중 하나 이상이 있어야 실행 허용 ──────────────────────
ALLOWED_PATTERNS = ["ai-db", "studybridge_ai", "localhost:5433", "5433"]

# ── 차단 패턴: URL에 이 중 하나라도 있으면 즉시 차단 ────────────────────────
# 주의: capstone-ai-db 컨테이너명은 허용해야 하므로 'capstone' 단독 금지는 사용하지 않는다.
# 대신 기존 팀플 DB를 특정할 수 있는 패턴만 사용한다.
BLOCKED_PATTERNS = [
    "localhost:5432",      # 로컬 기존 DB 포트 (AI DB는 5433)
    "@db:5432",            # docker-compose 기존 db 컨테이너 직접 참조
    "@db/",                # host가 'db'인 경우
    "127.0.0.1:5432",
    "0.0.0.0:5432",
    "/capstone",           # 데이터베이스 이름이 capstone인 경우 (경로 끝)
]


def validate_url(url: str) -> tuple[bool, str]:
    """
    AI_DATABASE_URL의 안전성을 검사한다.

    Returns:
        (is_safe, reason)
    """
    if not url:
        return False, "AI_DATABASE_URL이 설정되지 않았습니다."

    url_lower = url.lower()

    # 차단 패턴 검사 (우선)
    for blocked in BLOCKED_PATTERNS:
        if blocked.lower() in url_lower:
            return False, (
                f"위험: URL에 '{blocked}'가 포함되어 있습니다.\n"
                "이것은 기존 팀플 DB(capstone-db)로 보입니다.\n"
                "AI 전용 DB URL(studybridge_ai, ai-db, 포트 5433)로 설정하세요."
            )

    # 허용 패턴 검사
    has_allowed = any(p.lower() in url_lower for p in ALLOWED_PATTERNS)
    if not has_allowed:
        return False, (
            f"URL이 AI 전용 DB로 인식되지 않습니다.\n"
            f"허용 패턴: {ALLOWED_PATTERNS}\n"
            f"현재 URL: {_mask_url(url)}"
        )

    return True, "OK"


def _mask_url(url: str) -> str:
    """URL에서 비밀번호를 마스킹한다."""
    import re
    return re.sub(r":([^:@]+)@", ":****@", url)


def get_migration_files() -> list[Path]:
    """마이그레이션 SQL 파일 목록을 정렬해서 반환한다."""
    if not MIGRATIONS_DIR.exists():
        print(f"마이그레이션 디렉토리가 없습니다: {MIGRATIONS_DIR}")
        return []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return files


def run_dry() -> None:
    """실행할 마이그레이션 파일 목록만 출력한다."""
    print("\n[DRY-RUN] 마이그레이션 파일 목록:")
    files = get_migration_files()
    if not files:
        print("  (없음)")
        return
    for f in files:
        print(f"  - {f.name}")
    print(f"\n총 {len(files)}개 파일 (실행하려면 --apply 옵션 추가)")


def run_apply(url: str) -> None:
    """실제 마이그레이션을 실행한다."""
    is_safe, reason = validate_url(url)
    if not is_safe:
        print(f"\n[차단] {reason}")
        sys.exit(1)

    files = get_migration_files()
    if not files:
        print("실행할 마이그레이션 파일이 없습니다.")
        return

    print(f"\n대상 DB: {_mask_url(url)}")
    print(f"실행할 파일 {len(files)}개:")
    for f in files:
        print(f"  - {f.name}")

    confirm = input("\n정말 실행하시겠습니까? (yes 입력): ").strip()
    if confirm.lower() != "yes":
        print("취소되었습니다.")
        sys.exit(0)

    try:
        import psycopg
    except ImportError:
        print("psycopg가 설치되지 않았습니다: pip install psycopg[binary]")
        sys.exit(1)

    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for f in files:
                sql = f.read_text(encoding="utf-8")
                print(f"\n실행 중: {f.name} ...", end="", flush=True)
                try:
                    conn.execute(sql)
                    print(" 완료")
                except Exception as e:
                    print(f" 실패!\n  오류: {e}")
                    print("  이후 파일 실행을 중단합니다.")
                    sys.exit(1)
    except Exception as e:
        print(f"\nDB 연결 실패: {e}")
        sys.exit(1)

    print("\n모든 마이그레이션 완료!")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI 전용 DB 마이그레이션 (기본: dry-run)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 마이그레이션 실행 (AI_DATABASE_URL 대상에만 적용)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="사용할 DB URL (기본: AI_DATABASE_URL 환경변수)",
    )
    args = parser.parse_args()

    # .env 로드
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent / ".env"
        load_dotenv(dotenv_path=env_path)
    except ImportError:
        pass

    url = args.url or os.getenv("AI_DATABASE_URL") or os.getenv("VECTOR_DATABASE_URL")

    if not args.apply:
        run_dry()
        if url:
            is_safe, reason = validate_url(url)
            print(f"\nURL 유효성: {'✓ 안전' if is_safe else '✗ 차단'}")
            if not is_safe:
                print(f"  사유: {reason}")
        return

    if not url:
        print("AI_DATABASE_URL 또는 --url 이 필요합니다.")
        sys.exit(1)

    run_apply(url)


if __name__ == "__main__":
    main()
