# Android APK 자체 배포 인프라 (서버 측)

```text
GitHub android-main push
  → .github/workflows/android-release.yml (android 브랜치) : 빌드·서명·apksigner verify·Artifact 업로드 (기존)
  → publish-to-server 잡 : aapt2 로 packageName/versionCode/versionName 추출 + sha256 → release-manifest.json
  → scp  APK + manifest → EC2 /home/ubuntu/studybridge-android-releases/incoming/<run_id>/
  → ssh  python3 /home/ubuntu/studyBridge/ops/android/publish-android-release.py --incoming … --verify-public
       (EC2 .env 의 기존 AWS 키로 S3 비공개 버킷에 업로드 — GitHub 에 AWS 키 없음)
S3 (cloud.aws.s3.bucket, 비공개)
  android/releases/StudyBridge-<v>.apk   immutable 1y      android/releases/StudyBridge-<v>.json
  android/latest/StudyBridge-latest.apk  no-cache          android/latest/version.json  no-store (마지막 갱신)
EC2 Spring (LLM-clean, CD 배포)
  GET /api/app/version                                   → S3 version.json 중계(30s 메모리 캐시) / 404 NO_RELEASE
  GET /api/app/downloads/android/StudyBridge-latest.apk  → 302 presigned(15분, attachment, APK MIME)
  GET /api/app/downloads/android/StudyBridge-<v>.apk     → 302 presigned
nginx (snippets/studybridge-android-downloads.conf)
  /api/app/ , /downloads/android/ → Spring, Cache-Control no-store 단일 헤더 / /app 은 SPA 라우트
React (LLM-clean)
  /app  → pages/AppDownload.jsx (공개, 네비 없음, /api/app/version 표시 + downloadUrl 버튼)
```

## 공개 URL
- https://studybridge.co.kr/app
- https://studybridge.co.kr/api/app/version
- https://studybridge.co.kr/downloads/android/StudyBridge-latest.apk

## 수동 릴리즈(워크플로우 없이)
```bash
mkdir -p /home/ubuntu/studybridge-android-releases/incoming/manual-$(date +%Y%m%d%H%M)
# app-release.apk 와 release-manifest.json(아래 스키마) 을 그 디렉터리에 넣고
python3 /home/ubuntu/studyBridge/ops/android/publish-android-release.py \
  --incoming /home/ubuntu/studybridge-android-releases/incoming/manual-… --dry-run   # 검증만
python3 /home/ubuntu/studyBridge/ops/android/publish-android-release.py \
  --incoming /home/ubuntu/studybridge-android-releases/incoming/manual-… --verify-public
```

release-manifest.json (CI 가 생성; 수동 시 동일 스키마):
```json
{
  "packageName": "kr.co.studybridge.app",
  "versionCode": 2,
  "versionName": "1.0.1",
  "apkFileName": "app-release.apk",
  "sha256": "<apk sha256 hex>",
  "fileSize": 19196753,
  "releaseDate": "2026-10-06T21:00:00+09:00",
  "releaseNotes": ["모바일 안정성 개선", "회원가입 오류 수정"],
  "forceUpdate": false,
  "minimumSupportedVersionCode": 1,
  "signerCertSha256": "<apksigner --print-certs 의 Signer #1 SHA-256>",
  "gitSha": "<commit>",
  "runId": "<actions run id>"
}
```

## 규칙(스크립트가 강제)
- packageName 은 `kr.co.studybridge.app`, versionName 은 `숫자.숫자[.숫자]`, versionCode 는 현재 latest 보다 커야 한다.
- 같은 versionName 의 버전 고정 APK 는 불변(다른 내용으로 덮어쓰기 거부). 동일 sha256 재실행은 `--allow-same-version`.
- APK 는 sha256/fileSize 일치, zip 무결성, `AndroidManifest.xml`/`classes.dex` 존재, APK Signature Scheme v2+ 블록 존재,
  매니페스트 바이너리에 패키지명 존재를 EC2 에서 재검증한다(CI 의 apksigner verify 와 이중화).
- version.json 은 모든 업로드·HEAD 검증 뒤 가장 마지막에 쓴다. 실패 시 이전 latest 가 그대로 유지된다.
- `.env` 에 `ANDROID_RELEASE_SIGNER_SHA256=<릴리즈 인증서 SHA-256>` 을 두면 릴리즈 키스토어 외 서명은 거부된다(권장).

## 캐시 정책
| 대상 | 정책 |
|---|---|
| `/api/app/version`, `/downloads/android/*` 응답(메타데이터·302) | `Cache-Control: no-store, no-cache, max-age=0` (nginx 단일 헤더 + Spring 동일) |
| `android/latest/StudyBridge-latest.apk` (S3 객체) | `no-cache, max-age=0, must-revalidate` |
| `android/releases/StudyBridge-<v>.apk` (S3 객체) | `public, max-age=31536000, immutable` |
| presigned URL | 15분 서명 TTL — 공유용 링크는 항상 `/downloads/android/...` 안정 URL 을 쓴다 |

## 롤백
이전 버전을 다시 latest 로 돌리려면 해당 버전의 `releases/StudyBridge-<v>.apk` + `.json` 로 `latest/` 두 객체를
서버측 복사(`aws s3 cp` 또는 boto3 copy_object)하면 된다. versionCode 가 더 큰 값이 다시 배포될 때까지 스크립트는
감소 배포를 거부하므로, 의도한 롤백은 수동으로 수행한다.
