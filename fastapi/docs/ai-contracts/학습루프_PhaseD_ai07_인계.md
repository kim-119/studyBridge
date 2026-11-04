학습 루프 Phase D ai07 인계서 (EC2 PHASE_D_AI07_CONTRACT_REQUESTS 대응 · 로드맵 분할 평가 · 근거 반환 · 비전 관측 · Learning Memory 수신)

작성 2026-11-05, ai07 세션. 브랜치 feature/learning-loop-ai07 (PR 116). 비교 기준 EC2 브랜치 feature/learning-loop-ec2 head f9c878f5 (PR 117).
대상 요청서: EC2 docs/ai-contracts/PHASE_D_AI07_CONTRACT_REQUESTS.md (R1~R5), docs/ai-contracts/LEARNING_LOOP_EC2_CANONICAL_V1.md.
운영 반영 없음: LLM-clean 병합, 운영 배포·재시작, 운영 DB 변경, 모델 교체, 실사용 데이터 QLoRA 학습 모두 하지 않았다.
단, 테스트 중 운영 Redis 키 1개에 테스트 데이터가 기록된 사고가 있었다(11장). 반드시 읽을 것.


1. 계약 정합 (R4)

  java-verdicts.v1.jsonl 을 EC2 f9c878f5 의 Java 계약 클래스로 다시 기록했다(14줄 변경). known-divergences.v1.json 의 divergences 는 비웠다
  (해소 이력은 resolved 에 남김). 차등 605건이 판정·displayable 모두 Java 와 일치한다. 새 불일치는 여전히 'Python 이 더 엄격' 방향만 허용된다.
  expectations.json 은 EC2 최신본으로 바꾸고, EC2 도구 verify_training_requests_ai07.py · run_ai07_evaluator_isolated.sh 사본을 넣었다.
  response-quality.v1 · learning-context.v1 · training-sample.v1 스키마는 바꾸지 않았다. 아래 기능은 모두 기존 v1 필드 위에서 동작한다.


2. 로드맵 4개 경로 분할 품질 평가 (R2 · R5-1)

2.1 무엇이 바뀌었나
  EC2 가 지금 보내는 그대로를 인식한다: taskType PLANNER_COACHING, outputKind plan_json, proposedOutput 은 {"/weeks/3": {...}} 세그먼트,
  originalRequest 끝에 [분할 평가 i/N manifest=… segment=… checksum=…], requestId 는 <rid>.a<k>.s<i>. EC2 Java 수정 없이 승인이 가능해졌다.
  로드맵 판정은 출력 모양(로드맵 전체 또는 로드맵 포인터만 가진 세그먼트)으로 고르고, evaluationProfile 이 ROADMAP_PLAN 이면 명시적으로 고른다.
  일반 plan_json(items/plan/tasks + date)은 예전 일정 검사를 그대로 쓴다.

2.2 세그먼트 안에서 보는 것(세그먼트 밖은 추측하지 않는다)
  구조: 일자 제목·목표·과제 필수(HARD), 주차·일자 번호 순서(MAJOR), 과제 estimated_minutes 1..600(HARD), 하루 합계 1440분 또는
    constraints.maxDailyHours 이하(HARD), 날짜 형식(HARD)·오름차순(MAJOR)·마감일(HARD), 헤더 total_* 가 양의 정수인지, success=false 응답 거부.
  내용: 대체 문구·비밀/개인정보·주입 문장·근거에 없는 페이지 인용(기존 공통 검사), 자료 관련성(일자 개념이 자료 원문·요청에 나오는 비율 25% 미만이면
    ROADMAP_OFF_MATERIAL), 같은 제목·목표 일자 반복(50% 초과).
  자료 범위(allowedMaterialIds)가 있는데 근거가 없으면 ROADMAP_EVIDENCE_REQUIRED(HARD, 재생성 불가)로 승인하지 않는다.
  결정적 템플릿 로드맵(fallback_used=true)은 INFO 로만 드러내고 감점하지 않는다.
  프로파일 차원: schema_validity 30, feasibility 20, material_relevance 30, request_fulfillment 5, format 15. judge 를 쓰지 않는다.

