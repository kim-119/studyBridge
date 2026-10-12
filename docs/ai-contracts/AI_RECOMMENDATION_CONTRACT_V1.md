# AI_RECOMMENDATION_CONTRACT_V1

EC2(Spring) ↔ AI07(FastAPI) 학습 추천·피드백 API 계약 — `recommendation.v1`

| 항목 | 값 |
|---|---|
| 계약 버전 | `recommendation.v1` (피드백 섹션: `concept_review_v1`) |
| 작성 | 2026-10-13, EC2 `LLM-clean` |
| EC2 구현 | `backend/src/main/java/com/studybridge/api/service/recommendation/*`, `MaterialFeedbackService` |
| EC2 플래그 | `AI_RECOMMENDATION_ENABLED=false`, `AI_FEEDBACK_CONCEPT_REVIEW_ENABLED=false` (기본 OFF) |
| AI07 상태(작성 시점) | `/api/ai/recommendation/*` **미구현**, `/api/ai/feedback` 은 `content` 만 읽고 평문 피드백 반환 |

이 문서는 EC2 코드가 **실제로 보내는 요청과 실제로 해석하는 응답**을 기준으로 썼다. 필드 이름·검증 규칙은 위 EC2 코드와 1:1 대응한다.

---

## 0. 원칙

1. **AI07 은 후보만 만든다. 채택은 EC2 가 한다.** EC2 는 사용자 권한, 근거 ID, 실제 교재 목차, 로드맵 그래프(DAG), 중복을 검증해 통과한 후보만 사용자에게 보여 준다.
2. **AI07 은 사용자 DB 에 접근하지 않는다.** 필요한 데이터는 EC2 가 최소한으로 요청 본문에 담아 보낸다. 요청에는 userId·이메일·토큰이 없다.
3. **근거 없는 내용을 만들지 않는다.** 근거는 요청의 `evidence[].id` 중에서만 인용한다. 확인된 목차에 없는 장 제목, 존재하지 않는 노드는 EC2 가 버린다(환각으로 집계).
4. **유료 외부 API 를 쓰지 않는다.** 모델 장애 시 OpenAI 등으로 폴백하지 말고 `success:false` 를 돌려준다. EC2 는 규칙 추천으로 폴백한다.
5. **AI 는 보강(augmentation)이다.** 추천 라우트가 실패해도 EC2 기능은 동작한다. 피드백은 실패 시 기존 피드백을 보존한다.

### 기능 책임 분리

| 기능 | 담당 | 하는 일 | 하지 않는 일 |
|---|---|---|---|
| 사용자 플래너 — Learning Task | `task_recommendation` | 현재 계획 다음에 할 구체적 과제 후보 | 계획 최적화, 일정 계산 |
| 로드맵 — Learning Node | `roadmap_candidate_generation` | 다음 노드 후보 + 선수관계 간선 제안 | 순위 확정·진입 조건 판정(EC2) |
| AI 학습 계획 진단 — Optimization | `plan_analysis` | 작업의 의미적 분해(작업·선수 개념) | A/W/D·마감 창·충돌 계산(EC2) |
| 문서 기반 | `document_recommendation` | 개념 복습·실습·심화 후보 | 로드맵 단계/주차 표현 |
| 자료 피드백 | `feedback_regenerate` | 개념 정확성·오개념·누락·심화·검증 실습 | DB 저장(EC2) |

---

## 1. 공통 규약

### 1.1 전송

- `POST`, `Content-Type: application/json; charset=utf-8`, 응답도 JSON.
- 베이스 URL: EC2 Spring 컨테이너에서 `FASTAPI_PRIMARY_BASE_URL`(= ai07 :18000 reverse tunnel).
- **failover 없음**: 이 문서의 라우트는 primary(AI07) 만 호출한다. secondary(EC2 :8000)는 OpenAI 경로를 쓰기 때문에 유료 API 신규 사용이 되므로 일부러 제외했다.

### 1.2 헤더

| 헤더 | 방향 | 필수 | 설명 |
|---|---|---|---|
| `Authorization: Bearer <AI_SERVER_API_KEY>` | EC2→AI07 | 설정 시 항상 전송 | 새 라우트는 **반드시 검증**할 것(현재 AI07 은 semantic-graph 만 검사). 불일치 → 401 |
| `X-Request-ID` | EC2→AI07 | 항상 | `fb-<uuid>` / `rec-<uuid>`. AI07 로그·응답 `requestId` 에 그대로 사용 |
| `X-Contract-Version` | EC2→AI07 | 추천 라우트 | `recommendation.v1` |

