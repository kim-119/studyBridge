# 배포 체크리스트 — 목요일 AWS 시연

> 목요일은 개발 없이 배포 + 시연만. 수요일 밤까지 이 목록 완료.

---

## Phase 1: 로컬 검증 (수요일 낮)

### 서비스 기동 순서
```bash
# 1. PostgreSQL + pgvector
sudo systemctl start postgresql
psql -c "CREATE EXTENSION IF NOT EXISTS vector;" studybridge_ai

# 2. Qwen2.5 vLLM 서버
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-14B-Instruct \
  --host 0.0.0.0 --port 8001 \
  --api-key EMPTY

# 3. FastAPI
cd /home/ai07/capstoneLLM/fastapi
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 4. Spring Boot
./mvnw spring-boot:run
```

### 환경변수 확인
```bash
# fastapi/.env 확인
cat fastapi/.env
# 반드시 있어야 할 항목:
# OPENAI_API_KEY=sk-...
# TAVILY_API_KEY=tvly-...
# QWEN_BASE_URL=http://localhost:8001/v1
# VECTOR_DATABASE_URL=postgresql://...
# AI_SERVER_API_KEY=...
```

### 로컬 smoke test
```bash
# 헬스 체크
curl http://localhost:8000/health

# 에이전트 채팅 (Qwen 연결 확인)
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Authorization: Bearer {AI_SERVER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"question":"안녕","knowledge_level":"입문","personality":"친절_설명형","agent_name":"테스트","use_gpt_validation":false}'

# GPT 검증 확인
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Authorization: Bearer {AI_SERVER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"question":"트랜잭션이란?","knowledge_level":"학사","personality":"친절_설명형","use_gpt_validation":true}'
# → validation_job_id 확인 후 폴링

# 티키타카 확인
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Authorization: Bearer {AI_SERVER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"question":"데드락이란?","knowledge_level":"학사","personality":"비판적_분석형","enable_tiki_taka":true,"use_gpt_validation":false}'
```

---

## Phase 2: AWS 배포 (수요일 저녁)

### EC2 인스턴스 확인
- [ ] EC2 타입: GPU 지원 (Qwen vLLM용) — g4dn.xlarge 이상 권장
- [ ] 포트 8000 (FastAPI), 8080 (Spring Boot), 8001 (vLLM) 보안 그룹 열기
- [ ] EBS 볼륨 여유 공간 확인 (Qwen 모델 최소 30GB)

### 배포 스크립트
```bash
# SSH 접속 후
cd ~/capstoneLLM

# 1. 코드 동기화
git pull  # 또는 scp

# 2. 의존성 설치
pip install -r fastapi/requirements.txt

# 3. .env 파일 설정 (서버에서 직접 편집)
nano fastapi/.env

# 4. 서비스 기동 (순서 중요)
# 4a. PostgreSQL
# 4b. vLLM (백그라운드)
nohup python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-14B-Instruct \
  --host 0.0.0.0 --port 8001 &

# 4c. FastAPI (백그라운드)
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2 \
  > /var/log/fastapi.log 2>&1 &

# 5. Spring Boot
./mvnw spring-boot:run --spring-boot:run.jvmArguments="-Xmx2g"
```

### AWS 배포 후 확인
```bash
# FastAPI 헬스 (외부 접속)
curl http://{EC2_PUBLIC_IP}:8000/health

# Swagger 문서 접속
open http://{EC2_PUBLIC_IP}:8000/docs
```

---

## Phase 3: 시연 전 최종 점검 (목요일 아침)

### 기능별 체크
- [ ] `GET /health` → `{"status": "ok", "version": "0.4.0"}`
- [ ] 입문 수준 채팅 → 비유·쉬운 설명 확인
- [ ] 박사 수준 채팅 → 이론 깊이 확인
- [ ] 친절형/비판형 성격 차이 → 말투 차이 확인
- [ ] 티키타카 → 3개 에이전트 + 정리 출력 확인
- [ ] GPT 검증 → pending → completed 흐름 확인
- [ ] RAG ingest → 청크 수 확인
- [ ] PDF Q&A → PDF 근거 기반 답변 확인
- [ ] 퀴즈 생성 → 5개 문제 + 정답 확인
- [ ] 로드맵 생성 → 단계별 커리큘럼 확인

### 장애 대응 계획
| 문제 | 대응 |
|---|---|
| Qwen vLLM 다운 | 사전 캐시된 예시 답변 준비 |
| GPT API 한도 | use_gpt_validation=false로 우회 |
| pgvector 연결 실패 | 미리 수집한 RAG 결과 파일로 대체 시연 |
| 네트워크 불안정 | 로컬 서버(노트북)로 전환 |

---

## Phase 4: 시연 당일 (목요일)

### 시연 순서 (DEMO_SCENARIO.md 참고)
1. 아키텍처 소개 (1분)
2. 지식수준별 답변 차이 (2분)
3. 성격별 답변 차이 (2분)
4. 티키타카 대화 (3분)
5. PDF 자료보관함 분석 (2분)
6. 퀴즈/로드맵 (1분)
7. 검증 흐름 (1분)
8. 파인튜닝 현황 설명 (30초)

### 백업 화면
- Swagger UI (`/docs`) 캡처
- `cleaning_report.md` 화면 준비
- `AI_ARCHITECTURE_PLAN.md` 다이어그램 슬라이드 변환

---

## 긴급 롤백 계획

v0.3 (기존 deep-search)으로 롤백 시:
```bash
git stash  # 변경사항 임시 저장
# main.py에서 agent_chat_router import 제거
# version 0.3.0으로 되돌리기
uvicorn main:app --host 0.0.0.0 --port 8000
```

v0.4 신규 라우터 없이도 기존 `/api/agent/deep-search`와 `/api/rag/*`는 정상 동작.