2.3 실측
  ai07 /api/ai/roadmap/generate 가 실제로 만든 84일 로드맵(결정적 경로, GPU 미사용)을 EC2 의 실제 코드(MaterialRoadmapQualityGate.aiBody·segmenter·
  VALIDATOR + SegmentedQualityGate + AiResponseQualityGate + QualityEvaluatorClient)에 붙여 ai07 격리 평가기와 HTTP 로 왕복했다.
    세그먼트 5개(hdr, s1~s4) 모두 승인 100점 → 전체 승인, generateApproved 첫 시도 승인, 진행 토글은 승인 유지·본문 1글자 변경은 결속 해제.
    자료와 무관한 근거로 평가하면 주차 세그먼트 4개 모두 ROADMAP_OFF_MATERIAL 로 거절(전체 미승인).
    EC2 NON_REGENERABLE_CODES(PLAN_EMPTY 등)는 더 이상 나오지 않는다.
  이 검증용 Java 테스트는 EC2 저장소에 커밋하지 않았다(격리 worktree 의 임시 파일). 필요하면 EC2 가 같은 방식으로 정식 테스트를 추가하면 된다.
  LLM 이 쓴 로드맵(qwen3 아웃라인 덮어쓰기)은 GPU 를 써야 해서 이번에 평가하지 않았다. LLM 이 "p.12" 같은 페이지를 지어내면
  근거에 페이지가 없으므로 UNVERIFIED_CITATION(HARD)으로 거절된다(의도된 엄격 동작, 재생성 대상).

2.4 EC2 가 할 일
  가. 로드맵 4개 경로(GET roadmap, POST regenerate, days toggle, tasks toggle)의 BLOCKED_BY_AI07 해제 여부를 EC2 테스트로 판단(ai07 쪽 차단 사유는 해소).
  나. MaterialRoadmapQualityGate.NON_REGENERABLE_CODES 에 SEGMENT_MARKER_MISSING, SEGMENT_INDEX_INVALID, SEGMENT_INDEX_MISMATCH,
      SEGMENT_CHECKSUM_MISMATCH, SEGMENT_POINTER_INVALID, SEGMENT_OVERLAP, SEGMENT_*_CONFLICT, ROADMAP_EVIDENCE_REQUIRED 추가 권장(호출 측 결함·입력 문제).
  다. 원하면 Spec 의 evaluationProfile 에 "ROADMAP_PLAN" 을 넣어 명시적으로 고를 수 있다(선택, 스키마 변경 없음).
  라. 요청서의 TaskType ROADMAP_PLAN 신설과 constraints.segment 구조화 필드는 ai07 단독으로 넣지 않았다. Java enum·record 와 동시에 바꿔야 하고,
      한쪽만 바꾸면 차등 605건과 '모르는 필드 거부' 대칭이 깨진다. 지금은 표식 문자열로 같은 검증을 하므로 급하지 않다. 넣는다면 v1.1 로 두 PR 동시 변경.


