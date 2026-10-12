package com.studybridge.api.service.recommendation;

import com.studybridge.api.service.recommendation.LearningGraph.Edge;
import com.studybridge.api.service.recommendation.LearningGraph.Node;
import com.studybridge.api.service.recommendation.NodeEligibility.NodeState;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/** DAG · 숙련도 진입 조건 · 점수 · 목차 · 시간 진단 — 순수 알고리즘 검증. */
class RecommendationAlgorithmsTest {

    private static List<Node> nodes(String... keys) {
        Node[] out = new Node[keys.length];
        for (int i = 0; i < keys.length; i++) out[i] = new Node(keys[i], keys[i], i);
        return List.of(out);
    }

    @Nested
    class Graph {
        @Test
        void sequentialRoadmap_isDagInOriginalOrder() {
            LearningGraph g = LearningGraph.sequential(List.of(new Node("c", "c", 3), new Node("a", "a", 1), new Node("b", "b", 2)));
            assertTrue(g.validate().valid());
            assertEquals(List.of("a", "b", "c"), g.topologicalOrder());
            assertEquals(java.util.Set.of("a"), g.prereqs("b"));
            assertEquals(java.util.Set.of("a", "b"), g.ancestors("c"));
        }

        @Test
        void cycle_isDetected_andTopologicalOrderRefused() {
            LearningGraph g = new LearningGraph(nodes("a", "b", "c"), List.of(new Edge("a", "b"), new Edge("b", "c"), new Edge("c", "a")));
            LearningGraph.Validation v = g.validate();
            assertFalse(v.valid());
            assertEquals(List.of("a", "b", "c"), v.cycleNodes());
            assertThrows(IllegalStateException.class, g::topologicalOrder);
        }

        @Test
        void selfLoop_andUnknownNodeEdges_areInvalid() {
            assertFalse(new LearningGraph(nodes("a"), List.of(new Edge("a", "a"))).validate().valid());
            LearningGraph.Validation v = new LearningGraph(nodes("a", "b"), List.of(new Edge("a", "zzz"))).validate();
            assertFalse(v.valid());
            assertEquals(List.of("a->zzz"), v.unknownNodeEdges());
        }

        @Test
        void branchingDag_topoOrderRespectsEdges_andIsStableByOrder() {
            // a → c, b → c, c → d ; a,b 는 독립
            LearningGraph g = new LearningGraph(nodes("a", "b", "c", "d"),
                    List.of(new Edge("a", "c"), new Edge("b", "c"), new Edge("c", "d")));
            List<String> topo = g.topologicalOrder();
            assertEquals(List.of("a", "b", "c", "d"), topo);
            assertTrue(g.withEdges(List.of(new Edge("d", "a"))).validate().cycleNodes().size() > 0);
        }
    }

    @Nested
    class Eligibility {
        private final LearningGraph g = new LearningGraph(nodes("u1", "u2", "v"), List.of(new Edge("u1", "v"), new Edge("u2", "v")));

        @Test
        void completedButUnmeasured_isUnknown_notMastered() {
            NodeEligibility.Result r = NodeEligibility.evaluate(g, "v",
                    Map.of("u1", NodeState.unmeasured(true), "u2", NodeState.unmeasured(true)), Map.of(), 0.7);
            assertEquals(NodeEligibility.Status.UNKNOWN, r.status());
            assertTrue(r.allPrereqsCompleted());
            assertNull(r.measuredSatisfaction(), "완료만으로 숙련도 충족을 만들지 않는다");
        }

        @Test
        void anyMeasuredBelowThreshold_isNotEligible() {
            NodeEligibility.Result r = NodeEligibility.evaluate(g, "v",
                    Map.of("u1", new NodeState(true, 0.9, "QUIZ:1"), "u2", new NodeState(true, 0.4, "QUIZ:2")), Map.of(), 0.7);
            assertEquals(NodeEligibility.Status.NOT_ELIGIBLE, r.status());
            assertEquals(0.5, r.measuredSatisfaction());
        }

        @Test
        void allMeasuredAboveThreshold_isEligible_andPerNodeThresholdApplies() {
            Map<String, NodeState> st = Map.of("u1", new NodeState(true, 0.75, "q"), "u2", new NodeState(true, 0.8, "q"));
            assertEquals(NodeEligibility.Status.ELIGIBLE, NodeEligibility.evaluate(g, "v", st, Map.of(), 0.7).status());
            assertEquals(NodeEligibility.Status.NOT_ELIGIBLE, NodeEligibility.evaluate(g, "v", st, Map.of("u1", 0.9), 0.7).status());
        }

