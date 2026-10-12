package com.studybridge.api.service.recommendation;

import com.studybridge.api.service.recommendation.RecommendationCandidate.Evidence;
import com.studybridge.api.service.recommendation.UserPlannerTaskRecommender.NoteRef;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static com.studybridge.api.service.recommendation.RecommendationCandidate.*;
import static org.junit.jupiter.api.Assertions.*;

/** 세 추천기(사용자 플래너 Task / 로드맵 Node / 문서 기반) + AI 후보 검증. */
class RecommendersTest {

    private static final String PLAN = "김도현 저자의 선형대수 2장 학습하기";
    private static final TextbookToc TOC = TextbookToc.extract("목차\n1장 벡터와 공간 .... 1\n2장 행렬과 연립방정식 .... 35\n3장 행렬식 .... 70");

    private static UserPlannerTaskRecommender.Context ctx(int total, int done, TextbookToc toc, Integer score,
                                                          List<NoteRef> notes, List<String> upcoming) {
        return new UserPlannerTaskRecommender.Context(10L, PLAN, "선형대수", null, LocalDate.of(2026, 10, 13), total, done, null,
                toc == null ? null : new UserPlannerTaskRecommender.Textbook(345L, "선형대수 교재", toc),
                score == null ? null : 86L, score, notes, upcoming);
    }

    private static List<String> types(List<RecommendationCandidate> cs) {
        return cs.stream().map(RecommendationCandidate::type).toList();
    }

    @Nested
    class UserPlanner {
        @Test
        void planSentenceIsNotCompletion_noNextChapterUntilChecklistDone() {
            var out = UserPlannerTaskRecommender.recommend(ctx(0, 0, TOC, null, List.of(), List.of()));
            assertEquals(List.of(CONCEPT_REVIEW, PRACTICE), types(out.candidates()));
            assertTrue(out.candidates().get(0).title().startsWith("김도현 저자의 선형대수 2장"));
            assertFalse(types(out.candidates()).contains(NEXT_CHAPTER));

            var partial = UserPlannerTaskRecommender.recommend(ctx(4, 3, TOC, null, List.of(), List.of()));
            assertFalse(types(partial.candidates()).contains(NEXT_CHAPTER));
        }

        @Test
        void completed_withVerifiedToc_nextChapterUsesRealTitle() {
            var out = UserPlannerTaskRecommender.recommend(ctx(3, 3, TOC, null, List.of(), List.of()));
            RecommendationCandidate next = out.candidates().stream().filter(c -> c.type().equals(NEXT_CHAPTER)).findFirst().orElseThrow();
            assertEquals("김도현 저자의 선형대수 3장 행렬식 학습", next.title());
            assertFalse(next.verificationRequired());
            assertTrue(next.evidence().stream().anyMatch(e -> e.type().equals("TOC")));
            // 숙련도 측정 없음 → 확인 퀴즈(완료 ≠ 숙련)
            assertTrue(out.candidates().stream().anyMatch(c -> c.type().equals(PRACTICE) && c.title().contains("확인 퀴즈")));
        }

        @Test
        void completed_withoutToc_noInventedChapterTitle_andVerificationRequired() {
            var out = UserPlannerTaskRecommender.recommend(ctx(3, 3, null, null, List.of(), List.of()));
            RecommendationCandidate next = out.candidates().stream().filter(c -> c.type().equals(NEXT_CHAPTER)).findFirst().orElseThrow();
            assertEquals("김도현 저자의 선형대수 3장 학습", next.title());
            assertTrue(next.verificationRequired());
            assertNotNull(next.verificationNote());
        }

        @Test
        void lastChapterInToc_noNextChapter() {
            String plan3 = "선형대수 3장 학습하기";
            var c = new UserPlannerTaskRecommender.Context(10L, plan3, "선형대수", null, null, 2, 2, null,
                    new UserPlannerTaskRecommender.Textbook(345L, "교재", TOC), null, null, List.of(), List.of());
            assertFalse(types(UserPlannerTaskRecommender.recommend(c).candidates()).contains(NEXT_CHAPTER));
        }

