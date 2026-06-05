# 🚀 StudyBridge AI/RAG 연동 명세서 - FastAPI 개발자용

본 문서는 StudyBridge 백엔드(Spring Boot)와 AI 엔진(FastAPI) 간의 데이터 연동 규격 및 설계 요구사항을 정의한 연동 명세서입니다. FastAPI 개발자는 이 문서에 정의된 API 규격을 정확히 준수하여 비즈니스 로직과 모델 추론 엔진을 구축해야 합니다.

---

## 📌 1. 연동 아키텍처 개요
Spring Boot 백엔드는 핵심 웹 서비스, 데이터베이스 영속화, 실시간 소켓 및 인증 처리를 담당하며, FastAPI 엔진은 TensorFlow 모델 기반의 예측 연동 및 LLM 기반의 PDF RAG/멀티 에이전트 연동을 수행합니다.

Spring Boot에서 AI 기능 호출 시 HTTP Client를 기반으로 FastAPI의 REST API를 동기적으로 호출하며, 네트워크 장애나 모델 오류 발생 시 서비스의 가용성을 유지하기 위해 **Spring Boot 내부적으로 즉각적인 Fallback(대체) 기능**이 탑재되어 있습니다.

---

## 🧠 2. 핵심 연동 API 명세

### 1) TensorFlow 기반 내일의 학습 시간 예측
* **호출 시점**: 사용자가 메인 대시보드나 마이페이지에 접근하여 다음 날 예상 집중 시간을 조회할 때 Spring Boot가 호출.
* **Spring Boot 호출 서비스**: `StudyTimePredictionService.java`
* **FastAPI 엔드포인트**: `POST /api/ai/predict/study-time`
* **요청/응답 포맷 및 데이터 구조**:

#### Request Body (JSON)
```json
{
  "userId": 42,
  "weeklyStudySeconds": [3600, 7200, 5400, 0, 1800, 9000, 4500]
}
```
| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| `userId` | Long | 사용자 고유 식별자 ID |
| `weeklyStudySeconds` | Array (Integer) | 지난 7일간의 일별 타이머 공부 시간 기록 (초 단위, 크기 7 고정) |

#### Response Body (JSON)
```json
{
  "predictedStudySeconds": 5800.5
}
```
| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| `predictedStudySeconds` | Float | 예측 엔진이 반환한 다음 날 예상 공부 집중 시간 (초 단위) |

* **장애 극복(Fallback) 설계**:
  * FastAPI 서버가 응답하지 않거나 예외 발생 시, Spring Boot는 내부적으로 `weeklyStudySeconds`의 **7일 평균 집중 시간**을 자동 계산하여 에러 없이 프론트엔드에 전달합니다.

---

### 2) LLM 기반 PDF 텍스트 추출 및 객관식 퀴즈 자동 생성
* **호출 시점**: 그룹스터디 룸 내부에서 사용자가 PDF 학습 자료를 업로드할 때, Spring Boot가 AWS S3 비공개 버킷에 원본 파일을 안전하게 업로드 완료한 직후 호출.
* **Spring Boot 호출 서비스**: `GroupStudyMaterialService.java`
* **FastAPI 엔드포인트**: `POST /api/ai/quiz/generate`
* **요청/응답 포맷 및 데이터 구조**:

#### Request Body (JSON)
```json
{
  "materialId": 12,
  "s3Key": "materials/user_42/bf42e2b9-7a54-46ab-a279-d102ba2ce501.pdf",
  "fileName": "중간고사_운영체제_요약본.pdf"
}
```
| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| `materialId` | Long | 백엔드 데이터베이스에 임시 등록된 자료 고유 식별자 ID |
| `s3Key` | String | S3 Bucket 내의 PDF 비공개 경로 Key (FastAPI는 이 Key를 사용해 AWS SDK로 버킷에 접근) |
| `fileName` | String | 사용자가 업로드한 원본 파일 이름 (텍스트 분석 시 참조용) |

