학습 루프 Phase B ai07 인계서 (EC2 canonical v1 정합 · 내부 인증 · 동의/삭제 · 품질 평가 · 외부 전송 · 학습 DB)

작성 2026-11-04, ai07 세션. 브랜치 feature/learning-loop-ai07 (PR 116). 비교 기준 EC2 브랜치 feature/learning-loop-ec2 head b14b0e83 (PR 117).
운영 반영 없음: 운영 재시작, 운영 DB 마이그레이션, 모델 교체, 장시간 학습, LLM-clean/main 수정, PR 병합 모두 하지 않았다.
모든 신규 동작은 기본 OFF 이거나 운영 Spring 호출과 호환되는 report 모드다. 단 외부 전송 정책은 기본 차단이다(7장 참고).


1. 계약 정합 (B1)

1.1 결과
  EC2 canonical fixture 30개: EC2 가 만든 tools/crosscheck_pydantic.py 를 수정 없이 실행 → fixtures=30 mismatches=0, exit 0.
  기존 불일치 4건 해소: C-ID-1(끝 개행 식별자), C-TYPE-1(문자열 materialId), C-RQ-2(100.5 APPROVED), C-TIME-1(타임존 없는 시각).
  C-RQ-1: 출력에 mandatoryValidatorsPassed 추가. 평가기는 항상 채운다(HARD 위반 0 이면 true, 평가 실패면 false).
  C-SIG-1: scope 용도 토큰을 consent 로 제시하면 CONSENT_TOKEN_TYPE_INVALID(만료 판정보다 먼저).
  승인 판정은 is_displayable(output, expectedRequestId) 하나로 Java isDisplayable 과 같다:
    success, verified, qualityStatus=APPROVED, 80<=score<=100(NaN/Inf 불가), minimumScore 가 null 또는 80, hardFail=false,
    HARD 위반 0, mandatoryValidatorsPassed 가 false 아님, schemaVersion 일치, requestId 일치.
  ai07 내부 스트림 게이트도 평가마다 자체 requestId 를 발급하고, 다른 requestId 로 돌아온 승인 판정은 버린다.

1.2 Java 와 같은 입력에 대한 판정 비교(차등 검증)
  방법: EC2 Java 계약 클래스(ContractJson, LearningContextV1, ResponseQualityV1, TrainingSampleV1, AiContractSigning, CanonicalJson)를
  git ref 또는 같은 checkout 에서 그대로 꺼내 JDK 21 + Jackson 2.15.4(Spring Boot 3.2.4 와 같은 버전)로 컴파일해 실행했다.
  케이스 605개(타입 강제변환, 끝 개행, 날짜 37가지 형식, null/누락, int/long 범위, NaN/Infinity, 뒤따르는 토큰, BOM, 잘못된 UTF-8,
  점수 경계 79/79.99/80/100/100.5, APPROVED 불변식, 서명 토큰 변조 50여 가지, 본문 서명 14가지).
  결과: 598 일치, 7 불일치. 불일치 7건은 전부 Java 가 받고 Python 이 거부하는 방향이며, 테스트가 이 방향만 허용한다.
    C-TIME-2 (4건): Java OffsetDateTime 은 연도 0000, 5자리 연도(+12026), epoch 253402300800 이상을 받는다. Python datetime 은
      0001~9999 만 표현 가능. 제안: EC2 validate 에 1 <= year <= 9999.
    C-JSON-1 (2건): Jackson 기본값은 중복 키 허용(마지막 값). ai07 은 파서 차이 공격면을 없애려고 거부. 제안: ContractJson.STRICT 에
      JsonParser.Feature.STRICT_DUPLICATE_DETECTION 활성화.
    C-JSON-2 (1건): Jackson 은 짝 없는 서러게이트(\ud800) 문자열을 받는다. ai07 은 UTF-8 로 표현 불가한 문자열을 거부. 정상 트래픽에서는
      발생하지 않는다. 제안: EC2 validate 에서 고립 서러게이트 거부(선택).
  Java 측 관찰(문서와 코드가 다른 점, EC2 판단 필요):
    가. 문서는 minimumScore==80 을 승인 조건으로 적었지만 코드는 null 도 허용한다. ai07 은 코드와 같게 맞췄고 출력에는 항상 80 을 넣는다.
    나. ResponseQualityV1.isDisplayable 은 validate(Output) 를 다시 하지 않는다. 지금은 QualityEvaluatorClient 135행이 먼저 검증하므로
        실제 위험은 없지만, isDisplayable 안에서도 validate 를 호출하는 방어선 추가를 권한다.
    다. Jackson 은 시각 문자열의 앞뒤 공백, +0900/+09 오프셋, epoch 숫자/숫자 문자열을 받는다. 모두 오프셋이 확정된 값이라 C-TIME-1 취지에는
        맞아 ai07 도 똑같이 받는다. 더 엄격하게 바꾸려면 두 쪽을 함께 바꿔야 한다.
  EC2 가 할 일:
    expectations.json 의 4개 항목 ai07Observed 를 INVALID 로 바꾸고 ContractV1FixturesTest 의 열린 이슈 목록을 Map.of() 로 비운다.
    signing-vectors.v1.json 의 scope_token_as_consent 기대값을 CONSENT_TOKEN_TYPE_INVALID 로 갱신하고(ai07 파일은 이미 갱신) 테스트의
    오버라이드 맵을 지운다. 토큰·키·본문 바이트는 바뀌지 않았다.

