# 로컬 개발 환경 설치 (SETUP)

이 문서는 저장소를 처음 받은 개발자가 **자기 PC에서 StudyBridge를 실행**하기 위한 절차입니다.
운영 서버 배포는 [DEPLOYMENT.md](DEPLOYMENT.md)를 참고하세요.

> 모든 명령과 설정값은 저장소의 `docker-compose.yml`, `backend/src/main/resources/application.yml`,
> `frontend/package.json`, `fastapi/requirements.txt`, `.github/workflows/*.yml`에서 확인한 것입니다.

---

## 1. 무엇을 띄워야 하나

| 구성요소 | 필수 여부 | 실행 방법 | 포트 |
|---|---|---|---|
| PostgreSQL | 필수 | `docker compose up -d db` (`postgres:16`) | 5432 |
| Redis | 필수 | `docker compose up -d redis` (`redis:7-alpine`) | 6379 |
| Spring Boot | 필수 | `./gradlew bootRun` 또는 `docker compose up -d spring` | 8080 |
| React | 필수 | `npm run dev` | 3000 |
| OpenVidu | 그룹 화상 기능만 | `docker compose up -d openvidu` | 127.0.0.1:14443 |
| coturn | 원격 화상(다른 네트워크)만 | `docker compose up -d coturn` (host network) | 3478, 49160-49200/udp |
| FastAPI + Ollama | AI 기능만 | 아래 [5. AI 서버](#5-ai-서버-선택) | 8000, 11434 |

AI 서버가 없어도 회원가입·로그인·자료 업로드(S3 설정 시)·플래너·그룹 등 대부분 화면은 동작합니다.
AI 응답이 필요한 기능(채팅, 요약, 퀴즈 생성 등)은 실패 메시지나 규칙 기반 폴백으로 끝납니다.

## 2. 선행 설치

| 도구 | 버전 | 근거 |
|---|---|---|
| JDK | 21 | `backend/build.gradle` (`sourceCompatibility = '21'`), CI `setup-java 21` |
| Node.js | 20 (웹) / 22 (Android·Capacitor CLI) | `ci.yml`, `android-ci.yml` |
| Python | 3.12 | `ci.yml` `fastapi-ci`, `fastapi/Dockerfile` |
| Docker, Docker Compose v2 | 최신 | `docker-compose.yml` |
| Git | 최신 | |

## 3. 저장소와 환경변수

```bash
git clone https://github.com/kim-119/studyBridge.git
cd studyBridge
cp .env.example .env
```

`.env`에서 최소한 다음을 채웁니다.

```dotenv
JWT_SECRET=<32자 이상 임의 문자열>      # 없으면 Spring 이 기동하지 않습니다
DB_HOST=localhost                        # bootRun 으로 실행할 때. compose 의 spring 컨테이너는 db
DB_PORT=5432
DB_NAME=capstone
DB_USER=capstone
DB_PASSWORD=<로컬 DB 비밀번호>
POSTGRES_PASSWORD=<위와 같은 값>
```

> `JWT_SECRET`은 `openssl rand -base64 48` 등으로 생성하세요. 실제 운영 값을 로컬에 복사하지 않습니다.

### 환경변수

| 변수 | 용도 | 필수 | 서비스 | 예시 / 기본값 | 주의 |
|---|---|---|---|---|---|
| `JWT_SECRET` | JWT 서명 키 | ✅ | Spring | (임의 문자열) | 기본값 없음 |
| `JWT_EXPIRATION_MS` | 액세스 토큰 수명 | | Spring | `1800000` | |
| `DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD` | DB 접속 | ✅ | Spring | `localhost` / `5432` / `capstone` | 운영은 RDS 값 |
| `POSTGRES_DB` `POSTGRES_USER` `POSTGRES_PASSWORD` | 로컬 `db` 컨테이너 초기화 | 로컬 DB 사용 시 | db | `capstone` | |
| `SPRING_DATA_REDIS_HOST` `SPRING_DATA_REDIS_PORT` | Redis | | Spring | `redis` / `6379` | bootRun 이면 `localhost` |
| `AWS_ACCESS_KEY_ID` `AWS_SECRET_ACCESS_KEY` `AWS_REGION` `AWS_S3_BUCKET` | 자료·이미지·APK 저장 | 업로드 시 | Spring, FastAPI | | 개인 테스트 버킷 사용 권장 |
| `FASTAPI_PRIMARY_BASE_URL` | AI 서버 1순위 | AI 사용 시 | Spring | compose 기본 `http://host.docker.internal:18000` | bootRun 이면 `http://localhost:8000` |
| `FASTAPI_SECONDARY_BASE_URL` | AI 서버 2순위(failover) | | Spring | compose 기본 `http://host.docker.internal:8000` | 비우면 failover 없음 |
| `FASTAPI_TIMEOUT` | PDF 추출 등 호출 타임아웃(ms) | | Spring | `180000` | |
| `AI_SERVER_API_KEY` | Spring↔FastAPI Bearer 키 | 운영 권장 | Spring, FastAPI | | 양쪽 같은 값. FastAPI 는 미설정 시 검사 생략 |
| `AI_STREAM_*`, `AI_UPSTREAM_*`, `AI_*_TIMEOUT_SECONDS` | SSE·failover·기능별 타임아웃 | | Spring | compose 기본값 참고 | |
| `AI_RECOMMENDATION_ENABLED`, `AI_FEEDBACK_CONCEPT_REVIEW_ENABLED` | 기능 플래그 | | Spring | `false` | |
| `OPENVIDU_SECRET` `OPENVIDU_PUBLICURL` `OPENVIDU_DOMAIN_OR_PUBLIC_IP` | 화상 서버 | 화상 사용 시 | Spring, openvidu | | 기본 secret 은 개발용 값 |
| `TURN_USERNAME` `TURN_PASSWORD` `TURN_PUBLIC_IP` `TURN_PRIVATE_IP` | TURN relay | 원격 화상 시 | coturn | | 로컬에서는 자신의 IP 로 덮어쓰기 |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USERNAME` `SMTP_PASSWORD` `SMTP_FROM` `SMTP_FROM_NAME` | 비밀번호 재설정 메일 | 선택 | Spring | `587`, STARTTLS | 미설정 시 해당 API 503 |
| `PASSWORD_RESET_*` | 인증번호 TTL·발송 제한 | | Spring | | |
| `BANNER_MAIN_*` | 메인 배너 문구 | | Spring | | `BANNER_MCP_TOKEN` 은 서버 전용 |
| `ANDROID_RELEASE_*` | APK 다운로드(S3) | | Spring | | |
| `EXHIBIT_*` | 전시 체험 계정 | | Spring | | 공개 배포 시 비활성 권장 |
| `TZ` | 시간대 | | 전체 | `Asia/Seoul` | |
| `VITE_API_BASE_URL` | 프론트 → API 오리진 | 로컬 dev 시 | Frontend(빌드 시점) | `http://localhost:8080` | 운영은 비워 두면 같은 오리진 |
| `VITE_FASTAPI_BASE_URL` | (레거시) 브라우저 → FastAPI 직접 경로 | | Frontend | 빈 값 | 현재 화면은 Spring 경유 |
| `VITE_STUDYMATE_SSE` | 스터디메이트 SSE 사용 | | Frontend | `true` | |
| `OLLAMA_BASE_URL` `OLLAMA_MODEL` `OLLAMA_SUMMARY_MODEL` | LLM | AI 서버 | FastAPI | `http://localhost:11434`, `qwen3:14b` | `fastapi/.env.example` 참고 |
| `VISION_BACKEND` `VISION_MODEL` `VISION_OLLAMA_BASE_URL` | 화면 분석 비전 모델 | 화면 AI 시 | FastAPI | `qwen3-vl:4b-instruct` | |
| `OPENAI_API_KEY` `OPENAI_MODEL` | 일부 검증·비전 답변 | 선택 | FastAPI | `gpt-4o-mini` | |
| `EMBEDDING_MODEL_NAME` `AI_DATABASE_URL` `REDIS_URL` `RAG_*` | 임베딩·pgvector·메모리 | RAG 사용 시 | FastAPI | `intfloat/multilingual-e5-base` | |

FastAPI 전체 변수(약 300여 개, 대부분 선택)는 [`fastapi/.env.example`](../fastapi/.env.example)에 주석과 함께 있습니다.

## 4. 웹 실행

### 4.1 DB · Redis
```bash
docker compose up -d db redis
docker compose ps
```

### 4.2 Spring Boot
```bash
cd backend
set -a; source ../.env; set +a          # .env 값을 셸에 로드
export DB_HOST=localhost SPRING_DATA_REDIS_HOST=localhost
./gradlew bootRun
```
- 스키마는 `spring.jpa.hibernate.ddl-auto: update`로 자동 생성됩니다. `backend/src/main/resources/db/migration/*.sql`은 Flyway가 없어 **자동 실행되지 않는** 참고용 SQL입니다.
- 관리자 계정 등 초기 데이터는 `AdminInitializer` 등 기동 시 코드로 생성됩니다. **관리자 기본 비밀번호는 코드에 고정되어 있으므로 실제 환경에서는 즉시 변경**하세요.
- 컨테이너로 띄우려면 `docker compose up -d spring` (이미지 빌드에 수 분 소요, `DB_HOST=db`).

### 4.3 React
```bash
cd frontend
npm ci
VITE_API_BASE_URL=http://localhost:8080 npm run dev      # http://localhost:3000
```
`vite.config.js`에는 프록시가 없으므로 로컬에서는 `VITE_API_BASE_URL`을 지정해야 합니다.

### 4.4 정상 동작 확인
```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/banners/main   # 200
```
브라우저에서 http://localhost:3000 → 회원가입 → 로그인 → 자료보관함 화면이 열리면 웹·API·DB 연결이 정상입니다.

## 5. AI 서버 (선택)

운영 AI 서버는 GPU 머신(ai07)에서 동작합니다. 로컬에서 재현하려면 **NVIDIA GPU(16GB VRAM 권장)** 와 Ollama가 필요합니다.

```bash
# 1) Ollama 설치 후 모델 준비 (모델 태그는 fastapi/.env.example 기준)
ollama pull qwen3:14b
ollama pull qwen3-vl:4b-instruct      # 화면 분석을 쓸 때만

# 2) FastAPI
cd fastapi
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # 값 채우기 (AI_SERVER_API_KEY 는 Spring 과 동일하게)
uvicorn hotfix_main:app --host 0.0.0.0 --port 8000
```

- 운영 진입점은 `hotfix_main:app`입니다(`main.app`을 import 후 호환·기능 라우터를 추가). `fastapi/Dockerfile`은 `main.py`만 복사하는 오래된 파일이라 운영 구성과 다릅니다.
- `sentence-transformers` 등으로 첫 설치·기동 시 수 GB의 모델 다운로드가 일어날 수 있습니다.
- Spring을 bootRun으로 실행 중이면 `FASTAPI_PRIMARY_BASE_URL=http://localhost:8000`을 지정합니다.
- 확인: `curl http://localhost:8000/health`

## 6. Android (선택)

Android 앱 개발 라인은 `android-features` 브랜치입니다. `main`에도 `android/` 프로젝트가 있으나 최신 네이티브 기능(화면공유 모듈, 위젯 등)은 `android-features`/`android-main`에 있습니다.

```bash
# Node 22, JDK 21, Android SDK(platform 36) 필요
npm ci && npm --prefix frontend ci
MOBILE_API_BASE_URL=https://studybridge.co.kr npm run build:mobile
npx cap sync android
cd android && ./gradlew assembleDebug        # app/build/outputs/apk/debug/
```
- 모바일 번들의 API 주소는 `VITE_API_BASE_URL`(빌드 시 주입)이며 https가 아니면 빌드가 실패합니다(WebView 오리진이 `https://localhost`).
- 테스트: `npm --prefix frontend run test:mobile`, `cd android && ./gradlew testDebugUnitTest lintDebug`
  - Node 20에서는 `node --test`가 glob을 펼치지 못하므로 `cd frontend && node --test src/mobile/__tests__/*.test.mjs`로 실행하세요.

## 7. 테스트 명령 모음

| 대상 | 명령 |
|---|---|
| 백엔드 빌드 + 단위 테스트 | `cd backend && ./gradlew clean build` |
| 프론트 빌드 | `cd frontend && npm run build` |
| 모바일 lint / 테스트 / 번들 | `npm --prefix frontend run lint:mobile` / `test:mobile` / `build:mobile` |
| FastAPI 문법 검사 | `cd fastapi && python -m compileall .` |
| FastAPI 테스트 | `cd fastapi && python -m pytest -q tests` |
| Compose 설정 검사 | `docker compose config -q` |

> 전체 `npm run lint`(`eslint .`)는 웹 영역 ESLint 설정 파일이 없어 현재 실행되지 않습니다. 모바일 영역은 `src/mobile/.eslintrc.cjs`로 `lint:mobile`이 동작합니다.