3. 대용량 JSON 누락 · 중복 · 체크섬 (R2)

  평가기(세그먼트 1개 단위, 모두 HARD·재생성 불가):
    SEGMENT_CHECKSUM_MISMATCH 받은 본문을 Jackson JsonNode.toString() 과 같은 바이트로 다시 직렬화한 SHA-256 앞 16자가 표식과 다름
    SEGMENT_MARKER_MISSING   세그먼트 모양인데 표식 없음
    SEGMENT_INDEX_INVALID / SEGMENT_INDEX_MISMATCH  1 ≤ i ≤ N 위반 / requestId 의 .s<k> 와 표식 번호 불일치
    SEGMENT_POINTER_INVALID / SEGMENT_OVERLAP  RFC 6901 형식 오류 / 같은 세그먼트 안 포인터 겹침(같은 내용 중복 평가)
    SEGMENT_COUNT_CONFLICT / SEGMENT_DUPLICATE_CONFLICT / SEGMENT_INDEX_CONFLICT  같은 manifest 안에서 세그먼트 수가 다름 / 같은 세그먼트 ID 에
      다른 본문 / 같은 번호에 다른 세그먼트 (프로세스 단위 30분 기록, Primary·Secondary 간 공유 안 함. 같은 본문 재시도는 충돌 아님)
  전체 커버리지(모든 문자열 잎이 정확히 한 세그먼트에)는 전체 문서를 가진 Spring 이 판정한다. ai07 에는 같은 규칙의 참조 구현
    segments.verify_manifest 가 있고 테스트로 누락·중복·겹침·크기·포인터 누락·ID 중복을 고정했다.
  Jackson 호환 직렬화(키 순서, 대문자 16진 제어문자 이스케이프, Double.toString 형식)와 EC2 분할기 Python 이식을 EC2 소스 그대로 컴파일한
    Java 로 대조했다(scripts/contract_crosscheck/run_segment_crosscheck.sh, 테스트에서 JDK 가 있으면 자동 실행): 실제 로드맵, 부동소수·제어문자·
    이모지·'/'·'~' 키, 일자 단위 분할 85개를 포함한 5건 모두 분할·체크섬·manifestId 바이트 일치.
  생성 응답 무결성 content-integrity.v1(추가 필드): /api/ai/roadmap/generate 성공 응답에
    origin(LLM | DETERMINISTIC_FALLBACK), generationId(rg-<체크섬 앞 24자>, 같은 초안이면 같은 ID라 Spring 동일 초안 차단과 충돌 없음),
    integrity {schemaVersion, algorithm sha256, canonicalization jackson-jsonnode-tostring, excludedFields [integrity, generationId],
      checksum, counts {weeks, days, tasks, textLeaves}}.
  받는 쪽 대조: integrity·generationId 를 뺀 응답 Map 을 valueToTree(...).toString() 으로 직렬화해 checksum·counts 비교. Spring 은
    callRoadmapDraft 에서 Map 으로 받은 직후, sanitizeRoadmapNoise 전에 해야 한다(정리 후에는 체크섬이 당연히 달라진다).
    잘림(11주)·주차 중복·본문 편집을 각각 탐지하는 것을 테스트로 고정했고, Java 체크섬이 integrity.checksum 과 같음을 확인했다.


4. PDF 퀴즈 · 자료 질문 근거 반환 (R1 · R5-5) — grounding.v1

  형식: 응답 최상위 grounding {schemaVersion "grounding.v1", evidence [{evidenceId ev-N, sourceType PDF_ORIGINAL, materialId, documentId?,
    chunkId?, page?, quote, charStart, charEnd}]} (app/contracts/grounding_v1.py). 최대 32개, quote 1000자 이하.
  규칙: quote 는 요청 원문의 부분 문자열 그대로다(생성기가 본 정규화 텍스트에서 고른 구간도 원문에서 다시 찾아 원문 쪽 문자열을 쓴다).
    page 는 원문에 \f 또는 [Page N]/[페이지 N] 표식이 있을 때만(추측 금지). 원문에서 못 찾은 근거는 버린다.
    charStart/charEnd 는 Python 코드포인트 기준이라 Spring 은 오프셋이 아니라 부분 문자열 일치로 대조해야 한다.
  경로:
    /api/ai/quiz: quizzes[i].evidenceIds + grounding. quizData 문자열은 바이트 그대로(Spring 저장·프런트 파싱 호환).
    /api/ai/quiz/generate: S3·text·오답노트 유사문제 경로 모두 questions[i](text 경로는 quiz[i]).evidenceIds + grounding. 실패 응답은 이전과 같다.
    /api/ai/question: 프롬프트에 실제로 들어간 청크만, 순서대로, chunkId m<materialId>-c<chunkIndex>. usedChunks 의미 불변.
  문항별 근거 선택(결정적): 생성기 스니펫(sourceSnippet, 개념어가 든 sourceTrace.evidence) → 없으면 문항+정답+해설과 3-gram 이 가장 많이 겹치는
    문장(겹침 8개 이상, 비율 0.25 이상). 문항당 최대 2개. 못 찾으면 evidenceIds [].
  EC2 확인 사항:
    가. 그룹 퀴즈 S3 경로의 원문은 ai07 이 PDF 에서 추출한 텍스트라 Spring(OpenPDF) 추출본과 공백 등이 다르면 대조에서 대부분 버려질 수 있다.
        또 그룹 자료 근거의 materialId 는 그룹 자료 id 이고 Spring 평가 범위는 documentId "group-material-<id>" 다 — Spring 매핑 필요.
    나. 퀴즈 grounding 의 quote 는 정답 근거 문장이다. 브라우저로 내보내지 말 것(Spring DTO 는 ignoreUnknown 이라 현재는 전달되지 않는다).
    다. Secondary 가 구버전이면 grounding 이 없다. '근거 없음'으로 처리(평가기가 근거 부재로 거절).
    라. 퀴즈 근거에는 chunkId 가 없다(퀴즈 경로는 청크 캐시를 쓰지 않는다).
  재생성 힌트(C-RQ-3·R5-4): /api/ai/quiz, /api/ai/quiz/generate(3경로), /api/ai/summary 가 regenerationAttempt·regenerationHints 를 받는다
    (느슨한 타입 — 잘못된 타입이어도 422 없음). 알려진 위반 코드만 고정 지침으로 바꿔 프롬프트 끝에 붙인다(app/quality_gate/hints.py).
    자유 문장·모르는 코드는 버린다. attempt 가 없거나 0 이면 프롬프트·응답이 바이트 동일(9개 시나리오로 원본 트리와 비교 확인).
    재생성 시 metadata.regeneration {attempt, appliedCodes, ignoredCount}. 이 경로들에는 초안 캐시가 없어 우회할 캐시도 없었다.


