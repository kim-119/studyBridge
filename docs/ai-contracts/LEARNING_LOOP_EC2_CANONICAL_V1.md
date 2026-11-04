# Learning Loop / Quality Gate / Training — EC2 canonical v1 + ai07 Phase B 인계

- 작성: 2026-11-04, EC2 세션(브랜치 `feature/learning-loop-ec2`, 격리 worktree)
- 기준: `origin/LLM-clean` = `13dae5e4ddf76d040e978c1a4fc29e6ece53f0e2` (작업 시작 시 fetch 확인)
- ai07 PR #116: OPEN·미병합, head `a4bd8fac69884405555ab839e8e1d547ac5d7672` (2026-11-04T03:23Z `gh pr view` 확인). 이 PR 은 병합·수정하지 않았다.
- 운영 반영: **없음**. 배포·운영 DB DDL/DML·컨테이너 재시작·ai07/Ollama 변경 없음. 모든 신규 기능 기본 OFF.

## 1. canonical 3계약(EC2 owner)

정의 위치(코드가 정본): `backend/src/main/java/com/studybridge/api/ai/contract/v1/`
fixture·기대값: `backend/src/test/resources/ai-contracts/v1/` (`expectations.json` = canonical 결과 + ai07 관측값 + openIssue)

| 계약 | Java | ai07 adapter | fixture |
|---|---|---|---|
| learning-context.v1 | `LearningContextV1` | `app/contracts/learning_context_v1.py` | 9 + ec2 3 |
| response-quality.v1 | `ResponseQualityV1.Input/Output` | `app/contracts/response_quality_v1.py` | 8 + ec2 3 |
| training-sample.v1 | `TrainingSampleV1` | `app/contracts/training_sample_v1.py` | 6 + ec2 2 |

공통 규칙(EC2 canonical — ai07 PROPOSED 와 다른 점은 굵게):
- 모르는 필드 거부(extra=forbid). **JSON 타입 엄격: 문자열→숫자, 숫자→문자열, 실수→정수 강제변환 금지** (C-TYPE-1).
- 식별자 정규식은 전체 일치. **끝 개행 불허** — Python 은 `$` 대신 `\Z`/`fullmatch` (C-ID-1, learning-context 의 `_ID_RE`).
- 시각은 **오프셋 필수(ISO-8601, `Z`)** — 타임존 없는 시각 거부 (C-TIME-1).
- 길이는 코드포인트(Python `len`).
- 신뢰 등급: `trustLevel` 은 `sourceType` 상한 이하만 유효(`effectiveTrust`). PDF_ORIGINAL 만 SOURCE_PRIMARY. AI 요약/답변은 AI_GENERATED, 메모/대화는 USER_ASSERTED. `materialId`(Spring PK, 정수) ≠ `documentId`(pgvector 문자열).
- `contentHash` = SHA-256(NFKC + Python 공백 규칙 `\s+`→' ', strip, `question + "\n" + answer`). Java 공백 집합을 Python `str.isspace()` 29개 코드포인트와 일치 확인.

response-quality.v1 승인(사용자 노출) 단일 규칙 — `ResponseQualityV1.isDisplayable(output, expectedRequestId)`:
`success && verified && qualityStatus==APPROVED && score!=null && 80<=score<=100 && minimumScore==80 && hardFail==false && HARD 위반 0 && mandatoryValidatorsPassed!=false && requestId 일치`.
- **score ≤ 100 상한**(C-RQ-2: ai07 출력 모델은 100.5 APPROVED 를 통과시킴).
- **`mandatoryValidatorsPassed`(선택 bool) 추가 제안**(C-RQ-1). 없으면 hardFail/HARD 위반으로 파생.
- 80 은 자체 rubric 점수이지 정답 확률이 아니다. null/NaN/Inf/평가 실패/다른 requestId 판정 재사용 = 미노출.