        @Test
        void nextChapterAlreadyScheduled_isNotDuplicated() {
            var out = UserPlannerTaskRecommender.recommend(ctx(3, 3, TOC, null, List.of(), List.of("선형대수 3장 행렬식")));
            assertFalse(types(out.candidates()).contains(NEXT_CHAPTER));
        }

        @Test
        void quizAndWrongNotes_driveGapReviewAndApplication() {
            var low = UserPlannerTaskRecommender.recommend(ctx(3, 3, TOC, 40, List.of(), List.of()));
            assertTrue(types(low.candidates()).contains(PREREQUISITE_GAP));
            var withNotes = UserPlannerTaskRecommender.recommend(ctx(3, 3, TOC, 40, List.of(new NoteRef(7L, "행렬 오답")), List.of()));
            assertFalse(types(withNotes.candidates()).contains(PREREQUISITE_GAP));
            assertTrue(types(withNotes.candidates()).contains(WRONG_ANSWER_REVIEW));
            var high = UserPlannerTaskRecommender.recommend(ctx(3, 3, TOC, 92, List.of(), List.of()));
            assertTrue(types(high.candidates()).contains(APPLICATION));
        }

        @Test
        void emptyDefaultPlanner_hasNoData() {
            var c = new UserPlannerTaskRecommender.Context(1L, "공부 플래너", null, null, null, 0, 0, null, null, null, null, List.of(), List.of());
            var out = UserPlannerTaskRecommender.recommend(c);
            assertEquals(UserPlannerTaskRecommender.STATUS_NO_DATA, out.status());
            assertTrue(out.candidates().isEmpty());
        }
    }

    @Nested
    class Roadmap {
        private RoadmapNodeRecommender.NodeInput n(int i, boolean done, Double mastery, LocalDate date) {
            return new RoadmapNodeRecommender.NodeInput("p" + i, (long) i, "[로드맵 1주차 " + i + "일] 주제" + i, i, date, done, mastery,
                    mastery == null ? null : "QUIZ:" + i);
        }

        private final LocalDate today = LocalDate.of(2026, 10, 13);

        @Test
        void sequential_frontierIsFirstIncomplete_unknownMasteryNeedsVerification() {
            var out = RoadmapNodeRecommender.recommend(List.of(n(1, true, null, today.minusDays(2)), n(2, true, null, today.minusDays(1)),
                    n(3, false, null, today), n(4, false, null, today.plusDays(1))), "p2", null, today, List.of(), NodeScorer.DEFAULT_WEIGHTS);
            assertEquals(1, out.candidates().size());
            RecommendationCandidate c = out.candidates().get(0);
            assertEquals(ROADMAP_NODE, c.type());
            assertEquals("p3", c.targetKey());
            assertTrue(c.verificationRequired(), "선수 단계 숙련도 미측정 → UNKNOWN");
            assertEquals("UNKNOWN", c.score().get("eligibility"));
            assertEquals(false, c.score().get("weightsValidated"));
        }

        @Test
        void outOfOrderCompletion_yieldsMultipleFrontier_rankedByScore() {
            // 1 미완료, 2 완료, 3 미완료 → frontier {1(선수 없음), 3(선수 2 완료)}
            var out = RoadmapNodeRecommender.recommend(List.of(n(1, false, null, today.minusDays(5)), n(2, true, null, today.minusDays(4)),
                    n(3, false, null, today.plusDays(6))), "p2", null, today, List.of(), NodeScorer.DEFAULT_WEIGHTS);
            assertEquals(Set.of("p1", "p3"), Set.of(out.candidates().get(0).targetKey(), out.candidates().get(1).targetKey()));
            // p1: P=1(선수 없음, 공허 참)·C=0·T=1 → 0.6875 / p3: P 미측정(제외)·C=1·T=1/7 → 0.619 → 밀린 p1 이 앞선다
            assertEquals("p1", out.candidates().get(0).targetKey());
            assertEquals(0.6875, (Double) out.candidates().get(0).score().get("score"), 1e-3);
        }

        @Test
        void measuredMasteryBelowThreshold_recommendsPrereqReviewInstead() {
            var out = RoadmapNodeRecommender.recommend(List.of(n(1, true, 0.4, today), n(2, false, null, today)), "p1", null, today,
                    List.of(), NodeScorer.DEFAULT_WEIGHTS);
            assertEquals(List.of(PREREQUISITE_GAP), types(out.candidates()));
            assertEquals("p1", out.candidates().get(0).targetKey());
        }

