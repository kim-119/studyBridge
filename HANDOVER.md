# StudyBridge 작업 인수인계 (LLM-clean)

작성 시점 기준 EC2 `/home/ubuntu/studyBridge`, branch `LLM-clean`.

---

## 0. ⚠️ 가장 먼저 알아야 할 것 — CD가 미커밋/미푸시 작업을 지움

- 외부 CD 파이프라인이 주기적으로(수 분 간격) `git reset --hard origin/LLM-clean` + (untracked 제거)`git clean` 류 동작을 수행한다.
- 그 결과:
  - **로컬 커밋만 한 작업도 사라짐**(reset --hard로 origin 기준 복원). 실제로 로컬 커밋 `af3670cb`가 한 번 reset으로 사라진 것을 reflog로 확인함.
  - **untracked 신규 파일도 사라짐**(git clean). 작성 직후의 신규 파일이 지워지는 현상 확인.
- **유일한 영구 보존 방법 = `git push origin LLM-clean`** (사용자가 이번에 push 허용함).
- 배포 산출물(구동 중 spring 컨테이너, `/var/www/studybridge/current` 정적 릴리스)은 git과 무관하게 살아남아 **라이브는 계속 동작**한다. 단, 소스가 reset되면 재빌드 시 기능이 유실되므로 반드시 push 상태를 유지할 것.
- 따라서 작업 원칙: **조금씩 commit + push**. push 안 하면 다음 CD tick에 소실.

배포 방법(아티팩트, git 무관):
- 백엔드: `docker compose up -d --build spring`
- 프론트: `cd frontend && npm run build` 후 `sudo cp -r dist/. /var/www/studybridge/current/ && sudo chown -R www-data:www-data /var/www/studybridge/current`
- 프론트 라이브 = nginx 정적(`/etc/nginx/sites-enabled/studybridge`, root `/var/www/studybridge/current`, index.html no-cache, /assets immutable). `:3000` vite 컨테이너 없음.
- compose 서비스: db / fastapi-tunnel-proxy / openvidu / redis / spring (react/frontend 서비스 없음).
- ai07 FastAPI = 원격 SSH 터널 박스, EC2에서 `http://127.0.0.1:18001`로 접근(컨테이너 내부는 `http://host.docker.internal:18001`). **ai07/FastAPI 코드는 수정 금지.**

---

## 1. 완료 + push 된 작업 (commit `af3670cb`, origin/LLM-clean 반영됨)

라이브 배포 완료 + 소스 push 완료. 안전.

### (A) 자료보관함 폴더(문서) 뷰 + 유형 필터 탭
- 별도 `Folder` 엔티티(`folders` 테이블, parentId nullable) + `materials.folder_id`(nullable) 컬럼. ddl-auto 자동 생성. 기존 material id 체계/요약/퀴즈/로드맵/오답노트 무손상.
- **폴더 id와 material id는 별도 시퀀스** → 프론트 key는 `folder-${id}`/`material-${id}`, 폴더 클릭은 절대 자료 상세/AI로 가지 않음.
- 백엔드 신규: `entity/Folder`, `repository/FolderRepository`, `service/FolderService`, `controller/FolderController`, `dto/FolderDTO`, `dto/ArchiveListDTO`.
- API: `GET /api/materials/items?parentId=`(folders+materials+breadcrumb), `PATCH /api/materials/{id}/move`{folderId}, `GET/POST /api/folders`, `PATCH /api/folders/{id}`(rename), `PATCH /api/folders/{id}/move`(순환차단), `DELETE /api/folders/{id}`(A안: 비어야 삭제, 아니면 409 "폴더 안에 자료가 있어 삭제할 수 없습니다.").
- 업로드/학습일지 생성에 `folderId` 연동(현재 폴더에 저장). `MaterialService.getArchiveItems/moveMaterial/resolveOwnedFolderId`.
- 프론트 `pages/Archive.jsx` 전면 재작성: 폴더 그리드 + 상단 유형 탭(전체/학습PDF/학습일지/플래너, `materialTabKind`로 자료 필터, **폴더는 모든 탭 표시**, 탭 변경 시 currentFolderId/breadcrumb 유지) + `?folderId=` URL 유지 + breadcrumb/뒤로가기 + 신규카드 메뉴(폴더만들기/자료업로드) + ⋮ 메뉴(이름변경/이동/삭제) + 선택모드 일괄삭제 + 정렬(최신순/이름순, 폴더먼저).
- **신규/⋮ 메뉴 클릭 무반응 버그 수정**: `.doc-card:hover { transform }`가 hover 시 스태킹 컨텍스트를 만들어 풀스크린 닫기 오버레이가 메뉴를 덮던 문제 → transform 제거(box-shadow만, 떨림도 해결) + 메뉴 열린 카드 `z-index:40` + 오버레이 대신 **document mousedown 바깥클릭 리스너**로 닫기. `index.css` `.doc-*` 클래스.
- `services/api.js`에 `folderService` + `materialService.getArchiveItems/moveMaterial/getStudyNote/uploadMaterial(folderId)`.