1.3 수정 위치
  fastapi/app/contracts/jtypes.py (신규, Java 호환 타입·원시 JSON 파서)
  fastapi/app/contracts/response_quality_v1.py, learning_context_v1.py, training_sample_v1.py, signing.py
  fastapi/app/quality_gate/evaluator.py (schemaVersion·mandatoryValidatorsPassed·latencyMs 범위 고정), routes.py(원시 바이트 파서)
  fastapi/app/contracts/fixtures/ (EC2 원본 복사 + differential/)
  fastapi/scripts/contract_crosscheck/ (ContractDiffHarness.java, run_java_crosscheck.sh, build_cases.py, python_verdicts.py)
  발견한 잠재 결함: 평가기 latencyMs 가 Java Integer 범위를 넘을 수 있었다(시작 시각 0 → 1.79e12). Spring 이 계약 위반으로 거부했을 값이다.
  0 ~ 2147483647 로 고정했다.


2. 내부 API 인증 (B2)

2.1 동작
  fastapi/app/core/internal_auth.py 의 InternalAuthMiddleware(순수 ASGI, SSE 버퍼링 없음)를 hotfix_main 에 등록했다.
  경로 분류는 라우팅과 같은 디코딩 경로로 하므로 퍼센트 인코딩 우회가 안 된다. 출발지 IP, loopback, reverse SSH 는 판단에 쓰지 않는다.
    PUBLIC: GET/HEAD /health, /api/health, /api/ai/health, /api/native-engine/health. 항상 통과.
    DOCS: /docs, /redoc, /docs/oauth2-redirect. 기본 404. AI_DOCS_ENABLED=true 여도 Bearer 필요.
    SPRING_COMPAT: 운영 Spring 이 아직 Bearer 없이 부르는 21개 POST 경로 + GET /openapi.json.
    PROTECTED: 그 밖의 전부(미등록·신규 경로 포함). 모드와 관계없이 Bearer 필수.
  AI_INTERNAL_AUTH_MODE
    report(기본): SPRING_COMPAT 은 토큰이 없거나 틀려도 통과시키고 경로별로 집계·기록한다. PROTECTED 는 강제.
    enforce: SPRING_COMPAT 도 Bearer 필수. 예외는 AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST(기본 POST /api/extract, POST /api/ai/intent/route)의
      '토큰 없음' 뿐이고 틀린 토큰은 401. 이 목록에는 SPRING_COMPAT 안의 정확한 경로만 넣을 수 있다.
    알 수 없는 값은 enforce 로 본다.
  공통: 서버 키(AI_SERVER_API_KEY)가 없거나 24자 미만이면 보호 경로는 503(모드 무관 fail-closed). 회전용 AI_SERVER_API_KEY_PREVIOUS 허용.
  report 모드에서 바로 막히는 경로: fetch-stream 5개, learning-mate/chat, review-note 2개, plan-analysis/recommendation, planner expand/roadmap,
    /api/ai/roadmap, /api/quiz/generate, native-engine schedule/textprep, gateway/status, planner/adaptive/health 등 미사용 레거시·관리 경로.
    Spring·React 호출부가 없다는 정적 추적 결과(37곳 전수)에 근거했다. n8n 회귀 워크플로가 이 경로를 Bearer 없이 부르면 실패한다(개발 도구).