        @Test
        void cyclicExtraEdges_areRejected_andSequentialGraphKept() {
            var out = RoadmapNodeRecommender.recommend(List.of(n(1, true, null, today), n(2, false, null, today), n(3, false, null, today)),
                    "p1", null, today, List.of(new LearningGraph.Edge("p3", "p1")), NodeScorer.DEFAULT_WEIGHTS);
            assertFalse(out.extraEdgesApplied());
            assertFalse(out.graphValidation().valid());
            assertEquals("p2", out.candidates().get(0).targetKey());
        }

        @Test
        void validExtraEdge_changesPrerequisites() {
            // 추가 간선 p1 → p3 (p3 는 p2 와 p1 모두 필요) — 순환 없음
            var out = RoadmapNodeRecommender.recommend(List.of(n(1, false, null, today), n(2, true, null, today), n(3, false, null, today)),
                    "p2", null, today, List.of(new LearningGraph.Edge("p1", "p3")), NodeScorer.DEFAULT_WEIGHTS);
            assertTrue(out.extraEdgesApplied());
            assertEquals(List.of("p1"), out.candidates().stream().map(RecommendationCandidate::targetKey).toList());
        }

        @Test
        void allCompleted() {
            var out = RoadmapNodeRecommender.recommend(List.of(n(1, true, null, today)), "p1", null, today, List.of(), NodeScorer.DEFAULT_WEIGHTS);
            assertEquals(RoadmapNodeRecommender.STATUS_ALL_DONE, out.status());
        }
    }

    @Nested
    class Document {
        @Test
        void noPlanner_documentBasedTypesOnly_neverRoadmapStep() {
            var c = new DocumentRecommender.Context(345L, "Android ViewModel 정리", "PDF", List.of("ViewModel", "SavedStateHandle"),
                    new DocumentRecommender.StudyNote(List.of("ViewModelStoreOwner", "구성 변경", "SavedStateHandle"), List.of(), List.of("프로세스 종료 복원"),
                            List.of("ViewModel 은 언제 파괴되는가?")),
                    null, null, 0, List.of(), null);
            var out = DocumentRecommender.recommend(c);
            assertEquals("OK", out.status());
            for (RecommendationCandidate r : out.candidates()) {
                assertTrue(RecommendationCandidate.DOCUMENT_TYPES.contains(r.type()), r.type());
                assertFalse(r.title().contains("주차"), "확인되지 않은 로드맵 단계로 표현 금지");
            }
            assertTrue(out.candidates().get(0).title().contains("ViewModelStoreOwner"));
        }

        @Test
        void quizScoreDrivesReviewOrDeepDive_andStudyLogNextPlanIsATodo() {
            var low = DocumentRecommender.recommend(new DocumentRecommender.Context(1L, "문서", "PDF", List.of(), null, 9L, 50, 1, List.of(), null));
            assertTrue(types(low.candidates()).contains(DOCUMENT_REVIEW));
            var high = DocumentRecommender.recommend(new DocumentRecommender.Context(1L, "문서", "PDF", List.of(), null, 9L, 95, 1, List.of(), null));
            assertTrue(types(high.candidates()).contains(DOCUMENT_DEEP_DIVE));
            var log = DocumentRecommender.recommend(new DocumentRecommender.Context(1L, "일지", "STUDY_LOG", List.of(), null, null, null, 1, List.of(), "3장 연습문제"));
            assertTrue(log.candidates().stream().anyMatch(r -> r.title().contains("다음 계획")));
        }
    }

    @Nested
    class AiValidation {
        private final Map<String, Evidence> index = new LinkedHashMap<>(Map.of(
                "PLANNER:10", new Evidence("PLANNER", "10", "선형대수 2장"),
                "TOC:345:3", new Evidence("TOC", "345:3", "3장 행렬식")));

        private AiCandidateValidator.RawCandidate raw(String type, String title, List<String> ev, Integer ch, String chTitle, String node) {
            return new AiCandidateValidator.RawCandidate(type, title, "이유", ev, ch, chTitle, node);
        }