### ai07 Pydantic 교차 점검 결과(실행: `tools/crosscheck_pydantic.py`, pydantic 2.13.4, ai07 PR a4bd8fac)
- fixture 30개 중 **불일치 4건 = FAIL 로 관리**(제외 아님): C-ID-1, C-TYPE-1, C-RQ-2, C-TIME-1. 나머지 26 일치. contentHash 벡터 4/4 일치.
- Java 쪽(`ContractV1FixturesTest`)은 30/30 canonical 일치, 불일치 목록이 테스트에 고정돼 있어 ai07 이 고치면 `ai07Observed` 갱신 후 목록에서 제거.

## 2. 서명·헤더(바이트 단위 — `AiContractSigning`, 벡터 `signing-vectors.v1.*`)

| 헤더 | 발급 | 형식 | 키 env |
|---|---|---|---|
| `Authorization` | Spring(모든 ai07 호출 기본값) | `Bearer <AI_SERVER_API_KEY>` | AI_SERVER_API_KEY |
| `X-AI-Contract-Signature` / `-Timestamp` | Spring | `v1=` + hex(HMAC-SHA256(key, ascii(ts) + "." + RAW_BODY)), ts=unix초(≤12자리), ±300s | AI_TRAINING_SAMPLE_SIGNING_KEY |
| `X-AI-Scope` | Spring(DB 소유권 확인 후) | b64url(json).b64url(HMAC(key, b64url(json))), `{v:1,typ:"ai-scope",sub,materialIds[int↑],documentIds[str↑],iat,exp,rid}` | AI_SCOPE_SIGNING_KEY |
| `X-AI-Training-Consent` | Spring(동의 DB 확인 후) | 같은 형식, `{v:1,typ:"training-consent",sub,cv,ct,scope[],rights{},dtid,rid,iat,exp}` | AI_TRAINING_CONSENT_SIGNING_KEY |
| `X-Request-Id` | Spring | `[A-Za-z0-9._:-]{8,128}` | — |

- 키: 32바이트 이상, 용도별 서로 다름 + Bearer 와 다름(아니면 `SIGNING_KEY_NOT_CONFIGURED`/`SIGNING_KEY_REUSED`, fail-closed). `AI_PSEUDONYM_SECRET` 은 EC2 전용(가명 키·삭제 추적 id 파생, ai07 로 안 보냄).
- 토큰: TTL ≤ 600s, iat ≤ now+30s, typ 필수, rid 바인딩 필수. 서명 비교는 상수 시간. JSON 직렬화는 Python `json.dumps(sort_keys=True, separators=(",",":"))`(ensure_ascii) 와 바이트 동일 — Java 발급 토큰이 Python 벡터 토큰과 문자 단위 동일(테스트 고정).
- 벡터 결과(Java): 본문 5/5, scope 6/6, consent 4/4, TSV raw HMAC 4/4. **C-SIG-1**: scope 토큰을 consent 로 제시하면 canonical=`CONSENT_TOKEN_TYPE_INVALID`, ai07=`CONSENT_TOKEN_EXPIRED`(둘 다 거부, 코드만 다름).
- 신원: 사용자 주체는 Spring Security principal 의 userId 에서만 파생(`PseudonymousUserKeys`: `pk_` + b64url(HMAC(secret,"studybridge:user:v1:"+id))[0..32)). 클라이언트 헤더/본문의 userId·actorId·role·consent 주장은 받지 않는다. `X-Actor-Id` 는 신원 증명이 아니다.
- 회전: ai07 이 {현재, 이전} 키를 함께 검증하도록 먼저 배포 → EC2 값 교체 → 유예 후 이전 키 제거. `AI_PSEUDONYM_SECRET` 회전은 모든 가명이 바뀌므로 ai07 lineage 재매핑이 선행돼야 한다(현재 미지원 → 회전 금지).

## 3. 사용자 실패 계약(Spring → React)

| errorCode | 의미 | HTTP/SSE | retryable |
|---|---|---|---|
| `AI_QUALITY_REJECTED` | 평가 결과 미승인(79↓, hardFail, HARD 위반, 재생성 소진, 동일 초안 반복) | JSON 200 `success:false,qualityStatus:REJECTED` / SSE `agent_error code=QUALITY_REJECTED` | true |
| `AI_QUALITY_UNAVAILABLE` | 평가 불가(timeout/503/429/서킷/계약 위반 응답/200+success:false) | JSON 200 `qualityStatus:VALIDATION_ERROR` / SSE `agent_error code=QUALITY_UNAVAILABLE` | true |
| `AI_QUALITY_GATE_NOT_WIRED` | 게이트 ON 인데 아직 게이트 미연결 경로 | HTTP 503(인터셉터, 본문 없음) | false |