5. 비전 관측 근거 · 불확실성 (R1 · R5-2) — vision-observation.v1

  VISION_RETURN_OBSERVATIONS=true 일 때만(기본 꺼짐) /api/ai/vision/analyze 성공 응답에 추가:
    observationSchemaVersion, observations [{observationId obs-N, kind TEXT|CODE|ERROR|MATH|CHART|VISUAL|QUESTION_EVIDENCE|EMBEDDED_INSTRUCTION|UNCERTAIN,
      text(마스킹 후), confidence OBSERVED|UNCERTAIN}], answerObservationIds, uncertainObservationIds, legible, screenType.
  정직성: VLM 은 숫자 확률도 좌표도 내지 않는다. 그래서 숫자 confidence 와 bbox 는 만들지 않았다(요청서의 '정규화 bbox' 는 VLM 스키마 확장과
    GPU 실측이 필요한 별도 작업). confidence 는 VLM 의 uncertain 목록 또는 판독 불가 화면이면 UNCERTAIN.
  text 는 mask_obj 를 거친 판독 결과로만 만든다. answerObservationIds 는 결정적 대조(관측 텍스트 12자 조각이 답변에 그대로 나옴, 또는 [근거:obs-N]).
  Spring 이 평가기에 넘길 형태: groundingEvidence {evidenceId obs-N, sourceType VISION_OBSERVATION 또는 VISION_OBSERVATION_UNCERTAIN, text}.
  평가기 검증: 관측에 없는 인용·수치(HARD, 기존), 근거 없는 화면 서술(HARD, 기존), 없는 관측 id 인용(HARD), 그리고 신규
    VISION_UNCERTAIN_ASSERTED — 불확실 관측에만 있는 내용을 불확실 표현 없이 단정(MAJOR, uncertainty_honesty 0 → 점수 미달 거절).
    확실한 관측으로 교차 확인되면 단정해도 된다. 판독이 모두 확실하면 불확실 표현을 요구하지 않는다.
  실측(mock VLM·mock 답변): 플래그 ON 응답의 관측으로 평가하면 근거 부재 HARD 가 사라진다. 불확실 단정 40점 거절, 불확실 고지 98점 승인.
  EC2 가 할 일: GroupScreenAiService 가 observations 를 groundingEvidence 로 변환해 VISION_CAPTION 평가에 넣기. 켜려면 ai07 .env 에
    VISION_RETURN_OBSERVATIONS=true(운영 재시작 필요, 이번에 하지 않음). 마스킹된 판독 텍스트가 Spring 으로 가므로 로그 저장 금지 유지.