        @Test
        void hallucinatedEvidenceAndUnverifiedChapters_areDiscarded() {
            var r = AiCandidateValidator.validate(List.of(
                            raw(PRACTICE, "연습문제", List.of("PLANNER:10", "QUIZ:999"), null, null, null),
                            raw(NEXT_CHAPTER, "4장 고유값 학습", List.of("PLANNER:10"), 4, "고유값과 고유벡터", null),
                            raw(NEXT_CHAPTER, "3장 학습", List.of("PLANNER:10"), 3, "행렬식", null),
                            raw("MAKE_COFFEE", "x", List.of("PLANNER:10"), null, null, null),
                            raw(PRACTICE, "근거 없음", List.of(), null, null, null)),
                    TASK_TYPES, index, TOC, null, null, "ollama", "qwen");
            assertEquals(List.of(AiCandidateValidator.UNKNOWN_EVIDENCE, AiCandidateValidator.UNVERIFIED_TOC,
                            AiCandidateValidator.INVALID_TYPE, AiCandidateValidator.NO_EVIDENCE),
                    r.discarded().stream().map(AiCandidateValidator.Discard::reason).toList());
            assertEquals(1, r.accepted().size());
            assertEquals("3장 행렬식 학습", r.accepted().get(0).title(), "제목은 AI 문자열이 아니라 목차 원문");
            assertEquals(AI, r.accepted().get(0).generator());
            assertEquals("선형대수 2장", r.accepted().get(0).evidence().get(0).label(), "근거 라벨은 EC2 데이터");
        }

        @Test
        void noVerifiedToc_rejectsAnyAiChapterTitle() {
            var r = AiCandidateValidator.validate(List.of(raw(NEXT_CHAPTER, "3장 행렬식 학습", List.of("PLANNER:10"), 3, "행렬식", null)),
                    TASK_TYPES, index, TextbookToc.none(), null, null, null, null);
            assertEquals(AiCandidateValidator.UNVERIFIED_TOC, r.discarded().get(0).reason());
        }

        @Test
        void roadmapNodes_mustExistAndBeInFrontier() {
            Map<String, Evidence> idx = Map.of("ROADMAP_NODE:p3", new Evidence("ROADMAP_NODE", "p3", "3일"));
            var r = AiCandidateValidator.validate(List.of(
                            raw(ROADMAP_NODE, "a", List.of("ROADMAP_NODE:p3"), null, null, "p99"),
                            raw(ROADMAP_NODE, "b", List.of("ROADMAP_NODE:p3"), null, null, "p4"),
                            raw(ROADMAP_NODE, "c", List.of("ROADMAP_NODE:p3"), null, null, "p3")),
                    List.of(ROADMAP_NODE), idx, null, Set.of("p3"), Set.of("p3", "p4"), null, null);
            assertEquals(List.of(AiCandidateValidator.UNKNOWN_NODE, AiCandidateValidator.NOT_FRONTIER),
                    r.discarded().stream().map(AiCandidateValidator.Discard::reason).toList());
            assertEquals("p3", r.accepted().get(0).targetKey());
        }

        @Test
        void clientParse_rejectsWrongMajorVersionAndFailure() {
            assertTrue(AiRecommendationClient.parse(Map.of("success", false)).isEmpty());
            assertTrue(AiRecommendationClient.parse(Map.of("contractVersion", "recommendation.v2", "candidates", List.of())).isEmpty());
            var ok = AiRecommendationClient.parse(Map.of("contractVersion", "recommendation.v1.1",
                    "candidates", List.of(Map.of("type", NEXT_CHAPTER, "title", "t", "evidenceIds", List.of("PLANNER:10"),
                            "chapter", Map.of("number", 3, "title", "행렬식"))),
                    "edges", List.of(Map.of("from", "p1", "to", "p3")), "model", Map.of("provider", "ollama", "name", "qwen2.5")));
            assertTrue(ok.isPresent());
            assertEquals(3, ok.get().candidates().get(0).chapterNumber());
            assertEquals("ollama", ok.get().provider());
            assertEquals(1, ok.get().edges().size());
        }
    }
}
