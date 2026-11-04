# Learning Loop / Quality Gate / Training — EC2 canonical v1 + Phase C 통합 인계

- 작성: 2026-11-04, EC2 세션(브랜치 `feature/learning-loop-ec2`, 격리 worktree). Phase C(ai07 Phase B 결과 반영) 갱신 포함.
- 기준: `origin/LLM-clean` = `13dae5e4ddf76d040e978c1a4fc29e6ece53f0e2` (Phase C 시작 시 재확인)
- ai07 PR #116: OPEN·미병합, head `d7346fc6434cae30af9c1ee68762cb70935f6d86` (Phase C 시작 시 `gh pr view` 확인). 병합·수정하지 않았다.
  ai07 원문 인계: `fastapi/docs/ai-contracts/학습루프_PhaseB_ai07_인계.md`(feature/learning-loop-ai07).
- EC2 PR #117: OPEN·Draft·미병합(Phase C 시작 head `b14b0e83`). 최신 head 는 PR 본문 참고.
- 운영 반영: **없음**. 배포·운영 DB DDL/DML·컨테이너 재시작·ai07/Ollama/Nginx 변경 없음. 모든 신규 기능 기본 OFF.

## 0. Phase C 에서 바뀐 것(요약)

| 항목 | 결과 | 위치 |
|---|---|---|
| C-TIME-3 동의 시각 9시간 미래 | 수정. 동의·철회 행 시각 = 실제 UTC 순간(`Instant`→timestamptz), 사용자 단위 단조 증가(advisory lock) | `AiTrainingConsent`, `TrainingConsentService` |
| C-SIG-2 철회·삭제·피드백 서명 | 구현. training-control.v1 본문을 outbox 에 원시 바이트로 저장, 보낼 때 같은 바이트에 서명 | `TrainingControlV1`, `TrainingOutboxWriter`, `TrainingOutboxDispatcher` |
| 디스패처 응답 판정 | 409 = 성공 아님(샘플 DEAD, 제어 메시지 CONFLICT + 같은 issuedAt 로 새 eventId 재발행), 503/429 = Retry-After 하한 재시도, 200 은 status 로 최종 여부 판정 | `TrainingOutboxDispatcher.classify` |
| 재동의 바인딩 | 샘플에 `consent_id`(만든 동의 행) 저장 → 전송 직전 현재 유효 동의 행과 다르면 취소 | `AiTrainingOutbox.consentId` |
| 회원 탈퇴 훅 | `TrainingConsentService.onAccountDeleted` (철회 + 사용자·자료 단위 삭제 요청). Spring 에 탈퇴 흐름이 없어 호출처 없음 | B-ACCOUNT |
| 피드백 | `TrainingCandidateCollector.onAnswerFeedback` + FEEDBACK 전송(대상 샘플 전송 전이면 미룸). 좋아요/싫어요 엔드포인트 없음 → 호출처 없음 | — |
| Bearer 누락 | 0. `intentRouterWebClient`, `PdfExtractionService`(`/api/extract`·비전 폴백) 추가 | `WebClientConfig`, `PdfExtractionService` |
| 계약 경계 C-TIME-2/C-JSON-1/C-JSON-2 | 수정. 차등 605건 **605 일치**(판정·displayable 모두) | `ContractJson` |
| isDisplayable 방어선 | 내부에서 `validate(output)` 재실행(계약 위반 APPROVED 6건이 true 를 내던 결함) | `ResponseQualityV1` |
| 노출 경로 | 누락 5개 등록 + 자료 피드백 2개 게이트 연결 → **GATED 5 / BLOCKED 40 / EXEMPT 1 (46)** | `AiQualityGateCoverage` |
| 외부 전송 차단 시 Spring 처리 | 비전 `VISION_ANSWER_DISABLED` → 재시도 불가 `SCREEN_AI_DISABLED`, 피드백 `success:false AI_UNAVAILABLE` → 기존 보존 실패 | `VisionUpstreamClient`, `MaterialFeedbackService` |

## 1. canonical 3계약(EC2 owner)