### 1.3 버전 호환

- 요청·응답 모두 `contractVersion` 을 가진다. **major(`recommendation.v1` 접두) 가 다르면 EC2 는 응답 전체를 무시**하고 규칙 추천으로 폴백한다. `recommendation.v1.1` 처럼 minor 는 허용.
- minor 변경은 **필드 추가만** 허용한다. 필드 삭제·의미 변경·enum 값 의미 변경은 major 증가.
- AI07 은 모르는 요청 필드를 무시해야 한다(pydantic `extra="ignore"`). EC2 는 모르는 응답 필드를 무시한다.

### 1.4 null 정책

- 배열 필드는 **null 금지, 없으면 `[]`**. 객체 필드는 정보가 없으면 `null`.
- 문자열 필드 빈 값은 `null` 로 보낸다(`""` 대신).
- 숫자(분·점수)는 근거가 없으면 `null`. **추정값을 만들지 않는다.**

### 1.5 오류 응답

| 상황 | HTTP | 본문 |
|---|---|---|
| 모델 실패/타임아웃/파싱 실패(일시적) | **200** | `{"success":false,"errorCode":"AI_TIMEOUT","message":"...","retryable":true,"requestId":"..."}` |
| 입력 부족(재시도 무의미) | 200 | `{"success":false,"errorCode":"PDF_TEXT_EMPTY","retryable":false,...}` |
| 요청 스키마 위반 | 422 | FastAPI 기본 `detail` |
| 인증 실패 | 401 | |
| 라우트 없음(미배포) | 404 | EC2 는 규칙 폴백(추천) / `AI_UPSTREAM_UNAVAILABLE`(피드백) |
| 서버 오류 | 5xx | EC2: 추천=규칙 폴백, 피드백=503 `AI_UPSTREAM_UNAVAILABLE` |

`message` 는 사용자에게 보여도 되는 한국어 문장만. 스택·URL·모델명·`num_ctx` 등 내부 정보 금지(EC2 가 걸러 내지만 원천에서 막을 것).

### 1.6 타임아웃·재시도

| 라우트 | EC2 대기 상한 | AI07 권장 내부 예산 | EC2 재시도 |
|---|---|---|---|
| `/api/ai/feedback` | 125s (`AI_FEEDBACK_TIMEOUT_SECONDS`) | ≤ 110s 안에 성공 또는 `AI_TIMEOUT` | 없음(사용자 [다시 시도]) |
| `/api/ai/recommendation/*` | 30s (`AI_RECOMMENDATION_TIMEOUT_SECONDS`) | ≤ 25s | 없음(규칙 폴백) |
| `/api/ai/planner/analyze-semantic` | 120s (`AI_PLANNER_EXPAND_TIMEOUT_SECONDS`) | ≤ 110s | 없음(EC2 결정적 폴백) |

- EC2 는 같은 사용자·같은 대상에 대해 동시 1건만 보낸다(Redis 잠금). AI07 은 같은 `requestId` 가 다시 오면 같은 결과를 돌려주는 것이 바람직하다(멱등, 선택).
- 브라우저 타임아웃은 180s 이므로 AI07 이 EC2 상한보다 오래 붙잡으면 사용자에게는 실패로 보인다.

### 1.7 모델 장애 시 폴백

- Ollama 장애/과부하 → `success:false, errorCode:"AI_MODEL_UNAVAILABLE", retryable:true`.
- **OpenAI/GPT 등 유료 API 로 폴백 금지.** (현재 AI07 `/api/ai/feedback` 의 summary 가 "(GPT)" 로 표기되어 있음 — 실제 경로가 유료 API 면 이번 작업에서 Ollama 로 바꾸거나 운영자 확인 필요.)
- 응답 `model.provider`/`model.name`(추천) 또는 `metadata.provider`/`metadata.model`(피드백)에 실제 사용 모델을 적는다. EC2 는 이를 추천 행(`model_provider`, `model_name`)에 저장한다.

---

## 2. feedback_regenerate — `POST /api/ai/feedback`

자료보관함 학습일지/자료의 AI 피드백 생성·재생성. EC2 는 성공 응답만 같은 행에 덮어쓰고, 실패면 **기존 피드백을 그대로 둔다**.