2.2 SPRING_COMPAT 21개
  /api/ai/multi-chat, /api/ai/multi-chat/stream, /api/ai/predict-study-time, /api/ai/feedback, /api/ai/summary, /api/ai/quiz, /api/ai/question,
  /api/ai/quiz/generate, /api/ai/roadmap/generate, /api/ai/keyword/define, /api/ai/material/classify, /api/ai/major-analysis/note,
  /api/ai/intent/route, /api/ai/study-journal/validate, /api/ai/planner/analyze, /api/ai/planner/analyze-semantic, /api/ai/planner/assist,
  /api/ai/review/wrong-note-feedback, /api/ai/review/variant-question, /api/ai/review-needed, /api/extract
  EC2 문서의 'SPRING_INTERNAL 21개에 Bearer 를 붙여도 회귀 없음'은 2개가 사실이 아니다:
    POST /api/extract: PdfExtractionService 69~80행 RestTemplate 이 Authorization 없이 호출(막으면 자료 업로드 텍스트 추출 전부 실패).
    POST /api/ai/intent/route: intentRouterWebClient(WebClientConfig 241~255행)에 기본 Authorization 없음.
    FastApiInternalAuthHeaderTest 는 fastApiWebClient 만 검증한다.

2.3 enforce 전환 순서(운영 승인 필요)
  1) EC2 PR 117 배포(공용 fastApiWebClient 기본 Bearer) + PdfExtractionService RestTemplate, intentRouterWebClient 에 Bearer 추가.
  2) Secondary 의 AI_SERVER_API_KEY 를 Spring 이 보내는 키와 맞춘다(과거 메모: Spring 64자 ≠ Secondary 27자). 안 맞으면 enforce 에서
     Secondary failover 가 401 이 된다.
  3) ai07 ops 재설치: sudo ops/install-ai07-ops.sh. 헬스체크·카나리·라우트 게이트가 Bearer 를 0600 임시 헤더 파일로 보낸다.
     설치본이 옛 버전인 채로 enforce 하면 1분 헬스체크가 /openapi.json 401 을 실패로 보고 서비스를 재시작한다(재시작 루프).
     EC2 쪽 postcheck/route-verify/cd.yml ai-route-gate 에는 AI_ROUTE_GATE_AUTH_HEADER_FILE(또는 AI_SERVER_API_KEY) 주입 필요.
  4) report 로그 [INTERNAL_AUTH] summary 에서 COMPAT_TOLERATED_MISSING/INVALID 가 0 인지 24시간 확인.
  5) AI_INTERNAL_AUTH_MODE=enforce, 이후 /api/extract·intent 수정이 배포되면 AI_INTERNAL_AUTH_UNAUTH_ALLOWLIST= (빈 값).

2.4 Nginx·노출 감사(EC2 읽기 전용)
  nginx -T: /api/ 는 127.0.0.1:8080(Spring)으로만 프록시. FastAPI(18000/8000)·Ollama(11434)로 가는 location 없음.
  EC2 Secondary python 이 0.0.0.0:8000 에 바인딩돼 있다. ai07 에서 공인 IP 43.202.211.123:8000 으로 /health 등 4개를 시도하면 모두 접속 실패(000).
  보안 그룹에서 막힌 것으로 보이지만, EC2 가 SG 규칙(8000, 18000 인바운드 없음)을 직접 확인하고 Secondary 바인딩을 127.0.0.1 또는
  docker 브리지로 좁히길 권한다.
  React 의 fastApi axios 기본 주소는 빈 문자열이라 운영에서는 nginx → Spring 으로 간다. /api/ai/chat 을 부르는 함수 2개는 호출처가 없고,
  /activity/weekly, /agents/1/chat 은 FastAPI 에 없는 경로다. 브라우저가 FastAPI 를 직접 부르는 운영 경로는 확인되지 않았다.


3. 동의·삭제·피드백 (B3, C-SIG-2 계약 정의)

