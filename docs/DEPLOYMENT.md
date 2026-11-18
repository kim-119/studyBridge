# 배포 및 운영 (DEPLOYMENT)

운영 구성: **AWS EC2(Ubuntu) + Nginx + Docker Compose + AWS RDS + AWS S3 + 외부 GPU AI 서버(ai07)**.
구조는 [ARCHITECTURE.md](ARCHITECTURE.md)를 참고하세요.

> 이 문서는 절차와 설정 방법만 다룹니다. 실제 호스트 IP, 비밀번호, 키 값은 적지 않습니다.

---

## 1. 서버 요구사항

| 항목 | 내용 |
|---|---|
| OS | Ubuntu (운영: 24.04 계열) |
| 패키지 | Docker, Docker Compose v2, Nginx, certbot, git, Python 3.12(EC2 SECONDARY FastAPI), Node 20(수동 프론트 빌드 시) |
| 포트(보안 그룹) | 80/443(웹), 4443(OpenVidu 공개 URL), 3478 tcp/udp + 49160-49200/udp(TURN) |
| 내부 포트(127.0.0.1 바인딩) | 8080 Spring, 6379 Redis, 14443 OpenVidu, 5432 로컬 DB, 8000 FastAPI, 18000 ai07 터널 |
| 디스크 | Docker 이미지·빌드 캐시가 빠르게 늘어납니다. **루트 디스크가 가득 차면 Spring 재빌드·Nginx가 실패해 502가 발생**하므로 주기적으로 `docker system df`, `docker builder prune`을 점검하세요 |

## 2. 최초 구성

```bash
# 1) 코드
cd /home/ubuntu && git clone https://github.com/kim-119/studyBridge.git && cd studyBridge
git switch LLM-clean            # 현재 운영 배포 브랜치

# 2) 비밀값 (Git 에 커밋하지 않음)
cp .env.example .env            # DB_*(RDS), AWS_*, OPENVIDU_*, TURN_*, SMTP_*, AI_SERVER_API_KEY …
mkdir -p /home/ubuntu/.studybridge-secrets
printf 'JWT_SECRET=%s\n' "$(openssl rand -base64 48)" > /home/ubuntu/.studybridge-secrets/spring.env
chmod 600 .env /home/ubuntu/.studybridge-secrets/spring.env

# 3) 백엔드 계열 기동 (DB 는 RDS — db 컨테이너는 띄우지 않음)
docker compose up -d redis openvidu coturn
docker compose up -d --build spring
docker logs -f capstone-spring | grep -m1 'Started ApiApplication'

# 4) 프론트 정적 릴리스
cd frontend && npm ci && npm run build
SHA=$(git rev-parse --short=8 HEAD)
sudo mkdir -p /var/www/studybridge/releases/$SHA
sudo cp -r dist/. /var/www/studybridge/releases/$SHA/
sudo ln -sfn /var/www/studybridge/releases/$SHA /var/www/studybridge/current
```

### 2.1 Nginx · HTTPS
- 설정 원본: `ops/nginx/studybridge-sites.conf`(server 블록), `studybridge-site-common.conf`(공통 location), `studybridge-mobile-ua.conf`, `studybridge-seo.conf`.
- 설치·인증서·롤백 절차는 [`ops/nginx/README.md`](../ops/nginx/README.md)에 있습니다(`certbot`으로 apex·www·m 도메인 SAN 인증서 발급).
- 핵심 설정: `/api/`는 `proxy_buffering off`·긴 timeout(SSE), `/ws-group`은 WebSocket 업그레이드, `/openvidu/`는 `127.0.0.1:14443`, `client_max_body_size 100M`.
- 적용: `sudo nginx -t && sudo systemctl reload nginx`

### 2.2 데이터베이스(RDS) · Redis
- `docker-compose.override.yml`이 `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`를 Spring에 주입합니다.
- 스키마는 `ddl-auto: update`로 갱신됩니다. **NOT NULL 컬럼 추가, enum CHECK 제약 변경, 인덱스**는 자동 반영되지 않으므로 배포 전에 RDS에 수동 SQL을 적용해야 합니다.
- Redis는 compose `redis` 컨테이너(127.0.0.1:6379)입니다.