6. Learning Memory learningContext 실제 수신 (R3)

  Spring 이름과 맞춤(EC2 코드 확인): 본문 최상위 learningContext(ChatService 83·501·932행), 헤더 X-AI-Scope, 경로 /api/ai/multi-chat/stream·
    /api/ai/multi-chat 두 개, rid = 본문 requestId = X-Request-ID = 토큰 rid = learningContext.requestId, sub = pseudonymousUserKey.
  AI_LEARNING_CONTEXT_ENABLED(기본 false). 꺼져 있거나 필드가 없으면 프롬프트·응답 바이트 동일(테스트 고정).
  처리(app/studymate/learning_context_intake.py): 스키마 실패 → 전체 무시 LEARNING_CONTEXT_INVALID. scope 토큰 누락·위조·만료·용도·rid·sub 불일치·
    키 미구성 → 전체 무시 LEARNING_CONTEXT_SCOPE_INVALID + 세부 코드. 컨텍스트 materialId/documentId 가 토큰 범위 밖이면 전체 무시.
    항목 자료(sourceId material:N / document:D, chunkId mN-…)가 범위 밖이면 그 항목만 제외. 자료를 특정할 수 없는 PDF 원문 항목도 제외.
    신뢰 상한 effective_trust: SOURCE_PRIMARY 만 '원문 근거(인용 가능)', AI_GENERATED 는 '참고(검증된 이전 답변)', USER_ASSERTED 는 '사용자의 주장',
    SYSTEM_RECORD 는 '학습 기록'. 항목 본문은 한 줄로 펴고 꺾쇠·대괄호·역할 표식·구분선·제어/bidi 문자를 무력화한 뒤 데이터 블록으로만 넣는다.
    주입 지점은 llm_gateway.generate 하나(에이전트 답변 render/repair/engine 의 user 메시지 앞). 플래너·판정·요약·분류·system 프롬프트는 그대로.
    6000자 예산 + 호출별 남은 num_ctx 에 맞춰 자름. 어떤 실패도 요청을 막지 않는다(422 없음). 저장·학습 후보 경로와 연결하지 않았다.
  응답: SSE all_complete 와 non-stream 본문에 learningContextReceipt(개수·코드만).
  EC2 확인 사항: 가. QualityStreamGate 가 켜져 있으면 all_complete 의 learningContextReceipt 가 평가 대상 extras 로 묶인다 — META_STRUCT_KEYS 에 추가 권장.
    나. STUDYMATE_PIPELINE_V2=off 레거시 non-stream 경로에는 적용되지 않는다(기본 on). 다. FastAPI 가 이미 파싱한 dict 를 검증하므로 JSON 중복 키는
    여기서 잡지 못한다(Java STRICT 와 다른 점). 라. 켜려면 ai07 .env 에 AI_LEARNING_CONTEXT_ENABLED=true + Spring 과 같은 AI_SCOPE_SIGNING_KEY + 재시작.


7. 재생성 힌트와 평가 오류 응답 계약 정합성

  평가기 출력 regenerationHints 는 고정 지침 표의 값만 담는다(원문·근거·정답 없음). Spring 은 이 필드가 아니라 위반 코드(reasonCodes)를 다음 생성
    요청의 regenerationHints 로 보내며, ai07 생성 경로는 그 코드를 같은 표로 지침화한다(4장). 왕복을 테스트로 고정했다.
  POST /api/ai/quality/evaluate 오류 계약(Spring 은 HTTP 상태로만 분류):
    200 출력 계약: APPROVED/REJECTED, 또는 평가 불가 VALIDATION_ERROR(success=false, score null, mandatoryValidatorsPassed=false) → Spring UNAVAILABLE
    401 인증 실패 → EVALUATOR_AUTH_FAILED
    409 IDEMPOTENCY_CONFLICT(retryable false) / IDEMPOTENCY_IN_PROGRESS(retryable true) → EVALUATOR_IDEMPOTENCY_CONFLICT
    413 PAYLOAD_TOO_LARGE, 422 CONTRACT_VALIDATION_FAILED(입력 원문 미반환) → EVALUATOR_INPUT_REJECTED
    429 EVALUATOR_BUSY(Retry-After 1) / RATE_LIMITED(Retry-After) → EVALUATOR_BUSY
    503 FEATURE_DISABLED → EVALUATOR_UNAVAILABLE
    라우트가 직접 만드는 오류 본문은 {success false, errorCode, retryable} 로 통일했다(401·413 은 인증 의존성·본문 제한 계층이 만든다).
  본문 상한(R5-9): 256KiB → 2,009,536 바이트(= 6 × (6만 + 8천 + 32 × 8천) + 64KiB). 계약 안의 한글 최대 입력(약 1MB, \u 이스케이프 시 약 1.9MB)이
    더는 413 이 되지 않는다. EC2 QualityEvaluatorClient.MAX_REQUEST_BYTES(256KiB)도 같은 값으로 올려야 한다(지금은 Spring 이 먼저 막는다).
    MaterialRoadmapQualityGate 의 세그먼트 예산 2만 자도 이 제한 때문에 잡은 값이라 키울 수 있다(키우면 평가 횟수가 준다).


