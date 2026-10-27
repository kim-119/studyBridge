StudyBridge 화면공유 비전 API 연동 계약 (ai07)
작성 2026-10-27, 최종 갱신 2026-10-28(운영 반영 준비: 출발지 네트워크 가드, AI Gateway, 실모델 검증 반영), 대상: Spring Boot·React 연동 담당
요약은 14절(최종 운영 계약), Spring·React 구현 순서는 15절에 있다.


1. 개요

엔드포인트: POST /api/ai/vision/analyze
상태 확인: GET /api/ai/vision/health
경로 규칙: 기존 Spring → ai07 호출이 모두 /api/ai/* 를 쓰므로 그 규칙을 따랐다(지시서의 /internal/vision/analyze 대신).
모델: qwen3-vl:4b-instruct (Apache-2.0, Q4_K_M, 약 3.3GB). 비전 전용 Ollama 0.40.11 이 127.0.0.1:11435 에서 서비스한다.
기능 플래그: VISION_API_ENABLED=true 일 때만 동작한다. 기본값 false 이고, 이때는 503 VISION_DISABLED 를 반환한다.
분석 단위: 브라우저가 캡처한 화면공유 프레임 1장과 질문 1개. 스트림은 받지 않는다.


2. 인증

헤더: Authorization: Bearer {AI_SERVER_API_KEY}
기존 Spring ↔ FastAPI 내부 키를 그대로 재사용한다.
기존 verify_internal_token 과 다르게 fail-closed 로 동작한다. 서버에 키가 설정되어 있지 않으면 503 VISION_AUTH_NOT_CONFIGURED 를 반환하고 요청을 통과시키지 않는다.
토큰 비교는 hmac.compare_digest 로 한다.
인증은 바디를 읽기 전에 검사한다.
ai07 은 사용자 권한(JWT, 그룹 JOINED, SCREEN 연결 활성, 공유자 동의)을 검증하지 않는다. 이 검증은 전부 Spring 의 책임이다.


3. 요청 JSON

필드 requestId: 필수. 문자열 또는 정수, 영숫자와 _ . : - 만 허용, 최대 128자. UUID 사용을 권장한다.
필드 groupId: 필수. 정수(Long) 또는 문자열. 그룹당 동시 처리 한도의 기준이 된다.
필드 streamId: 선택. 화면공유 connection id.
필드 sharerUserId, askerUserId: 선택. 정수 또는 문자열. 로그 상관관계 용도이며 ai07 은 이 값을 신뢰하거나 검증하지 않는다.
필드 question: 필수. 공백을 제거한 뒤 1자 이상, 최대 1000자(VISION_MAX_QUESTION_CHARS).
필드 image: 필수. Base64 문자열. data:image/jpeg;base64, 접두사는 허용한다.
필드 mime: 필수. 기본 허용값은 image/jpeg 하나다(image/jpg 는 image/jpeg 로 취급). VISION_ALLOWED_MIMES 로 image/png, image/webp 를 추가할 수 있다.

예시
{"requestId":"6f1c...","groupId":123,"streamId":"con_abc","sharerUserId":10,"askerUserId":20,"question":"이 화면에 표시된 Python 오류의 원인은 무엇인가요?","image":"/9j/4AAQ...","mime":"image/jpeg"}


4. 이미지 제한(서버 설정)

요청 바디 전체: 최대 2MB (VISION_MAX_BODY_BYTES). Content-Length 로 먼저 검사하고, 스트리밍으로 읽는 중에도 상한을 넘으면 즉시 중단한다.
디코딩된 이미지: 최대 1MB (VISION_MAX_IMAGE_BYTES). Base64 길이로 디코딩 전에 먼저 판단한다.
클라이언트 권장 크기: 약 300KB 이하. 1280px 캔버스에 JPEG quality 0.7~0.8 이면 충분하다. 실측 화면 픽스처는 33~52KB 였다.
해상도: 긴 변 최대 1280px (VISION_MAX_LONG_SIDE), 픽셀 수 최대 1280x1280, 짧은 변 최소 32px. 서버는 크기를 줄여 주지 않고 초과 시 거부하므로, 브라우저에서 축소한 뒤 보내야 한다.
검증 순서: 인증 → 바디 크기 → JSON → 필드/질문/MIME/길이 → Base64 엄격 디코딩 → magic bytes 와 MIME 일치 → 헤더 기준 해상도(픽셀 로드 전) → 픽셀 로드(손상 검출) → RGB JPEG 재인코딩(EXIF/ICC 제거).
압축 해제 폭탄 방어: 헤더만 읽은 상태에서 해상도를 검사하고, Pillow 의 DecompressionBomb 경고를 이 요청 범위에서만 오류로 승격한다. 전역 설정은 바꾸지 않는다.
다중 프레임 이미지는 거부한다.


5. 성공 응답 (200)

{"requestId":"6f1c...","answer":"화면에 보이는 내용: ... 분석: ...","model":"qwen3-vl:4b-instruct","latencyMs":1536,"queueWaitMs":0,"inferenceMs":1468}

latencyMs: ai07 이 요청을 받은 시점부터 응답을 만들 때까지의 서버 측 시간(대기열 대기 포함).
queueWaitMs: 추론 슬롯을 얻을 때까지 기다린 시간.
inferenceMs: 추론에 걸린 시간.
answer: 한국어 Markdown 이다. 화면에서 읽은 내용과 모델의 분석을 구분하도록 지시되어 있다. 최대 6000자이며, 넘으면 잘라 내고 생략 안내를 덧붙인다.


6. 오류 응답

형식
{"error":{"code":"VISION_QUEUE_FULL","message":"...","retryable":true,"requestId":"6f1c..."}}
재시도할 수 있는 오류에는 Retry-After 헤더(초)가 붙는 경우가 있다. message 에는 질문이나 이미지 같은 입력값을 넣지 않는다.

코드 목록 (HTTP 상태, 재시도 가능 여부)
AI_NETWORK_FORBIDDEN 403 아니오 — 신뢰 구간(loopback·사설망) 밖에서 내부 키 없이 호출(출발지 네트워크 가드, 응답 형식 동일)
VISION_DISABLED 503 아니오 — 기능 플래그 꺼짐
VISION_AUTH_NOT_CONFIGURED 503 아니오 — 서버에 내부 키 미설정
VISION_UNAUTHORIZED 401 아니오 — 토큰 없음 또는 불일치
VISION_BODY_TOO_LARGE 413 아니오
VISION_INVALID_JSON 400 아니오
VISION_INVALID_FIELD 422 아니오 — requestId, groupId 등 형식 오류
VISION_QUESTION_EMPTY 422 아니오
VISION_QUESTION_TOO_LONG 422 아니오
VISION_IMAGE_MISSING 422 아니오
VISION_UNSUPPORTED_MIME 415 아니오
VISION_INVALID_BASE64 422 아니오
VISION_IMAGE_TOO_LARGE 413 아니오
VISION_MIME_MISMATCH 415 아니오 — 선언한 MIME 과 실제 형식이 다름
VISION_IMAGE_CORRUPT 422 아니오 — 잘림, 손상, 다중 프레임
VISION_IMAGE_DIMENSIONS 422 아니오 — 너무 크거나 작음, 압축 해제 폭탄
VISION_DUPLICATE_REQUEST 409 아니오
VISION_GROUP_LIMIT 429 예 — 그룹당 동시 2건 초과
VISION_QUEUE_FULL 429 예 — 전체 대기열 초과(AI Gateway 의 비전 대기열 또는 사용자별 대기 상한 초과 포함)
VISION_QUEUE_TIMEOUT 503 예 — 대기 120초 초과. AI Gateway 가 켜져 있으면 GPU 슬롯 대기 30초 초과, 또는 GPU 텔레메트리를 읽을 수 없어 비전 모델 신규 적재를 보류한 경우도 포함
VISION_SHUTTING_DOWN 503 예 — 서버 종료 중
VISION_INFERENCE_TIMEOUT 504 예 — 추론 90초 초과
VISION_RESOURCE_EXHAUSTED 503 예 — GPU 또는 메모리 부족(OOM)
VISION_MODEL_UNAVAILABLE 503 아니오 — 모델이 설치되어 있지 않음
VISION_BACKEND_UNAVAILABLE 503 예 — 비전 Ollama(:11435) 연결 불가
VISION_EMPTY_RESPONSE 502 예 — 1회 재시도 후에도 빈 답
VISION_BACKEND_ERROR 502 예
VISION_CLIENT_CANCELLED 499 아니오 — Spring 이 연결을 끊음(로그 전용, 실제로 응답이 전달되지는 않음)
VISION_INTERNAL_ERROR 500 예


7. 중복 requestId 정책

같은 requestId 가 처리 중이면 409 VISION_DUPLICATE_REQUEST 를 반환한다.
성공한 requestId 는 10분(VISION_DUPLICATE_TTL_SECONDS) 동안 기억해 두고, 그동안 다시 오면 409 를 반환한다. 이전 답변을 다시 돌려주지는 않는다(답변을 저장하지 않기 때문).
실패한 requestId 는 기억하지 않으므로, 같은 id 로 재시도할 수 있다.
기억은 프로세스 메모리에만 있어서 ai07 을 재시작하면 초기화된다.


8. 동시성

받아들이는 요청 수와 GPU 에서 실제로 동시에 돌리는 추론 수를 분리했다.
VISION_MAX_CONCURRENCY=1: GPU 추론은 기본적으로 직렬로 실행한다. 실측에서 2로 올려도 처리량 이득이 없었다(10건 처리 11.7초 → 12.9초).
VISION_MAX_QUEUE=8: 추론 중 1건 외에 8건까지 대기한다. 그보다 많으면 429 VISION_QUEUE_FULL.
VISION_MAX_PER_GROUP=2: 한 그룹에서 처리 중인 요청은 최대 2건이다. 그보다 많으면 429 VISION_GROUP_LIMIT.
VISION_QUEUE_TIMEOUT_SECONDS=120, VISION_INFERENCE_TIMEOUT_SECONDS=90.
Spring 의 HTTP read timeout 은 대기와 추론 시간의 합보다 길게 잡아야 한다. 권장값은 250초 이상이다(최악: VisionGate 대기 120초 + AI Gateway 비전 슬롯 30초 + 추론 90초). 현재 Spring 컨테이너의 FASTAPI_TIMEOUT=180000(180초)은 이보다 짧으므로 비전 호출만 별도 타임아웃을 두거나 VISION_QUEUE_TIMEOUT_SECONDS 를 낮춘다.
요청마다 변수를 독립적으로 쓰고 이미지는 요청 스코프에서만 다루므로, 요청 사이에 답변이 섞이지 않는다. 동시 테스트에서 requestId 와 답변이 일대일로 일치하는 것을 확인했다.
동시성 게이트는 프로세스 단위다. 현재 운영은 단일 uvicorn 워커라서 이것으로 충분하다. 워커를 늘리면 한도도 워커 수만큼 곱해진다.
AI Gateway(AI_GATEWAY_ENABLED=true) 와 함께 쓰면 VisionGate 통과 뒤 GPU 가드를 한 번 더 거친다. 가드는 qwen3:14b 가 부분 offload 로 적재되지 않게 보호하고, 텍스트가 30초 이상 한가할 때만 텍스트를 내려 VL 을 전량 GPU 에 올린다. 텍스트 사용 중에는 VL 이 일부 CPU 로 밀린 채 공존한다(아래 13절 실측). 부분 offload 로 남은 VL 은 텍스트가 한가해지면 자동으로 전량 GPU 로 다시 올린다(재승격).
GPU 텔레메트리(nvidia-smi)를 10초 넘게 읽지 못하면 비전 모델 신규 적재를 보류한다(이미 상주 중이면 그대로 처리). 기본값 AI_GW_UNKNOWN_TELEMETRY_VISION=deny.


9. Spring 에서 구현할 일

1) 사용자 JWT 인증, 그룹 JOINED 확인, SCREEN 연결 활성 확인, 공유자 식별, 공유자의 AI 분석 동의 확인
2) 사용자별·그룹별 rate limit (ai07 의 그룹 한도 2는 마지막 방어선일 뿐이다)
3) 업로드 검증: JPEG, 긴 변 1280px 이하, 약 300KB, Base64 인코딩
4) requestId 를 UUID 로 생성하고, 재시도할 때는 새 id 를 쓴다(실패한 경우에는 같은 id 도 허용된다)
5) 호출: fastApiWebClient 로 Authorization: Bearer AI_SERVER_API_KEY 헤더와 함께, read timeout 250초 이상
6) 429/503 이면서 retryable=true 이면 Retry-After 를 참고해 재시도하거나 사용자에게 "잠시 후 다시" 를 안내하고, 4xx 이면서 retryable=false 이면 재시도하지 않는다
7) 응답 answer 를 RedisChatService 에 저장하고 STOMP 로 전달한다. 이미지는 Spring 에서도 저장하지 않을 것을 권장한다
8) 공정성 식별자(선택, 권장): Authorization 헤더와 함께 X-AI-User-Id(askerUserId), X-AI-Group-Id(groupId) 를 JWT 에서 꺼낸 값으로 보낸다. ai07 은 내부 인증이 맞는 요청의 이 헤더만 검증된 식별자로 쓰고, 본문 값은 클라이언트 주장값으로만 취급한다. 이 헤더는 AI 호출 전반(멀티챗, 퀴즈 등)에 같이 보내면 사용자·그룹 단위 공정성이 동작한다(현재 그룹스터디 멀티챗 payload 에는 사용자 식별자가 없다).
9) 주의: 기존 감사(09-28)에서 확인된 내용으로, fastApiWebClient 는 PRIMARY 전용이고 Secondary 는 API 키가 다르다. 그래서 Secondary 로 failover 하면 401 이 난다. Secondary 에는 비전 데몬도 없다.


10. 개인정보

이미지와 질문 원문은 디스크, DB, 로그에 쓰지 않는다. 임시 파일도 만들지 않는다(BytesIO 만 사용하며, 테스트로 확인했다).
로그에는 requestId, groupId, HTTP 상태, 오류 코드, 처리 시간, 이미지 가로·세로·바이트 수, 모델 id 만 남긴다.
예외를 로그에 남길 때는 예외 타입 이름만 쓰고, 메시지와 스택은 남기지 않는다.
이미지는 127.0.0.1:11435 의 로컬 Ollama 로만 전달하며 외부 서비스로는 보내지 않는다. Ollama 서버 로그에는 접근 줄([GIN])만 남고 프롬프트는 남지 않는다(OLLAMA_DEBUG 를 끈 상태 기준).
한계: Python 과 Ollama 의 메모리는 참조를 해제해도 즉시 지워진다는 보장이 없다. 이미지 텐서와 KV 캐시는 Ollama 프로세스 메모리에 keep_alive(2분) 동안 남을 수 있다.


11. 운영 반영 절차 (사용자 수행, 미실행)

1) 비전 데몬 상시화: cp fastapi/scripts/ollama-vision.service ~/.config/systemd/user/ 후 systemctl --user daemon-reload, systemctl --user enable --now ollama-vision. 모델은 ~/ollama-vision/models 에 이미 받아 두었다.
2) hotfix_main.py 라우터 등록 블록은 feature/ai-gateway-scheduler 브랜치에 반영되어 있다(아래와 같은 내용, tracked 파일이므로 commit+push 해야 autodeploy reset 후에도 남는다).
   try:
       from app.vision.router import router as vision_router
       paths = {getattr(route, "path", None) for route in app.routes}
       if "/api/ai/vision/analyze" not in paths:
           app.include_router(vision_router)
   except Exception as e:
       import logging
       logging.getLogger(__name__).warning("vision 라우터 로드 실패 (계속 기동): %s", e)
3) app/vision/, tests/test_vision_api.py, scripts/vision_load_test.py, scripts/ollama-vision.service, 이 문서를 함께 커밋한다.
4) fastapi/.env 에 VISION_API_ENABLED=true 를 넣고 studybridge-ai 를 재시작한다(sudo).
5) 확인: curl -H "Authorization: Bearer $AI_SERVER_API_KEY" http://127.0.0.1:8000/api/ai/vision/health


12. 롤백과 비활성화

즉시 비활성화: VISION_API_ENABLED=false 로 바꾸고 재시작한다. 라우트는 남아 있지만 503 VISION_DISABLED 만 반환하고, 기존 기능에는 영향이 없다.
비전 데몬 중지: systemctl --user disable --now ollama-vision. 이후 API 는 503 VISION_BACKEND_UNAVAILABLE 를 반환한다.
완전 제거: hotfix_main.py 에서 위 블록을 빼고 app/vision/ 을 삭제한 뒤, rm -rf ~/ollama-vision 으로 바이너리와 모델(약 4.8GB)을 지운다.


13. 운영 위험 (실측 기반)

VRAM: 16GB 한 장을 세 프로세스가 나눠 쓴다. 기존 uvicorn 이 1.5GB, 시스템 Ollama 의 qwen3:14b 가 9.7GB, 비전 Ollama 가 4.5GB 를 쓴다. 두 Ollama 데몬은 서로의 VRAM 사용을 모른다.
실측 1: qwen3:14b 가 먼저 적재되어 있으면 qwen3:14b 는 전량 GPU 에 남는다. 대신 VL 이 37개 레이어 중 30개만 GPU 에 올라가 비전 추론이 1.5초에서 4.5~9.2초로 느려진다.
실측 2: 비전 추론 중에 qwen3:14b 가 새로 적재되면, qwen3:14b 의 일부(9672MiB 중 약 1GB)가 CPU 로 밀려 운영 채팅 속도가 82 tok/s 에서 37~46 tok/s 로 떨어진다. 이 상태는 qwen3:14b 의 keep_alive(30분) 동안 유지된다.
완화: VISION_KEEP_ALIVE=2m 으로 VL 을 빨리 내려 두 모델이 겹치는 시간을 줄인다.
근본 해결(sudo 필요): 시스템 Ollama 를 0.30 이상으로 올려 한 스케줄러가 두 모델을 함께 관리하게 한다. 다만 10-06 에 GPU 커널/드라이버 스택 불일치로 장애가 났던 이력이 있으므로 단계적으로 진행한다.
실측 3(2026-10-27, AI Gateway + GPU 가드 adaptive, 합성 화면 9종): 유형별 품질 9/9(코드·Python/Java 오류·이진 탐색·수식·웹페이지·슬라이드·PDF·인젝션 거부·판독 불가 시 추측 거부), VL 전량 GPU 일 때 단건 0.8~3.2초, 서로 다른 화면 2건 동시 1.3초/2.6초, 10건 동시 9건 성공·1건 429, 재승격 적용 후 10건 p50 7.5초(적용 전 44.8초). 채팅·멀티에이전트 실행 중의 비전은 VL 이 21/37 레이어만 GPU 에 올라가 12~25초.
완화 2: FastAPI 임베딩을 CPU 로 옮기면(EMBEDDING_DEVICE=cpu, 약 1.5GB 반환) 계산상 두 모델이 함께 전량 GPU 에 들어간다(미검증, 운영 FastAPI 재시작 필요).
보안: 화면 속 지시문 인젝션은 실측에서 "화면 지시대로 해줘" 요청에 1회 중 1회 순응했다. 프롬프트를 보강한 뒤에는 8회 중 0회, 시스템 프롬프트 누출도 0회였다. 4B 모델이므로 완전한 차단을 보장하지는 않는다. 답변을 그대로 실행하는 도구 연동은 하지 않는다.


14. 최종 운영 계약 요약 (2026-10-28)

호출 주체: Spring Boot 서버만 호출한다. 브라우저·앱이 ai07 을 직접 호출하지 않는다(nginx 는 /api/ 를 Spring 으로만 보낸다).
주소: POST {FASTAPI_PRIMARY_BASE_URL}/api/ai/vision/analyze (현재 http://host.docker.internal:18000, ai07 역터널). Secondary(:8000)로 failover 하지 않는다(키가 다르고 비전 데몬이 없다).
헤더: Content-Type: application/json, Authorization: Bearer {AI_SERVER_API_KEY}(필수, 없거나 틀리면 401). 권장: X-AI-User-Id(askerUserId), X-AI-Group-Id(groupId) — JWT·DB 에서 확인한 값만 넣는다. 내부 키가 맞을 때만 ai07 이 검증된 공정성 식별자로 쓴다.
출발지 제한: ai07 은 loopback·사설망 출발지(SSH 역터널, 도커 브리지)만 받는다. 그 밖의 출발지는 내부 키가 있을 때만 통과하고, 없으면 403 AI_NETWORK_FORBIDDEN.
요청: requestId(문자열 UUID 권장, 재시도는 새 id), groupId(Long), streamId(화면공유 connection id), sharerUserId(Long), askerUserId(Long), question(1~1000자), image(Base64, data URI 접두사 허용), mime("image/jpeg").
이미지 제한: 디코딩 1MB 이하, 요청 바디 2MB 이하, 긴 변 1280px 이하, 짧은 변 32px 이상, 단일 프레임 JPEG. 서버는 축소하지 않고 거부한다. 권장 업로드: 긴 변 1280px, JPEG quality 0.7~0.8, 약 300KB 이하(실측 화면 27~53KB).
응답 200: requestId, answer(한국어 Markdown, 최대 6000자, '화면에 보이는 내용:'과 '분석:' 구분), model, latencyMs, queueWaitMs, inferenceMs.
시간 예산(서버 설정 기본값): VisionGate 대기 120초, AI Gateway 비전 슬롯 대기 30초(게이트웨이 켜짐 시), 추론 90초. Spring read timeout 은 250초 이상(최악 120+30+90초). 실측: 비전 모델이 전부 GPU 에 있을 때 단건 0.8~3.2초, 다른 화면 2건 동시 1.3초/2.6초, 10건 동시 p50 7.5초(1건 429), 채팅·멀티에이전트가 동시에 돌 때 12~25초.
재시도: retryable=true(429/503/502/504/500) 이면 Retry-After 초를 지켜 1회 재시도 또는 사용자에게 잠시 후 안내. retryable=false(4xx) 는 재시도하지 않는다. 409 는 같은 requestId 로 보낸 중복이다.
동시성 한도: 전체 대기 8건(초과 429 VISION_QUEUE_FULL), 그룹당 처리 중 2건(초과 429 VISION_GROUP_LIMIT). 그룹당 화면공유 최대 2명과 ai07 전체 동시 요청 수는 별개다 — ai07 은 여러 그룹의 요청을 한 대기열에서 직렬 처리한다.
개인정보: ai07 은 이미지·질문을 저장하거나 로그에 남기지 않는다. Spring 도 이미지를 저장하지 않는 것을 권장한다.
ai07 이 검증하지 않는 것(Spring 책임): 사용자 JWT, 그룹 JOINED, 공유자 식별, SCREEN 연결 활성, 공유자의 AI 분석 동의, 사용자·그룹별 rate limit.


15. Spring·React 구현 순서 (후속 개발)

React(공유 화면을 보는 참가자):
1) 질문 버튼을 누른 시점의 공유 영상(OpenVidu subscriber video 요소) 프레임 1장을 canvas 로 캡처한다. 연속 스트림은 보내지 않는다.
2) 긴 변을 1280px 이하로 축소하고 canvas.toBlob(..., 'image/jpeg', 0.75) 로 인코딩한다. 300KB 를 넘으면 quality 를 0.6 까지 낮춘다.
3) Spring 의 그룹 스터디 API(예: POST /api/group-studies/{groupId}/screen-ai/ask, 경로는 Spring 에서 결정)에 groupId, streamId(공유자 connection id), question, image(Base64), mime 을 보낸다. 사용자 식별자는 보내지 않는다(Spring 이 JWT 로 결정).
4) 응답 대기 중 "화면을 분석하고 있어요" 상태를 보여 주고, 429/503 은 "잠시 후 다시" 로, 4xx 검증 오류는 메시지 그대로 안내한다. 답변은 STOMP 로 그룹 채팅에 들어온다.

Spring:
1) JWT 사용자 확인 → 그룹 JOINED 확인 → streamId 가 지금 화면공유 중인 연결인지 확인 → 공유자 동의 확인 → 사용자·그룹 rate limit(예: 사용자당 분당 3회).
2) requestId 를 UUID 로 만들고, sharerUserId/askerUserId 를 서버에서 채운다.
3) fastApiWebClient(PRIMARY)로 위 14절 형식으로 호출한다. Authorization: Bearer {AI_SERVER_API_KEY} 와 X-AI-User-Id, X-AI-Group-Id 를 붙인다. responseTimeout·ReadTimeoutHandler 250초 이상(현재 공용 FASTAPI_TIMEOUT 180초라 비전 전용 WebClient 또는 요청별 timeout 필요).
4) 성공하면 answer 를 RedisChatService 에 AI 메시지로 저장하고 STOMP /topic 으로 그룹에 전달한다. 실패 코드는 14절 재시도 규칙대로 처리한다.
5) 다른 AI 호출(멀티챗·퀴즈 등)에도 X-AI-User-Id/X-AI-Group-Id 와 Authorization 을 붙이면 ai07 의 사용자·그룹 공정성이 정확해지고, 이후 AI_NETWORK_GUARD=strict(모든 AI 호출 키 필수)로 올릴 수 있다.