### 2.3 AI 서버 연결 (ai07 · 외부 의존성)
| 항목 | 내용 |
|---|---|
| PRIMARY | ai07 GPU 서버의 FastAPI(`hotfix_main:app`) + Ollama. 저장소 밖 하드웨어·드라이버·모델 파일이 필요 |
| 연결 | ai07 → EC2 reverse SSH tunnel(`127.0.0.1:18000`), Docker에서 접근하도록 `ops/studybridge-bridge-18000.service`(socat) |
| SECONDARY | EC2의 `studybridge-fastapi.service`(:8000). `cd.yml` fastapi 잡이 설치·재기동 |
| 인증 | Spring `AI_SERVER_API_KEY` ↔ FastAPI `AI_SERVER_API_KEY` 동일 값(Bearer) |
| ai07 배포 | `ops/studybridge-ai07-autodeploy.sh`(스냅샷·격리·`--rollback` 지원), `ops/install-ai07-ops.sh` |
| 검증 | `scripts/ai-route-gate.sh <base> --label …`, `ops/studybridge-ai-route-verify.timer`(1분 주기) |

> ai07 GPU 서버, Ollama 모델, NVIDIA 드라이버, SSH 터널 키는 이 저장소만으로 재현할 수 없는 **운영 전용 외부 의존성**입니다.

### 2.4 OpenVidu · TURN
- `openvidu/openvidu-dev:2.30.0`은 내부에서 평문으로 동작하고, 호스트 Nginx가 Let's Encrypt 인증서로 TLS를 종단합니다(`OPENVIDU_PUBLICURL`).
- coturn은 host 네트워크로 실행되며 `TURN_PUBLIC_IP`/`TURN_PRIVATE_IP`를 서버 값으로 지정해야 합니다. relay 포트 범위가 좁으면 동시 접속 시 "카메라 연결 중"이 지속될 수 있습니다.

## 3. CI/CD