3.1 collect-v1
  본문 서명(X-AI-Contract-Signature/Timestamp) 위에 X-AI-Training-Consent 검증을 추가했다:
  rid = eventId, sub = 가명 키, typ = training-consent, scope 에 MODEL_TRAINING, cv = consentVersion, dtid = deletionTrackingId,
  ct = consentTimestamp(같은 시각), X-Request-Id = eventId, ct 가 현재보다 5분 넘게 미래면 거부.
  판정 결과: 200 STORED/QUARANTINED/DUPLICATE/REJECTED_CONSENT_WITHDRAWN/REJECTED_SOURCE_DELETED(최종), 200 재전송(Idempotent-Replay),
  409 같은 eventId 다른 본문, 503 다른 워커 처리 중·저장소 불가(재시도), 401 서명·토큰, 422 계약·동의 불일치.

3.2 철회·삭제·피드백: Bearer 만으로는 401(SIGNATURE_MISSING). 서명된 training-control.v1 본문만 받는다.
  헤더: Authorization Bearer, X-AI-Contract-Signature, X-AI-Contract-Timestamp(AI_TRAINING_SAMPLE_SIGNING_KEY, 원시 바이트, ±300초),
        X-Request-Id = eventId, Content-Type application/json.
  공통 필드: schemaVersion "training-control.v1", typ "training-control", messageType, eventId([A-Za-z0-9._:-]{8,128}),
            issuedAt(오프셋 필수 ISO-8601, 실제 UTC 순간), 모르는 필드 거부.
  CONSENT_WITHDRAWAL: pseudonymousUserKey, scope ["MODEL_TRAINING"]. 그 밖의 필드 불가.
  DELETION: deletionTrackingId (pseudonymousUserKey 선택).
  FEEDBACK: pseudonymousUserKey, candidateEventId 또는 contentHash 중 정확히 하나, score -1/0/1, reasonCode 선택.
  messageType 이 라우트와 다르면 422 CONTROL_MESSAGE_TYPE_MISMATCH(용도 간 재사용 차단). scope 는 MODEL_TRAINING 외 불가.
  응답 공통: status, invalidated_datasets, retirement_required_adapters, purged_datasets, trainedModelEffect, modelWeightsErased(false 고정).
  EC2 디스패처 변경 필요: 현재 REVOCATION/DELETION 은 {"pseudonymousUserKey"} / {"deletionTrackingId"} 를 서명 없이 보낸다. 위 본문으로
  outbox 에 저장하고, 보낼 때 저장 바이트 그대로 서명한다. ai07 이 401 을 주는 동안 EC2 는 철회·삭제를 계속 재시도하므로 유실은 없다.
  FEEDBACK 은 EC2 에 아직 없다.

3.3 철회·삭제 효과
  철회: DB tombstone(서명된 issuedAt) 먼저 → 그 시각 이전 동의로 만든 후보만 REVOKED → manifest INVALIDATED → 그 manifest 로 학습한
    어댑터 RETIREMENT_REQUIRED. 재동의 이후 후보는 유지된다(늦게 도착한 옛 철회가 새 후보를 지우지 않음).
  삭제: tombstone → 내용 파기(해시와 계보만 보존) → manifest·어댑터 동일 처리. 이후 같은 deletionTrackingId 샘플은 영구 거부.
  수집은 저장 전과 후에 tombstone 을 다시 확인한다. 철회와 수집이 동시에 일어나도 철회 이전 동의 후보는 남지 않는다(PG 경합 20회 검증).
  학습된 가중치에서 샘플이 지워졌다고 주장하지 않는다(trainedModelEffect = RETIREMENT_REQUIRED_WEIGHTS_NOT_ERASED).
  피드백은 대상 후보의 가명 키와 일치할 때만 반영하고, 아니면 NOT_FOUND(존재 여부 비노출).

3.4 멱등·다중 워커
  ai.training_processed_event(eventId PK)로 1회 처리한다. 같은 본문 재전송은 이전 결과를 돌려주고, 처리 중이면 503(재시도) — 409 를 주면
  EC2 가 SENT 로 끝내 미완료 처리가 유실되므로 쓰지 않는다. 실패한 선점은 해제하고, 오래된 선점은 lease 후 인수한다.
  프로세스 메모리 재전송 캐시는 제거했다. 검증: PG 에서 같은 eventId 동시 12개 → 처리 1회, 별도 OS 프로세스 4개 → 적용 1회.
  CI 러너에서 실제로 잡힌 경합 결함(수정함): 수집이 행을 저장한 직후 동시 철회가 먼저 REVOKED 로 바꾸면 수집의 분류 전이가
  InvalidTransition 예외(500)로 끝났다. 또 철회·삭제 루프가 행 갱신 CAS 충돌을 만나면 나머지 행을 건너뛴 채 409 를 반환할 수 있었다
  (EC2 는 409 를 SENT 로 끝낸다). 지금은 수집은 최종 REJECTED_CONSENT_WITHDRAWN 으로 응답하고, 철회·삭제는 행 단위로 다시 읽어
  재시도하며, 충돌이 남으면 503(재시도)을 준다. 결정적 재현 테스트 2개 + PG 경합 60쌍(10쌍 동시) 반복.