        @Test
        void noPrereqs_isEligible() {
            assertEquals(NodeEligibility.Status.ELIGIBLE, NodeEligibility.evaluate(g, "u1", Map.of(), Map.of(), 0.7).status());
        }
    }

    @Nested
    class Scorer {
        @Test
        void weightsMustBeNonNegative_andSumToOne() {
            assertThrows(IllegalArgumentException.class, () -> new NodeScorer.Weights(0.5, 0.5, 0.5, -0.5));
            assertThrows(IllegalArgumentException.class, () -> new NodeScorer.Weights(0.3, 0.3, 0.3, 0.3));
        }

        @Test
        void missingComponents_areExcluded_andWeightsRenormalized() {
            NodeScorer.Score s = NodeScorer.score(new NodeScorer.Components(null, null, 1.0, 0.5), NodeScorer.DEFAULT_WEIGHTS);
            // C=0.25, T=0.2 → 정규화 0.5556 / 0.4444
            assertEquals(1.0, s.usedWeights().values().stream().mapToDouble(Double::doubleValue).sum(), 1e-3);
            assertFalse(s.usedWeights().containsKey("R"));
            assertEquals(0.7778, s.score(), 1e-3);
        }

        @Test
        void noData_noScore() {
            assertNull(NodeScorer.score(new NodeScorer.Components(null, null, null, null), NodeScorer.DEFAULT_WEIGHTS).score());
        }
    }

    @Nested
    class Toc {
        @Test
        void tocSection_isVerified_andTitlesMatch() {
            String text = "선형대수학 입문\n김도현 지음\n\n목차\n1장 벡터와 공간 ........ 1\n2장 행렬과 연립방정식 ........ 35\n3장 행렬식 ........ 70\n\n1장 벡터와 공간\n본문";
            TextbookToc toc = TextbookToc.extract(text);
            assertTrue(toc.verified());
            assertEquals("행렬식", toc.chapter(3).orElseThrow().title());
            assertTrue(toc.matchesTitle(3, "행렬식"));
            assertFalse(toc.matchesTitle(3, "고유값과 고유벡터"));
            assertEquals(3, toc.lastChapter().orElseThrow());
        }

        @Test
        void bodyHeadings_chapterEnglish_areVerified() {
            TextbookToc toc = TextbookToc.extract("Chapter 1 Introduction\ntext\nChapter 2 Processes\ntext");
            assertTrue(toc.verified());
            assertEquals("Processes", toc.chapter(2).orElseThrow().title());
        }

        @Test
        void singleChapterMention_isNotATableOfContents() {
            TextbookToc toc = TextbookToc.extract("이번 시간에는 3장 내용을 공부합니다.\n제3장 행렬식");
            assertFalse(toc.verified());
            assertFalse(toc.matchesTitle(3, "행렬식"));
        }

        @Test
        void chapterRef_fromPlanSentence() {
            TextbookToc.ChapterRef r = TextbookToc.chapterRef("김도현 저자의 선형대수 2장 학습하기").orElseThrow();
            assertEquals(2, r.number());
            assertEquals("김도현 저자의 선형대수", r.prefix());
            assertEquals(3, TextbookToc.chapterRef("SB36 운영체제 3장 프로세스 복습").orElseThrow().number());
            assertTrue(TextbookToc.chapterRef("binary search 3 times").isEmpty());
        }
    }

    @Nested
    class Capacity {
        private final LocalDate today = LocalDate.of(2026, 10, 13);

        private PlanCapacityCalculator.Task t(String k, int dayOffset, Integer min, boolean done, String... prereqs) {
            return new PlanCapacityCalculator.Task(k, k, today.plusDays(dayOffset), null, min, done, List.of(prereqs));
        }

        @Test
        void deficit_isMaxZeroWMinusA() {
            var r = PlanCapacityCalculator.calculate(today, today.plusDays(1), 60,
                    List.of(t("a", 0, 90, false), t("b", 1, 60, false), t("c", 1, 30, true)), List.of(), List.of());
            assertEquals(120, r.availableMinutes());   // 2일 × 60
            assertEquals(150, r.workloadMinutes());    // 완료 작업 제외
            assertEquals(30, r.deficitMinutes());
            assertEquals(PlanCapacityCalculator.SHORTAGE, r.status());
        }