기존 DTO(success/errorCode/message/retryable) 어휘를 유지하고 `qualityStatus/qualityScore/verified` 를 추가(게이트 OFF 면 null — 기존 응답과 동일). 평가 사유 원문은 사용자에게 노출하지 않는다(위반 코드만 로그).

평가기 오류 코드(로그/진단): EVALUATOR_TIMEOUT, EVALUATOR_BUSY(bulkhead/429), EVALUATOR_UNAVAILABLE(503), EVALUATOR_ROUTE_NOT_DEPLOYED(404), EVALUATOR_AUTH_FAILED(401/403), EVALUATOR_INPUT_REJECTED(413/422), EVALUATOR_IDEMPOTENCY_CONFLICT(409), EVALUATOR_OUTPUT_CONTRACT_INVALID, EVALUATOR_REQUEST_MISMATCH, EVALUATOR_CIRCUIT_OPEN, EVALUATOR_AUTH_NOT_CONFIGURED, EVALUATOR_INPUT_CONTRACT_INVALID.

## 4. multi-chat SSE 게이트 계약(`QualityStreamGate`, 학습메이트 studymate-sse-2)

- 진행 이벤트(turn_start/agent_start/stage_*/progress/heartbeat/phase_progress 등): **식별자 allowlist 만으로 재구성**(모든 이벤트에 `content` 키가 있으므로 원본 복사 금지).
- 본문 이벤트(agent_answer, debate_section, socratic_step, simulation_stage, follow_up_suggestions, direct_reply …): 메시지 단위 평가(taskType=learningMode 매핑, outputKind=agent_message). 승인 → [식별자 + 평가한 본문 필드(content/answer/question/hint/feedback/assessment + suggestions 등)] + `qualityStatus:"APPROVED"`. 거절 → `agent_error`(code/failureCode=QUALITY_REJECTED|QUALITY_UNAVAILABLE, status=FAILED, degraded, retryable, eventId/agentIndex/turnId 유지, 고정 문구).
- 델타/토큰 이벤트 미방출, 모르는 이벤트 폐기, error 계열은 코드만 유지·문구 고정.
- `all_complete`: 승인된 answers/messages 만 재구성, 그 밖의 본문성 필드(socraticSteps/plan …)는 한 덩어리로 평가해 승인 시만 포함(아니면 `qualityRedactedFields`), `agentErrors` 는 식별자만, `qualityGate:{applied,approved,rejected}`.
- 모든 게이트 프레임에 `qualityGateMode:"spring-v1"` — React 표시 경계(`utils/aiQualityDisplay.js`)가 이 턴의 미승인 본문을 2차 차단(게이트 OFF 에선 ai07 자체 `qualityStatus:"PARTIAL"` 도 기존대로 표시).
- 영속: 게이트를 영속화(doOnNext) **앞**에 둔다 → 거절 초안은 화면·DB(chat_messages)·Redis 어디에도 없음. 승인 행 `quality_status=APPROVED`. 취소 시 partial 영속도 승인분만.
- 순서 보존(concatMap), 중복(키+본문 해시) 1회, 메시지 60,000자·턴 400,000자 상한, 취소 → 진행 중 평가/상류 구독 취소. Spring 은 에이전트별 재생성 불가(ai07 API 없음) → 스트림은 attempt 0 만.
- 그룹 스터디 stream(`/api/groups/{id}/chats/stream`)은 미연결 → 게이트 ON 시 503.

## 5. 경로 매트릭스(단위 = Spring 공개 엔드포인트)