3.5 C-TIME-3 (EC2 실제 버그, 확인됨)
  EC2 Spring 컨테이너 TZ=Asia/Seoul(docker inspect·date 확인). TrainingCandidateCollector 가 consent.getCreatedAt()(LocalDateTime, KST 벽시계)에
  .atOffset(ZoneOffset.UTC) 를 붙여 consentTimestamp 와 토큰 ct 를 만든다 → 실제보다 9시간 미래인 UTC 값이 된다.
  철회 시각(issuedAt)을 Instant 로 만들면 철회 이전/이후 판정이 9시간 어긋난다. 수정: atZone(ZoneId.systemDefault()).toOffsetDateTime()
  또는 저장을 Instant/OffsetDateTime 으로. ai07 은 5분 넘는 미래 동의 시각을 거부해 이 오류가 조용히 지나가지 않게 했다.

3.6 마이그레이션
  migrations/003_training_control_v1.sql(원장·tombstone), 004_rollback_training_control_v1.sql(tombstone 이 있으면 거부).
  001 만 적용되고 003 이 없으면 수집은 DEFERRED(저장 안 함, fail-closed).


4. 품질 평가기 연결 준비 (B4)

4.1 측정(합성: 가짜 LLM 캡처 + 결정적 평가기 + 지연 주입. 운영 실측 아님)
  결정적 평가 1건: 캡처 크기(수백~수천 자) 평균 0.2~2ms, p95 3ms 미만. 60,000자 27ms.
  중복 평가: 소크라테스 캡처에서 메시지 3건 + all_complete.messages[] 3건 = 6회(스트림 메시지는 content+question, 집계는 content 만이라 해시가 달라 재평가).
  순차 지연(평가 600ms 주입): 소크라테스 턴 3.61s — EC2 합성값 3.68s 와 같은 구조(Σ평가 지연).
  상류 정지: 게이트가 평가를 기다리는 동안 상류 생성기를 읽지 않아 다음 에이전트 생성이 멈춘다(pull 기반). 생성 1.0s + 평가 0.6s × 3명 = 4.81s.
  동시성(평가 API 세마포어 2, 대기 상한 2s, 평가 600ms): 4건 대기 avg 301ms p95 601ms / 8건 avg 901ms p95 1803ms / 16건 8건 429.
    평가 2.5s 면 8건 중 6건 429.
  취소: 소비자 취소 후 0.07~0.11ms 안에 상류 종료·진행 중 평가 취소.
  judge(qwen3:14b, 운영 Ollama 순차 5회, 2026-11-04): 평균 1,661ms, 최소 404ms, 최대 5,415ms(첫 호출), 판정 5/5 정답 일치. 기본은 judge OFF.

4.2 ai07 개선(적용됨)
  all_complete 항목이 같은 스트림에서 같은 에이전트가 이미 승인받은 필드 값과 완전히 같으면 그 판정을 재사용 → 소크라테스 6회→3회, 턴 3.61s→1.81s.
    다른 에이전트 이름, 변조된 본문, 미승인 판정은 재사용하지 않는다.
  재사용할 수 없는 집계 항목은 병렬 평가(상한 2, 평가 API 동시성과 같게, GPU judge 동시 점유 증가 없음). 순서 보존.
  상류 선읽기(128 이벤트): 평가 중에도 생성 진행 → 4.81s→3.61s, 첫 본문 지연 동일(1.60s), 승인 전 0자 노출 유지.
  judge 없는 큰 본문(8,000자 이상)은 워커 스레드에서 평가 → 60,000자 이벤트 루프 점유 27.4ms→5.7ms.
  평가기 결함 수정: 마인드맵 그래프 엣지 from/to 를 source/target 과 같게 해석(예전: 엣지 전부 GRAPH_DANGLING_EDGE HARD),
    플래너 서술형 코칭(outputKind=text)에 일정 JSON 검사를 적용하지 않음(예전: 항상 JSON_SCHEMA_INVALID HARD).
  평가 API: 기능 OFF 503, 대기 초과 429 EVALUATOR_BUSY, 평가 timeout 은 VALIDATION_ERROR(success=false, mandatoryValidatorsPassed=false),
    NaN/중복 키/뒤따르는 토큰은 422. 어떤 실패도 승인 본문을 내지 않는다. 재생성은 env 가 더 크게 요구해도 최대 2회.

