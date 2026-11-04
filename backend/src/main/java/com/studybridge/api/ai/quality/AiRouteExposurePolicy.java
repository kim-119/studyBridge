package com.studybridge.api.ai.quality;

import java.util.Map;
import java.util.Set;

/**
 * AI 경로 분류 정책(Phase D2). AiRouteClassifierTest 가 컴파일된 바이트코드 호출 그래프로 모든 엔드포인트를 분류할 때 쓰는 입력.
 *
 *  · AI_ARTIFACT_STORES: AI 생성 결과를 저장·캐시하는 저장소. 엔드포인트가 이들의 조회 메서드에 닿으면 "AI 저장본 재노출" 후보.
 *  · NON_AI_HTTP_CLASSES: WebClient/RestTemplate 을 쓰지만 AI 생성이 아닌 클래스(영상 서버·평가기·학습 데이터 전송).
 *  · NOT_USER_EXPOSED: AI 코드에 닿지만 사용자에게 AI 생성 본문을 돌려주지 않는 엔드포인트 — 반드시 사유를 적는다.
 * 여기 없는 AI 도달 엔드포인트는 AiQualityGateCoverage.ROUTES 에 있어야 한다(없으면 CI 실패).
 */
public final class AiRouteExposurePolicy {

    private AiRouteExposurePolicy() {
    }

    public static final Set<String> AI_ARTIFACT_STORES = Set.of(
            "com.studybridge.api.repository.ChatMessageRepository",
            "com.studybridge.api.repository.GroupChatMessageRepository",
            "com.studybridge.api.repository.GroupStudyQuizQuestionRepository",
            "com.studybridge.api.repository.GroupStudyQuizRepository",
            "com.studybridge.api.repository.LearningRecommendationRepository",
            "com.studybridge.api.repository.MaterialFeedbackRepository",
            "com.studybridge.api.repository.MaterialQuestionRepository",
            "com.studybridge.api.repository.MaterialQuizRepository",
            "com.studybridge.api.repository.MaterialStudyNoteAnalysisRepository",
            "com.studybridge.api.repository.MaterialSummaryRepository",
            "com.studybridge.api.repository.PlanAnalysisItemRepository",
            "com.studybridge.api.repository.PlanAnalysisRepository",
            "com.studybridge.api.repository.PlannerAiResultRepository",
            "com.studybridge.api.repository.ReviewNoteRepository",
            "com.studybridge.api.repository.RoadmapRepository",
            "com.studybridge.api.repository.RoadmapTaskRepository",
            "com.studybridge.api.repository.StudyJournalRepository",
            "com.studybridge.api.service.RedisChatService");

    public static final Set<String> NON_AI_HTTP_CLASSES = Set.of(
            "com.studybridge.api.service.OpenViduService",
            "com.studybridge.api.ai.quality.QualityEvaluatorClient",
            "com.studybridge.api.ai.training.TrainingOutboxDispatcher",
            "com.studybridge.api.config.WebClientConfig");

    public static final Map<String, String> NOT_USER_EXPOSED = Map.ofEntries(
            Map.entry("DELETE /api/agent-rooms/{roomId}", "방 삭제 — 이력 키 계산용 조회, AI 본문 응답 없음"),
            Map.entry("DELETE /api/groups/{groupId}/quizzes/{quizId}", "삭제 — 소유권 확인용 조회"),
            Map.entry("DELETE /api/materials/{materialId}/quiz/{quizId}", "삭제 — 소유권 확인용 조회"),
            Map.entry("DELETE /api/materials/{materialId}/study-journals/{journalId}", "삭제 — 소유권 확인용 조회"),
            Map.entry("DELETE /api/review-notes/{id}", "삭제 — 소유권 확인용 조회"),
            Map.entry("GET /api/groups/{groupId}/shared-materials", "자료 제목·공유 시각·퀴즈 개수만(AI 본문 없음)"),
            Map.entry("GET /api/materials/{materialId}/progress", "완료 개수·퍼센트만"),
            Map.entry("GET /api/materials/{materialId}/quiz/{quizId}/ranking", "점수·닉네임 랭킹만"),
            Map.entry("GET /api/recommendations/metrics", "상태별 집계 수치만"),
            Map.entry("GET /api/test/performance/db/{roomId}", "건수·지연만(기본 비활성 — studybridge.perf-test.enabled)"),
            Map.entry("GET /api/test/performance/redis/{groupId}", "건수·지연만(기본 비활성 — studybridge.perf-test.enabled)"),
            Map.entry("POST /api/learning-loop/events", "오답노트 소유권 검증용 조회, 응답 = 이벤트 id"),
            Map.entry("POST /api/learning-loop/review-recommendation", "결정적 복습 간격·날짜 계산(오답노트는 소유권 확인)"),
            Map.entry("POST /api/learning-loop/review-schedule", "할 일 등록 결과(id·날짜). 제목은 요청 값 또는 오답노트 개념명 — 개념명은 오답노트 게이트에서 다룸"),
            Map.entry("POST /api/materials/upload", "업로드 응답에 AI 텍스트 없음. 백그라운드 학습노트는 GET /api/materials/{materialId}/study-note(BLOCKED)로만 노출"),
            Map.entry("PUT /api/materials/{materialId}", "MaterialDTO 에 AI 필드 없음(피드백 조회는 갱신 처리용). 오답노트 자료는 공용 convertToDTO 가 가림"),
            Map.entry("GET /api/materials", "목록은 REVIEW_NOTE 제외 + 공용 convertToDTO 가 오답노트 자료를 가림(ReviewNoteMaterialRedactionTest)"),
            Map.entry("GET /api/materials/items", "보관함 항목은 REVIEW_NOTE 제외 + 공용 convertToDTO 가림"),
            Map.entry("PATCH /api/materials/{materialId}/move", "폴더 이동 결과 — 공용 convertToDTO 가림"),
            Map.entry("POST /api/materials/log", "학습일지 생성(사용자 작성) — REVIEW_NOTE 생성 금지 + 공용 convertToDTO 가림"),
            Map.entry("POST /api/materials/mindmap", "마인드맵 자료 생성(사용자 구조) — 공용 convertToDTO 가림"));

    /**
     * AI 저장본에 닿는 STOMP(WebSocket) 핸들러와 게이트 적용 방식. HTTP 인터셉터(AiQualityGateCoverage)가 STOMP 프레임을 보지 못하므로
     * 서비스 안에서 막는다 — 여기 없는 AI 도달 STOMP 핸들러는 AiRouteClassifierTest 가 실패시킨다.
     */
    public static final Map<String, String> STOMP_REVIEWED = Map.ofEntries(
            Map.entry("STOMP /group/{groupId}/quiz/start", "게이트 ON + 미승인 퀴즈 시작 거부(QUIZ_NOT_VERIFIED), 모든 퀴즈 방송 payload redactUnverified"
                    + "(GroupStudyQuizQualityGateTest#liveQuiz*)"),
            Map.entry("STOMP /group/{groupId}/quiz/submit", "답안 제출 ack·점수만(문항·정답 본문 없음). 이어지는 방송은 redactUnverified 를 거친다"));
}