정의 위치(코드가 정본): `backend/src/main/java/com/studybridge/api/ai/contract/v1/`
fixture·기대값: `backend/src/test/resources/ai-contracts/v1/` (`expectations.json` = canonical 결과 + ai07 관측값 + 해소 이력)

| 계약 | Java | ai07 adapter | fixture |
|---|---|---|---|
| learning-context.v1 | `LearningContextV1` | `app/contracts/learning_context_v1.py` | 9 + ec2 3 |
| response-quality.v1 | `ResponseQualityV1.Input/Output` | `app/contracts/response_quality_v1.py` | 8 + ec2 3 |
| training-sample.v1 | `TrainingSampleV1` | `app/contracts/training_sample_v1.py` | 6 + ec2 2 |
| training-control.v1 (Phase C) | `TrainingControlV1` | `app/training_pipeline/control.py` | 실제 전송 요청 교차 검증(§10) |

공통 규칙(EC2 canonical, ai07 d7346fc6 와 동일):
- 모르는 필드 거부. JSON 타입 엄격(문자열↔숫자·실수→정수 강제변환 금지, C-TYPE-1). 식별자 전체 일치·끝 개행 불허(C-ID-1).
- 시각: 오프셋 필수(C-TIME-1). **연도 0001..9999 — 문자열에 적힌 오프셋 기준 연도, epoch 숫자는 UTC 연도**(C-TIME-2; Java 는 오프셋을 보존해 파싱).
- **중복 키 거부**(C-JSON-1, `STRICT_DUPLICATE_DETECTION`). **고립 서러게이트 거부**(C-JSON-2 — 파싱 경로와 생성 경로 `TrainingSampleV1.validate` 모두).
- 길이는 코드포인트. 신뢰 등급 상한·`materialId`(정수) ≠ `documentId`(문자열), `contentHash` 규칙은 이전과 같다.
- 그대로 받는 것(두 쪽 동일, 바꾸려면 함께): 시각 문자열 앞뒤 공백, `+0900`/`+09` 오프셋, epoch 숫자/숫자 문자열.

승인(사용자 노출) 단일 규칙 — `ResponseQualityV1.isDisplayable(output, expectedRequestId)` = ai07 `is_displayable`:
`validate(output) 통과 && success && verified && qualityStatus==APPROVED && 80<=score<=100(NaN/Inf 불가) && minimumScore ∈ {null, 80} && hardFail==false && HARD 위반 0 && mandatoryValidatorsPassed!=false && schemaVersion·requestId 일치`.
- **minimumScore 확정**: null 또는 80 허용(ai07 평가기는 항상 80 을 채운다). 승인 기준은 언제나 수신측 상수 80 — 평가기가 70 을 보내도 승인 불가(테스트 고정).
- 80 은 자체 rubric 점수이지 정답 확률이 아니다. 사람 검수 gold 미측정 → 서비스 정확도 주장 금지.

교차 점검(2026-11-04 Phase C, 이 세션에서 실행):
- `tools/crosscheck_pydantic.py` × ai07 d7346fc6: **fixtures=30 mismatches=0**(기존 FAIL 4건 C-ID-1/C-TYPE-1/C-RQ-2/C-TIME-1 해소). `ContractV1FixturesTest` 의 열린 이슈 목록 = `Map.of()`.
- 서명 벡터: ai07 이 `scope_token_as_consent` 기대값을 `CONSENT_TOKEN_TYPE_INVALID` 로 갱신(C-SIG-1 해소) → EC2 사본 교체, 테스트 오버라이드 제거.
- 차등 605건(ai07 `cases.v1.jsonl` + ai07 `ContractDiffHarness.java` 로 EC2 작업 트리 Java 판정 vs ai07 `python_verdicts.py`):
  수정 전 **판정 598 일치 / 7 불일치**(C-TIME-2 4, C-JSON-1 2, C-JSON-2 1) + displayable 6건 불일치(Java isDisplayable 이 계약 위반 출력에 true) →
  수정 후 **605/605 일치(판정·displayable 모두)**. ai07 은 `known-divergences.v1.json` 의 divergences 를 비우고 `java-verdicts.v1.jsonl` 을 재생성해야 한다(ai07 소유 파일 — EC2 는 수정하지 않음).

