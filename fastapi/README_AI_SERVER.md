# StudyBridge AI Server — README

> v0.5 | FastAPI AI Orchestrator

---

## 1. 전제 조건

- Docker / Docker Compose
- Python 3.11+
- (선택) Ollama: `qwen2.5:7b` 모델 pull
- (선택) OpenAI API Key
- (선택) Tavily API Key

---

## 2. 환경변수 설정

```bash
cp fastapi/.env.example fastapi/.env
# .env 파일을 열고 OPENAI_API_KEY, TAVILY_API_KEY 등 입력
```

---

## 3. AI 인프라 실행 (ai-db + Redis만)

기존 capstone-db와 독립적으로 AI 전용 인프라를 실행한다.

```bash
docker compose -f fastapi/infra/docker-compose.ai.local.yml up -d
```

컨테이너 확인:
```bash
docker ps | grep capstone-ai
# capstone-ai-db  (포트 5433)
# capstone-redis  (포트 6380)
```

---

## 4. 마이그레이션

### dry-run (기본)
```bash
cd fastapi
python scripts/run_migrations.py
```

### 실제 실행 (AI DB에만)
```bash
python scripts/run_migrations.py --apply
# "yes" 입력 확인 필요
```

> Docker Compose 사용 시: ai-db 컨테이너 최초 기동 시 자동 실행됨 (initdb.d)

---

## 5. FastAPI 서버 실행

### 기존 진입점 (하위 호환, uvicorn main:app)
```bash
cd fastapi
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 신규 진입점 (v0.5, DB/Redis lifespan 포함)
```bash
cd fastapi
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 6. 헬스 체크

```bash
curl http://localhost:8000/api/health
```

응답 예시:
```json
{
  "status": "ok",
  "version": "0.5.0",
  "dependencies": {
    "ai_db": {"status": "ok"},
    "redis": {"status": "ok"},
    "ollama": {"status": "ok"},
    "openai_key_set": true,
    "tavily_key_set": true
  }
}
```

---

## 7. Smoke Test

```bash
cd fastapi
python scripts/smoke_test_ai_server.py
```

---

## 8. API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | /api/health | 서버 상태 |
| POST | /api/ai/chat | 에이전트 채팅 |
| POST | /api/ai/agent-tikitaka | 티키타카 대화 |
| GET | /api/ai/validation/{job_id} | 검증 상태 조회 |
| POST | /api/materials/{id}/ai/analyze | PDF 분석 |
| POST | /api/materials/{id}/rag/ingest | RAG 인제스트 |
| POST | /api/materials/{id}/rag/query | RAG 검색 |
| DELETE | /api/materials/{id}/rag | RAG 삭제 |
| GET | /api/training-candidates/stats | 학습 후보 통계 |
| POST | /api/training-candidates/export-jsonl | JSONL 내보내기 |

Swagger 문서: `http://localhost:8000/docs`

---

## 9. 포트 정보

| 서비스 | 호스트 포트 | 컨테이너 포트 | 비고 |
|---|---|---|---|
| FastAPI | 8000 | 8000 | |
| capstone-db (기존) | **5432** | 5432 | Spring Boot 전용 — 건드리지 않음 |
| capstone-ai-db (신규) | **5433** | 5432 | FastAPI AI 전용 |
| capstone-redis (신규) | **6380** | 6379 | FastAPI AI 전용 |

---

## 10. Spring/React 연결

현재: FastAPI AI 서버 독립 skeleton 완성 단계.
Spring Boot 연동은 다음 단계에서 진행:
- `fastapi/spring-integration/` 참고
- `MaterialServiceIntegrationGuide.java` 참고