#### Response Body (JSON)
```json
{
  "quizTitle": "[중간고사_운영체제_요약본.pdf] 자료 기반 학습 퀴즈",
  "questions": [
    {
      "question": "데드락(Deadlock)이 발생하기 위한 4가지 필요조건이 아닌 것은?",
      "options": ["상호 배제 (Mutual Exclusion)", "점유와 대기 (Hold and Wait)", "선점 (Preemption)", "순환 대기 (Circular Wait)"],
      "correctAnswer": 2,
      "timeLimitSeconds": 30
    },
    {
      "question": "임계 구역(Critical Section) 문제를 해결하기 위한 세 가지 조건이 아닌 것은?",
      "options": ["상호 배제 (Mutual Exclusion)", "진행 (Progress)", "한정 대기 (Bounded Waiting)", "동적 할당 (Dynamic Allocation)"],
      "correctAnswer": 3,
      "timeLimitSeconds": 30
    }
  ]
}
```
| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| `quizTitle` | String | 생성된 퀴즈의 대분류 타이틀명 |
| `questions` | Array | 생성된 퀴즈 문제 리스트 (기본 3문제 출제 권장) |
| `question` | String | 퀴즈 문항 지문 |
| `options` | Array (String) | 4지선다형 보기 리스트 (배열 크기 4 고정) |
| `correctAnswer` | Integer | 정답 번호의 인덱스 (0-indexed: 0, 1, 2, 3 중 하나) |
| `timeLimitSeconds` | Integer | 해당 문항의 제한 시간 (초 단위, 기본 30초 설정 권장) |

* **장애 극복(Fallback) 설계**:
  * PDF 분석 및 LLM 퀴즈 생성 도중 타임아웃(기본 15초) 또는 연결 오류 발생 시, 시스템 흐름을 유지하기 위해 Spring Boot 백엔드는 내부의 **학습 메이트 안내용 가이드 문제 3가지**를 자동으로 생성하여 DB에 안전하게 기록하고 처리합니다.

---

### 3) LLM RAG 기반 멀티 에이전트 토론 엔진
* **호출 시점**: 그룹스터디 룸 내부에서 사용자가 AI 에이전트들과 토론을 시작하고 메시지를 보낼 때 호출.
* **Spring Boot 호출 컨트롤러**: `GroupStudyStreamController.java`
* **FastAPI 엔드포인트**: `POST /api/ai/multi-chat`
* **요청/응답 포맷 및 데이터 구조**:

#### Request Body (JSON)
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
| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| `message` | String | 사용자가 새로 전송한 채팅 메시지 본문 |
| `mode` | String | 토론 모드 (`multi_agent_discussion` 등이 들어옴) |
| `rounds` | Integer | 토론 라운드 횟수 (기본값: 3) |
| `showFinalSynthesis` | Boolean | 최종 요약봇의 합성 의견 포함 여부 |
| `targetAgentId` | Long | [선택] 특정 에이전트 1명에게 질문할 시 지정할 ID |
| `previousAnswers` | Array | **최근 최대 100개**의 단기 대화 이력 (Spring Boot의 Redis 캐시가 주입하여 전달) |
| `previousAnswers[].agentName`| String | 발언한 사용자 이름 또는 에이전트 이름 |
| `previousAnswers[].answer` | String | 발언 내용 본문 |
| `previousAnswers[].role` | String | 발언 역할 (`USER` 또는 `ASSISTANT`) |
| `previousAnswers[].agentId` | Long | 발언한 에이전트의 ID (유저인 경우 null) |
| `agents` | Array | 스터디룸에 지정된 AI 에이전트 세부 속성/성격 목록 |

#### Response Body (JSON)
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
| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| `mode` | String | 응답 처리 모드 |
| `answers` | Array | 각 에이전트가 생성한 최종 답변 목록 |
| `answers[].agentName` | String | 답변한 에이전트명 |
| `answers[].answer` | String | 답변 내용 본문 |

* **특이 사항**:
  * Spring Boot 백엔드는 FastAPI가 반환하는 동기 `answers` 결과물을 받아 리액티브 지연 방출 에뮬레이터(`delayElements`)를 거쳐 프론트엔드로 SSE 스트리밍 형태로 전송합니다. 따라서 FastAPI 개발자는 스트리밍 통신이 아닌 **정상적인 동기 REST API**로 본 규격만 완벽히 구현하면 됩니다.