## 2. 서명·헤더(바이트 단위 — `AiContractSigning`, 벡터 `signing-vectors.v1.*`)

| 헤더 | 발급 | 형식 | 키 env |
|---|---|---|---|
| `Authorization` | Spring(모든 ai07 호출) | `Bearer <AI_SERVER_API_KEY>` | AI_SERVER_API_KEY |
| `X-AI-Contract-Signature` / `-Timestamp` | Spring | `v1=` + hex(HMAC-SHA256(key, ascii(ts) + "." + RAW_BODY)), ts=unix초, ±300s | AI_TRAINING_SAMPLE_SIGNING_KEY |
| `X-AI-Scope` | Spring(DB 소유권 확인 후) | b64url(json).b64url(HMAC), `{v:1,typ:"ai-scope",sub,materialIds,documentIds,iat,exp,rid}` | AI_SCOPE_SIGNING_KEY |
| `X-AI-Training-Consent` | Spring(동의 DB 확인 후, collect-v1 만) | 같은 형식, `{v:1,typ:"training-consent",sub,cv,ct,scope[],rights{},dtid,rid,iat,exp}` | AI_TRAINING_CONSENT_SIGNING_KEY |
| `X-Request-Id` | Spring | `[A-Za-z0-9._:-]{8,128}`. 학습 경로에서는 = eventId | — |

- 키: 32바이트 이상, 용도별로 서로 다르고 Bearer 와도 달라야 한다(fail-closed). `AI_PSEUDONYM_SECRET` 은 EC2 전용.
- 토큰 TTL ≤ 600s, iat ≤ now+30s, typ·rid 바인딩 필수. JSON 직렬화는 Python `json.dumps(sort_keys, compact, ensure_ascii)` 와 바이트 동일.
- 벡터(Java): 본문 5/5, scope 6/6, consent 4/4(오버라이드 없음), TSV 4/4.
- **training-control.v1**(철회·삭제·피드백, C-SIG-2): Bearer + 본문 서명(샘플과 같은 키) + `X-Request-Id = eventId`. 동의 토큰은 싣지 않는다.
  - 공통 `{schemaVersion:"training-control.v1", typ:"training-control", messageType, eventId, issuedAt}` — issuedAt 은 사건의 실제 UTC 순간(마이크로초, `Z`).
  - CONSENT_WITHDRAWAL `+ pseudonymousUserKey, scope:["MODEL_TRAINING"]` / DELETION `+ deletionTrackingId`(가명 키는 보내지 않음 — 최소 전송) /
    FEEDBACK `+ pseudonymousUserKey, candidateEventId(EC2 는 항상 이쪽), score ∈ {-1,0,1}, reasonCode?`.
  - eventId: `cw-|dl-|fb-` + UUID(전역 유일, 환경 간 충돌 없음). 재시도 = 같은 행·같은 바이트·같은 eventId, 헤더 timestamp 만 새로.
- 회전: ai07 이 {현재, 이전} 키를 함께 검증하도록 먼저 배포 → EC2 값 교체 → 유예 후 이전 키 제거. `AI_PSEUDONYM_SECRET` 회전 금지(lineage 재매핑 미지원).

## 3. 사용자 실패 계약(Spring → React)

| errorCode | 의미 | 경로별 표현 | retryable |
|---|---|---|---|
| `AI_QUALITY_REJECTED` | 평가 미승인(79↓, hardFail, HARD 위반, 재생성 소진, 동일 초안 반복, 거절 쿨다운 중) | 요약: JSON 200 `success:false,qualityStatus:REJECTED` / 피드백: HTTP 422 오류 본문 / SSE: `agent_error code=QUALITY_REJECTED` | true |
| `AI_QUALITY_UNAVAILABLE` | 평가 불가(timeout/503/429/서킷/계약 위반 응답/200+success:false) | 요약: JSON 200 `qualityStatus:VALIDATION_ERROR` / 피드백: HTTP 503 / SSE: `code=QUALITY_UNAVAILABLE` | true |
| `AI_QUALITY_GATE_NOT_WIRED` | 게이트 ON 인데 미연결 경로 | HTTP 503(인터셉터) | false |