4.3 EC2 Spring 게이트 권고(측정 근거)
  QualityStreamGate 의 all_complete 부가 평가에 같은 재사용 규칙(같은 에이전트 + 필드 값 완전 일치)을 적용하면 Σ평가 지연이 메시지 수만큼 준다.
  concatMap 순서 보존은 유지하되 상류 구독을 평가와 분리(prefetch)하면 생성과 평가가 겹친다.
  Spring bulkhead(2)와 ai07 세마포어(2)가 같아 동시 16 스트림이면 절반이 429 → 사용자 노출은 QUALITY_UNAVAILABLE. judge ON 운영 전 동시성 상한 재산정 필요.


5. 사용자 노출 경로 (B5)

5.1 분담(Spring 41개 중 BLOCKED 37개): Spring 만 24(그중 9개는 DB 재노출 마스킹이라 생성 경로가 먼저), ai07 만 2, 양쪽 11.
  공통 ai07 전제: AI_QUALITY_EVALUATE_API_ENABLED=true(PRIMARY 배포), 근거 없는 대화형 프로파일은 judge 가 없으면 승인 불가.
5.2 ai07 에서 이번에 고친 것: 마인드맵 그래프 검증기 키, 플래너 서술형 코칭 프로파일(위 4.2).
5.3 ai07 남은 작업(파일:행은 feature/learning-loop-ai07 기준, 대략)
  그룹 퀴즈 quiz/generate: 원문 청크·페이지 근거를 응답에 실어야 PDF_QUIZ 승인 가능(main.py 1846, 1865 부근은 sourceSnippet 만).
  자료 질문 /api/ai/question: usedChunks 인덱스만 반환(material_legacy_routes 508행 부근) → 청크 본문과 chunkId/page 반환 필요.
  화면 AI vision/analyze: 판독 결과를 지우고 응답에 넣지 않음(vision/router.py 140행 부근) → 마스킹된 판독 근거 반환 필요.
  학습노트 major-analysis/note: 페이지별 원문·위키 근거 반환 필요, 업로드 시점 비동기 생성이라 생성 시점 게이트가 맞다.
  로드맵 roadmap/generate: 84일 JSON 약 15만 자 > response-quality.v1 proposedOutput 상한 60,000자 → 현재 계약으로 승인 불가.
    주 단위 분할 평가 등 v2 계약 설계 필요(EC2 owner). 로드맵용 TaskType 도 없다.
  추천 /api/ai/recommendation/{task,roadmap-candidates,document}: ai07 에 라우트 없음(404). Spring 기본 OFF 라 당장 영향 없음.
  /api/ai/pdf/extract-vision-text/upload: ai07 에서 삭제된 경로(항상 404, Spring 이 예외를 삼킴).
5.4 Spring 남은 작업: 나머지 경로에 /api/ai/quality/evaluate 연결, DB 재노출 경로 마스킹, 그룹 stream 게이트(현재 503).
  ROUTES 에 없는 노출 경로: POST /api/materials/{id}/plan-recommendation(저장된 AI 추천 재노출), POST /api/groups/{gid}/materials/upload-quiz,
  GET /api/{materials|planners}/{id}/recommendations, POST /api/materials/upload(학습노트 생성 트리거), POST /api/materials/{id}/study-journals.
5.5 SSE 누출 검증: ai07 게이트 기준 실캡처 9종 deny-all 본문 0자(카나리·비밀키 문자열 검사), 사이드카 필드·중간 답변·all_complete 필드 차단,
  모르는 이벤트 폐기. 통합 트리에서 EC2 QualityStreamGateTest 포함 Java 55건 통과.