### 2.1 요청 (EC2 → AI07)

```json
{
  "content": "ViewModel 은 Activity 간에 자동으로 유지된다. ...",
  "feedback_mode": "balanced",
  "min_strengths": 8,
  "min_recommendations": 8,
  "min_concerns": 8,
  "sanitize_markdown": true,
  "request_id": "fb-9f0c...",
  "schema_version": "concept_review_v1",
  "sections": ["conceptAccuracy", "misconceptions", "missingKnowledge", "advancedConcepts", "verificationPractice"]
}
```

| 필드 | 타입 | 항상 | 설명 |
|---|---|---|---|
| `content` | string | ✓ | 추출 텍스트(없으면 학습일지 본문). 비어 있으면 EC2 가 보내지 않음(`FEEDBACK_SOURCE_EMPTY`) |
| `feedback_mode` … `sanitize_markdown` | | ✓ | 기존(레거시 balanced) 힌트 |
| `request_id` | string | ✓ | `X-Request-ID` 와 동일 |
| `schema_version`, `sections` | | 플래그 ON 시만 | `AI_FEEDBACK_CONCEPT_REVIEW_ENABLED=true` 일 때만 전송 |

### 2.2 응답 — concept_review_v1 (신규, `schema_version` 요청 시)

```json
{
  "success": true,
  "schemaVersion": "concept_review_v1",
  "summary": "ViewModel 의 유지 범위 설명이 부정확합니다.",
  "conceptAccuracy": [
    {"statement": "ViewModel 은 Activity 간에 자동으로 유지된다", "verdict": "부정확",
     "explanation": "ViewModel 은 ViewModelStoreOwner(Activity·Fragment·NavBackStackEntry) 범위에서만 유지된다."}
  ],
  "misconceptions": [
    {"claim": "다른 Activity 에서도 같은 ViewModel 인스턴스를 받는다",
     "correction": "다른 Activity 는 다른 ViewModelStoreOwner 이므로 새 인스턴스가 만들어진다. 공유하려면 상위 범위(Application 수준 저장소/Repository)를 쓴다."}
  ],
  "missingKnowledge": [
    "구성 변경(화면 회전)에서는 ViewModel 이 유지되지만, 프로세스 종료 후에는 유지되지 않는다",
    "프로세스 종료 후 복원은 SavedStateHandle(번들 저장)이 담당한다"
  ],
  "advancedConcepts": ["Navigation graph 범위 ViewModel(by navGraphViewModels)"],
  "verificationPractice": [
    {"task": "카운터 값을 ViewModel 에 두고 화면을 회전한다", "expected": "값이 유지된다"},
    {"task": "개발자 옵션 '활동 유지 안 함' 후 앱으로 복귀한다", "expected": "SavedStateHandle 에 둔 값만 복원된다"}
  ],
  "metadata": {"provider": "ollama", "model": "qwen2.5:14b", "elapsedMs": 41234}
}
```

| 섹션 | 원소 타입 | 의미 |
|---|---|---|
| `conceptAccuracy` | `{statement, verdict: "정확"\|"부분 정확"\|"부정확", explanation}` 또는 string | 학습자 문장별 정확성 판정 |
| `misconceptions` | `{claim, correction}` 또는 string | 틀린 이해 ↔ 올바른 설명 |
| `missingKnowledge` | string 또는 `{concept, explanation}` | 정확히 이해하려면 함께 알아야 할 것 |
| `advancedConcepts` | string 또는 `{concept, explanation}` | 다음 단계 확장 개념 |
| `verificationPractice` | `{task, expected}` 또는 string | 직접 실행해 확인하는 실습 |

- 각 섹션은 배열(빈 배열 허용). 학습 내용에 근거해야 하며, 학습 내용에 없는 주제를 길게 늘어놓지 않는다.
- EC2 저장 규칙: 위 키(또는 레거시 `strengths/recommendations/concerns/summary/feedback_balance/next_actions`) 중 하나라도 비어 있지 않으면 응답 JSON 을 저장한다(`success/errorCode/message/retryable/textStatus/warnings` 는 제거). 프런트는 다섯 섹션을 각각 구분해 표시한다.

### 2.3 응답 — 레거시(현재 AI07)

`{"success":true,"feedbackData":"...","feedback":"...","metadata":{...}}` — EC2 는 계속 지원한다(평문 표시).