실패해도 기존 저장본(요약·피드백)은 덮어쓰지 않는다. 평가 사유 원문은 사용자에게 보이지 않는다(위반 코드만 로그).

## 4. multi-chat SSE 게이트 계약(`QualityStreamGate`, 학습메이트 studymate-sse-2)

Phase B 이후 변경 없음. 진행 이벤트는 식별자 allowlist 로 재구성, 본문 이벤트는 메시지 단위 평가 후 승인분만, 델타 미방출, `all_complete` 는
승인 항목만 재구성, `qualityGateMode:"spring-v1"`, 게이트를 영속화 앞에 둔다(거절 초안 DB/Redis 0), concatMap 순서 보존, 취소 전파.
ai07 권고(성능, 미적용 — 다음 단계): all_complete 항목이 같은 에이전트의 승인 필드와 완전히 같으면 판정 재사용(ai07 측 6→3회, 3.61s→1.81s 합성),
상류 prefetch 로 생성·평가 겹치기. Spring bulkhead 2 = ai07 세마포어 2 → 동시 16 스트림이면 절반 429(QUALITY_UNAVAILABLE).

## 5. 경로 매트릭스(단위 = Spring 공개 엔드포인트, ai07 OpenAPI 수와 혼동 금지)

`AiQualityGateCoverage.ROUTES` 46개(컨트롤러 매핑과 리플렉션 일치 검증):
- **GATED 5**: 학습메이트 SSE `POST /api/agent-rooms/{roomId}/chat/stream`, 이력 `GET .../history`(미검증 행 가림), PDF 요약 `GET /api/materials/{id}/summary`,
  **자료 피드백 `GET /api/materials/{id}/feedback`, `POST .../feedback/regenerate`**(Phase C: GENERAL_EXPLANATION + 자료 원문 근거, 재생성 ≤2,
  승인분만 저장 `material_feedbacks.quality_status`, 미승인 레거시 저장본 미노출, 거절 쿨다운 120s, 생성 실패는 기존 계약).
- **BLOCKED_WHEN_GATE_ON 40**: Phase B 의 37 − 피드백 2 + Phase C 추가 5(`POST /api/groups/{groupId}/materials/upload-quiz`,
  `GET /api/materials/{id}/recommendations`, `GET /api/planners/{id}/recommendations`, `POST /api/materials/{id}/plan-recommendation`,
  `POST /api/materials/{id}/study-journals` — 거절 사유 reason/suggestion 이 AI 판정 문구).
- **EXEMPT 1**: `GET /api/study-time/predict`.
- 등록하지 않은 것: `POST /api/materials/upload` — 응답에 AI 텍스트가 없고, 백그라운드 학습노트는 `GET .../study-note`(BLOCKED)로만 노출.
- ai07 분담(인계 5.1): Spring 만 24 / ai07 만 2 / 양쪽 11. 남은 40 중 근거가 응답에 없는 경로(그룹 퀴즈·자료 질문·비전·학습노트)는
  ai07 근거 반환 변경 전에는 연결해도 거의 모두 REJECTED 가 된다. 로드맵(약 15만 자) > proposedOutput 상한 6만 자 → **v2 계약(주 단위 분할 평가 + 로드맵 TaskType) 필요, EC2 owner 설계 대상, 미착수**.
- **운영 ON Go 조건: BLOCKED_WHEN_GATE_ON = 0** (현재 40 → No-Go).

## 6. 내부 인증(Bearer) · enforce 전환

- Spring→ai07 Bearer 누락 **0**: 공용 `fastApiWebClient`(PRIMARY·SECONDARY 모두), `intentRouterWebClient`(Phase C), `PdfExtractionService`
  RestTemplate 의 `/api/extract`·비전 폴백(Phase C)·RAG ingest, `VisionUpstreamClient`·`AdaptivePlannerClient`(호출별 헤더). 값은 서버 env 만, 로그·브라우저 미노출.
