# API 명세 - Spring 호환성 가이드

## 필드명 주의사항

**FastAPI 응답은 모두 camelCase를 사용한다. snake_case로 반환하면 Spring 파싱 오류.**

Spring Boot는 `@JsonProperty` 또는 기본 Jackson camelCase 매핑으로 파싱한다.
FastAPI Pydantic 모델은 camelCase 필드명을 직접 정의하여 일치시킨다.

---

## Endpoint별 Request/Response 예시

### GET /api/health

**Response**:
```json
{
  "status": "ok",
  "service": "studybridge-fastapi",
  "openaiConfigured": true,
  "ollamaConfigured": true,
  "tavilyConfigured": false,
  "awsConfigured": true,
  "version": "0.5.0",
  "dependencies": {
    "ai_db": {"status": "unavailable"},
    "redis": {"status": "unavailable"},
    "ollama": {"status": "ok", "model": "qwen2.5:7b"},
    "openai_key_set": true,
    "tavily_key_set": false,
    "ai_database_url_set": false,
    "redis_url_set": false
  }
}
```

Spring이 읽어야 할 필드: `status`, `openaiConfigured`, `ollamaConfigured`, `tavilyConfigured`, `awsConfigured`

---

### POST /api/ai/predict/study-time

**Request**:
```json
{
  "userId": 42,
  "weeklyStudySeconds": [3600, 7200, 5400, 0, 1800, 9000, 4500]
}
```

**Response (정상)**:
```json
{
  "predictedStudySeconds": 5800.5
}
```

**Response (400 오류 - 길이 오류)**:
```json
{
  "detail": "weeklyStudySeconds는 정확히 7개여야 합니다."
}
```

**필드명 주의**:
| Spring 기대 | FastAPI 반환 | 상태 |
|------------|-------------|------|
| `predictedStudySeconds` | `predictedStudySeconds` | ✅ 일치 |
| `userId` | `userId` | ✅ 일치 (request) |
| `weeklyStudySeconds` | `weeklyStudySeconds` | ✅ 일치 (request) |

---

### POST /api/ai/quiz/generate

**Request**:
```json
{
  "materialId": 12,
  "s3Key": "materials/user_42/bf42e2b9-7a54-46ab-a279-d102ba2ce501.pdf",
  "fileName": "중간고사_운영체제_요약본.pdf"
}
```

**Response (정상 또는 fallback)**:
```json
{
  "quizTitle": "[중간고사_운영체제_요약본.pdf] 자료 기반 학습 퀴즈",
  "questions": [
    {
      "question": "데드락(Deadlock)이 발생하기 위한 4가지 필요조건이 아닌 것은?",
      "options": [
        "상호 배제 (Mutual Exclusion)",
        "점유와 대기 (Hold and Wait)",
        "선점 (Preemption)",
        "순환 대기 (Circular Wait)"
      ],
      "correctAnswer": 2,
      "timeLimitSeconds": 30
    }
  ]
}
```

**필드명 주의**:
| Spring 기대 | FastAPI 반환 | 상태 |
|------------|-------------|------|
| `quizTitle` | `quizTitle` | ✅ 일치 |
| `questions` | `questions` | ✅ 일치 |
| `question` | `question` | ✅ 일치 |
| `options` | `options` | ✅ 일치 |
| `correctAnswer` | `correctAnswer` | ✅ 일치 |
| `timeLimitSeconds` | `timeLimitSeconds` | ✅ 일치 |
| `materialId` | `materialId` | ✅ 일치 (request) |
| `s3Key` | `s3Key` | ✅ 일치 (request) |
| `fileName` | `fileName` | ✅ 일치 (request) |

---

### POST /api/ai/multi-chat

**Request**:
```json
{
  "message": "인공지능 RAG 아키텍처에 대해 에이전트들이 설명해줘",
  "mode": "multi_agent_discussion",
  "rounds": 3,
  "showFinalSynthesis": true,
  "targetAgentId": null,
  "previousAnswers": [
    {
      "agentName": "SummaryAgent",
      "answer": "RAG(Retrieval-Augmented Generation)는 정보 검색을 통합한 생성 기술입니다.",
      "role": "ASSISTANT",
      "agentId": 1
    }
  ],
  "agents": [
    {
      "id": 1,
      "agentId": 1,
      "name": "SummaryAgent",
      "role": "요약봇",
      "personality": "전문적",
      "personalityStrength": "extreme",
      "style": "전문적",
      "tone": "전문적",
      "knowledgeLevel": "학사 수준",
      "customInstruction": "핵심을 명료하고 차분하게 요약하세요."
    }
  ]
}
```

**Response**:
```json
{
  "mode": "multi_agent_discussion",
  "answers": [
    {
      "agentName": "SummaryAgent",
      "answer": "RAG의 장점은 모델 재학습 없이도 실시간 외부 정보를 지식 소스로 활용할 수 있다는 점입니다."
    }
  ]
}
```

**필드명 주의**:
| Spring 기대 | FastAPI 반환 | 상태 |
|------------|-------------|------|
| `mode` | `mode` | ✅ 일치 |
| `answers` | `answers` | ✅ 일치 |
| `agentName` | `agentName` | ✅ 일치 |
| `answer` | `answer` | ✅ 일치 |
| `message` | `message` | ✅ 일치 (request) |
| `showFinalSynthesis` | `showFinalSynthesis` | ✅ 일치 (request) |
| `targetAgentId` | `targetAgentId` | ✅ 일치 (request) |
| `previousAnswers` | `previousAnswers` | ✅ 일치 (request) |
| `knowledgeLevel` | `knowledgeLevel` | ✅ 일치 (agent profile) |
| `customInstruction` | `customInstruction` | ✅ 일치 (agent profile) |
| `personalityStrength` | `personalityStrength` | ✅ 일치 (agent profile) |

---

## Spring Boot 측 주의사항

1. FastAPI 응답 Content-Type은 `application/json; charset=utf-8`
2. 한국어 텍스트가 포함되므로 UTF-8 처리 필수
3. `predictedStudySeconds`는 float (소수점 가능)
4. `correctAnswer`는 int (0~3)
5. Spring fallback은 FastAPI가 4xx/5xx를 반환할 때 동작
6. FastAPI도 내부 fallback이 있으므로 200 응답에도 fallback 내용일 수 있음

---

## HTTP 상태 코드 정책

| 상황 | 상태 코드 |
|------|----------|
| 정상 응답 | 200 |
| 입력 검증 실패 (필드 누락, 타입 오류) | 422 |
| 비즈니스 로직 오류 (길이, 음수) | 422 (Pydantic) |
| 서버 내부 오류 | 500 |
| 인증 실패 | 401 |
