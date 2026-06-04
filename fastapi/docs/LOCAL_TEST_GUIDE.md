# 로컬 테스트 가이드

## 1. 환경 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집 (필요한 항목만 채워도 됨)
# OPENAI_API_KEY, OLLAMA_BASE_URL 등
```

## 2. 의존성 설치

```bash
cd fastapi
pip install -r requirements.txt
```

## 3. 서버 실행

```bash
# fastapi 폴더에서 실행
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

서버 기동 확인:
```bash
curl http://localhost:8000/health
```

---

## 4. API 테스트 (curl)

### Health Check
```bash
curl -X GET http://localhost:8000/api/health
```

예상 응답:
```json
{
  "status": "ok",
  "service": "studybridge-fastapi",
  "openaiConfigured": false,
  "ollamaConfigured": false,
  "tavilyConfigured": false,
  "awsConfigured": false
}
```

---

### 학습 시간 예측

```bash
curl -X POST http://localhost:8000/api/ai/predict/study-time \
  -H "Content-Type: application/json" \
  -d '{
    "userId": 42,
    "weeklyStudySeconds": [3600, 7200, 5400, 0, 1800, 9000, 4500]
  }'
```

예상 응답:
```json
{
  "predictedStudySeconds": 4950.0
}
```

오류 테스트 (6개 입력):
```bash
curl -X POST http://localhost:8000/api/ai/predict/study-time \
  -H "Content-Type: application/json" \
  -d '{"userId": 1, "weeklyStudySeconds": [3600, 7200, 5400, 0, 1800, 9000]}'
```

예상: 422 에러

---

### 퀴즈 생성 (S3 없이 테스트)

S3가 없는 경우 fallback quiz가 반환된다.

```bash
curl -X POST http://localhost:8000/api/ai/quiz/generate \
  -H "Content-Type: application/json" \
  -d '{
    "materialId": 12,
    "s3Key": "materials/user_42/test.pdf",
    "fileName": "운영체제_요약본.pdf"
  }'
```

예상: AWS 미설정 → fallback quiz 반환 (200 OK, 명세 구조 유지)

---

### 멀티 에이전트 채팅 (Ollama 없이 테스트)

Ollama와 OpenAI가 없는 경우 기본 안내 답변이 반환된다.

```bash
curl -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "인공지능 RAG 아키텍처에 대해 설명해줘",
    "mode": "multi_agent_discussion",
    "rounds": 2,
    "showFinalSynthesis": false,
    "targetAgentId": null,
    "previousAnswers": [],
    "agents": [
      {
        "id": 1,
        "agentId": 1,
        "name": "SummaryAgent",
        "role": "요약봇",
        "personality": "간결_요약형",
        "knowledgeLevel": "학사"
      }
    ]
  }'
```

targetAgentId 지정 테스트:
```bash
curl -X POST http://localhost:8000/api/ai/multi-chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "딥러닝이란?",
    "targetAgentId": 1,
    "agents": [
      {"id": 1, "agentId": 1, "name": "설명봇", "personality": "친절_설명형"},
      {"id": 2, "agentId": 2, "name": "분析봇", "personality": "비판적_분析형"}
    ]
  }'
```

예상: answers 배열에 "설명봇"만 포함

---

## 5. Ollama 없이 테스트하는 방법

Ollama가 없어도 서버는 정상 기동한다.
- `/api/ai/multi-chat`: OpenAI fallback → 기본 안내 답변 반환
- `/api/ai/quiz/generate`: OpenAI fallback → 기본 fallback quiz 반환

OPENAI_API_KEY만 설정해도 OpenAI로 동작한다.

---

## 6. S3 없이 테스트하는 방법

AWS 환경변수를 설정하지 않으면:
- `/api/ai/quiz/generate`: S3 접근 실패 → fallback quiz 반환 (200 OK)

fallback quiz도 명세 응답 구조(`quizTitle`, `questions`, `correctAnswer` 등)를 유지한다.

---

## 7. 자동화 테스트 실행

```bash
cd fastapi
pip install pytest httpx
pytest tests/ -v
```

외부 의존성(DB, S3, LLM) 없이 실행 가능한 테스트:
- `test_prediction_api.py` — 학습 시간 예측 (TF 모델 없이)
- `test_quiz_api.py` — 퀴즈 생성 (S3/LLM 없이 fallback 검증)
- `test_multi_chat_api.py` — 멀티 에이전트 (LLM 없이 응답 구조 검증)

---

## 8. Swagger UI 확인

서버 실행 후 브라우저에서:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

Spring Boot 계약 API는 "Study Time Prediction", "Quiz Generation", "Multi Agent Chat" 태그 아래에 있다.

---

## 9. 환경변수 우선순위

1. `.env` 파일 (로컬 개발)
2. 시스템 환경변수 (Docker, CI/CD)
3. 코드 기본값

`.env`는 Git에 커밋하지 않는다. `.env.example`만 커밋한다.