| 워크플로 | 트리거 | 동작 |
|---|---|---|
| `ci.yml` | push/PR: `main`, `develop`, `LLM-clean`, `backend`, `frontend`, `fastapi`, `feature/**` | 백엔드 `gradlew build`, 프론트 `npm run build`, FastAPI `compileall`, Docker 이미지 빌드, 결과 집계 |
| `cd.yml` | **push: `LLM-clean`**, 수동(`target`: all/frontend/backend/fastapi) | 변경 경로 감지 → 프론트·백엔드·FastAPI 개별 배포 |
| `android-ci.yml` | push/PR: `android-features`, `android-main` (경로 필터) | 모바일 lint·테스트, 웹/모바일 번들, 번들 가드, `cap sync`, Gradle 테스트·lint·Debug APK, 화면공유 APK 검증 |
| `android-release.yml` | **push: `android-features`**, 수동 | 다음 버전 계산(`/api/app/version` +1) → 릴리스 노트 검증 → 서명 APK/AAB → `apksigner verify` → EC2 `ops/android/publish-android-release.py`로 S3 게시 |
| `android-screenshare-e2e.yml` | PR → `android-features`(android/**), 수동 | 에뮬레이터 + 로컬 OpenVidu로 화면공유 E2E |

### 3.1 웹 배포(cd.yml) 상세
- **frontend**: GitHub Runner에서 빌드 → tar 전송 → `/var/www/studybridge/releases/<sha8>` → `ln -sfn … current` → `nginx -t` + reload → 응답 확인.
- **backend**: EC2에서 `git reset --hard <sha>` → 현재 이미지를 `:prev`로 태그 → `docker compose build spring` → spring만 재생성 → 최대 3분 `Started ApiApplication` 대기 → 실패 시 `:prev`로 자동 롤백.
- **fastapi**: EC2 `.venv`에 의존성 설치 → systemd 유닛 재기동 → `/health` → `scripts/ai-route-gate.sh`.
- spring 재생성 동안 약 20~30초 Nginx 502가 발생할 수 있습니다.
- `git reset --hard`는 EC2 작업 트리의 **커밋되지 않은 수정**을 덮어씁니다(untracked 파일은 유지, `git clean`은 하지 않음).

> `main` 브랜치의 `cd.yml`에는 "동일 SHA의 CI 성공 확인 후 배포"(`wait-for-ci.sh`), 배포 후 공개 API 점검, 프론트 심볼릭 링크 롤백이 추가되어 있습니다. 현재 운영에서 실행되는 것은 `LLM-clean` 브랜치의 `cd.yml`이므로, 배포 브랜치를 바꾸기 전에 두 파일의 차이를 검토해야 합니다([BRANCH_MERGE_REPORT.md](BRANCH_MERGE_REPORT.md) §6).

### 3.2 GitHub Secrets
| 이름 | 사용처 |
|---|---|
| `EC2_HOST`, `EC2_USERNAME`, `EC2_SSH_KEY` | `cd.yml`, `android-release.yml` (SSH/SCP) |
| `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` | `android-release.yml` 서명 (작업 종료 시 keystore 파일 삭제) |

AWS 키는 GitHub에 두지 않습니다. APK 게시 스크립트는 EC2의 `.env`에 있는 S3 자격증명을 사용합니다.
설정: GitHub → Settings → Secrets and variables → Actions → New repository secret.

## 4. Android 릴리스
1. `android/release-notes/<다음 versionName>.txt`를 작성합니다(한국어 8줄 이내, `feat:` 접두사·불릿 금지).
2. `android-features`에 push → `android-release.yml`이 버전을 자동 증가시키고 서명 APK를 빌드합니다.
3. EC2 게시 스크립트가 S3 `android/releases/StudyBridge-<ver>.apk` → `android/latest/` → `version.json` 순으로 갱신하고 공개 URL을 검증합니다.
4. 앱은 `/api/app/version`으로 새 버전을 확인합니다. 웹 다운로드 페이지는 `https://studybridge.co.kr/app`입니다.

Debug APK는 `android-ci.yml` 아티팩트(`studybridge-app-debug`)로 받을 수 있습니다. 서명 키스토어가 없으면 릴리스 빌드는 불가합니다.

## 5. 배포 확인
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://studybridge.co.kr/                 # 200
curl -s -o /dev/null -w '%{http_code}\n' https://studybridge.co.kr/api/banners/main  # 200
curl -s https://studybridge.co.kr/api/app/version | head -c 200
docker ps --format '{{.Names}}\t{{.Status}}'
curl -s http://127.0.0.1:8000/health          # EC2 SECONDARY
curl -s http://127.0.0.1:18000/health         # ai07 PRIMARY (터널)
```

## 6. 롤백
| 대상 | 방법 |
|---|---|
| 프론트 | `sudo ln -sfn /var/www/studybridge/releases/<이전sha> /var/www/studybridge/current && sudo systemctl reload nginx` |
| 백엔드 | `docker tag studybridge-backend:prev studybridge-backend:latest && docker compose up -d --no-deps --force-recreate spring` (cd.yml 실패 시 자동 수행) |
| FastAPI(EC2) | 이전 커밋으로 `git reset` 후 `sudo systemctl restart studybridge-fastapi` |
| FastAPI(ai07) | `ops/studybridge-ai07-autodeploy.sh --rollback` |
| Nginx | `ops/nginx/README.md`의 `.bak-<TS>` 복원 절차 |
| Git | 이력 재작성 대신 `git revert -m 1 <merge-commit>` |

## 7. 장애 점검 체크리스트
| 증상 | 확인 |
|---|---|
| 전체 502 | `df -h /`(디스크 포화), `docker ps`(spring 상태), 배포 직후 20~30초 재생성 구간인지 |
| AI 응답 실패/빈 응답 | `curl 127.0.0.1:18000/health`(터널), `curl 127.0.0.1:8000/health`, Spring 로그의 failover 기록, `AI_SERVER_API_KEY` 일치 |
| SSE가 끊기거나 한 번에 도착 | Nginx `/api/`의 `proxy_buffering off`, `X-Accel-Buffering no` |
| 화상 "카메라 연결 중" 지속 | coturn 실행 여부, relay 포트 범위, 보안 그룹 UDP 허용 |
| 비밀번호 찾기 503 | `SMTP_*` 미설정 |
| 업로드 무한 대기 | S3 자격증명, Spring 비동기 처리 로그 |
