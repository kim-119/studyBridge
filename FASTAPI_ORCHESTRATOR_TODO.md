# FastAPI Orchestrator TODO — v0.4

> 목요일 AWS 배포 기준 체크리스트

---

## ✅ 완료된 항목

### 핵심 서비스
- [x] `qwen_service.py` — Qwen2.5 vLLM 클라이언트 (max_tokens 파라미터 추가)
- [x] `tavily_service.py` — Tavily 웹 검색
- [x] `wikipedia_service.py` — Wikipedia 검색
- [x] `pdf_rag_service.py` — pgvector RAG 검색
- [x] `embedding_service.py` — multilingual-e5-base 임베딩
- [x] `pgvector_service.py` — 벡터 DB CRUD
- [x] `rag_ingest_service.py` — PDF 청킹·임베딩·저장
- [x] `answer_orchestrator.py` — Deep Search 파이프라인

### v0.4 신규 서비스
- [x] `knowledge_level_controller.py` — 5단계 지식수준 프롬프트 생성
- [x] `personality_prompt_builder.py` — 6가지 성격 프롬프트 생성
- [x] `gpt_verifier.py` — GPT-4o-mini 비동기 답변 검증
- [x] `tiki_taka_manager.py` — 멀티 에이전트 티키타카 (최대 4발화+정리)
- [x] `agent_chat_manager.py` — 에이전트 채팅 오케스트레이터
- [x] `material_ai_manager.py` — 자료보관함 GPT70%+Qwen30% 처리

### 라우터
- [x] `deep_search_router.py` — POST /api/agent/deep-search
- [x] `rag_router.py` — POST /api/rag/ingest | /search | DELETE /{id}
- [x] `agent_chat_router.py` — POST /api/ai/chat + 검증 폴링 + 자료보관함 AI

### 스키마
- [x] `deep_search_schema.py`
- [x] `rag_schema.py`
- [x] `agent_chat_schema.py`

### 인프라
- [x] `main.py` — 모든 라우터 등록, v0.4 버전
- [x] `config.py` — GPT 모델명, 에이전트 기본값, 티키타카 설정 추가
- [x] `security.py` — Bearer 토큰 인증

---

## 🔲 배포 전 확인 필수

### 환경변수 (.env)
- [ ] `OPENAI_API_KEY` 설정 (GPT 검증, 자료보관함 AI)
- [ ] `TAVILY_API_KEY` 설정 (웹 검색)
- [ ] `QWEN_BASE_URL` 설정 (vLLM 서버 주소)
- [ ] `VECTOR_DATABASE_URL` 설정 (PostgreSQL pgvector)
- [ ] `AI_SERVER_API_KEY` 설정 (Spring ↔ FastAPI 인증)

### 인프라
- [ ] Qwen2.5 vLLM 서버 기동 확인 (`GET http://QWEN_BASE_URL/health`)
- [ ] PostgreSQL + pgvector 확장 활성화 (`CREATE EXTENSION vector`)
- [ ] ai.document_chunks 테이블 생성 확인
- [ ] AWS EC2 포트 8000 보안 그룹 열기 (FastAPI)
- [ ] uvicorn 서비스 등록 또는 docker-compose 설정

### 기능 연동
- [ ] Spring Boot가 `/api/ai/chat` 엔드포인트 호출 가능한지 확인
- [ ] Spring Boot가 `/api/ai/material/qa` 호출 가능한지 확인
- [ ] Spring Boot가 에이전트 프로필 (knowledge_level, personality, agent_name) 전달 가능한지 확인

---

## 🔲 시연 전 smoke test

```bash
# 1. 헬스 체크
curl http://localhost:8000/health

# 2. 에이전트 채팅 (기본)
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Authorization: Bearer {AI_SERVER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "트랜잭션이 뭐야?",
    "knowledge_level": "입문",
    "personality": "친절_설명형",
    "agent_name": "자바도우미",
    "enable_tiki_taka": false,
    "use_gpt_validation": true
  }'

# 3. 티키타카 테스트
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Authorization: Bearer {AI_SERVER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "데드락이란?",
    "knowledge_level": "학사",
    "personality": "비판적_분석형",
    "enable_tiki_taka": true,
    "use_gpt_validation": true
  }'

# 4. 검증 폴링 (job_id는 위 응답에서)
curl http://localhost:8000/api/ai/chat/validation/{job_id} \
  -H "Authorization: Bearer {AI_SERVER_API_KEY}"
```

---

## 🔲 선택적 개선 (시간 여유 시)

- [ ] 검증 job 만료 처리 (1시간 후 자동 삭제 — 현재 무제한 메모리)
- [ ] Tavily 결과를 에이전트 채팅 컨텍스트에도 연결
- [ ] 에이전트 채팅 히스토리 (대화 이어가기 구조)
- [ ] Streaming 응답 (SSE/WebSocket)
- [ ] Redis 기반 검증 job 저장소 교체

---

## ❌ 현재 범위 밖 (목요일 이후)

- QLoRA 본학습 (데이터 52개 → 300개 필요)
- 에이전트 간 실제 DB 연동 (현재 인메모리)
- React 실시간 티키타카 UI
- 다국어 지원