8. 79점 거절 · 80점 승인 · Hard Fail 거절

  결함 수정: 점수를 소수 첫째 자리 반올림하던 탓에 원점수 79.95 가 80.0 이 되어 승인될 수 있었다 → 내림으로 바꿨다.
  테스트(tests/test_lq_phase_d_quality_boundaries.py): 79·79.9·79.99999 거절, 80·100 승인, MAJOR 감점 후 79 거절·80 승인, Hard Fail 은
    점수 80~100 이어도 거절(hardFail true, mandatoryValidatorsPassed false), 미검증은 점수와 무관하게 거절, APPROVED 79·APPROVED+hardFail·
    APPROVED+mandatoryValidatorsPassed=false·100.1·minimumScore 70 출력은 만들 수조차 없음, requestId 불일치는 노출 불가.
  같은 출력을 HTTP 라우트 → 엄격 파서 → Python is_displayable → EC2 Java isDisplayable(run_java_crosscheck.sh)로 다시 판정: Java 도 노출 가능은
    80·100 두 개뿐이고 timeout 출력을 포함해 모두 Java 출력 계약상 유효(VALID).


9. GPU 자원 경합 · 평가기 지연 측정

  별도 문서 학습루프_PhaseD_GPU경합_평가지연_측정계획.md. cpu 단계는 실측했고(로드맵 세그먼트 p50 8ms, 계약 최대치 PDF QA 1.3초·동시 4 이상
  429 과반), gpu 단계는 운영 GPU 점유라 실행하지 않았다(사전 점검 dry-run 만). judge 운영 결정(R5-3)은 gpu 단계 측정 전에는 근거가 없다.


10. 테스트 결과(2026-11-05, ai07 격리 venv + 일회용 pgvector PG, 운영 Redis·Ollama·GPU 차단)

  CI 목록(Phase D 포함): 772 통과, 실패 0. 기준 620 + Phase D 신규 152(로드맵 48, 경계·오류 29, 비전 13, 측정 도구 4, 근거 26, 학습 컨텍스트 32).
  전체 fastapi/tests: 2105 통과, 실패 3, 수집 오류 4. 실패·오류 7건은 기준선 d7346fc6 과 이름까지 같다(mode_contract 2, vision payload 1,
    major_analysis import 4). 새 회귀 0.
  EC2 crosscheck_pydantic.py: fixtures=30 mismatches=0. 차등 605건: 기록 판정·EC2 Java 라이브 재실행 모두 일치(divergences 0).
  Spring ↔ ai07 왕복(EC2 f9c878f5 격리 worktree, Gradle): RealAi07EvaluatorE2ETest 4개 통과(계약 fixture 실판정, 재생성 승인, SSE 미승인 본문 0자,
    지연·동시성) + 로드맵 분할 임시 E2E 4개 통과(2.3 절). 합계 8/8.
  EC2 가 실제로 보낸 학습 파이프라인 요청(TrainingPipelinePostgresTest 덤프, JVM TZ Asia/Seoul) → ai07 검증 코드: 5/5 ACCEPT.
  분할·체크섬 Java 대조 5/5 바이트 일치. 품질 게이트 합성 캘리브레이션 FAR 0, FRR 0(합성, 서비스 품질 수치 아님). gold 하네스 PREPARED_NOT_MEASURED.
  운영 미변경: 운영 checkout(LLM-clean)·프로세스·모델·DB 무변경. GPU 사용 0(측정 dry-run 은 nvidia-smi·/api/ps 읽기만).