### (B) AI 핵심 요약 노트 = 전공 분야 + 핵심 객체 중심(자동 분석)
- 별도 버튼 없음. PDF 업로드 → 추출 성공 후 백그라운드 자동 분석 → 자료 상세 "AI 핵심 요약 노트" 탭에 표시.
- ai07 `POST /api/ai/major-analysis/note` 호출(200, camelCase 응답 그대로 매핑). **업로드 성공과 분석 성공 분리**(분석 실패해도 PDF 유지).
- 백엔드: `entity/MaterialStudyNoteAnalysis`(table `material_study_note_analysis`, status PENDING/RUNNING/SUCCESS/FAILED, fallback/fallbackReason, *Json TEXT, pageSummariesJson), `repository/MaterialStudyNoteAnalysisRepository`, `dto/StudyNoteAnalysisDTO`, `service/StudyNoteAnalysisService`.
- `MaterialService.uploadAndSaveMaterial`가 PENDING 행 생성, `PdfExtractionService`가 추출 성공 후 `analyzeAsync` 트리거. `MaterialController` `GET /api/materials/{id}/study-note`(소유권 검증, PDF만, 그 외 null).
- **페이지별 전달**: 추출 텍스트를 form-feed(\f)로 페이지 분리해 `pageTexts[{page,text}]`로 ai07에 전달. ocrTexts/captions/tables/imageDescriptions는 **빈 배열(OCR 파이프라인 미구현)** → 이미지 전용 PDF는 ai07에서 `detectedTextSource=INSUFFICIENT`로 정상 처리.
- **pageSummaries** 저장/반환(page 오름차순). 프론트 세부 핵심 내용 = pageSummaries 페이지 카드(p.N 제목/배지/개요/keyConcepts/summaryBullets/studyFocus) 우선 → 없으면 detailedCoreContents fallback. detectedTextSource 한글 배지(TEXT/OCR/CAPTION/TABLE/IMAGE_DESCRIPTION/MIXED/INSUFFICIENT). INSUFFICIENT 경고 문구.
- fallback 판정: `domain=="GENERAL" && keywords 빈 배열` → SUCCESS + fallback=true + "PDF에서 명확한 전공 핵심 객체를 충분히 식별하지 못해 기본 학습 가이드로 생성되었습니다." 배너.
- 프론트 `pages/ArchiveDetail.jsx`: `StudyNoteView` 컴포넌트(11섹션) + `studyNote` 상태 + 5초 polling(PENDING/RUNNING) + 요약 탭 통합. `services/api.js` `getStudyNote`.
- 인트로 문구: "PDF의 전공 분야와 핵심 객체를 분석하여 생성한 학습용 핵심 요약 노트입니다."
- E2E 검증됨(미생물 PDF → 생명과학/미생물·대장균 중심 11섹션, wikiSummaries.used 반영).