### 2.4 실패 응답 → EC2 처리

| AI07 응답 | EC2 → 브라우저 | 기존 피드백 |
|---|---|---|
| `success:false, errorCode:"AI_TIMEOUT"` | 504 `AI_TIMEOUT`, retryable | 보존 |
| `success:false, errorCode:"PDF_TEXT_EMPTY"\|"PDF_TEXT_INSUFFICIENT"` | 422 `FEEDBACK_SOURCE_EMPTY`, 재시도 불가 | 보존 |
| `success:false`, 그 외 코드 | 502 `AI_GENERATION_FAILED` (`upstreamCode` 에 원래 코드) | 보존 |
| 200 인데 피드백 본문 없음/공백 | 502 `AI_RESPONSE_INVALID` | 보존 |
| 4xx(404/405 제외) | 원 상태 보존/매핑(`AI_REQUEST_REJECTED`, 401/403→502 `AI_UPSTREAM_AUTH`) | 보존 |
| 404/405/5xx/연결 실패 | 503 `AI_UPSTREAM_UNAVAILABLE` | 보존 |
| EC2 대기 상한 초과 | 504 `AI_TIMEOUT` | 보존 |

> 2026-10-13 운영 장애의 원인은 AI07 이 아니라 EC2 였다(재생성 시 delete 가 cascade 로 취소 → insert unique 위반 500). AI 응답은 성공했는데도 실패로 보였다. EC2 수정 완료.

---

## 3. task_recommendation — `POST /api/ai/recommendation/task`

사용자 플래너(Learning Task). EC2 규칙 후보를 이미 만든 뒤 보강용으로 호출한다.

### 3.1 요청 (EC2 `LearningRecommendationService.generateTask` 가 보내는 그대로)

```json
{
  "contractVersion": "recommendation.v1",
  "requestId": "rec-1c2d...",
  "feature": "task_recommendation",
  "locale": "ko-KR",
  "plan": {"title": "김도현 저자의 선형대수 2장 학습하기", "subject": "선형대수", "content": "(≤1000자)"},
  "progress": {"checklistTotal": 3, "checklistCompleted": 3, "completed": true},
  "textbook": {"tocVerified": true, "toc": [{"number": 1, "title": "벡터와 공간"}, {"number": 2, "title": "행렬과 연립방정식"}, {"number": 3, "title": "행렬식"}]},
  "quiz": {"latestScore": 72},
  "upcomingPlans": ["선형대수 연습문제 세트"],
  "evidence": [
    {"id": "PLANNER:1", "type": "PLANNER", "label": "김도현 저자의 선형대수 2장 학습하기"},
    {"id": "PLAN_ANALYSIS:1", "type": "PLAN_ANALYSIS", "label": "체크리스트 3/3"},
    {"id": "TOC:3:3", "type": "TOC", "label": "3장 행렬식"}
  ],
  "allowedTypes": ["NEXT_CHAPTER", "CONCEPT_REVIEW", "PRACTICE", "PREREQUISITE_GAP", "APPLICATION", "WRONG_ANSWER_REVIEW"],
  "maxCandidates": 5
}
```

- `textbook` 은 플래너에 본인 PDF 가 연결되고 추출 텍스트가 있을 때만 객체, 아니면 `null`. `tocVerified=false` 면 `toc` 는 참고용이며 **장 제목을 만들어 쓰면 안 된다.**
- `quiz` 는 측정 점수가 있을 때만 객체(없으면 `null` — 숙련도 미측정).
- `progress.completed` 는 **체크리스트 이행 기록**이다. 계획 문장("~학습하기")은 완료가 아니다.

### 3.2 응답

```json
{
  "contractVersion": "recommendation.v1",
  "requestId": "rec-1c2d...",
  "success": true,
  "candidates": [
    {"type": "NEXT_CHAPTER", "title": "3장 행렬식 학습", "reason": "2장 체크리스트 완료, 목차상 다음 장",
     "evidenceIds": ["PLANNER:1", "PLAN_ANALYSIS:1", "TOC:3:3"], "chapter": {"number": 3, "title": "행렬식"}},
    {"type": "PREREQUISITE_GAP", "title": "가우스 소거법 복습", "reason": "최근 퀴즈 72점",
     "evidenceIds": ["PLANNER:1"], "chapter": null}
  ],
  "model": {"provider": "ollama", "name": "qwen2.5:14b"}
}
```