- Secondary 키: 2026-11-04 읽기 전용 확인 — Spring 컨테이너 `AI_SERVER_API_KEY`(64자)와 EC2 Secondary(:8000, hotfix_main) 프로세스 키가 **일치**
  (값 비교만, 출력 없음). ai07 인계의 "64자 ≠ 27자" 는 과거 메모 기준이며 현재는 해당 없음. 운영 설정은 바꾸지 않았다.
- enforce 순서(운영 승인 필요, 미실행): ① PR #117 배포(Bearer 누락 0) → ② ai07 ops 재설치(헬스체크·카나리·라우트 게이트 Bearer) →
  ③ EC2 쪽 `cd.yml` 의 `ai-route-gate.sh http://127.0.0.1:8000`(302행), `studybridge-ai-route-verify.service/.timer`, light/medium healthcheck 에
  `AI_ROUTE_GATE_AUTH_HEADER_FILE`(0600) 주입 — ai07 PR 의 스크립트 변경 병합이 선행 → ④ report 로그 COMPAT_TOLERATED_MISSING/INVALID 0 을 24h 확인
  → ⑤ `AI_INTERNAL_AUTH_MODE=enforce`, `AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST=` (빈 값). Secondary 가 PR #116 코드를 받지 않으면 Secondary 는 계속 무인증(별도 결정).
- NetworkGuard·loopback 은 인증을 대체하지 않는다. Secondary 0.0.0.0:8000 바인딩 축소(127.0.0.1/docker 브리지)는 운영 변경이라 미실행 — SG 확인과 함께 승인 필요.

## 7. 외부(OpenAI 등) 전송 정책 — **BLOCKER(정책 미결정)**

- ai07 PR #116 은 `AI_EXTERNAL_EGRESS_ENABLED=false`(기본) + `AI_EGRESS_ALLOW` 목록으로 OpenAI/Tavily/Wikipedia/OpenAlex 를 기본 차단하고 로컬 Qwen 으로 대체한다.
  **배포하면 학습일지 판정·전공분석 OCR/노트·요약 이미지 경로·퀴즈/로드맵 보강·비전 답변의 출력/지연/실패 유형이 바뀐다.** EC2 는 허용 목록을 자동으로 켜지 않았다.
- Spring 처리 확인(Phase C, 테스트 고정): 비전 `503 VISION_ANSWER_DISABLED` → `SCREEN_AI_DISABLED`(재시도 불가, 예전엔 재시도 권유 502),
  피드백 `success:false AI_UNAVAILABLE` → `AI_GENERATION_FAILED`(기존 피드백 보존, 안내문을 피드백으로 저장하지 않음). 학습일지 검증은 응답 계약이 같아 코드 변경 없음
  (`STUDY_JOURNAL_LOCAL_JUDGE_ENABLED=false` 면 ai07 이 판정 불가 → Spring 저장 보류 경로).
- 결정 필요(운영·법무·보안): 기능별로 어떤 데이터(메모·PDF 본문/이미지·대화)를 어느 사업자·국외로 보낼지, 처리방침·동의 UI, 학습일지 최종 판정자(OpenAI vs 로컬).
  결정 전에는 PR #116 배포 보류가 안전하다. 가입 체크박스 "[필수] AI 제3자 제공 및 위탁 동의"는 서버에 기록되지 않는다(기존 결함).
- 로컬 대체 품질 E2E(실 ai07 + Ollama): **UNVERIFIED** — 이 세션은 ai07·GPU 에 접근하지 않았다. ai07 합성 측정(학습일지 14/14 등)은 ai07 인계서 6.2 참고.

## 8. 학습 후보 흐름(EC2)

