#!/usr/bin/env python3
"""
AI 전용 DB 마이그레이션 실행 스크립트.
기존 scripts/run_migrations.py의 래퍼 (동일한 안전장치 포함).

기본: dry-run (SQL 파일 목록만 출력)
실행: --apply 옵션 필요

안전장치:
  - AI_DATABASE_URL에 ai-db/studybridge_ai/localhost:5433 중 하나가 없으면 차단
  - URL에 capstone DB 패턴이 보이면 즉시 차단
  - capstone-db에는 절대 적용 금지
"""
import sys
from pathlib import Path

# run_migrations.py와 동일한 로직을 재사용
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    # run_migrations.py의 main() 직접 호출
    from scripts.run_migrations import main
    main()
