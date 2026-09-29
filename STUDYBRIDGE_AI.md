# StudyBridge AI 서버 — 통합 문서

> 브랜치: `LLM` | 최종 업데이트: 2026-06-07 (v0.8)  
> FastAPI AI 서버 + Spring Boot 연동 + 캡스톤 시연 가이드
>
> **v0.8 추가**: generation config 고도화 · 전 학문 domain classifier · OpenAlex 박사 전용 · Depth Verifier/Rewriter · Distillation/Offline Cache 구조

---

## 목차

1. [아키텍처](#1-아키텍처)
2. [빠른 시작 / 서버 실행](#2-빠른-시작--서버-실행)
3. [환경변수](#3-환경변수)
4. [API 레퍼런스](#4-api-레퍼런스)
5. [Spring 연동](#5-spring-연동)
6. [DB / pgvector / Redis](#6-db--pgvector--redis)
7. [학습 데이터 파이프라인](#7-학습-데이터-파이프라인)
8. [배포 & 시연 체크리스트](#8-배포--시연-체크리스트)
9. [완료 현황](#9-완료-현황)
10. [캡스톤 발표 가이드](#10-캡스톤-발표-가이드)

---

## 1. 아키텍처

### 전체 구조 (v0.6 확정)

```
[React 프론트]
      │ REST만 (FastAPI 직접 통신 없음)
      ▼
[Spring Boot 메인 서버 :8080]
      │ HTTP REST
      ▼
[FastAPI AI 서버 :8000]   ◄── 이 레포
      ├── Agent Router
      ├── Knowledge Level Controller
      ├── Personality Prompt Builder
      ├── RAG Retriever (pgvector)
      ├── Async Multi-Agent (asyncio.gather)
      ├── Tiki-Taka Turn Manager
      ├── Material AI Manager
      └── Feedback Validator + Rewriter
           │
    ┌──────┴─────────────────┐
    ▼                        ▼
Ollama (Qwen2.5-14B)    PostgreSQL + pgvector
    +                        (ai.document_chunks)
OpenAI GPT-4o-mini           (ai.training_candidate)
(fallback/검증)
```

### 핵심 원칙 (절대 위반 금지)

- React 프론트는 FastAPI와 직접 통신하지 않는다
- 프론트 → Spring REST → FastAPI HTTP 단방향이 원칙
- 프론트 SSE는 필수 아님. `AiChatSseController.java`는 optional/legacy
- 멀티에이전트는 jobId 기반 REST 조회 우선

### mode 기반 멀티에이전트 흐름 (v0.7)

| mode | 흐름 | 실행 방식 |
|------|------|---------|
| `default` | 기존 병렬 multi-agent 답변 | asyncio (병렬) |
| `tikitaka` | initial→critique→rebuttal 3라운드 | 라운드 단위 순차 |
| `debate` | supporter→critic→moderator 순차 체인 | 순차 (이전 답변이 입력) |
| `socratic` | 소크라테스 꼬리질문 단일 응답 | 단일 에이전트 |

### 멀티에이전트 비동기 흐름 (jobId 방식)

```
React
→ POST /api/study/ai/multi-chat/jobs       (Spring)
→ Spring이 jobId 즉시 반환 (PENDING)
→ Spring @Async: FastAPI POST /api/ai/multi-chat/async 호출
   └─ FastAPI: asyncio.gather()로 3명 병렬 답변 생성
→ 결과를 Spring in-memory job store에 저장
→ React: GET /api/study/ai/multi-chat/jobs/{jobId}/result 조회
```

### 모델 배분

| 기능 | 모델 |
|------|------|
| 에이전트 채팅 | Qwen2.5-14B (Ollama) |
| 자료보관함 Q&A | GPT 70% + Qwen 30% |
| 퀴즈/로드맵 생성 | GPT 전담 (정확성 우선) |
| GPT 검증 | GPT-4o-mini (background) |
| Ollama 실패 시 | OpenAI fallback |

---

## 2. 빠른 시작 / 서버 실행

### 서비스 기동 순서

```bash
# 1. PostgreSQL + pgvector (Docker)
docker compose -f fastapi/infra/docker-compose.ai.local.yml up -d
# capstone-ai-db :5433, capstone-redis :6380

# 2. Ollama + Qwen2.5
ollama pull qwen2.5:14b
ollama serve

# 또는 vLLM
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-14B-Instruct \
  --host 0.0.0.0 --port 8001 --api-key EMPTY

# 3. FastAPI (신규 진입점 권장)
cd fastapi
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Spring Boot
./mvnw spring-boot:run
```

### DB 마이그레이션

```bash
# dry-run (기본)
cd fastapi && python scripts/run_migrations.py

# 실제 실행 (AI DB에만)
python scripts/run_migrations.py --apply  # "yes" 입력 필요

# AI DB 연결 점검
python scripts/check_ai_db_connection.py
```

### 스모크 테스트

```bash
python scripts/smoke_test_ai_server.py
python scripts/smoke_test_ai.py
python scripts/smoke_test_rag.py
python scripts/smoke_test_prediction.py
```

### Swagger UI

```
http://localhost:8000/docs
http://localhost:8000/redoc
```

### 포트 정보

| 서비스 | 호스트 포트 | 비고 |
|--------|------------|------|
| FastAPI | 8000 | AI 서버 |
| Spring Boot | 8080 | 메인 서버 |
| capstone-db (기존) | 5432 | Spring 전용 — 건드리지 않음 |
| capstone-ai-db (신규) | 5433 | FastAPI AI 전용 |
| capstone-redis (신규) | 6380 | FastAPI AI 전용 |
| Ollama | 11434 | LLM |

---

## 3. 환경변수

```env
# LLM
QWEN_BASE_URL=http://localhost:8001/v1   # vLLM 사용 시
QWEN_MODEL_NAME=Qwen/Qwen2.5-14B-Instruct
QWEN_API_KEY=EMPTY
OLLAMA_BASE_URL=http://localhost:11434   # Ollama 사용 시
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# AI DB
AI_DATABASE_URL=postgresql://studybridge_ai:pw@localhost:5433/studybridge_ai
VECTOR_DATABASE_URL=postgresql://...    # AI_DATABASE_URL과 동일 가능
AUTO_RUN_AI_MIGRATIONS=false            # true이면 시작 시 자동 마이그레이션

# Search
TAVILY_API_KEY=tvly-...

# AWS S3 (퀴즈 생성용)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BUCKET=...
AWS_REGION=ap-northeast-2

# Redis
REDIS_URL=redis://localhost:6380/0

# Spring ↔ FastAPI 인증
AI_SERVER_API_KEY=studybridge-internal-secret

# 자동 재학습 (기본 모두 비활성화)
AUTO_RETRAIN_ENABLED=false
```

**절대 금지:** `.env`, 키 파일 git 커밋 금지

---

## 4. API 레퍼런스

### 공통

| 항목 | 값 |
|------|-----|
| Base URL | `http://<AI_SERVER_HOST>:8000` |
| 인증 | `Authorization: Bearer <AI_SERVER_API_KEY>` |
| Content-Type | `application/json` |
| 필드명 | camelCase (Spring Jackson 호환) |

---

### 4-1. 빠른 헬스체크

```
GET /api/health
```

```json
{
  "status": "ok",
  "service": "studybridge-fastapi",
  "openaiConfigured": true,
  "ollamaConfigured": true,
  "tavilyConfigured": false,
  "awsConfigured": true
}
```

---

### 4-2. 상세 헬스체크 (DB·pgvector·임베딩·Ollama)

```
GET /api/ai/health
```

```json
{
  "status": "degraded",
  "checks": {
    "database":               {"status": "fail",       "message": "AI_DATABASE_URL 연결 실패"},
    "pgvector":               {"status": "unknown",    "message": "DB 연결 실패로 확인 불가"},
    "documentChunksTable":    {"status": "unknown",    "message": "DB 연결 실패로 확인 불가"},
    "trainingCandidateTable": {"status": "unknown",    "message": "DB 연결 실패로 확인 불가"},
    "embeddingModel":         {"status": "ok",         "message": "임베딩 모델 로드됨"},
    "ollama":                 {"status": "ok",         "message": "Ollama 응답 정상"},
    "openai":                 {"status": "configured", "message": "API 키 설정됨"}
  }
}
```

**status:** `ok` | `degraded` | `unhealthy`

---

### 4-3. AI 채팅

```
POST /api/ai/chat
```

**Request:**
```json
{
  "question": "스프링이 뭐야?",
  "agent_name": "자바도우미",
  "material_id": null,
  "knowledge_level": "학사",
  "personality": "친절_설명형",
  "custom_instruction": null,
  "use_gpt_validation": true
}
```

**Response:**
```json
{
  "answer": "Spring은 ...",
  "validation_job_id": "uuid-...",
  "status": "pending_validation",
  "knowledge_level": "학사",
  "effective_knowledge_level": "학사",
  "personality": "친절_설명형",
  "intent": "learning_question",
  "process_logs": ["의도 분류: learning_question", "Qwen 1차 답변 생성"]
}
```

**effective_knowledge_level 규칙:**
- `learning_question` → 사용자 선택 지식수준 그대로
- `casual_greeting` → `일상대화` (인사/감사/잡담)

---

### 4-4. AI 채팅 SSE ⚠️ [OPTIONAL / LEGACY]

> 캡스톤 시연에서 필수 아님. REST `/api/ai/chat` 우선.

```
GET /api/ai/chat/stream?question=...&knowledgeLevel=학사&personality=친절_설명형
```

이벤트 순서: `start → retrieving_context → generating_answer → verifying_answer → complete → error`

---

### 4-5. 멀티에이전트 모드 기반 답변 (v0.7)

**지원 mode:** `default` | `tikitaka` | `debate` | `socratic`

**Request 공통 필드:**
```json
{
  "message": "스프링에서 IoC가 뭐야?",
  "mode": "debate",
  "agents": [
    {"agentId": 1, "name": "찬성봇", "role": "supporter", "knowledgeLevel": "학사"},
    {"agentId": 2, "name": "반대봇", "role": "critic",    "knowledgeLevel": "학사"},
    {"agentId": 3, "name": "사회자봇","role": "moderator", "knowledgeLevel": "학사"}
  ],
  "materialId": 10,
  "userAttempt": "사용자 시도 답변 (socratic 모드에서 오개념 분석에 사용)",
  "knowledgeLevel": "학사",
  "enableFeedback": false,
  "enableFeedbackValidation": true
}
```

**Response 공통 구조:**
```json
{
  "mode": "debate",
  "status": "COMPLETED",
  "question": "스프링에서 IoC가 뭐야?",
  "answers": [
    {
      "agentName": "찬성봇",
      "answer": "...",
      "agentId": 1,
      "role": "supporter",
      "speechType": "support_argument",
      "displayOrder": 1,
      "displayDelayMs": 0,
      "status": "SUCCESS",
      "metadata": {"knowledgeLevel": "학사", "usedRag": true}
    },
    {
      "agentName": "반대봇",
      "answer": "...",
      "role": "critic",
      "speechType": "counter_argument",
      "displayOrder": 2,
      "displayDelayMs": 700
    },
    {
      "agentName": "사회자봇",
      "answer": "...당신은 어떻게 생각하나요?",
      "role": "moderator",
      "speechType": "moderation_summary",
      "displayOrder": 3,
      "displayDelayMs": 1400
    }
  ],
  "validation": {"passed": true, "issues": []}
}
```

**socratic 모드 출력 예시:**
```json
{
  "mode": "socratic",
  "answers": [
    {
      "agentName": "소크라테스 튜터",
      "role": "socratic_tutor",
      "speechType": "follow_up_question",
      "answer": "좋아요. 다만 '멈춘다'는 결과만 말하면 핵심 조건이 빠질 수 있어요. 자원을 놓지 않은 채 서로 기다리는 상황과 단순 정지는 어떻게 다를까요?",
      "metadata": {"usedRag": true, "detectedMisconception": true, "directAnswerSuppressed": true}
    }
  ],
  "validation": {"passed": true, "directAnswerBlocked": true}
}
```

**status enum:** `COMPLETED` | `PARTIAL_SUCCESS` | `FAILED`
**answer status:** `SUCCESS` | `FAILED` | `TIMEOUT` | `BLOCKED` | `REWRITTEN` | `SKIPPED`

---

### 4-6. 멀티에이전트 비동기 답변 [jobId 방식, Spring @Async]

**Step 1 — job 생성 (즉시 반환)**
```
POST /api/study/ai/multi-chat/jobs        (Spring endpoint)
POST /api/ai/multi-chat/async             (FastAPI endpoint, Spring이 내부 호출)
```

**Request:**
```json
{
  "roomId": 1,
  "question": "스프링에서 IoC가 뭐야?",
  "materialId": 10,
  "agents": [
    {"agentId": 1, "name": "교수형", "personality": "논리적_탐구형", "knowledgeLevel": "박사"},
    {"agentId": 2, "name": "비판형", "personality": "비판적_분析형", "knowledgeLevel": "학사"},
    {"agentId": 3, "name": "입문형", "personality": "친절_설명형",  "knowledgeLevel": "입문"}
  ],
  "delayBetweenDisplayMs": 700,
  "timeoutSecondsPerAgent": 45,
  "enableFeedback": false,
  "enableFeedbackValidation": true,
  "shareRagContext": true
}
```

**Job 생성 Response:**
```json
{
  "jobId": "multi-agent-1748923456789-a1b2c3d4",
  "status": "PENDING",
  "message": "3명의 AI 에이전트가 답변을 생성 중입니다."
}
```

**Step 2 — 상태 조회**
```
GET /api/study/ai/multi-chat/jobs/{jobId}
```
```json
{"jobId": "...", "status": "RUNNING", "message": "3명의 AI 에이전트가 답변을 생성 중입니다."}
```

**Step 3 — 결과 조회**
```
GET /api/study/ai/multi-chat/jobs/{jobId}/result
```
```json
{
  "jobId": "...",
  "status": "COMPLETED",
  "result": {
    "answers": [
      {
        "agentId": 1, "agentName": "교수형", "status": "SUCCESS",
        "displayOrder": 1, "displayDelayMs": 0,
        "answer": "...",
        "metadata": {"knowledgeLevel": "박사", "personality": "논리적_탐구형", "usedRag": true, "latencyMs": 12400}
      }
    ],
    "validation": {"passed": true, "blockedFeedbackCount": 0, "rewrittenFeedbackCount": 0}
  }
}
```

**job status:** `PENDING` | `RUNNING` | `COMPLETED` | `PARTIAL_SUCCESS` | `FAILED` | `TIMEOUT`

---

### 4-6. 학습 시간 예측

```
POST /api/ai/predict/study-time
```

**Request:**
```json
{"userId": 42, "weeklyStudySeconds": [3600, 4200, 3000, 5400, 2700, 3900, 4500]}
```

**Response:**
```json
{"predictedStudySeconds": 4158.0, "method": "weighted_average_fallback", "confidence": 0.67}
```

**method:** `weighted_average_fallback` (기본) | `transformer` (모델 학습 후)  
**confidence:** 0.55 미만=낮음, 0.55~0.74=보통, 0.75+=높음

---

### 4-7. 퀴즈 생성

```
POST /api/ai/quiz/generate
```

**Request:**
```json
{
  "materialId": 123,
  "s3Key": "materials/123/lecture.pdf",
  "fileName": "lecture.pdf",
  "difficulty": "어려움",
  "knowledgeLevel": "석사",
  "numQuestions": 5,
  "questionType": "객관식"
}
```

**difficulty:** `쉬움` | `보통` | `어려움` (또는 `easy`/`normal`/`hard`)  
**questionType:** `객관식` | `주관식` | `혼합`

**Response:**
```json
{
  "quizTitle": "[lecture.pdf] 자료 기반 학습 퀴즈",
  "questions": [
    {"question": "...", "options": ["A", "B", "C", "D"], "correctAnswer": 2, "timeLimitSeconds": 30}
  ],
  "difficulty": "hard",
  "knowledgeLevel": "석사"
}
```

**Fallback:** S3/LLM 실패 시 기본 퀴즈 반환 (500 아님, 200 + fallback)

---

### 4-8. RAG Ingest

```
POST /api/rag/ingest
```

**Request:**
```json
{"material_id": 123, "document_title": "운영체제 강의자료", "text": "PDF 전체 텍스트..."}
```

**Response:**
```json
{"material_id": 123, "document_title": "운영체제 강의자료", "chunk_count": 15, "status": "success"}
```

---

### 4-9. RAG Query

```
POST /api/rag/query
```

**Request:**
```json
{"material_id": 123, "question": "프로세스와 스레드의 차이는?", "top_k": 5}
```

**Response:**
```json
{
  "material_id": 123,
  "question": "프로세스와 스레드의 차이는?",
  "chunks": [{"chunk_id": 1, "content": "...", "similarity": 0.892}]
}
```

---

### 4-10. RAG 삭제

```
DELETE /api/rag/materials/{material_id}
```

---

### 4-11. Deep Search

```
POST /api/agent/deep-search
```

**Request:**
```json
{"question": "Java GC란?", "material_id": null}
```

---

### 4-12. 파인튜닝 상태

```
GET  /api/ai/training/status
POST /api/ai/training/readiness-check
POST /api/ai/training/validate-candidates
POST /api/ai/training/export-jsonl
```

```json
{
  "current_status": "not_ready",
  "base_model": "Qwen2.5-14B",
  "training_method": "QLoRA",
  "readiness_check": {"pipeline_scripts": true, "training_data_sufficient": false, "minimum_samples_required": 300}
}
```

---

### 허용값

| 지식수준 | 설명 |
|---------|------|
| `입문` | 비유 중심, 전문용어 최소 |
| `학사` | 개념 정의 + 작동 원리 |
| `석사` | 구조적 설명 + 트레이드오프 |
| `박사` | 이론 근거 + 엣지 케이스 |
| `전문가` | 실서비스 운영, 병목/장애/비용 |

| 성격 | 설명 |
|------|------|
| `친절_설명형` | 따뜻하고 친근, 격려, 단계별 설명 |
| `비판적_분析형` | 츤데레 코치형, 허점 지적 후 개선 방향 |
| `논리적_탐구형` | 원인→구조→결과, 논리 접속사 |
| `창의적_확장형` | 새로운 비유, 다른 분야 연결 |
| `간결_요약형` | 핵심 압축, 목록, 한 줄 결론 |
| `직접_입력` | custom_instruction 우선 |

---

## 5. Spring 연동

### AiServerClient 메서드

| 메서드 | FastAPI 호출 | 설명 |
|--------|------------|------|
| `askChat(request)` | `POST /api/ai/chat` | 동기 AI 채팅 |
| `askMultiChatAsync(request)` | `POST /api/ai/multi-chat/async` | 비동기 3명 병렬 |
| `checkAiHealth()` | `GET /api/ai/health` | AI 서버 상태 |
| `predictStudyTime(request)` | `POST /api/ai/predict/study-time` | 학습 시간 예측 |
| `ingestMaterialText(...)` | `POST /api/rag/ingest` | RAG ingest |
| `deleteMaterialChunks(id)` | `DELETE /api/rag/materials/{id}` | RAG 삭제 |
| `askDeepSearch(...)` | `POST /api/agent/deep-search` | Deep Search |

### Spring application.yml

```yaml
ai:
  server:
    base-url: http://localhost:8000
    api-key: studybridge-internal-secret
    connect-timeout-ms: 5000
    read-timeout-ms: 60000
```

### Spring 신규 파일 목록 (`spring-integration/`)

| 파일 | 역할 |
|------|------|
| `client/AiServerClient.java` | FastAPI HTTP 클라이언트 (RestTemplate) |
| `config/AiServerProperties.java` | `ai.server.*` 설정 바인딩 |
| `controller/MultiAgentJobController.java` | `POST/GET /api/study/ai/multi-chat/jobs` |
| `service/MultiAgentJobService.java` | jobId in-memory job 관리 (`@Async`) |
| `dto/MultiAgentAsyncRequest.java` | 멀티에이전트 요청 DTO |
| `dto/MultiAgentAsyncResponse.java` | 멀티에이전트 응답 DTO |
| `dto/AiChatRequest.java` / `AiChatResponse.java` | AI 채팅 DTO |
| `dto/StudyTimePredictRequest.java` / `Response.java` | 학습시간 예측 DTO |
| `controller/AiChatSseController.java` | SSE 컨트롤러 (OPTIONAL/LEGACY) |

### 실제 Spring Boot 프로젝트에 적용할 때

1. `spring-integration/` 파일을 실제 Spring 패키지에 복사
2. `@SpringBootApplication` 클래스 또는 Config 클래스에 `@EnableAsync` 추가
3. `application.yml`에 `ai.server.*` 설정 추가
4. `MultiAgentJobService`가 `@Async`를 사용하므로 AsyncConfig 확인

### Fallback 정책

- FastAPI 연결 실패 → null 반환, Spring에서 사용자 친화적 메시지 표시
- AI 서버 타임아웃 → "AI 서비스 일시 불가" 메시지
- RAG DB 없음 → degraded 상태, 일반 지식 기반 답변

### HTTP 상태 코드

| 상황 | 코드 |
|------|------|
| 정상 | 200 |
| 입력 검증 실패 | 422 |
| 서버 내부 오류 | 500 |
| 인증 실패 | 401 |

---

## 6. DB / pgvector / Redis

### pgvector 스키마

```
studybridge_ai (포트 5433)
├── ai.*          — 대화/검증/학습후보 테이블
└── rag.*         — PDF 청크 + 임베딩 테이블
```

> **주의:** capstone-db(포트 5432, Spring 전용)에 절대 적용하지 않는다.

### ai.document_chunks 테이블

```sql
CREATE TABLE ai.document_chunks (
    id              BIGSERIAL    PRIMARY KEY,
    material_id     BIGINT       NOT NULL,
    document_title  TEXT,
    chunk_index     INTEGER      NOT NULL,
    content         TEXT         NOT NULL,
    content_hash    VARCHAR(64)  NOT NULL,
    token_count     INTEGER,
    embedding       VECTOR(768)  NOT NULL,   -- multilingual-e5-base
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (material_id, chunk_index)
);
```

### 유사도 검색 SQL

```sql
SELECT id, material_id, document_title, chunk_index, content,
       1 - (embedding <=> $1::vector) AS similarity
FROM ai.document_chunks
WHERE material_id = $2
  AND 1 - (embedding <=> $1::vector) >= 0.30
ORDER BY embedding <=> $1::vector
LIMIT 5;
```

### HNSW 인덱스

```sql
CREATE INDEX idx_document_chunks_embedding_hnsw
    ON ai.document_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

### 임베딩 모델

| 모델 | 차원 |
|------|------|
| `intfloat/multilingual-e5-base` | **768** (현재 사용) |
| OpenAI text-embedding-3-small | 1536 (미사용) |

### 마이그레이션 파일 순서

| 파일 | 내용 |
|------|------|
| 001_create_ai_schema.sql | ai 스키마 + 대화/검증/학습후보 테이블 |
| 002_create_rag_pgvector_schema.sql | pgvector extension + ai.document_chunks |
| 003_create_indexes.sql | 일반 인덱스 + HNSW 벡터 인덱스 |

마이그레이션 안전장치: URL에 `capstone`, `localhost:5432`, `db:5432` 중 하나라도 있으면 차단.

### Redis 키 구조

| 키 패턴 | 용도 | TTL |
|---------|------|-----|
| `validation:{job_id}` | GPT 검증 작업 상태 | 1시간 |
| `ai_cache:{agent_id}:{level}:{hash}` | AI 답변 캐시 | 10분 |
| `tavily_cache:{query_hash}` | Tavily 검색 캐시 | 10분 |
| `wiki_cache:{query_hash}` | Wikipedia 캐시 | 30분 |
| `rate_limit:ai:{user_id}` | 요청 rate limit | 1분 |

Redis 연결 실패 시 → in-memory fallback (서버 죽지 않음)

### Docker Compose Redis 설정

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
```

---

## 7. 학습 데이터 파이프라인

### 현재 상태: NOT_READY

| 항목 | 현재 | 필요 |
|------|------|------|
| reviewed/approved 샘플 | ~52개 | 300개+ |
| QLoRA 본학습 | 미진행 | 데이터 충족 후 |
| Transformer 예측 | 미학습 | 별도 |

### QLoRA 6단계 파이프라인 실행 순서

```bash
# 1. Markdown 검수 리포트 → JSONL 반영
python app/scripts/apply_human_review_report.py \
  --input-jsonl app/dataset/review/ai_reviewed_candidates.jsonl \
  --review-reports app/dataset/reports/human_review_report.md \
  --output-jsonl app/dataset/review/human_review_applied_dataset.jsonl

# 2. review_notes 정리
python app/scripts/clean_review_notes.py \
  --input app/dataset/review/human_review_applied_dataset.jsonl \
  --output app/dataset/review/cleaned_human_reviewed_dataset.jsonl

# 3. 에이전트 레벨 정규화
python app/scripts/normalize_agent_levels.py \
  --input app/dataset/review/cleaned_human_reviewed_dataset.jsonl \
  --output app/dataset/review/normalized_dataset.jsonl

# 4. 학습 후보 필터링
python app/scripts/filter_training_candidates.py

# 5. 더미 데이터 생성 (300개)
python app/scripts/generate_dummy_dataset.py

# 6. messages 형식 변환 + 병합
python app/scripts/convert_jsonl_to_messages.py

# 7. 최종 정리 (중복 제거, 민감정보 필터)
python app/scripts/clean_train_jsonl.py

# 8. 검증
python app/dataset/final/validate_clean_jsonl.py

# 9. QLoRA 준비도 점검
python app/scripts/check_qlora_readiness.py
```

### 자동 재학습 파이프라인

```bash
# dry-run (dataset까지만)
python scripts/run_auto_retrain.py --dry-run

# 실행 (auto_retrain_config.json 설정 따름)
python scripts/run_auto_retrain.py --yes

# 강제 학습 (GPU 필요)
python scripts/run_auto_retrain.py --force-train --yes
```

**기본값: autoTrain=false, autoDeploy=false** (명시적으로 켜야 동작)

### 학습 데이터 파이프라인 8단계 (auto_retrain_runner.py)

1. DB 후보 수집
2. 안전성/품질 검증 (PII/보안키 감지 시 즉시 중단)
3. Dataset version 생성 (중복제거 + train/valid/test 분리 + manifest)
4. Readiness gate 통과 확인
5. QLoRA 학습 (`autoTrain=true` + GPU 있을 때만)
6. 신구 모델 비교 평가
7. 모델 레지스트리 등록
8. `autoDeploy=true`일 때만 production 승격

### Dataset 제약

- train 최대 5,000 / valid 500 / test 500
- 일상대화 최대 5%
- 성격별 편향 40% 이내
- JSONL 포맷: `{"messages":[{"role":"system",...},{"role":"user",...},{"role":"assistant",...}]}`

---

## 8. 배포 & 시연 체크리스트

### 서버 기동 확인

- [ ] FastAPI `uvicorn app.main:app` 정상 기동
- [ ] `GET /api/health` → `{"status": "ok"}` 확인
- [ ] `GET /api/ai/health` → 각 컴포넌트 상태 확인
- [ ] pgvector DB 연결 상태 확인

### 환경변수 확인

- [ ] `VECTOR_DATABASE_URL` 또는 `AI_DATABASE_URL` 설정
- [ ] `OPENAI_API_KEY` (미설정 시 GPT 비활성)
- [ ] `OLLAMA_BASE_URL` 또는 `QWEN_BASE_URL`
- [ ] `AI_SERVER_API_KEY` (Spring 연동 인증)

### 기능별 확인

- [ ] 입문/박사 수준 채팅 → 깊이 차이 확인
- [ ] 친절형/비판형 성격 → 말투 차이 확인
- [ ] 티키타카 → 3개 에이전트 + 정리 출력 확인
- [ ] RAG ingest → 청크 수 확인
- [ ] PDF Q&A → PDF 근거 기반 답변 확인
- [ ] 퀴즈 생성 → 5개 문제 + 정답 확인
- [ ] 학습시간 예측 → method/confidence 포함 확인
- [ ] 비동기 멀티에이전트 → jobId → result 흐름 확인

### AWS 배포 순서

```bash
# EC2 SSH 접속 후
cd ~/capstoneLLM

# 1. 코드 동기화
git pull

# 2. 의존성 설치
pip install -r fastapi/requirements.txt

# 3. .env 설정
nano fastapi/.env

# 4. Ollama/vLLM 백그라운드 기동
nohup ollama serve &

# 5. FastAPI 백그라운드 기동
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 \
  > /var/log/fastapi.log 2>&1 &

# 6. 외부 접속 확인
curl http://{EC2_PUBLIC_IP}:8000/api/health
```

### 장애 대응

| 상황 | 대응 |
|------|------|
| Ollama 다운 | OpenAI fallback 자동 적용 |
| OpenAI API 오류 | Ollama fallback |
| pgvector 연결 실패 | RAG 없이 일반 답변 (경고 포함) |
| LLM 퀴즈 생성 실패 | fallback 퀴즈 반환 (서버 오류 없음) |
| 예측 API 타임아웃 | 가중평균 fallback 자동 적용 |
| AI 서버 전체 다운 | Spring이 null 반환, "AI 서비스 일시 불가" 표시 |
| 비동기 job 실패 | FAILED 상태 반환, 프론트 재시도 유도 |

---

## 9. 완료 현황

### v0.7 신규 (2026-06-07)

- [x] **하드코딩 최소화** — `agent_modes.yaml`, `feedback_policy.yaml`, `validation_policy.yaml`, `prompt_templates/*.md` 분리
- [x] **`policy_loader.py`** — YAML 로더, 파일 없으면 기본값 자동 사용, 서버 죽지 않음
- [x] **tikitaka 검증 버그 수정**
  - `all()` over empty iterator → `bool(items) and all(...)` 패턴
  - `content_has_all_agents` 오탐 → blend_markers + 3명 이름 동시 등장으로 좁힘
  - 연산자 우선순위 괄호 명시
  - critique 키워드에서 "하지만"/"반면" 단독 통과 제거
- [x] **mode 분기** — `default | tikitaka | debate | socratic` 완전 분기
- [x] **debate 모드** — supporter→critic→moderator 순차 체인, 비방 자동 검증+재작성
- [x] **socratic 모드** — 정답 직접 제공 차단, 꼬리질문 1개, 최대 1회 재작성
- [x] **`mode_validator.py`** — `validate_tikitaka_messages`, `validate_debate_answers`, `validate_socratic_answer`
- [x] **`AgentAnswer` 확장** — `role`, `speechType`, `displayOrder`, `displayDelayMs`, `status`, `metadata` 추가 (하위 호환)
- [x] **`MultiChatRequest` 확장** — `mode`, `materialId`, `userAttempt`, `knowledgeLevel`, `enableFeedback` 추가
- [x] **`MultiChatResponse` 확장** — `status`, `question`, `validation`, `feedbacks` 추가
- [x] **inter_agent_feedback_validator** — YAML 정책 참조 (키워드·임계값 코드에서 제거)
- [x] **constructive_feedback_rewriter** — YAML fallback 문구 참조
- [x] **policy_loader 워밍업** — `app/main.py` lifespan에서 시작 시 로드

### v0.6 신규 (2026-06-05)

- [x] `POST /api/ai/multi-chat/async` — 비동기 3명 병렬 답변 (asyncio.gather)
- [x] RAG context 공유 (한 번 검색 후 3명에게 공통 주입)
- [x] 에이전트별 개별 timeout + PARTIAL_SUCCESS 허용
- [x] `inter_agent_feedback_validator.py` — 독성/인신공격/건설성 점수화
- [x] `constructive_feedback_rewriter.py` — Qwen 재작성 + safe fallback
- [x] Spring `MultiAgentJobService` — jobId in-memory job 관리
- [x] Spring `MultiAgentJobController` — `POST/GET /api/study/ai/multi-chat/jobs`
- [x] Spring `AiServerClient.askMultiChatAsync()` 메서드
- [x] `/api/ai/health` 응답 구조화 + `trainingCandidateTable` 체크 추가
- [x] `scripts/check_ai_db_connection.py` — DB 점검 CLI
- [x] `AiChatSseController.java` optional/legacy 명확화

### 기존 완료 항목

- [x] FastAPI 서버 import 오류 없이 기동
- [x] `GET /api/health`, `GET /api/ai/health`
- [x] 메시지 의도 분류 (학습질문 vs 일상대화)
- [x] effective_knowledge_level 분리
- [x] 퀴즈 생성 (difficulty/knowledgeLevel/numQuestions/questionType)
- [x] 학습 시간 예측 (method/confidence)
- [x] RAG ingest/query/delete (pgvector, multilingual-e5-base, vector(768))
- [x] tiki-taka multi-agent
- [x] gpt_verifier (background)
- [x] personality prompt builder (6종)
- [x] knowledge level controller (5단계)
- [x] Spring DTOs: AiChatRequest/Response, StudyTimePredictRequest/Response
- [x] 자동 QLoRA 재학습 파이프라인 (8단계, 기본 비활성화)
- [x] Dataset version 관리 (sft_v001, sft_v002...)
- [x] model_registry, model_evaluator, model_rollback_manager

### 부분 구현 (제한 있음)

- [ ] Spring 실제 프로젝트 적용 — `spring-integration/` 파일 복사 + `@EnableAsync` 필요
- [ ] Job in-memory store → Redis/DB 교체 (재시작 시 job 유실, 시연은 허용)
- [ ] RAG ingest/query 실제 DB 연결 테스트 — DB 실행 환경 필요
- [ ] Ollama 실제 응답 테스트 — Ollama 서버 실행 환경 필요
- [ ] 퀴즈 생성 S3 연동 — AWS S3 설정 필요
- [ ] 피드백 검증 E2E 테스트 — Qwen 실행 환경 필요

### 의도적 미완성

- [ ] QLoRA 본학습 — 데이터 부족 (300개+ 필요, 현재 ~52개)
- [ ] Transformer 학습 시간 예측 — 모델 미학습 (`weighted_average_fallback` 사용)
- [ ] 실시간 토큰 단위 스트리밍 — 단계 이벤트 SSE로 대체

---

## 10. 캡스톤 발표 가이드

### 이렇게 말해도 됨 ✅

1. "현재 AI 서버는 **RAG(pgvector 유사도 검색)** 기반으로 PDF 자료에서 관련 내용을 검색하여 답변을 생성합니다."

2. "사용자가 선택한 **지식수준(입문/학사/석사/박사/전문가)** 에 따라 답변의 깊이와 어휘 수준이 달라집니다."

3. "**성격(친절/비판/논리/창의/간결)** 을 선택하면 같은 질문에 대해 다른 스타일로 답변합니다."

4. "**3명의 AI 에이전트**가 병렬로 각자의 성격과 지식수준에 맞는 답변을 동시에 생성하며, 에이전트 간 피드백은 건설적인 비판만 허용합니다."

5. "**학습 시간 예측**은 최근 7일 학습 패턴의 가중평균 기반 예측을 사용합니다."

6. "Spring Boot와 FastAPI는 내부 API 키를 통해 안전하게 연동됩니다."

7. "AI 서버는 한 가지 기능이 실패해도 다른 기능에 영향을 주지 않도록 격리 설계되어 있습니다."

### 절대 과장하면 안 됨 ❌

| 금지 표현 | 대신 이렇게 |
|----------|-----------|
| "파인튜닝 완료" | "파이프라인 준비됨, 데이터 수집 완료 후 진행 예정" |
| "Transformer로 예측합니다" | "가중평균 기반 예측, Transformer 구조 준비됨" |
| "실시간 스트리밍 답변" | "단계 이벤트 방식 SSE (토큰 단위 아님)" |
| "GPT-4로 모든 답변" | "Qwen 1차 답변, GPT-4o-mini로 품질 검증" |
| "100% 정확한 답변" | "PDF 자료 기반, 자료에 없는 내용은 추정임을 명시" |

### 예상 Q&A

**Q: 파인튜닝은 언제?**  
A: "현재는 RAG 중심으로 운영 중입니다. 300개 이상 고품질 데이터 수집 완료 후 QLoRA 방식으로 진행할 수 있도록 파이프라인을 준비해 두었습니다."

**Q: Transformer 모델이 실제 예측에 사용됩니까?**  
A: "현재는 최근 7일 학습 패턴의 가중평균 기반 예측을 사용합니다. Transformer 기반 예측을 위한 코드 구조는 준비되어 있으며, 데이터가 충분히 수집되면 학습하여 교체할 수 있습니다."

**Q: Qwen을 쓰는 이유?**  
A: "Ollama로 로컬 실행하여 API 비용 없이 빠른 1차 응답 생성이 가능합니다. GPT는 검증과 안정성 요구 기능에만 선별 사용합니다."

**Q: 3명 에이전트가 동시에 답한다는 게 어떻게?**  
A: "FastAPI 내부에서 asyncio.gather()로 3명을 병렬 실행합니다. 한 명이 실패해도 나머지 답변은 정상 반환됩니다."

**Q: 토론 모드와 소크라테스 모드는 어떻게 다른가요?**  
A: "토론 모드는 찬성봇→반대봇→사회자봇 순서로 학습 주제를 여러 관점에서 논의합니다. 소크라테스 모드는 AI가 정답을 주지 않고, 학생이 스스로 생각할 수 있도록 꼬리질문으로 유도합니다."

**Q: 에이전트 간 비방은 어떻게 방지하나요?**  
A: "모든 에이전트 간 피드백은 독성/인신공격/조롱 점수를 계산하여 기준 초과 시 Qwen으로 건설적 표현으로 재작성하고, 재작성 후에도 기준을 못 넘으면 safe fallback 문구로 대체됩니다."

**Q: 프롬프트를 바꾸려면 코드를 수정해야 하나요?**  
A: "아닙니다. `fastapi/app/core/prompt_templates/*.md` 파일만 수정하면 됩니다. 검증 키워드나 임계값도 `validation_policy.yaml`, `feedback_policy.yaml`만 수정하면 코드 변경 없이 반영됩니다."