5.6 운영 ON 승인 조건 BLOCKED_WHEN_GATE_ON = 0 은 아직 충족되지 않는다(37).


6. 외부 전송 정책 (B6)

6.1 운영 현재 상태(감사): OpenAI(학습일지 최종 판정, 전공분석 OCR·노트, 요약 이미지, 퀴즈, 리뷰·플래너 보강, 분류 검증 등), Tavily, Wikipedia 로
  사용자 메모·PDF 본문/이미지·대화가 전송되고 있다. 전송 전 마스킹은 비전 한 곳뿐. 가입 동의 체크박스는 Spring 에 기록되지 않는다.
6.2 ai07 변경: fastapi/app/core/egress_policy.py 가 모든 외부 호출(OpenAI 5개 생성 지점, Tavily 2, Wikipedia 4, OpenAlex 2)의 단일 관문.
  AI_EXTERNAL_EGRESS_ENABLED(기본 false, 마스터) AND AI_EGRESS_ALLOW("destination:feature" 목록)일 때만 허용. 기존 기능별 스위치와 AND.
  차단 시 로컬 qwen3:14b 로 대체하고 응답 계약(필드·타입)을 유지한다.
    학습일지: 로컬 판정(think:false, JSON Schema, temperature 0) — 합성 7케이스×2회 판정 14/14, JSON 유효 14/14, 적재 후 평균 1.25s.
    전공분석: 로컬 OCR(native → tesseract → qwen3-vl, 30초 예산) + 길이 상한을 건 로컬 노트 — 합성 4쪽 27.5s, 필드 16개 유지.
    요약: 이미지 경로 차단·실패 시 로컬 텍스트 요약(예전: 빈 요약 반환 버그). 피드백: 로컬, 모두 실패하면 success:false AI_UNAVAILABLE.
    멀티챗 grounding, 키워드 정의, 퀴즈, 로드맵, 리뷰·플래너 보강, 분류 검증: 외부 단계 생략 후 로컬 결과.
    비전 답변: 503 VISION_ANSWER_DISABLED(로컬 판독은 그대로).
6.3 BLOCKER(정책·운영 결정 필요)
  가. 병합·배포하면 외부 전송이 기본으로 꺼진다. 현재 동작을 유지하려면 운영 .env 에 AI_EXTERNAL_EGRESS_ENABLED=true,
      AI_EGRESS_ALLOW=openai:*,tavily:*,wikipedia:*,openalex:* 를 넣어야 한다(결정 전 병합 금지).
  나. 국외 이전 고지·동의(OpenAI·Tavily 미국): 메모·PDF·대화를 보내려면 처리방침·동의 UI 법무 검토 후 기능별로 허용 목록을 연다.
  다. 학습일지 판정자: 예전 'OpenAI 만 최종 판정, Qwen3 금지' 규칙을 차단 시 로컬 판정으로 대체했다. 유지 여부 결정 필요
      (STUDY_JOURNAL_LOCAL_JUDGE_ENABLED=false 면 예전처럼 판정 불가 → 저장 보류).
  라. /api/ai/feedback 실패 응답이 success:true 안내문에서 success:false AI_UNAVAILABLE 로 바뀐다 — Spring 처리 확인.


7. 학습 DB 와 QLoRA (B7)

7.1 구분
  레거시 ai.training_candidate(운영 RDS, 0행): 운영 venv 에 asyncpg 가 없어 app/db/postgres 풀이 만들어지지 않고, asyncpg 가 있어도 레거시 코드가 쓰는
  quality_status·candidate_uuid 컬럼이 운영 테이블(candidate_id, user_query, ai_response, feedback_score, is_exported, created_at)에 없다.
  격리 PG 재현 테스트로 고정했다(UndefinedColumnError). 레거시 경로는 쓰지 않는다.
  신규 v2(ai.training_sample_v2 등): psycopg3(운영 venv 3.3.4 설치됨) 사용, 레거시 테이블은 건드리지 않음(컬럼·행 지문 동일 검증).
