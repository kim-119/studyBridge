# Phase D 사용자 노출 AI 경로 매트릭스(코드에서 생성 — `AiQualityGateCoverage.ROUTES`, `AiRouteExposurePolicy`)

생성 기준: feature/learning-loop-ec2. 단위 = Spring 공개 엔드포인트(ai07 OpenAPI 수와 다름).
**합계 63 — GATED 55 / BLOCKED_WHEN_GATE_ON 4(전부 BLOCKED_BY_AI07 — 로드맵) / EXEMPT 4**. AI 도달인데 사용자에게 AI 본문을 돌려주지 않는 엔드포인트(NOT_USER_EXPOSED) 21개, STOMP 검토 2개.

검증 장치: `AiRouteClassifierTest`(바이트코드 호출 그래프 — AI 생성·AI 저장본 조회에 닿는 모든 HTTP·STOMP 핸들러는 아래 어딘가에 있어야 CI 통과), `AiQualityGateCoverageTest`(모든 GATED 경로에 실행 증거 `@GateEvidence` 테스트 1개 이상, 게이트 ON 시 BLOCKED = 503), `RealAi07EvaluatorE2ETest`(ai07 실제 평가기 코드 격리 실행).

| # | METHOD | 경로 | 상태 | 상류(ai07/저장소) | 게이트 방식·근거 |
|---|---|---|---|---|---|
| 1 | POST | `/api/agent-rooms/{roomId}/chat/stream` | GATED | /api/ai/multi-chat/stream | QualityStreamGate: 메시지 단위 평가, all_complete 재구성, 승인분만 DB/Redis 영속 |
| 2 | GET | `/api/agent-rooms/{roomId}/history` | GATED | (DB/Redis 저장 답변) | 게이트 ON: qualityStatus=APPROVED 아닌 AI 행은 본문을 가린다 |
| 3 | POST | `/api/agent-rooms/{roomId}/chat` | GATED | /api/ai/multi-chat | non-stream: 응답 전체를 QualityStreamGate all_complete 규칙(answers/messages 메시지 단위, 부가 필드 묶음)으로 평가 → 승인분만 응답·DB/Redis(APPROVED), 전부 미승인=AI_QUALITY_REJECTED/UNAVAILABLE |
| 4 | POST | `/api/learning-mate/chat` | GATED | /api/ai/multi-chat | STUDYMATE_*(모드)/agent_message, 평탄화 답변 전체 평가, 재생성 ≤2, 승인분만 응답(저장 없음), 거절/평가불가=success:false |
| 5 | POST | `/api/groups/{groupId}/chats/stream` | GATED | /api/ai/multi-chat/stream | 그룹 AI 봇: QualityStreamGate(GROUP_STUDY_MESSAGE, 참여자 제약)를 누적·DB 영속화 앞에, non-stream 폴백도 게이트 경유, 승인분만 저장(quality_status) |
| 6 | GET | `/api/groups/{groupId}/chats/history` | GATED | (DB) | 게이트 ON: quality_status≠APPROVED 인 AI 행 본문 가림(qualityRedacted), 사용자 메시지 유지. 그룹 AI 답변은 Redis 캐시 미사용 |
| 7 | POST | `/api/groups/{groupId}/materials/{materialId}/quiz` | GATED | /api/ai/quiz/generate | PDF_QUIZ/quiz_json(제목·문항·보기·정답·해설), 근거=원본 파일 결정적 추출(documentId 범위), 재생성 ≤2, 승인분만 저장(quality_status), 거절 422/평가불가 503 |
| 8 | GET | `/api/groups/{groupId}/quizzes` | GATED | (DB) | 게이트 ON: quality_status≠APPROVED 퀴즈는 AI 제목을 가림(qualityRedacted) |
| 9 | POST | `/api/groups/{groupId}/materials/upload-quiz` | GATED | /api/ai/quiz/generate | 그룹 자료 업로드+퀴즈 생성: 위와 같은 게이트, 거절/평가불가면 자료 행 롤백+S3 삭제 후 422/503(성공 위장 없음) |
| 10 | POST | `/api/groups/{id}/screen-ai/analyze` | GATED | /api/ai/vision/analyze | VISION_CAPTION/vision_text(근거 없음 — ai07 판독 근거 미반환), 재생성 ≤2(근거 부재 거절은 재생성 안 함), 승인분만 응답, 거절 422/평가불가 503 SCREEN_AI_QUALITY_* |
| 11 | GET | `/api/materials/{materialId}/summary` | GATED | /api/ai/summary | PDF_SUMMARY, 재생성 ≤2, 승인분만 저장, 미승인 캐시 미노출 |
| 12 | POST | `/api/materials/classify-before-save` | GATED | /api/ai/material/classify | GENERAL_EXPLANATION/text: 노출 문자열 전부(안내 문구·판단 근거 reason=LLM 자유 텍스트·선택지 라벨), 근거=분류기 입력(파일명·MIME·제목·키워드), 재분류 ≤2, 승인분만 응답, 거절=success:false(추천 미포함), ai07 장애=기존 Spring 고정 폴백(AI 문구 없음) |
| 13 | POST | `/api/materials/{materialId}/quiz` | GATED | /api/ai/quiz | PDF_QUIZ/quiz_json(문항·보기·정답·해설·오답해설), 자료 원문 근거, 재생성 ≤2, 승인분만 저장(quality_status), 거절 시 success=false |
| 14 | GET | `/api/materials/{materialId}/quiz` | GATED | (DB) | 게이트 ON: quality_status≠APPROVED 퀴즈는 문항·보기·해설을 가림(qualityRedacted), id·점수 기록 유지 |
| 15 | GET | `/api/materials/{materialId}/shared-quizzes` | GATED | (DB) | 위와 같은 가림 |
| 16 | POST | `/api/materials/{materialId}/quiz/{quizId}/submit` | GATED | (DB) | 채점은 결정적(보기 id 비교). 게이트 ON + 미승인 퀴즈면 AI 해설만 가림, 점수·답안 기록 유지 |
| 17 | POST | `/api/materials/{materialId}/question` | GATED | /api/ai/question | PDF_QA(질문 관련 자료 원문 근거), 재생성 ≤2, 승인 답변만 저장(quality_status), 라우터 LLM 문구→고정 문구, BLOCKED 파이프라인 미실행 |
| 18 | GET | `/api/materials/{materialId}/roadmap` | BLOCKED_WHEN_GATE_ON | /api/ai/roadmap/generate | BLOCKED_BY_AI07(계약 요청 R2·R5-1: 로드맵 세그먼트 평가 프로파일) — 캐시+생성. Spring 분할 게이트 연결 완료(PLANNER_COACHING/plan_json 주차 세그먼트, 진행 상태 제외 체크섬) — ai07 rqg-1.0.0 check_plan 이 세그먼트 객체를 PLAN_EMPTY(HARD)로 항상 거절해 승인 불가 → ai07 계약 변경 후 GATED |
| 19 | POST | `/api/materials/{materialId}/roadmap/regenerate` | BLOCKED_WHEN_GATE_ON | /api/ai/roadmap/generate | BLOCKED_BY_AI07(계약 요청 R2·R5-1: 로드맵 세그먼트 평가 프로파일) — 위와 같음(Spring 연결 완료, ai07 계약 대기) |
| 20 | POST | `/api/materials/{materialId}/keywords/define` | GATED | /api/ai/keyword/define | GENERAL_EXPLANATION/text(정의·중요성·예시·관련 개념·출처·링크 전부), 근거=자료 원문(클라이언트 context 아님), 재생성 ≤2, 승인분만 응답(저장 없음), 거절=success:false+errorCode+retryable |
| 21 | GET | `/api/materials/{materialId}/feedback` | GATED | /api/ai/feedback | GENERAL_EXPLANATION(자료 원문 근거), 재생성 ≤2, 승인분만 저장(quality_status), 미승인 저장본 미노출, 거절 쿨다운 120s |
| 22 | POST | `/api/materials/{materialId}/feedback/regenerate` | GATED | /api/ai/feedback | 위와 같은 게이트 |
| 23 | GET | `/api/materials/{materialId}/study-note` | GATED | /api/ai/major-analysis/note | 업로드 후 백그라운드 생성 시 분할 평가(GENERAL_EXPLANATION/text, 근거=자료 원문 페이지별) 재생성 ≤2 → 승인분만 저장(quality_status). GET: 미승인/레거시 행은 AI 필드 가림(status UNVERIFIED, qualityRedacted) |
| 24 | POST | `/api/materials/{materialId}/plan-analysis` | GATED | /api/ai/planner/analyze | PLANNER 자료: PLANNER_COACHING/text(근거=플래너 입력), 보일 문자열 전체 평가·재생성 ≤2, 승인분만 저장(plan_analysis.quality_status), 거절 422/평가불가 503·기존 분석 보존. PDF 자료는 결정적 PlanTextAnalyzer(AI 없음) |
| 25 | GET | `/api/materials/{materialId}/plan-analysis` | GATED | (DB) | 게이트 ON: 미승인 AI 분석(planner_analysis_json 있음)은 요약·추천·항목 문구 가림(qualityRedacted), 항목 id·완료·진행률 유지 |
| 26 | POST | `/api/materials/{materialId}/recommendations` | GATED | /api/ai/recommendation/* | PLANNER_COACHING/text(근거=자료 원문, allowedMaterialIds=이 자료), 후보 문구 전체 1회 평가(결정적 후보), 승인분만 저장(quality_status). AI 후보 경로 ON 인데 ai07 무응답(라우트 404)이면 503 RECOMMENDATION_AI_UNAVAILABLE(규칙 폴백 성공 위장 없음) |
| 27 | GET | `/api/materials/{materialId}/recommendations` | GATED | (DB) | 게이트 ON: quality_status≠APPROVED 추천은 제목·사유·확인 사항·근거 라벨 가림(qualityRedacted) |
| 28 | POST | `/api/materials/{materialId}/plan-recommendation` | GATED | (DB plan_analysis) | 게이트 ON + 미승인 AI 분석이면 추천 미노출(qualityRedacted, 저장 변경 없음). PDF 분석은 결정적 규칙 문구 |
| 29 | POST | `/api/materials/{materialId}/study-journals` | GATED | /api/ai/study-journal/validate | 판정(ACCEPT/수정요청/차단)은 저장 게이트로 유지, 노출 AI 문구(연결 경로·사유·제안)만 GENERAL_EXPLANATION 평가(근거=메모+자료 원문, 재생성 없음 — 재검증은 판정을 바꿈). 미승인: 경로 미저장, 거절 사유·제안은 분류별 고정 문구(qualityRedacted) |
| 30 | POST | `/api/review-notes/from-quiz/{quizSessionId}` | GATED | /api/ai/review/wrong-note-feedback | 초기 응답=AI 없는 퀴즈 기반본(가림), 백그라운드 보강 WRONG_NOTE_EXPLANATION(원본 자료 근거) 재생성 ≤2 → 승인분만 반영 |
| 31 | GET | `/api/review-notes` | GATED | (DB) | 게이트 ON: quality_status≠APPROVED 면 PDF·복습 필요 분석 가림(문항·메모 유지) |
| 32 | GET | `/api/review-notes/{id}` | GATED | (DB) | 위와 같음 |
| 33 | GET | `/api/review-notes/{id}/retry` | GATED | (DB) | 게이트 ON: 미승인 retryJson 의 해설·개념 제거(문항·정답·내 답·재풀이 기록 유지) |
| 34 | POST | `/api/review-notes/{id}/review-needed` | GATED | /api/ai/review-needed | WRONG_NOTE_EXPLANATION(원본 자료 근거), 재생성 ≤2, 승인분만 저장(review_needed_quality_status), 미승인 저장본 재생성 |
| 35 | POST | `/api/review-notes/{id}/variant-question` | GATED | /api/ai/review/variant-question | SIMILAR_QUESTION(quiz_json, 원본 자료 근거), 재생성 ≤2, 승인 문항만 응답, 거절=success:false |
| 36 | POST | `/api/mindmap/semantic-graph` | GATED | /api/ai/mindmap/semantic-graph | SEMANTIC_GRAPH/graph_json(개념·별칭·설명·관계명·출처, 근거=요청 답변 원문), 재생성 ≤2, 승인분만 응답·캐시(Redis q1 키 + qualityStatus 표식, 레거시 키 미사용), 거절 422/평가불가 503 |
| 37 | POST | `/api/planners/{plannerId}/ai-assist` | GATED | /api/ai/planner/assist | PLANNER_COACHING/text(근거=플래너 입력), 재생성 ≤2, 승인분만 저장(planner_ai_result.quality_status), 거절/평가불가=success:false·기존 보존. ai07 첫 호출 실패는 결정적 기본 피드백(usedFallback=true, used_fallback 저장 — AI 로 표기 안 함) |
| 38 | GET | `/api/planners/{plannerId}/ai-result` | GATED | (DB) | usedFallback 은 used_fallback 표식(폴백을 AI 로 표기하던 결함 수정). 게이트 ON: 승인·폴백 저장본만 노출, 미검증 AI 저장본은 가림(qualityRedacted) |
| 39 | POST | `/api/planners/{plannerId}/plan-analysis` | GATED | /api/ai/planner/analyze-semantic | PLANNER_COACHING/text(서술형 — ai07 일정 JSON 검사 미적용, 근거=플래너·로드맵 day 입력), AI07·결정적 폴백 모두 평가(로드맵 task 는 AI 로드맵 원문), 재생성 ≤2, 승인분만 캐시(planners.plan_analysis_quality_status), 거절 422/평가불가 503 |
| 40 | GET | `/api/planners/{plannerId}/plan-analysis` | GATED | (DB) | 게이트 ON: 승인 캐시(현재 문장 규칙)만 노출, 미검증·문장 재생성 필요 캐시는 empty+qualityRedacted |
| 41 | GET | `/api/planners/{plannerId}/schedule` | GATED | /api/ai/planner/analyze-semantic | ensure(): 게이트 ON 은 승인 캐시만 재사용, 없으면 게이트 경로로 생성 — 미승인이면 422/503(시간표 미생성). 시각 계산은 결정적 |
| 42 | POST | `/api/planners/{plannerId}/schedule/pdf` | GATED | /api/ai/planner/analyze-semantic | 위와 같은 ensure() — 미승인이면 PDF·S3 업로드 없음 |
| 43 | POST | `/api/planners/{plannerId}/adaptive` | GATED | /api/ai/planner/adaptive | PLANNER_COACHING/text(결과 본문+반영 후보 일정, 근거=플래너 항목, 일정 구조는 Spring 결정적 검증), 재생성 ≤2, 승인분만 응답·승인 표식(quality=APPROVED) 든 HMAC 제안 토큰 발급, 거절 422/평가불가 503 |
| 44 | POST | `/api/planners/{plannerId}/recommendations` | GATED | /api/ai/recommendation/* | PLANNER_COACHING/text(근거=플래너·관련 플래너 제목), 후보 문구 1회 평가, 승인분만 저장(quality_status). AI 후보 경로 ON + ai07 무응답이면 503 |
| 45 | GET | `/api/planners/{plannerId}/recommendations` | GATED | (DB) | 게이트 ON: quality_status≠APPROVED 추천은 문구 가림(qualityRedacted) |
| 46 | GET | `/api/study-time/predict` | EXEMPT | /api/ai/predict-study-time | 숫자 예측(로컬 폴백 있음) — response-quality.v1 프로파일 없음 |
| 47 | GET | `/api/materials/{materialId}/quiz/{quizId}/score` | GATED | (DB/Redis) | 채점 결과 results[].explanation = AI 해설 → 게이트 ON + 미승인 퀴즈면 해설만 가림(submit 과 같은 grade) |
| 48 | GET | `/api/groups/{groupId}/quiz/session` | GATED | (DB) | 현재 문항 = 저장된 AI 퀴즈 문항·보기 → 게이트 ON + 미승인 퀴즈면 제목·문항·보기 가림(REST 스냅샷만, STOMP 브로드캐스트 별도) |
| 49 | GET | `/api/review-notes/{id}/download` | GATED | (DB) | 게이트 ON: 오답노트 본문 미승인이면 PDF URL 미발급(가림 표식) |
| 50 | PATCH | `/api/review-notes/{id}/memo` | GATED | (DB) | 응답 ReviewNoteDTO 는 목록·상세와 같은 가림(메모는 사용자 데이터) |
| 51 | POST | `/api/review-notes/{id}/retry/submit` | EXEMPT | (DB) | 응답 = 사용자 재풀이 기록(index/userAnswer/correct/answeredAt)·개수뿐, AI 생성 문자열 없음(정답 대조는 원래 문제의 정답) |
| 52 | PUT | `/api/materials/{materialId}/roadmap/days/toggle` | BLOCKED_WHEN_GATE_ON | (DB) | BLOCKED_BY_AI07(계약 요청 R2·R5-1: 로드맵 세그먼트 평가 프로파일) — 응답 = AI 로드맵 전체. 게이트 ON 가림(미승인·체크섬 불일치, 진행 상태 유지) 연결 완료 — 승인 로드맵이 생길 수 없는 동안 GET 과 함께 BLOCKED |
| 53 | PUT | `/api/materials/{materialId}/roadmap/tasks/{taskId}/toggle` | BLOCKED_WHEN_GATE_ON | (DB) | BLOCKED_BY_AI07(계약 요청 R2·R5-1: 로드맵 세그먼트 평가 프로파일) — 응답 = AI 로드맵 과제(레거시 steps/tasks). 게이트 ON 이면 과제 문구 가림 연결 완료 — 위와 같은 이유로 BLOCKED |
| 54 | PATCH | `/api/plan-analysis/items/{itemId}` | GATED | (DB) | 완료/숨김 변경은 사용자 기록. 응답 분석은 GET 과 같은 가림(미승인 AI 분석 문구 → qualityRedacted) |
| 55 | GET | `/api/planners/{plannerId}/next-learning` | EXEMPT | (DB) | PlannerNextLearningService 확인: 응답 = 기존 플래너 id·제목·과목·날짜(planners 행)·week/day·고정 사유 문구·체크 완료 개수뿐. plan_analysis_item 은 완료 개수 집계에만 쓰고 항목 문구는 응답에 없음, AI 호출 없음 |
| 56 | GET | `/api/planners/{plannerId}/diagnosis` | EXEMPT | (DB) | PlanDiagnosisService 확인: A/W/D·마감 창·과부하·선수관계·일정 중복 = 결정적 계산, 문자열 = 플래너 제목·할 일(todos) 문구·고정 안내문. plan_analysis_item 은 완료 여부 집계에만 사용, AI 호출·AI 문구 없음 |
| 57 | POST | `/api/planners/{plannerId}/adaptive/apply` | GATED | (서명 제안 토큰) | 게이트 ON: 토큰 HMAC 안 승인 표식(quality=APPROVED) 없으면 409 ADAPTIVE_PROPOSAL_NOT_VERIFIED(쓰기 0). 응답·todo 제목은 결정적('[AI 학습 N분] 플래너 제목'), 날짜·분은 승인된 제안 |
| 58 | POST | `/api/recommendations/{id}/accept` | GATED | (DB) | 게이트 ON: 미승인 추천 승인 거부 409 RECOMMENDATION_NOT_VERIFIED(제목·사유가 새 플래너로 복사되므로), 응답 항목은 목록과 같은 가림 |
| 59 | POST | `/api/recommendations/{id}/reject` | GATED | (DB) | 상태 전이만. 응답 항목은 미승인이면 문구 가림 |
| 60 | POST | `/api/recommendations/{id}/complete` | GATED | (DB) | 상태 전이만. 응답 항목은 미승인이면 문구 가림 |
| 61 | GET | `/api/materials/{materialId}/study-journals` | GATED | (DB) | 게이트 ON: quality_status≠APPROVED 면 AI 연결 경로(relationPath) 가림(qualityRedacted), 판정 라벨은 허용 enum 값만. 메모 본문은 사용자 데이터 |
| 62 | GET | `/api/materials/{materialId}/study-journals/{journalId}` | GATED | (DB/S3) | 위와 같음(S3 메모 본문 유지) |
| 63 | GET | `/api/materials/{materialId}` | GATED | (DB/S3) | context=review-note 로 오답노트 자료 상세를 열 때 AI 해설 PDF URL·본문 사본 노출 → 게이트 ON + 원 노트 미승인이면 가림(qualityRedacted). 일반 자료는 AI 필드 없음(ai07 리뷰가 찾은 우회 경로) |

## NOT_USER_EXPOSED / STOMP_REVIEWED(사유)

| 엔드포인트 | 사유 |
|---|---|
| `DELETE /api/agent-rooms/{roomId}` | 방 삭제 — 이력 키 계산용 조회, AI 본문 응답 없음 |
| `DELETE /api/groups/{groupId}/quizzes/{quizId}` | 삭제 — 소유권 확인용 조회 |
| `DELETE /api/materials/{materialId}/quiz/{quizId}` | 삭제 — 소유권 확인용 조회 |
| `DELETE /api/materials/{materialId}/study-journals/{journalId}` | 삭제 — 소유권 확인용 조회 |
| `DELETE /api/review-notes/{id}` | 삭제 — 소유권 확인용 조회 |
| `GET /api/groups/{groupId}/shared-materials` | 자료 제목·공유 시각·퀴즈 개수만(AI 본문 없음) |
| `GET /api/materials/{materialId}/progress` | 완료 개수·퍼센트만 |
| `GET /api/materials/{materialId}/quiz/{quizId}/ranking` | 점수·닉네임 랭킹만 |
| `GET /api/recommendations/metrics` | 상태별 집계 수치만 |
| `GET /api/test/performance/db/{roomId}` | 건수·지연만(기본 비활성 — studybridge.perf-test.enabled) |
| `GET /api/test/performance/redis/{groupId}` | 건수·지연만(기본 비활성 — studybridge.perf-test.enabled) |
| `POST /api/learning-loop/events` | 오답노트 소유권 검증용 조회, 응답 = 이벤트 id |
| `POST /api/learning-loop/review-recommendation` | 결정적 복습 간격·날짜 계산(오답노트는 소유권 확인) |
| `POST /api/learning-loop/review-schedule` | 할 일 등록 결과(id·날짜). 제목은 요청 값 또는 오답노트 개념명 — 개념명은 오답노트 게이트에서 다룸 |
| `POST /api/materials/upload` | 업로드 응답에 AI 텍스트 없음. 백그라운드 학습노트는 GET /api/materials/{materialId}/study-note(생성 시점 게이트 + 미승인 가림, GATED)로만 노출 |
| `PUT /api/materials/{materialId}` | MaterialDTO 에 AI 필드 없음(피드백 조회는 갱신 처리용). 오답노트 자료는 공용 convertToDTO 가 가림 |
| `GET /api/materials` | 목록은 REVIEW_NOTE 제외 + 공용 convertToDTO 가 오답노트 자료를 가림(ReviewNoteMaterialRedactionTest) |
| `GET /api/materials/items` | 보관함 항목은 REVIEW_NOTE 제외 + 공용 convertToDTO 가림 |
| `PATCH /api/materials/{materialId}/move` | 폴더 이동 결과 — 공용 convertToDTO 가림 |
| `POST /api/materials/log` | 학습일지 생성(사용자 작성) — REVIEW_NOTE 생성 금지 + 공용 convertToDTO 가림 |
| `POST /api/materials/mindmap` | 마인드맵 자료 생성(사용자 구조) — 공용 convertToDTO 가림 |
| `STOMP /group/{groupId}/quiz/start` | 게이트 ON + 미승인 퀴즈 시작 거부(QUIZ_NOT_VERIFIED), 모든 퀴즈 방송 payload redactUnverified(GroupStudyQuizQualityGateTest#liveQuiz*) |
| `STOMP /group/{groupId}/quiz/submit` | 답안 제출 ack·점수만(문항·정답 본문 없음). 이어지는 방송은 redactUnverified 를 거친다 |