사용자 요청 → AI 초안 → 품질 평가 → **APPROVED** → 노출 → **MODEL_TRAINING 동의(현재 버전, 동의 행 id 고정)** → training-sample.v1 → outbox(커밋 후, eventId 멱등)
→ 디스패처(서명 + 동의 토큰) → ai07 collect-v1 → NEEDS_REVIEW → (ai07) TRAIN_ELIGIBLE → (별도 승인) QLoRA.
- A 노출 승인 / B 동의 / C 정답 검증 / D 학습 실행 승인은 서로 대체하지 않는다. 80점·피드백으로 자동 승격 금지(`qualityLabel=UNLABELED`).
- 권리: 업로드 PDF → `THIRD_PARTY_UNVERIFIED`, 대화 → `UNKNOWN` → 어떤 후보도 TRAIN_ELIGIBLE 불가(B-RIGHTS, 의도된 보수 동작).
- **시각(C-TIME-3 수정)**: 동의·철회 행 `created_at` = 실제 UTC 순간(timestamptz, 마이크로초). 같은 사용자 안에서 동의 < 철회 < 재동의 가 항상 성립
  (트랜잭션 advisory lock + 직전 행보다 1µs 이상 늦게, 시계 역행에도). 샘플 `consentTimestamp` = 토큰 `ct` = 동의 행 순간, 철회 `issuedAt` = 철회 행 순간.
  같은 버전 재동의 클릭은 새 행을 만들지 않는다(기존 후보의 동의 바인딩 유지). Asia/Seoul·UTC·America/New_York(DST)·Australia/Lord_Howe(30분 DST) JVM TZ 에서 검증.
  운영 영향 감사: `ai_training_consents` 는 PR 미병합·미배포라 운영 RDS 에 없다(코드·배포 이력 근거, RDS 조회 안 함) → 소급 보정 대상 0.
- 철회: WITHDRAWN 행 + 미전송 샘플 즉시 취소·원문 삭제 + CONSENT_WITHDRAWAL 적재(같은 트랜잭션 — 적재 실패면 철회 자체를 롤백, 503).
- 자료 삭제: 미전송 샘플 취소 + DELETION(자료 단위 deletionTrackingId).
- 회원 탈퇴(`onAccountDeleted`, 호출처 없음 — B-ACCOUNT): 미전송 샘플·피드백 취소 → 동의 중이면 WITHDRAWN 행 → CONSENT_WITHDRAWAL + DELETION(사용자 단위 dtid
  + 한 번이라도 전송 시도된 샘플의 자료 단위 dtid). 탈퇴 구현 시 반드시 같은 트랜잭션에서 호출.
- 피드백(`onAnswerFeedback`, 호출처 없음): 대상 = 같은 (사용자, 작업, 질문, 답변) 샘플. 미전송 샘플에 부정 피드백 → 보내지 않고 취소. 그 밖에는 FEEDBACK 적재,
  대상 샘플이 PENDING/IN_FLIGHT 면 디스패처가 미룬다(시도 횟수 미소모).
- 디스패처 판정(ai07 d7346fc6 라우트 기준): 제어 메시지 먼저(tombstone 우선) → 샘플.
  200 + 최종 status(샘플: STORED/QUARANTINED/DUPLICATE/NEAR_DUPLICATE/IDEMPOTENT_REPLAY/REJECTED_*, 철회: CONSENT_WITHDRAWN, 삭제: DELETED,
  피드백: FEEDBACK_RECORDED/NOT_FOUND) → SENT(`result_status` 기록, 원문 삭제). 200 DEFERRED/모르는 status/본문 없음 → 재시도.
  409 EVENT_ID_CONFLICT → 샘플 DEAD / 제어 메시지 CONFLICT + 같은 내용·같은 issuedAt 로 새 eventId 재발행. 그 밖의 409(처리 경합) → 재시도.
  503/429/5xx/404/401/403/timeout → 지수 백오프+지터(Retry-After 하한, 상한 1h). 400/413/422 → 샘플 DEAD, 제어 메시지는 DEAD 없이 계속 재시도 + ERROR 로그.
  서명 키 미구성 → 미전송·시도 미소모. lease 만료 IN_FLIGHT 는 다른 워커/재시작 후 인수(같은 eventId — ai07 원장 1회 처리).