11. 사고 — 운영 Redis 키에 테스트 데이터 기록 (조치 필요)

  무엇: Learning Memory 테스트 초기 실행에서 레거시 multi-chat 대화기억 모듈(app/services/multi_chat_redis_memory.py, 기본 ON, 기본 주소
    redis://127.0.0.1:16379 = ai07 의 운영 Redis 터널)이 켜진 채 roomId 1 요청이 흘러, 운영 키 studybridge:multi-chat:memory:room:1 에
    RPUSH → LTRIM(-20) → EXPIRE(7일)가 30~40회 실행됐다.
  현재 상태(읽기 전용 확인, 내용 미출력): 길이 20, TTL 약 7일, 테스트 문구가 보이는 항목 10건(나머지는 같은 테스트의 가짜 답변으로 추정).
    room 1 이 실제 방이면 기존 기억 20건은 잘려 나갔고, 7일 동안 그 방 프롬프트에 테스트 대화가 섞인다.
  원인: tests/conftest.py 가 STUDYMATE_REDIS 만 끄고 이 레거시 모듈은 끄지 않았다. 이전 세션의 전체 테스트 실행(roomId 1 을 쓰는 기존 테스트 포함)도
    같은 경로로 이 키를 썼을 수 있다(확인 불가).
  재발 방지(커밋함): conftest 에서 MULTI_CHAT_REDIS_MEMORY_ENABLED=false, MULTI_CHAT_REDIS_URL=닫힌 포트. 이후 전체 실행은 이 설정으로 했다.
  조치 결정 필요(운영 쓰기라 하지 않았다): 해당 키 삭제(DEL) 또는 7일 만료 대기. room 1 이 실제 사용 중인지 EC2 DB 로 확인 후 결정 권장.


12. 남은 일 · Go/No-Go

  ai07 남은 일: R5-6 학습노트 섹션별 pageRefs, R5-7 자료 분류 사유 enum, R5-8 학습일지 구조화, R5-10 리뷰 계열 결정적 폴백 origin 표식,
    R4 에이전트별 재생성 API(선택), 비전 bbox(VLM 스키마 확장 + GPU 실측), gpu 단계 측정 후 judge 운영 결정(R5-3).
  EC2 남은 일: 2.4·4·5·6·7장의 확인 사항(로드맵 BLOCKED 해제 검증, NON_REGENERABLE 코드 추가, 무결성 대조 위치, 근거 대조·매핑, 비전 관측 변환,
    learningContextReceipt META 키, MAX_REQUEST_BYTES 상향).
  Blockers(변동 없음): B-EGRESS(외부 전송 정책 — 이 PR 병합 시 운영 외부 전송 기본 차단), B-RIGHTS, B-ACCOUNT, gold benchmark 미측정,
    enforce 전 ops 재설치, GPU 경합 미측정, 그리고 11장 Redis 조치 결정.
  Go/No-Go: No-Go(운영 배포·게이트 ON·학습 수집 ON 모두). 두 PR 모두 병합 금지 유지.

  플래그 요약(전부 기본 꺼짐 또는 계약 호환):
    VISION_RETURN_OBSERVATIONS=false, AI_LEARNING_CONTEXT_ENABLED=false, AI_QUALITY_EVAL_MAX_BODY_BYTES=2009536(기본),
    AI_CONTENTION_PROBE_ALLOW(측정 도구 전용). grounding·evidenceIds·로드맵 origin/generationId/integrity 는 플래그 없는 추가 필드라
    병합 즉시 응답에 붙는다(Spring DTO 는 ignoreUnknown·Map 수신이라 파싱 영향 없음, 응답 크기만 증가).