ai07 79/53/22/0 은 FastAPI OpenAPI path 단위, 여기는 Spring 엔드포인트 단위라 숫자를 맞추지 않는다. Spring→FastAPI 호출부 28곳/FastAPI path 31개(사용자 노출 ~22) 전수 추적 결과를 41개 사용자 노출 엔드포인트로 정리(`AiQualityGateCoverage.ROUTES`, 컨트롤러 매핑과 리플렉션 일치 검증):

- **GATED 3**: `POST /api/agent-rooms/{roomId}/chat/stream`(SSE), `GET /api/agent-rooms/{roomId}/history`(미검증 AI 행 가림), `GET /api/materials/{materialId}/summary`(PDF_SUMMARY, 재생성 ≤2, 승인분만 저장, 미승인 캐시 미노출).
- **BLOCKED_WHEN_GATE_ON 37**: non-stream 채팅, learning-mate, 그룹 stream/이력/퀴즈/비전, 자료 분류·퀴즈(생성·저장본·제출)·질문·로드맵·키워드·피드백·학습노트·계획분석·추천, 오답노트(생성·목록·상세·retry·review-needed·variant), 마인드맵, 플래너 assist/ai-result/plan-analysis/schedule/pdf/adaptive/recommendations.
- **EXEMPT 1**: `GET /api/study-time/predict`(숫자 예측, rubric 프로파일 없음).
- 내부(비노출): intent route, PDF extract/OCR, RAG ingest, study-journal validate(게이트 판단에만 사용), openapi probe.
- 프런트가 FastAPI 를 직접 부르는 레거시 코드(`api.js` `fastApi` 클라이언트: `/api/ai/chat`, `/agents/*`, `/activity/weekly`)는 Spring 게이트 밖이다 → 브라우저→ai07 경로 차단 여부를 nginx 에서 확인·차단 필요(인계 B-NGINX).
- **운영 ON 전환 Go 조건: BLOCKED_WHEN_GATE_ON = 0** (현재 37 → No-Go).

## 6. FastAPI 인증 없는 라우트(LLM-clean 코드 정적 집계)

- 등록 라우트 객체 80(고유 79; predict-study-time 이중 등록). Depends(verify_internal_token) 25, 핸들러 내부 Bearer 3, **무인증 52(+문서 4)**. ai07 의 "43" 은 ai07 브랜치 기준에서 health 6·핸들러 인증 3·중복 1 을 뺀 값과 같고, 같은 방식으로 LLM-clean 은 45.
- 분류: PUBLIC/ops 6(health 류; adaptive/health·gateway/status·/docs 는 ADMIN 성격), **SPRING_INTERNAL 21**(Spring 이 호출 — Bearer 필수화 대상), UNUSED_LEGACY 25(호출처 없음 — 비활성/제거 권장; fetch-stream·jobs/{id} 류는 사용자 바인딩 없음).
- EC2 조치: 공용 `fastApiWebClient` 가 **모든 호출에 Bearer 기본 탑재**(기존엔 28곳 중 3곳만). ai07 은 SPRING_INTERNAL 21개에 `Depends(verify_internal_token)` 를 붙여도 Spring 회귀 없음(SECONDARY 키 정합은 기존 메모 기준 확인 필요).
- NetworkGuard 가 사설망/loopback 을 무인증 통과시키므로(reverse SSH·docker bridge 경유도 127.0.0.1) IP 는 인증을 대체하지 못한다.

## 7. 외부(OpenAI) 전송 감사

| 경로 | 보내는 데이터 | 조건 | Spring 호출자 | 고지/동의 |
|---|---|---|---|---|
| study-journal/validate | 사용자 메모 원문, 자료 제목, 키워드, RAG 청크 3×300자 | OPENAI_API_KEY 만 | StudyJournalValidationClient(저장 시 매번) | 없음 |
| major-analysis/note | PDF 페이지 이미지(gpt-4o 고정), 페이지 텍스트 ≤9000자(refine) | s3Key + 키, ENABLE_OPENAI_REFINER(기본 true) | StudyNoteAnalysisService(업로드 후 자동) | 없음 |
| learning-loop | RAG/메모/오답/대화 | ai07 PR 에서 기본 OFF | 호출자 없음 | — |
| quiz/generate, multi-chat, classify, review/planner 류 | 자료 텍스트·대화·초안 | 키 설정 시(일부 OpenAI 우선) | 그룹 퀴즈·채팅 등 | 없음 |