- 이미 학습된 가중치는 지워지지 않는다 → ai07 manifest INVALIDATED + adapter RETIREMENT_REQUIRED.

## 9. 플래그·설정·스키마·롤백

| env | 기본 | 위치 |
|---|---|---|
| AI_RESPONSE_QUALITY_GATE_ENABLED | false | AiQualityGateSettings |
| AI_QUALITY_MAX_REGENERATIONS / AI_QUALITY_EVALUATE_TIMEOUT_MS / AI_QUALITY_EVAL_MAX_CONCURRENCY / AI_QUALITY_EVAL_QUEUE_WAIT_MS | 2 / 8000 / 2 / 2000 | 〃 |
| AI_QUALITY_CIRCUIT_FAILURE_THRESHOLD / AI_QUALITY_CIRCUIT_OPEN_MS | 5 / 30000 | 〃 |
| AI_SCOPE_SIGNING_KEY / AI_TRAINING_CONSENT_SIGNING_KEY / AI_TRAINING_SAMPLE_SIGNING_KEY / AI_PSEUDONYM_SECRET | 비어 있음(=기능 거부) | AiSigningKeys |
| AI_TRAINING_COLLECTION_ENABLED / AI_TRAINING_OUTBOX_DISPATCH_ENABLED | false / false | AiTrainingSettings |
| ai.training.feedback-path | /api/training-candidates/feedback | 〃 (Phase C) |

- 값 주입: `/home/ubuntu/.studybridge-secrets/spring.env`(compose env_file, 600).
- 스키마(배포 = ddl-auto 가 ALTER/CREATE 실행 = **운영 RDS 변경**, 승인 + 스냅샷 필요): 승인 요청서 SQL `backend/src/main/resources/db/migration/V20261104_2__ai_quality_training_schema.sql`
  (Phase C: `material_feedbacks.quality_status/quality_score` 추가, `ai_training_*` 시각 timestamptz, `kind` 32자, `consent_id`, `result_status`). 전부 nullable 컬럼 또는 신규 테이블.
  롤백 = 앱 롤백(컬럼 무시). 필요 시 같은 파일 하단의 DROP 문(신규 테이블에 동의·철회 행이 있으면 감사 근거 소실 → 데이터가 있으면 DROP 금지, 플래그 OFF 로만 롤백).
- 기능 롤백 = 플래그 OFF. 보안 fail-closed(키·서명·소유권)는 플래그로 우회하지 않는다.
- Canary(승인 후, 미실행): ① ai07 evaluator 배포(평가기만 ON) → ② EC2 키 4종 주입, 게이트 OFF 섀도 평가(별도 구현) → ③ 내부 계정 한정 ON → ④ BLOCKED 0 확인 후 전체 ON.

## 10. 테스트(EC2, 2026-11-04 Phase C) — 실측/합성 구분, 최신 수치는 PR 본문

- 계약: `ContractStrictParsingTest`(C-TIME-2 경계·오프셋 보존·중복 키 최상위/중첩·고립 서러게이트·생성 경로·isDisplayable 재검증·minimumScore null/70),
  fixture 30/30, 열린 이슈 0, 서명 벡터 오버라이드 0. 차등 605/605(위 §1, 스크립트 실행 실측).
- 학습 파이프라인(PG 16 일회용): TZ 4종 동의 시각, 시계 역행 단조성, 같은 버전 재동의 멱등, training-control.v1 서명·바이트 동일·X-Request-Id 바인딩·직접 식별자 0,
  재시도 = 같은 바이트·eventId + 새 timestamp, Retry-After 하한, 409 제어 재발행(같은 issuedAt)·409 샘플 DEAD·처리 경합 409 재시도, 200 DEFERRED/무상태 재시도,
  REJECTED_* 최종, 제어 우선·재동의 샘플 consentTimestamp > 옛 철회 issuedAt, 탈퇴 → 철회 + 삭제 2건, 피드백 미룸/부정 취소/대상 없음, lease 인수, 제어 422 비DEAD.
