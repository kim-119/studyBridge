# FastAPI Spring 계약 구현 결과

## 개요

이 문서는 Spring Boot가 호출하는 FastAPI REST API 3개의 구현 결과를 정리한다.

Spring Boot ↔ FastAPI 호출 방향:
```
React → Spring Boot → FastAPI (HTTP Client)
```

FastAPI는 동기 REST JSON만 반환한다. SSE 스트리밍은 Spring Boot가 처리한다.

---

## 구현된 Endpoint 목록

### 1. GET /api/health

**목적**: 서버 상태 및 의존 서비스 설정 여부 확인

**Spring 호환 필드**:
- `status`: 항상 "ok"
- `service`: "studybridge-fastapi"
- `openaiConfigured`: OpenAI API Key 설정 여부 (bool)
- `ollamaConfigured`: Ollama 서버 응답 가능 여부 (bool)
- `tavilyConfigured`: Tavily API Key 설정 여부 (bool)
- `awsConfigured`: AWS 자격증명 + S3 버킷 설정 여부 (bool)

실제 key 값은 절대 응답에 포함되지 않는다.

---

### 2. POST /api/ai/predict/study-time

**목적**: 최근 7일 학습 시간 데이터 기반 다음 학습 시간 예측

**Request**:
```json
{
  "userId": 42,
  "weeklyStudySeconds": [3600, 7200, 5400, 0, 1800, 9000, 4500]
}
```

**Response**:
```json
{
  "predictedStudySeconds": 5800.5
}
```

**Fallback 정책**:
- TensorFlow 모델 파일 없음 → 7일 가중 평균 기반 예측 (최근 3일 가중치 우선)
- TensorFlow import 실패 → 서버 죽지 않고 평균 예측으로 자동 fallback
- 이 fallback은 "FastAPI 내부 안전장치"이며 Spring Boot의 fallback과 별개임

**입력 검증**:
- `weeklyStudySeconds` 길이 != 7 → 422 에러
- 음수 값 → 422 에러

---

### 3. POST /api/ai/quiz/generate

**목적**: S3 PDF 기반 4지선다 퀴즈 3문항 생성

**Request**:
```json
{
  "materialId": 12,
  "s3Key": "materials/user_42/bf42e2b9-7a54-46ab-a279-d102ba2ce501.pdf",
  "fileName": "중간고사_운영체제_요약본.pdf"
}
```

**Response**:
```json
{
  "quizTitle": "[중간고사_운영체제_요약본.pdf] 자료 기반 학습 퀴즈",
  "questions": [
    {
      "question": "...",
      "options": ["보기1", "보기2", "보기3", "보기4"],
      "correctAnswer": 2,
      "timeLimitSeconds": 30
    }
  ]
}
```

**Fallback 정책**:
| 실패 단계 | 처리 방식 |
|----------|----------|
| S3 접근 실패 | fallback quiz 반환 (명세 구조 유지) |
| PDF 텍스트 추출 실패 | fallback quiz 반환 |
| PDF 텍스트 너무 짧음 | fallback quiz 반환 |
| OpenAI 실패 | Ollama fallback |
| Ollama도 실패 | fallback quiz 반환 |

fallback quiz도 반드시 명세 응답 구조를 지킨다.

**LLM 호출 순서**:
1. OpenAI GPT (OPENAI_API_KEY 설정 시)
2. Ollama (OLLAMA_BASE_URL 설정 시)
3. 기본 fallback quiz

---

### 4. POST /api/ai/multi-chat

**목적**: 멀티 에이전트 토론 (동기 REST JSON 반환)

**Request 필드**:
- `message`: 사용자 메시지 (필수)
- `agents`: 참여 에이전트 목록 (빈 배열이면 기본 에이전트 사용)
- `targetAgentId`: 특정 에이전트 지정 (null이면 전체)
- `previousAnswers`: 이전 대화 맥락 (최대 100개 수신, 실제 최근 20개 사용)
- `rounds`: 토론 라운드 수 (최대 3라운드로 제한)
- `showFinalSynthesis`: true이면 종합정리봇 답변 추가

**Response**:
```json
{
  "mode": "multi_agent_discussion",
  "answers": [
    {
      "agentName": "SummaryAgent",
      "answer": "..."
    }
  ]
}
```

**Fallback 정책**:
| 실패 단계 | 처리 방식 |
|----------|----------|
| Ollama 실패 | OpenAI fallback |
| OpenAI도 실패 | 기본 안내 답변 반환 |
| agents 없음 | 기본 에이전트 자동 생성 |
| previousAnswers 과다 | 최근 20개만 컨텍스트 사용 |

오류가 발생해도 응답 JSON 구조(mode, answers)는 깨지지 않는다.

---

## 에이전트 성격 반영

| 성격 유형 | 말투 특징 |
|----------|----------|
| 친절_설명형 | 따뜻하고 친근한 비유·예시 중심 |
| 비판적_분析형 | 문제 지적 후 개선 방향 제시 (코치형) |
| 논리적_탐구형 | 원인→구조→결과 순서 추론 |
| 창의적_확장형 | 비유·다른 분야 연결 |
| 간결_요약형 | 핵심 압축, 글머리 기호, 한 줄 결론 |
| 전문적 | 학술적 어조, 정확한 용어 |

비판적 성격은 공격적 욕설이 아니라 살짝 지적하고 개선 방향을 제시하는 코치형으로 처리한다.

---

## 지식수준 차등화

| 수준 | 설명 방식 |
|------|----------|
| 입문 | 쉬운 비유, 어려운 용어 최소화 |
| 학사 | 개념 정의, 작동 원리, 기본 예시 |
| 석사 | 구조, 한계, 적용 조건 |
| 박사 | 이론적 배경, 예외, 구조적 분석 |
| 전문가 | 실서비스 기준, 병목, 장애 대응, 운영 리스크 |

---

## 보안 원칙

- AWS Key, API Key 코드 하드코딩 금지
- 모든 인증 정보는 환경변수로만 관리
- 헬스 체크 응답에 실제 key 값 절대 미포함
- stack trace를 사용자 응답에 노출하지 않음 (로그에만 기록)

---

## 남은 작업

- [ ] 실제 TensorFlow 모델 파일 연결 및 테스트
- [ ] 실제 S3 환경 연동 테스트
- [ ] 실제 Ollama/GPT API 키 기반 엔드투엔드 테스트
- [ ] RAG/pgvector 고도화 (후속 단계)
- [ ] Spring Boot 실연동 테스트