### (C) 오답노트 복습 필요(AI) + 자료보관함 저장 버튼 제거
- `ReviewNotesPage.jsx`: `AI 해설` 옆 `복습 필요` 버튼(Lightbulb). `POST /api/review-notes/{id}/review-needed` → 결과 카드(로딩/에러/캐싱·재클릭 토글, 중복호출 방지). "자료보관함에 저장(됨)" 버튼 2종 제거.
- 백엔드: `ReviewNoteController.reviewNeeded` + `ReviewNoteService.generateReviewNeeded`: 기존 `/api/ai/multi-chat`(mode=basic) 재사용(새 ai07 라우트 추가 안 함) → 실패 시 데이터 기반 결정적 폴백. 항상 `"{개념}에 대한 개념이 부족하여 복습이 필요합니다. ..."` 형식 + 600자 trim. 소유권 loadOwnedStrict(없으면 404, 타인 403).
- 자료보관함 목록은 이미 REVIEW_NOTE 제외(비노출). 물리 삭제는 안 함.

---

## 2. 진행 중(미완) — 소크라테스 복습 세션

> 사용자 요청으로 **작업 중지**. 백엔드는 작성+컴파일 통과, **프론트는 시작 안 함**, **ai07 신규 route는 404(서비스 재시작 필요)**.

### 목표
자료 상세의 중복 `진행률` 기능을 `소크라테스 복습 세션`으로 대체 + 세션 완료 후 `다음 복습일 주간 일정에 등록하기`를 플래너 DB에 연결. React→Spring→ai07.

### ⚠️ ai07 상태
- `POST http://127.0.0.1:18001/api/ai/socratic-review/sessions` → **404** (openapi에 socratic 경로 없음).
- **`ai07 신규 route 404: studybridge-ai.service 재시작 필요. 사용자 승인 전이라 EC2에서 ai07 재시작하지 않음.`**
- 재시작 명령(사용자 승인 후): `sudo systemctl restart studybridge-ai.service` (AI 서버 잠시 중단).
- 재시작 전에는 실제 세션 E2E 검증 불가. Spring/React 구현 + 404 안내처리까지만 가능.

### 완료된 백엔드(커밋/푸시 대상) — 컴파일 통과
- `entity/SocraticReviewSession.java` (table `socratic_review_sessions`, sessionId/materialId/userId/status/finish결과 캐시. ddl-auto 자동생성)
- `repository/SocraticReviewSessionRepository.java`
- `service/SocraticReviewService.java`
- `controller/SocraticReviewController.java`

엔드포인트(모두 `/api/materials/{materialId}/socratic-review` 하위, 소유권+PDF타입 검증, 폴더 제외):
- `POST /sessions` (body `{maxTurnsPerChunk, maxChunks}`) → ai07 `/api/ai/socratic-review/sessions` 호출, sessionId 매핑 저장. 404 시 `{aiAvailable:false, message:"...AI 서버 재시작 후 다시 시도..."}` 반환(전체 오류로 안 터뜨림).
- `POST /sessions/{sessionId}/answers` (body `{answer}`) → 빈 답변 400, ai07 answers 호출.
- `POST /sessions/{sessionId}/finish` → ai07 finish 호출, recommendReviewInDays/recommendedReviewDate/summaryForPlanner/weakConcepts 캐시 저장, status=COMPLETED.
- `POST /sessions/{sessionId}/schedule-review` (body `{reviewDate}`) → COMPLETED 검증 후 **기존 `Planner`로 복습 일정 등록**(plannerDate=reviewDate, title "복습: {제목}", sourceType="SOCRATIC_REVIEW", sourceMaterialId). 중복 등록 방지(user+sourceMaterialId+SOCRATIC_REVIEW+plannerDate). 날짜 우선순위: reviewDate > recommendedReviewDate > 오늘+recommendReviewInDays > 오늘+2.
- 응답 **화이트리스트 sanitize**: question/message/visibleMessageType/progress/overallMastery/recommend*/weakConcepts/summaryForPlanner만 통과. rubric/eval_json/grounding/reasoning/`<think>` 등 내부 평가는 차단.