- **ai07 Python 교차 검증(실측)**: `TrainingPipelinePostgresTest.dumpRealRequestsForAi07Verification`(JVM TZ=Asia/Seoul)이 실제로 보낸 5개 요청을
  `tools/verify_training_requests_ai07.py` 가 ai07 d7346fc6 의 `verify_body`·`parse_sample_json`·`verify_consent_token`·collect-v1 동의 판정·`verify_control` 로 판정
  → **5/5 ACCEPT**(SAMPLE 2, FEEDBACK, DELETION, CONSENT_WITHDRAWAL). 같은 바이트를 다른 제어 라우트로 보내면 CONTROL_MESSAGE_TYPE_MISMATCH, 1바이트 변조는 401.
  ai07 FastAPI 라우트·DB 를 띄운 왕복 E2E 는 **SKIP**(ai07 원장/tombstone 동작은 ai07 테스트 소관).
- Bearer: `FastApiInternalAuthHeaderTest` 5(공용·intent router·PDF 추출+비전 폴백, 키 없음 = 헤더 없음).
- 게이트: 자료 피드백 7(79→85 승인 저장·전부 거절 저장 0·평가기 503 미노출·레거시 미노출·승인 캐시 AI 0·쿨다운·생성 실패 기존 계약·OFF 회귀 없음).
- egress: 비전 VISION_ANSWER_DISABLED, 피드백 AI_UNAVAILABLE.
- 전체 백엔드·CI·스키마 dry-run 수치: PR 본문 표 참고.
- 성능: Phase C 에서 새로 측정하지 않았다(Phase B 합성 수치 그대로, 운영 실측 아님). GPU P50/P95·자원 경합 **미측정**.
- 품질 수치: gold benchmark **PREPARED_NOT_MEASURED**(ai07). FAR/FRR·95% CI 주장 없음.

## 11. 남은 작업 · blocker · Go/No-Go

ai07(다음 단계):
1. `known-divergences.v1.json` 비우기 + `java-verdicts.v1.jsonl` 재생성(EC2 head 기준 605/605) + `test_meta_marks_ec2_as_canonical_owner` 유지.
2. 근거 반환: 그룹/자료 퀴즈(청크·페이지), `/api/ai/question`(청크 본문·chunkId/page), 비전(마스킹된 판독 근거), 학습노트(페이지별 원문).
3. 에이전트별 재생성 API(선택), all_complete 판정 재사용 규칙의 계약화.
4. enforce 전환 전 ops 재설치·report 카운터 0 확인(§6), 외부 전송 정책 결정 후 `AI_EGRESS_ALLOW` 설정(§7).
5. 학습 DB 001→003 은 RDS 스냅샷·DB 담당 승인 후(EC2 는 RDS 변경 안 함).

EC2(다음 단계):
1. BLOCKED 40 연결: Spring 만 경로부터(오답노트 저장본 마스킹·마인드맵 캐시·플래너 assist 등), 그룹 SSE 는 `QualityStreamGate` 재사용.
2. 로드맵 v2 계약(분할 평가) 설계·ai07 합의, `X-AI-Scope` 실제 발급 경로, 사용자별 평가 rate limit, all_complete 판정 재사용(성능).
3. 회원 탈퇴 흐름 구현 시 `onAccountDeleted` 호출, 좋아요/싫어요 UI 추가 시 `onAnswerFeedback` 호출.

Blockers: B-RIGHTS(권리 확인 UI 없음), B-ACCOUNT(탈퇴 흐름 없음), B-EGRESS(외부 전송 정책 미결정), B-NGINX(직접 경로 없음 확인 — 해소 판정은 SG 확인 후),
게이트 미연결 40, 로드맵 v2 계약, gold benchmark 미측정, 미성년자 법정대리인 동의 미구현, enforce 전 ops 재설치.

**Go/No-Go: No-Go**(운영 배포·게이트 ON·학습 수집 ON 모두). 두 PR 모두 병합 금지 상태 유지.