- 가입 체크박스 "[필수] AI 제3자 제공 및 위탁 동의"(Register.jsx)는 클라이언트 상태일 뿐 Spring 에 기록되지 않고, 국외 이전·OpenAI·메모/PDF 이미지를 명시하지 않는다.
- EC2 에서 바꾸지 않은 것: ai07 의 외부 전송 경로 자체(ai07 소유). **정책 승인 전 권고: study-journal·major-analysis 의 OpenAI 경로를 ai07 에서 기본 OFF + 로컬 추론으로 대체**, 국외 이전 고지·동의 UI 는 법무 검토 후 별도 작업(인계 B-EGRESS).

## 8. 학습 후보 흐름(EC2)

사용자 요청 → AI 초안 → 품질 평가 → **APPROVED** → 사용자 노출 → **MODEL_TRAINING 동의(현재 버전) 확인** → training-sample.v1 → outbox(커밋 후, event_id 멱등) → 디스패처(서명) → ai07 collect-v1 → NEEDS_REVIEW → (ai07) TRAIN_ELIGIBLE 판정 → (별도 승인) QLoRA.
- A 노출 승인 / B 학습 권한(동의) / C 정답 검증(ai07 검수) / D 학습 실행 승인 — 서로 대체하지 않는다. 좋아요·80점으로 자동 승격 금지(`qualityLabel=UNLABELED`).
- 권리: 업로드 PDF → `THIRD_PARTY_UNVERIFIED`(업로드 ≠ 권리), 대화 → `UNKNOWN`. 권리 확인 UI 가 없으므로 현재 어떤 후보도 권리 요건으로 TRAIN_ELIGIBLE 가 될 수 없다(의도된 보수 동작, blocker B-RIGHTS).
- 동의 API `/api/ai/training-consent`(GET/POST/DELETE): 버전 `tc-2026-11` 고지문 해시·만 14세 이상 확인 저장, 철회 → 미전송 후보 즉시 취소·원문 삭제 + `REVOCATION`(ai07 /consent-withdrawal) 적재. 소급 적용 없음. 14세 미만 법정대리인 동의 흐름 미구현(동의 불가).
- 자료 삭제 → 미전송 후보 취소 + `DELETION`(deletionTrackingId=자료 단위 HMAC 파생 id). **회원 탈퇴 흐름이 Spring 에 없음** → 생기면 consent-withdrawal + deletion(사용자 단위) 호출 필수(B-ACCOUNT).
- 이미 학습된 가중치는 행 삭제로 지워지지 않는다 → ai07 manifest INVALIDATED + adapter RETIREMENT_REQUIRED 로 추적, 다음 재학습 제외(고지문 5항).
- 플래그(모두 기본 false): `AI_TRAINING_COLLECTION_ENABLED`, `AI_TRAINING_OUTBOX_DISPATCH_ENABLED`. 신규 테이블 `ai_training_consents`, `ai_training_outbox`(ddl-auto 가 배포 시 생성).
- 운영 `ai.training_candidate` 레거시 스키마/asyncpg 부재, ai07 migration 001/002 는 ai07 소유 — EC2 는 적용하지 않았고 운영 RDS 를 조회하지도 않았다.

## 9. 플래그·설정·스키마·롤백

| env | 기본 | 위치 |
|---|---|---|
| AI_RESPONSE_QUALITY_GATE_ENABLED | false | AiQualityGateSettings |
| AI_QUALITY_MAX_REGENERATIONS | 2(0..2) | 〃 |
| AI_QUALITY_EVALUATE_TIMEOUT_MS / AI_QUALITY_EVAL_MAX_CONCURRENCY / AI_QUALITY_EVAL_QUEUE_WAIT_MS | 8000 / 2 / 2000 | 〃 |
| AI_QUALITY_CIRCUIT_FAILURE_THRESHOLD / AI_QUALITY_CIRCUIT_OPEN_MS | 5 / 30000 | 〃 |
| AI_SCOPE_SIGNING_KEY / AI_TRAINING_CONSENT_SIGNING_KEY / AI_TRAINING_SAMPLE_SIGNING_KEY / AI_PSEUDONYM_SECRET | 비어 있음(=기능 거부) | AiSigningKeys |
| AI_TRAINING_COLLECTION_ENABLED / AI_TRAINING_OUTBOX_DISPATCH_ENABLED | false / false | AiTrainingSettings |