### 3.3 응답 JSON Schema (task/document 공통, roadmap 은 §4.3)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["contractVersion", "success", "candidates"],
  "properties": {
    "contractVersion": {"type": "string", "pattern": "^recommendation\\.v1(\\.\\d+)?$"},
    "requestId": {"type": ["string", "null"]},
    "success": {"type": "boolean"},
    "errorCode": {"type": ["string", "null"]},
    "message": {"type": ["string", "null"]},
    "retryable": {"type": ["boolean", "null"]},
    "candidates": {
      "type": "array", "maxItems": 10,
      "items": {
        "type": "object",
        "required": ["type", "title", "evidenceIds"],
        "properties": {
          "type": {"type": "string"},
          "title": {"type": "string", "minLength": 1, "maxLength": 200},
          "reason": {"type": ["string", "null"], "maxLength": 500},
          "evidenceIds": {"type": "array", "minItems": 1, "items": {"type": "string"}},
          "chapter": {"type": ["object", "null"], "properties": {"number": {"type": "integer"}, "title": {"type": ["string", "null"]}}},
          "nodeKey": {"type": ["string", "null"]}
        }
      }
    },
    "model": {"type": ["object", "null"], "properties": {"provider": {"type": "string"}, "name": {"type": "string"}}}
  }
}
```

### 3.4 EC2 검증(`AiCandidateValidator`) — 탈락 사유

| 사유 | 조건 | 환각 집계 |
|---|---|---|
| `INVALID_TYPE` | `type` 이 `allowedTypes` 밖 | ✗ |
| `INVALID_TITLE` | 제목 공백 또는 200자 초과 | ✗ |
| `NO_EVIDENCE` | `evidenceIds` 비어 있음 | ✗ |
| `UNKNOWN_EVIDENCE` | 요청 `evidence[].id` 에 없는 ID 인용 | ✓ |
| `UNVERIFIED_TOC` | `NEXT_CHAPTER` 인데 목차 미확인, 또는 `chapter.number/title` 이 확인된 목차와 불일치 | ✓ |

- 통과한 `NEXT_CHAPTER` 의 제목은 **목차 원문으로 교체**된다(`"3장 행렬식 학습"`). 근거 라벨도 EC2 데이터로 채운다(AI 문자열 미사용).
- 탈락 후보는 `status=DISCARDED` 로 저장(사용자 미노출) → 환각률·근거 일치율 계산에 쓰인다.
- 규칙 후보와 `type + targetKey` 가 같으면 중복으로 버린다.

---

## 4. roadmap_candidate_generation — `POST /api/ai/recommendation/roadmap-candidates`

로드맵 플래너(Learning Node). 한 번의 호출로 **후보 노드 + 제안 선수관계 간선**을 받는다.

### 4.1 요청

```json
{
  "contractVersion": "recommendation.v1",
  "requestId": "rec-77aa...",
  "feature": "roadmap_candidate_generation",
  "locale": "ko-KR",
  "goal": "선형회귀를 실제 데이터에 적용한다 (≤300자, 없으면 null)",
  "currentNodeKey": "p3171",
  "nodes": [
    {"key": "p3170", "title": "[로드맵 1주차 1일] 데이터 전처리", "order": 1001, "completed": true, "mastery": null},
    {"key": "p3171", "title": "[로드맵 1주차 2일] 최소제곱법", "order": 1002, "completed": false, "mastery": null}
  ],
  "edges": [{"from": "p3170", "to": "p3171"}],
  "allowedTypes": ["ROADMAP_NODE"],
  "maxCandidates": 5
}
```

- `nodes` 는 같은 사용자·같은 로드맵의 플래너 전체(최대 ~84). `key` 는 EC2 노드 키(`p<plannerId>`), `order` 는 기존 week/day 순서 키.
- `edges` 는 현재 EC2 가 쓰는 순차 간선(레거시 순차형 로드맵 호환).
- `mastery` 는 0..1 측정값 또는 `null`(**현재 운영 데이터는 전부 null** — 노드 단위 숙련도 측정 경로가 없다). 완료(`completed`)를 숙련으로 해석하지 말 것.

### 4.2 응답

```json
{
  "contractVersion": "recommendation.v1",
  "requestId": "rec-77aa...",
  "success": true,
  "candidates": [
    {"type": "ROADMAP_NODE", "title": "최소제곱법", "reason": "선수 단계 완료", "evidenceIds": ["ROADMAP_NODE:p3171"], "nodeKey": "p3171"}
  ],
  "edges": [{"from": "p3170", "to": "p3175"}],
  "model": {"provider": "ollama", "name": "qwen2.5:14b"}
}
```

### 4.3 EC2 처리 규칙(수학 모델)

- 그래프 `G=(V,E)`, `Prereq(v)={u | (u,v)∈E}`. E = 순차 간선 ∪ AI07 제안 간선.
- 제안 간선 검증: 노드 미존재·자기 루프·**순환**(Kahn 위상 정렬 잔여 노드) 중 하나라도 있으면 **제안 간선 전체를 버리고** 순차 그래프만 쓴다(`context.graphValid=false`).
- 진입 가능 집합 `F = {v | ¬completed(v) ∧ ∀u∈Prereq(v): completed(u)}`.
- 숙련도 진입 조건 `Eligible(v) = ∧_{u∈Prereq(v)} (Mastery(u) ≥ τ_u)`, 3값: 측정값 τ 미만 하나라도 → NOT_ELIGIBLE(대신 선수 노드 복습 추천), 미측정 포함 → UNKNOWN(추천하되 `verificationRequired=true`), 전부 τ 이상 → ELIGIBLE. 기본 τ=0.7.
- 순위 `Score(v)=w₁R+w₂P+w₃C+w₄T`(Σw=1, w≥0), 기본 w=(0.2, 0.35, 0.25, 0.2) **— 휴리스틱 초기값이며 검증되지 않았다**(`score.weightsValidated=false`). 근거 데이터가 없는 항은 제외하고 남은 가중치를 재정규화한다.
  - R: 노드 제목과 로드맵 goal 의 토큰 겹침 비율(goal 없으면 제외)
  - P: 측정된 선수 노드 중 τ 충족 비율(선수 없음=1, 전부 미측정=제외)
  - C: 현재 노드이거나 현재 노드의 직후 노드면 1, 아니면 0
  - T: 계획일이 오늘 이전/당일 1, 7일 뒤 0 으로 선형 감소(날짜 없으면 제외)
- AI 후보 노드는 `nodeKey ∈ V`(아니면 `UNKNOWN_NODE`, 환각) 이고 `nodeKey ∈ EC2 가 계산한 후보 집합`(아니면 `NOT_FRONTIER`)일 때만 채택. **순위·진입 조건은 EC2 계산이 우선**한다.

---

## 5. plan_analysis — `POST /api/ai/planner/analyze-semantic` (기존 라우트)

AI 학습 계획 진단 중 **의미적 분해만** AI07 담당. 시간 계산은 EC2 `PlanDiagnosisService`/`PlanCapacityCalculator` 가 한다.

- 요청: `PlannerSemanticDTO.Request`(기존 그대로) — `plannerId,title,topic,subject,learningType,priority,targetMinutes,learningGoal,content,memo,detailTasks[],checklist[],reviewQuestions[],outputs[],coreConcepts[],priorConcepts[],sourceType,roadmapContext`.
- 응답(기존 rich schema): `summary, goalAlignment, prerequisites[], tasks[{type, title, recommendedMinutes, goalAlignment, whyImportant, prerequisites[], learningSequence}], flow[]`.
- 계약 보강(v1):
  - `tasks[].recommendedMinutes` 는 **참고값**이다. EC2 는 이를 목표 시간에 맞춰 정규화(`PlannerTimeAllocator`)하므로 **W(예상 작업량) 계산에 쓰지 않는다**(순환 논리 방지). AI07 은 시간 합계·부족량·마감 판정을 응답에 넣지 않는다.
  - `tasks[].prerequisites` 는 같은 응답 안 다른 task 의 `title` 또는 개념명만 인용한다. 문장형 조각 금지(EC2 `LearningConceptValidator` 가 거른다).
  - "다음에 새로 공부할 것"을 이 응답에 섞지 않는다(그건 §3/§4/§6).
- EC2 진단 공식(참고): `A = Σ_d AvailableTime(d)`(사용자 입력 하루 가용 시간 × 기간 일수, 미입력이면 계산 안 함), `W = Σ EstimatedDuration(task_i)`(플래너 `estimatedMinutes` 또는 `goalTime` 기록값, 없으면 W 에서 제외하고 개수만 보고), `D = max(0, W−A)` + 날짜별 누적 창(EDF)·과부하일·선수관계 위반·todos 시간 중복.

---

## 6. document_recommendation — `POST /api/ai/recommendation/document`

원본 플래너가 없는 자료(PDF, 원본이 삭제된 PLANNER 보관본, 학습일지).

### 6.1 요청

```json
{
  "contractVersion": "recommendation.v1",
  "requestId": "rec-5e1f...",
  "feature": "document_recommendation",
  "locale": "ko-KR",
  "document": {"title": "Android ViewModel 정리", "materialType": "PDF",
               "keywords": ["ViewModelStoreOwner", "구성 변경", "SavedStateHandle"],
               "studyPoints": ["프로세스 종료 후 상태 복원"]},
  "quiz": {"latestScore": 64, "count": 2},
  "evidence": [
    {"id": "MATERIAL:345", "type": "MATERIAL", "label": "Android ViewModel 정리"},
    {"id": "STUDY_NOTE:345", "type": "STUDY_NOTE", "label": "AI 핵심 요약 노트 키워드"},
    {"id": "QUIZ:86", "type": "QUIZ", "label": "64점"}
  ],
  "allowedTypes": ["DOCUMENT_CONCEPT_REVIEW", "DOCUMENT_PRACTICE", "DOCUMENT_DEEP_DIVE", "DOCUMENT_REVIEW", "WRONG_ANSWER_REVIEW"],
  "maxCandidates": 5
}
```

### 6.2 응답

§3.3 스키마와 같다(`chapter`, `nodeKey` 는 `null`). **"N주차", "로드맵 N단계" 같은 진도 표현 금지** — 문서에는 확인된 진도가 없다.

---

## 7. 오류 코드 일람

| 코드 | 발생 | HTTP(EC2→브라우저) | retryable |
|---|---|---|---|
| `FEEDBACK_SOURCE_EMPTY` | 분석할 텍스트 없음 | 400 / 422 | ✗ |
| `FEEDBACK_GENERATION_IN_PROGRESS` | 같은 자료 재생성 진행 중(Redis 잠금) | 409 | ✓ |
| `AI_TIMEOUT` | AI07 `AI_TIMEOUT` 또는 EC2 대기 초과 | 504 | ✓ |
| `AI_GENERATION_FAILED` | AI07 `success:false`(기타) | 502 | AI07 `retryable` |
| `AI_RESPONSE_INVALID` | 200 이지만 본문 없음/해석 불가 | 502 | ✓ |
| `AI_UPSTREAM_UNAVAILABLE` | 404/405/5xx/연결 실패 | 503 | ✓ |
| `AI_REQUEST_REJECTED` | AI07 400/422 | 400/422 | ✗ |
| `AI_UPSTREAM_AUTH` | AI07 401/403 | 502 | ✗ |
| `RECOMMENDATION_IN_PROGRESS` | 같은 대상 추천 생성 중 | 409 | ✓ |
| `RECOMMENDATION_RATE_LIMITED` | 사용자별 10분 20회 초과 | 429 | ✓ |
| AI07 측 권장 `errorCode` | `AI_TIMEOUT`, `AI_MODEL_UNAVAILABLE`, `AI_RESPONSE_PARSE_FAILED`, `PDF_TEXT_EMPTY`, `PDF_TEXT_INSUFFICIENT`, `UNKNOWN_ERROR` | — | — |

브라우저 오류 본문: `{"status", "code", "message", "retryable", "requestId", "upstreamCode?"}` + 헤더 `X-Request-ID`, retryable 이면 `Retry-After: 5`.

---

## 8. 저장·평가 (EC2)

- 테이블 `learning_recommendations`(신규): 출처(`source_kind`), 유형, 근거(`evidence_json`), 순위 근거(`score_json`), 검증 필요(`verification_required`, `verification_note`), 생성기(`RULE|AI`), 모델(`model_provider`, `model_name`), `contract_version`, 상태 `GENERATED → ACCEPTED/REJECTED → COMPLETED` (+ `DISCARDED`), `dedup_key`(사용자별 unique), `presented_count`, `request_id`, 시각(`created_at/decided_at/completed_at`).
- 승인 = 조건부 UPDATE(`GENERATED→ACCEPTED`) 1건만 성공 → 같은 추천으로 플래너가 두 번 생기지 않는다. 확인 필요 추천은 사용자가 명시적으로 확인 체크해야 승인된다.
- 지표(`GET /api/recommendations/metrics`, 사용자 본인):
  - `AcceptanceRate = N_accepted / N_presented`, `CompletionRate = N_completed / N_accepted`
  - 중복률 = 재제시 횟수 / 총 제시 횟수, 환각률 = (`UNKNOWN_EVIDENCE`+`UNVERIFIED_TOC`+`UNKNOWN_NODE`) / AI 후보, 근거 일치율 = 검증 통과 AI 후보 / AI 후보
  - 표본이 0 이면 `null`(수치를 만들지 않음).

---

## 9. AI07 작업 목록(인수인계)

1. `POST /api/ai/recommendation/task`, `/roadmap-candidates`, `/document` 구현(§3·§4·§6). Ollama 만 사용, 25s 내 응답, 실패는 200 `success:false`.
2. `/api/ai/feedback` 에 `schema_version=concept_review_v1` 지원(§2.2). 요청에 없으면 기존 응답 유지(하위 호환).
3. 새 라우트 Bearer 키 검증(§1.2), `X-Request-ID` 로그·응답 반영.
4. `/api/ai/feedback` 의 실제 모델 경로 확인 — 유료 API(GPT)면 Ollama 로 전환 또는 운영자 승인.
5. `/openapi.json` 에 새 라우트 노출(EC2 route-gate 가 확인 가능하도록). 배포 후 `scripts/ai-route-gate.sh` 의 REQUIRED 목록에 추가 요청.
6. 계약 테스트: 아래 §10 벡터를 pytest 로 고정.

## 10. 계약 검증 벡터(AI07 pytest 권장)

| # | 입력 | 기대 |
|---|---|---|
| T1 | task, `progress.completed=false`, 계획 "2장 학습하기" | `NEXT_CHAPTER` 없음, 현재 장 과제 |
| T2 | task, `textbook=null`, 완료 | `NEXT_CHAPTER` 를 내더라도 `chapter.title=null` (EC2 는 어차피 버림) |
| T3 | task, `tocVerified=true` | `NEXT_CHAPTER.chapter` 가 `toc` 항목과 정확히 일치 |
| T4 | 모든 라우트 | `evidenceIds ⊆ evidence[].id` |
| T5 | roadmap, 순환을 만드는 간선 | 제안하지 않음(EC2 는 전체 간선 폐기) |
| T6 | roadmap, `mastery` 전부 null | 숙련 판정 문구 없음 |
| T7 | document | "주차/로드맵 단계" 표현 없음 |
| T8 | feedback concept_review_v1, "ViewModel 은 Activity 간 자동 유지" | `misconceptions` 에 ViewModelStoreOwner 범위, `missingKnowledge` 에 구성 변경 vs 프로세스 종료·SavedStateHandle |
| T9 | Ollama 중지 | 200 `success:false, errorCode:"AI_MODEL_UNAVAILABLE"`, 유료 API 호출 0 |
| T10 | 같은 `requestId` 재요청 | 같은 결과(선택) |

EC2 측 동일 시나리오는 `backend/src/test/java/com/studybridge/api/service/recommendation/*`, `MaterialFeedbackServiceTest` 에 고정되어 있다.

## 11. 플래그 ON 절차

1. AI07 배포 → `curl -s :18000/openapi.json | jq '.paths | keys'` 로 3개 라우트 확인.
2. EC2 스테이징(로컬 Spring, 스크래치 DB)에서 `AI_RECOMMENDATION_ENABLED=true` 로 §10 벡터 확인.
3. compose 는 이미 배선됨(기본 `false`). 운영 루트 `.env` 에 `AI_RECOMMENDATION_ENABLED=true`(및 `AI_FEEDBACK_CONCEPT_REVIEW_ENABLED=true`)만 추가 후 `docker compose up -d --no-deps --force-recreate spring`(재기동 ~26초 502 창 주의).
4. 1주 관찰: `GET /api/recommendations/metrics` 의 환각률·근거 일치율, Spring 로그 `[AI-REC]`.
5. 이상 시 플래그 OFF(재배포 없이 env 변경 + 재기동) → 규칙 추천만으로 즉시 복귀.

## 변경 이력

- v1 (2026-10-13): 최초 작성. feedback concept_review_v1, task/roadmap/document 추천, plan_analysis 책임 경계.