### 남은 작업(다음 담당자)
1. **프론트 `ArchiveDetail.jsx`** (미착수):
   - 상단 액션 유지: `AI 계획 분석`/`다음 학습 추천`/`메모`/**`소크라테스 복습`**(기존 `진행률` 대체)/`삭제`.
   - 하단 보조 버튼 제거: `학습계획`/`일정 체크리스트`/`일정/로드맵`/`원문/PDF` + 중복 `진행률` 패널. (왼쪽 PDF 뷰어·요약카드 진행률 바는 유지)
   - 우측 패널 세션 UI: 안내→질문→답변(textarea, 빈답 차단, 중복클릭 차단)→꼬리질문→완료요약(overallMastery/weakConcepts/recommendedReviewDate)→`다음 복습일 주간 일정에 등록하기` 버튼.
   - `services/api.js`에 socraticReviewService 추가(위 4개 Spring 엔드포인트만 호출, **ai07 직접 호출 금지**).
   - `aiAvailable===false`면 "AI 서버 재시작 필요" 안내만 패널에 표시(상세 전체 깨지지 않게).
   - 내부 eval/rubric/grounding 노출 금지(백엔드에서 이미 sanitize).
   - 안내 문구 교체: 기존 "...학습 항목 14개를 추출했습니다 (소스 1개·청크 3개·문장 13개)..." → "오늘 학습할 내용을 자료 흐름에 맞춰 정리했습니다. 위에서부터 하나씩 확인하면서 완료한 항목을 체크하면, 이 자료의 핵심 목표를 빠짐없이 점검할 수 있습니다." (소스/청크/문장 통계 화면 노출 금지)
2. 빌드: `frontend npm run build`, `backend ./gradlew clean build -x test`.
3. 배포: spring 재빌드 + dist 복사(위 0번 참조).
4. **ai07 재시작 승인 후** 세션 시작/답변/완료/일정등록 브라우저 E2E.
5. 회귀 확인: PDF 뷰어/체크리스트/메모/다음 학습 추천/AI 계획 분석/삭제/요약·퀴즈·로드맵.
6. **commit + push**(필수, 안 하면 CD가 지움).

### 주의/정책
- React에서 `/api/ai/...`, `18001`, ai07 URL/API key 직접 사용 금지(프론트는 Spring `.../socratic-review/...`만).
- folderId를 materialId로 보내지 말 것. 폴더는 세션 대상 아님(PDF만).
- 세션 완료가 자료/체크리스트 전체를 자동 완료 처리하지 않음. 복습일 등록은 버튼 클릭 시에만.
- 주간 일정 등록은 **실제 Planner DB insert**(UI 표시만 아님). 기존 플래너/주간일정 화면에서 plannerDate 기준으로 보임.

---

## 3. 참고 좌표
- 인증: `@AuthenticationPrincipal CustomUserDetails` → `userDetails.getId()`.
- 예외 매핑(GlobalExceptionHandler): IllegalArgument→400, IllegalState→409, NoSuchElement→404, Security→403.
- DB: RDS(`database=postgres`), ddl-auto=update(신규 테이블/nullable 컬럼 자동 반영). Flyway 미사용.
- ai07 호출: Spring `fastApiWebClient`(WebClient) 사용. 범용 LLM은 `/api/ai/multi-chat`(mode=basic) 존재. `/api/ai/major-analysis/note`는 라이브 200. `/api/ai/socratic-review/*`는 현재 404.
- 테스트용 임시 계정: foldertest_*@example.com / testpass123 (이전 검증 때 생성, 무해).