- 값 주입: Spring 컨테이너는 `/home/ubuntu/.studybridge-secrets/spring.env`(compose env_file)로 받는다 — 키는 반드시 그 파일(600)에.
- 스키마 변경(배포 시 ddl-auto ALTER/CREATE, 운영 승인 + RDS 스냅샷 필요): `learning_loop_events.origin`, `chat_messages.quality_status`, `material_summaries.quality_status/quality_score`, 신규 `ai_training_consents`, `ai_training_outbox`. 모두 nullable/신규 — 기존 데이터 변경 없음. 롤백 = 앱 롤백(컬럼 무시), 필요 시 `DROP COLUMN/TABLE`(SQL 은 `db/migration/V20261104__*`).
- 기능 롤백 = 플래그 OFF. 보안 fail-closed(키 미구성·서명 불일치·소유권)는 플래그로 우회하지 않는다 — 원인 수정 또는 커밋 revert.
- Canary(승인 후, 미실행): ① ai07 PR #116 evaluator 배포 + `AI_QUALITY_EVALUATE_API_ENABLED` ON(평가기만) → ② EC2 키 4종 주입, 게이트 OFF 상태로 섀도 평가 로그 수집(별도 구현 필요) → ③ 내부 테스트 계정 한정 ON → ④ BLOCKED 0 확인 후 전체 ON.

## 10. 테스트(EC2 로컬, 2026-11-04) — 결과는 PR 본문에 최신값

- 게이트: 79 거절·80 승인·100 승인·100.5/NaN/Inf/null 거절·95+hardFail 거절·APPROVED+hardFail(계약 위반)=미노출·79→70→85 재생성 승인·3회 실패 차단·평가기 503/timeout/200+success:false 미노출·동일 초안 반복 중단·서킷 오픈/반개방 복구·bulkhead.
- SSE: ai07 실캡처 3종 deny-all 본문 0자(canary·문장 전수 검사), approve-all 이벤트 순서·answers·eventId·agentIndex 보존, 델타/미지/오류 문구 차단, 중복 1회, timeout→QUALITY_UNAVAILABLE, 초과 크기 미평가 거절, 취소 상류 전파, 동시 2 스트림 판정 비혼입. ChatService 실체인: 거절 시 DB/Redis AI 행 0, 승인 시 APPROVED 저장, OFF 회귀 없음, 이력 가림, Learning Memory 미승인 제외.
- 요약: 재생성 승인 저장, 전부 거절 시 저장 0·기존 요약 보존, 미승인 캐시 재생성, 승인 캐시 AI 호출 0, 평가기 다운 재생성 0, 생성 실패 기존 계약, OFF 평가기 호출 0.
- 학습 후보(PG): 동의 없음 0건, 미승인 0건, 버전/나이 검증, 1회 적재·중복 0, 롤백 0건, 철회 → 취소·차단·재동의 시 신규만, 서명·consent 토큰 검증, 백오프→DEAD, 422 DEAD, 철회 경합 미전송, 자료 삭제 → 취소+deletion, 동시 디스패처 중복 0.
- 전체 백엔드: **765 tests / 0 failures / 0 errors / 12 skipped**(MaterialQuizRankingRedisIT — 별도 env) — 일회용 PG(postgres:16, tmpfs)·Redis 로 PG/Redis 통합 포함. 기준선(LLM-clean 13dae5e4) 679/0/0/24.
- 로컬 부팅(일회용 DB·Redis, ai07 대신 127.0.0.1:9, 게이트 ON, 서명 키 4종): `Started ApiApplication` 25.8s, 신규 테이블/컬럼 6개 ddl-auto 생성 확인. 인증 E2E: 미연결 AI 경로 503 `AI_QUALITY_GATE_NOT_WIRED`, 위조 `AI_CHAT_ANSWERED` 403, aiOutputSummary/score 400, 동의(14세 미확인) 400 → 동의/철회 → REVOCATION outbox 1행. 부팅 중 기존 ScreenSharePolicyEnforcer 가 로컬 OpenVidu(localhost:4443) 세션 목록 GET 을 시도해 TLS 단계에서 실패(상태 변경 없음).
- 프런트: vite build PASS(출력은 scratchpad, 추적 dist 미변경), smoke 6 PASS, ESLint 는 저장소에 설정 파일이 없어 SKIP.
- 합성 지연(스텁 평가기, 운영 수치 아님, socratic 3답변 캡처): 게이트 OFF 첫 본문 ~0ms / ON(평가 0ms) 첫 본문 p50 45ms·턴 p50 197ms / ON(평가 600ms) 첫 본문 p50 605ms·턴 p50 3.68s — 메시지·all_complete 부가 필드를 순차 평가하므로 턴 지연 ≈ Σ평가 지연. 운영 판단 전 ai07 실평가기로 측정 필요(병렬 평가·messages[] 중복 평가 제거는 개선 과제).
- 품질 수치: 사람 검수 gold benchmark 미측정(ai07 seed 32건은 AI 초안 smoke, 서비스 품질 수치 아님). FAR/FRR·95% CI 는 측정 불가 — 주장하지 않는다.