7.2 적용 순서(운영 RDS 직접 적용 금지, DB 담당 승인 후)
  1) RDS 스냅샷. 2) 001_training_pipeline_v2.sql. 3) 003_training_control_v1.sql. 4) 테이블·제약 확인(processed_event PK, tombstone PK).
  5) ai07 env: AI_TRAINING_REPOSITORY=postgres, AI_TRAINING_DATABASE_URL(전용 계정, ai 스키마 최소 권한), AI_TRAINING_ENV.
  6) 수집은 계속 OFF(AI_TRAINING_COLLECTION_ENABLED=false) 상태에서 연결만 확인. 롤백: 004 → 002(데이터·tombstone 있으면 스스로 거부).
7.3 QLoRA
  TRAIN_ELIGIBLE = 0 이므로 사용자 데이터 학습은 하지 않았다. 권리 확인 UI 가 없어 현재 어떤 후보도 자격 요건을 채울 수 없다(B-RIGHTS).
  도구 검증(CPU, 합성 27건): 데이터셋 manifest → Qwen3-14B 채팅 템플릿, assistant 토큰만 라벨, think 태그 없음, test 4 / train 23.
  사전 점검(읽기 전용): canStart=false — 운영 qwen3:14b 적재, 여유 VRAM 5.6GiB < 추정 12.0GiB, 운영 추론과 공존 불가, 플래그 OFF, 승인 없음.
  14B QLoRA 는 운영 GPU 에서 돌리지 않는다. 별도 GPU 또는 운영 정지 창이 필요하다.
  배포·롤백 절차: 어댑터는 후보 태그만 쓴다(DB CHECK 로 qwen3:14b·qwen3:latest 금지). gold 벤치마크(사람 검수 300건 이상, 현재 미측정)와
  계약 테스트, 내부 계정 canary 를 통과해야 승격. 롤백은 Ollama 태그를 이전 모델로 되돌리는 것. 철회·삭제로 RETIREMENT_REQUIRED 가 된 어댑터는
  재학습 전 폐기한다(가중치에서 개별 샘플 삭제를 주장하지 않음).


8. 테스트 결과(2026-11-04, ai07 격리 venv + 일회용 pgvector PG)

  CI fastapi-tests 목록 + Phase B 신규: 로컬 620 통과(경합 수정 후). 첫 GitHub CI 는 615 통과 1 실패(위 경합 결함 — 수정 후 재실행). 한 번 큰 묶음 실행에서 라이브 Java 차등 테스트가 1회 실패했고 같은 조건 재실행 2회는
    통과(동시 Gradle 의존성 다운로드와 겹친 시점, 원인 미확정).
  전체 fastapi/tests: 1953 통과, 실패 3, 수집 오류 4. 실패·오류 7건은 기준선(a4bd8fac)에도 있던 것과 동일(mode_contract 2, vision payload 1,
    major_analysis import 4). 새 회귀 0.
  EC2 crosscheck_pydantic.py: fixtures=30 mismatches=0. 차등 605 중 598 일치 + 허용된 엄격 방향 7.
  서명 교차: EC2 Java 하네스로 scope 32·consent 19·body 14 케이스 판정 일치, 기존 벡터(본문 5·scope 6·consent 4·TSV 4) 일치.
  통합 트리(LLM-clean + PR 117 + 이 브랜치): 병합 충돌 0(ci.yml 자동 병합, job 8개 공존), EC2 Java 테스트 55 통과(contract.v1, quality, 내부 인증 헤더).
    EC2 전체 백엔드 783건은 이번에 돌리지 않았다(SKIP).
  품질 게이트 합성 캘리브레이션 FAR 0, FRR 0(합성 케이스, 서비스 품질 수치 아님). gold 하네스는 PREPARED_NOT_MEASURED.
  운영 미변경 확인: 운영 checkout(LLM-clean 13dae5e4) 무변경, 운영 프로세스·모델·DB 무변경. GPU 사용은 측정 목적의 judge 5회와 B6 실측 15회뿐.


9. 운영 Go/No-Go: No-Go
  조건: BLOCKED_WHEN_GATE_ON 37 → 0, EC2 PR 117 배포와 Bearer 누락 2곳 수정, Secondary 키 정합, ops 재설치 후 enforce 전환,
  외부 전송 정책 결정(6.3), C-TIME-3 수정, training-control.v1 디스패처 구현, 학습 DB 001→003 승인 적용, 권리 확인 UI(B-RIGHTS),
  회원 탈퇴 흐름(B-ACCOUNT), 사람 검수 gold 벤치마크 측정.
