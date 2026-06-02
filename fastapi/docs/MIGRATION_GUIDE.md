# 마이그레이션 가이드

> **중요: 모든 마이그레이션은 AI 전용 DB(studybridge_ai)에만 적용한다.**

---

## 절대 금지

- capstone-db (기존 팀플 서비스 DB)에 마이그레이션 적용 금지
- `DB_HOST=db`, `DB_NAME=capstone` 대상 실행 금지
- `--apply` 없이 SQL이 자동 실행되는 상황 금지

## Dry-run (기본)

```bash
cd fastapi
python scripts/run_migrations.py
```

출력 예시:
```
[DRY-RUN] 마이그레이션 파일 목록:
  - 001_create_ai_schema.sql
  - 002_create_rag_pgvector_schema.sql
  - 003_create_indexes.sql

총 3개 파일 (실행하려면 --apply 옵션 추가)

URL 유효성: ✓ 안전
```

## 실제 실행

```bash
# AI_DATABASE_URL 환경변수 필요
export AI_DATABASE_URL=postgresql://studybridge_ai:studybridge_ai_pw@localhost:5433/studybridge_ai

python scripts/run_migrations.py --apply
```

실행 안전장치:
1. URL에 `studybridge_ai`, `ai-db`, `localhost:5433` 중 하나가 있어야 함
2. URL에 `capstone`, `localhost:5432`, `db:5432` 중 하나라도 있으면 차단
3. "yes" 직접 입력 확인 필요

## Docker 컨테이너 자동 실행

`docker-compose.ai.local.yml`의 `ai-db` 서비스는 `/docker-entrypoint-initdb.d/`에
마운트된 SQL 파일을 컨테이너 최초 기동 시 자동으로 실행한다.

```yaml
volumes:
  - ../app/db/migrations:/docker-entrypoint-initdb.d:ro
```

## 마이그레이션 파일 순서

| 파일 | 내용 |
|---|---|
| 001_create_ai_schema.sql | ai 스키마 + 대화/검증/학습후보 테이블 |
| 002_create_rag_pgvector_schema.sql | pgvector + rag 스키마 + document_chunk |
| 003_create_indexes.sql | 일반 인덱스 + HNSW 벡터 인덱스 |