## 11. ai07 Phase B 작업(순서)

1. **C-ID-1/C-TYPE-1/C-TIME-1/C-RQ-2/C-RQ-1/C-SIG-1** 반영: `\Z`, `ConfigDict(strict=True)`(최소 식별자·숫자), `AwareDatetime`, `score<=100` 및 APPROVED 불변식, 출력에 `mandatoryValidatorsPassed`, consent typ 불일치 코드 분리. EC2 `expectations.json` 을 fixture 정본으로 복사하고 `tools/crosscheck_pydantic.py` 가 exit 0 이 되게. `test_meta_marks_ec2_as_owner` 의 PROPOSED 단정 갱신.
2. `/api/ai/quality/evaluate` 를 PRIMARY(ai07)에 배포(기본 503 유지). 응답 `requestId` 에코·`evaluatorVersion` 필수 유지. 시도별 requestId 가 다르므로 409 는 버그 신호.
3. SPRING_INTERNAL 21 라우트 Bearer 필수화(Spring 은 이미 전송), UNUSED_LEGACY 25 비활성, `/docs`·`/openapi.json` 운영 비공개(단, Spring 라우트 프로브가 `/openapi.json` 을 쓰므로 Bearer 허용 형태로).
4. `/consent-withdrawal`·`/deletion`·`/feedback` 에 본문 서명 요구(C-SIG-2) — 현재 내부 Bearer 만으로 임의 사용자 철회 가능.
5. collect-v1 이 동의 토큰(`X-AI-Training-Consent`)도 검증하도록(현재 본문 서명만; EC2 는 이미 전송, rid=eventId, sub=가명 키).
6. 에이전트별 재생성 API(선택) — 없으면 SSE 는 거절 후 사용자 재시도만 가능.
7. study-journal·major-analysis OpenAI 경로 기본 OFF + 로컬 대체(B-EGRESS), CPU 동기 검증을 스레드풀/프로세스로 분리(이벤트 루프 점유), 멱등 저장을 DB 기반으로(프로세스 메모리 한정 → 워커 다중 실행 경합).
8. 운영 학습 저장소(asyncpg·스키마) 정리 후 승인 하에 migration — EC2 는 RDS 변경 안 함.

Blockers: B-RIGHTS(권리 확인 UI 없음), B-ACCOUNT(회원 탈퇴 흐름 없음), B-NGINX(브라우저→FastAPI 직접 경로), B-EGRESS(외부 전송 정책 미승인), 게이트 미연결 37 경로, gold benchmark 미측정, 미성년자 법정대리인 동의 미구현.