        @Test
        void totalFits_butEarlyDeadlineWindowIsShort() {
            var r = PlanCapacityCalculator.calculate(today, today.plusDays(4), 60,
                    List.of(t("a", 0, 100, false), t("b", 4, 10, false)), List.of(), List.of());
            assertEquals(0, r.deficitMinutes());
            assertNotNull(r.firstShortageWindow());
            assertEquals(today, r.firstShortageWindow().dueDate());
            assertEquals(40, r.firstShortageWindow().shortage());
            assertEquals(PlanCapacityCalculator.SHORTAGE, r.status());
            assertEquals(1, r.overloadedDays().size());
        }

        @Test
        void noAvailability_noFabricatedAorD() {
            var r = PlanCapacityCalculator.calculate(today, null, null, List.of(t("a", 0, 100, false)), List.of(), List.of());
            assertNull(r.availableMinutes());
            assertNull(r.deficitMinutes());
            assertEquals(PlanCapacityCalculator.NEEDS_AVAILABILITY, r.status());
        }

        @Test
        void noEstimates_isReported_notZeroFilled() {
            var r = PlanCapacityCalculator.calculate(today, null, 60, List.of(t("a", 0, null, false), t("b", 1, null, false)), List.of(), List.of());
            assertEquals(PlanCapacityCalculator.NO_ESTIMATES, r.status());
            assertEquals(2, r.unestimatedCount());
            assertNull(r.deficitMinutes());
        }

        @Test
        void dependencyAndOverlap_areDetected_priorityIsEdfThenTopo() {
            var r = PlanCapacityCalculator.calculate(today, null, 120,
                    List.of(t("pre", 3, 30, false), t("next", 1, 30, false, "pre"), t("old", -2, 30, false), t("x", 5, 30, false, "old")),
                    List.of(new PlanCapacityCalculator.Interval("1", "수업", LocalDateTime.of(2026, 10, 13, 9, 0), LocalDateTime.of(2026, 10, 13, 11, 0)),
                            new PlanCapacityCalculator.Interval("2", "스터디", LocalDateTime.of(2026, 10, 13, 10, 30), LocalDateTime.of(2026, 10, 13, 12, 0)),
                            new PlanCapacityCalculator.Interval("3", "운동", LocalDateTime.of(2026, 10, 13, 12, 0), LocalDateTime.of(2026, 10, 13, 13, 0))),
                    List.of("old", "pre", "next", "x"));
            assertTrue(r.dependencyIssues().stream().anyMatch(d -> d.taskKey().equals("next") && d.kind().equals("SCHEDULED_BEFORE_PREREQ")));
            assertTrue(r.dependencyIssues().stream().anyMatch(d -> d.taskKey().equals("x") && d.kind().equals("PREREQ_OVERDUE")));
            assertEquals(1, r.overlaps().size());
            assertEquals(30, r.overlaps().get(0).overlapMinutes());
            assertEquals(List.of("old", "next", "pre", "x"), r.priorityOrder());
        }

        @Test
        void minutesAndDeadlineParsing_neverGuessUnits() {
            assertEquals(125, PlannerProgressReader.parseMinutes("125분"));
            assertEquals(120, PlannerProgressReader.parseMinutes("2시간"));
            assertEquals(90, PlannerProgressReader.parseMinutes("1시간 30분"));
            assertEquals(90, PlannerProgressReader.parseMinutes("1.5시간"));
            assertEquals(150, PlannerProgressReader.parseMinutes("02:30"));
            assertNull(PlannerProgressReader.parseMinutes("3"));
            assertNull(PlannerProgressReader.parseMinutes("많이"));
            assertEquals(LocalDate.of(2026, 9, 18), PlannerProgressReader.parseDeadline("2026-09-18", today));
            assertEquals(today.plusDays(7), PlannerProgressReader.parseDeadline("D-7", today));
            assertEquals(LocalDate.of(2026, 12, 1), PlannerProgressReader.parseDeadline("12/1", today));
            assertNull(PlannerProgressReader.parseDeadline("기말고사 전", today));
            assertEquals(30, PlannerProgressReader.focusMinutes("{\"7\":[false,true,false,false,false,false],\"9\":[true,true,false,false,false,false]}"));
            assertNull(PlannerProgressReader.focusMinutes("{}"));
        }
    }
}
