package com.studybridge.api.service.recommendation;

import com.studybridge.api.service.recommendation.LearningGraph.Edge;
import com.studybridge.api.service.recommendation.NodeEligibility.NodeState;
import com.studybridge.api.service.recommendation.RecommendationCandidate.Evidence;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 로드맵 플래너 — Learning Node 추천. 단일 문장이 아니라 로드맵 전체(목표·선수관계·진도·숙련도)로 다음 단계를 정한다.
 *
 * <ol>
 *   <li>G=(V,E) 구성: V = 같은 사용자·같은 로드맵의 플래너(노드), E = 기존 순서(week/day) 기반 순차 간선(레거시 호환)
 *       + 검증된 추가 간선(AI07 후보 등). 추가 간선으로 순환이 생기면 추가 간선 전체를 버리고 순차 그래프만 쓴다.</li>
 *   <li>Frontier F = { v | ¬completed(v) ∧ ∀u∈Prereq(v): completed(u) } — 진도 조건.</li>
 *   <li>F 의 각 v 에 대해 Eligible(v)(숙련도, 3값). NOT_ELIGIBLE 이면 그 노드 대신 미달 선수 노드 복습을 낸다.
 *       UNKNOWN 은 추천하되 verificationRequired=true(숙련도 미측정 — 완료만으로 숙련 100% 로 보지 않음).</li>
 *   <li>여럿이면 {@link NodeScorer} 로 순위(근거 있는 항만 사용).</li>
 * </ol>
 */
public final class RoadmapNodeRecommender {

    public static final double DEFAULT_THRESHOLD = 0.7;
    static final int MAX_CANDIDATES = 3;

    public record NodeInput(String key, Long plannerId, String title, long order, LocalDate date,
                            boolean completed, Double mastery, String masterySource) {}

    public record Output(List<RecommendationCandidate> candidates, String status, String note,
                         LearningGraph.Validation graphValidation, int nodeCount, int completedCount, boolean extraEdgesApplied) {}

    public static final String STATUS_OK = "OK";
    public static final String STATUS_ALL_DONE = "ALL_COMPLETED";
    public static final String STATUS_NO_DATA = "NO_DATA";

    private RoadmapNodeRecommender() {}

    public static Output recommend(List<NodeInput> inputs, String currentKey, String roadmapGoal, LocalDate today,
                                   List<Edge> extraEdges, NodeScorer.Weights weights) {
        if (inputs == null || inputs.isEmpty()) {
            return new Output(List.of(), STATUS_NO_DATA, "로드맵 노드를 찾지 못했습니다.", LearningGraph.Validation.ok(), 0, 0, false);
        }
        List<LearningGraph.Node> nodes = inputs.stream().map(n -> new LearningGraph.Node(n.key(), n.title(), n.order())).toList();
        LearningGraph base = LearningGraph.sequential(nodes);
        LearningGraph graph = base;
        LearningGraph.Validation validation = base.validate();
        boolean applied = false;
        if (extraEdges != null && !extraEdges.isEmpty()) {
            LearningGraph withExtra = base.withEdges(extraEdges);
            LearningGraph.Validation v = withExtra.validate();
            if (v.valid()) { graph = withExtra; applied = true; }
            validation = v;
        }

        Map<String, NodeInput> byKey = new LinkedHashMap<>();
        Map<String, NodeState> states = new HashMap<>();
        for (NodeInput n : inputs) {
            byKey.put(n.key(), n);
            states.put(n.key(), new NodeState(n.completed(), n.mastery(), n.masterySource()));
        }
        int completedCount = (int) inputs.stream().filter(NodeInput::completed).count();
        if (completedCount == inputs.size()) {
            return new Output(List.of(), STATUS_ALL_DONE, "로드맵의 모든 단계를 완료했습니다.", validation, inputs.size(), completedCount, applied);
        }

        List<String> topo = graph.topologicalOrder();
        Map<String, Integer> topoIdx = new HashMap<>();
        for (int i = 0; i < topo.size(); i++) topoIdx.put(topo.get(i), i);

        Set<String> goalTokens = tokens(roadmapGoal);
        List<Ranked> ranked = new ArrayList<>();
        Set<String> gapTargets = new LinkedHashSet<>();
        for (String v : topo) {
            NodeInput n = byKey.get(v);
            if (n.completed()) continue;
            boolean frontier = graph.prereqs(v).stream().allMatch(u -> states.get(u).completed());
            if (!frontier) continue;
            NodeEligibility.Result el = NodeEligibility.evaluate(graph, v, states, Map.of(), DEFAULT_THRESHOLD);
            if (el.status() == NodeEligibility.Status.NOT_ELIGIBLE) {
                el.checks().stream().filter(ch -> ch.status() == NodeEligibility.Status.NOT_ELIGIBLE)
                        .forEach(ch -> gapTargets.add(ch.prereqKey()));
                continue;
            }
            Double relevance = goalTokens.isEmpty() ? null : overlap(goalTokens, tokens(n.title()));
            Double prereq = el.measuredSatisfaction();
            Double continuity = currentKey == null || !byKey.containsKey(currentKey) ? null
                    : (v.equals(currentKey) || graph.prereqs(v).contains(currentKey) ? 1.0 : 0.0);
            Double schedule = n.date() == null ? null : scheduleFit(n.date(), today);
            NodeScorer.Score s = NodeScorer.score(new NodeScorer.Components(relevance, prereq, continuity, schedule), weights);
            ranked.add(new Ranked(n, el, s, topoIdx.get(v)));
        }
        ranked.sort(Comparator.comparing((Ranked r) -> r.score.score() == null ? -1.0 : r.score.score()).reversed()
                .thenComparingInt(r -> r.topoIndex));

        List<RecommendationCandidate> out = new ArrayList<>();
        for (Ranked r : ranked.subList(0, Math.min(MAX_CANDIDATES, ranked.size()))) {
            out.add(toCandidate(r, graph, byKey, weights));
        }
        for (String gap : gapTargets) {
            NodeInput g = byKey.get(gap);
            out.add(RecommendationCandidate.rule(RecommendationCandidate.PREREQUISITE_GAP,
                    "선수 단계 복습: " + UserPlannerTaskRecommender.trim(g.title(), 80),
                    "다음 단계의 선수 단계 숙련도(" + pct(g.mastery()) + ")가 기준(" + pct(DEFAULT_THRESHOLD) + ")에 못 미칩니다.",
                    g.key(), List.of(new Evidence("ROADMAP_NODE", g.key(), g.title()),
                            new Evidence("MASTERY", g.masterySource() == null ? g.key() : g.masterySource(), pct(g.mastery()))),
                    false, null));
        }
        return new Output(out, STATUS_OK, null, validation, inputs.size(), completedCount, applied);
    }

    private record Ranked(NodeInput node, NodeEligibility.Result eligibility, NodeScorer.Score score, int topoIndex) {}

    private static RecommendationCandidate toCandidate(Ranked r, LearningGraph g, Map<String, NodeInput> byKey, NodeScorer.Weights w) {
        NodeInput n = r.node();
        List<Evidence> ev = new ArrayList<>();
        ev.add(new Evidence("ROADMAP_NODE", n.key(), n.title()));
        List<String> prereqTitles = new ArrayList<>();
        for (String u : g.prereqs(n.key())) {
            NodeInput p = byKey.get(u);
            ev.add(new Evidence("ROADMAP_NODE", u, (p.completed() ? "[완료] " : "") + p.title()));
            prereqTitles.add(UserPlannerTaskRecommender.trim(p.title(), 40));
        }
        boolean unknown = r.eligibility().status() == NodeEligibility.Status.UNKNOWN;
        String reason = prereqTitles.isEmpty()
                ? "선수 단계가 없는 로드맵 시작 단계입니다."
                : "선수 단계(" + String.join(", ", prereqTitles) + ")를 완료했습니다.";
        if (unknown) reason += " 선수 단계의 숙련도는 아직 측정되지 않았습니다(UNKNOWN).";
        Map<String, Object> score = new LinkedHashMap<>();
        score.put("eligibility", r.eligibility().status().name());
        score.put("prereqCompletionRatio", r.eligibility().prereqCompletionRatio());
        score.put("score", r.score().score());
        score.put("components", Map.of(
                "R", String.valueOf(r.score().components().relevance()),
                "P", String.valueOf(r.score().components().prerequisite()),
                "C", String.valueOf(r.score().components().continuity()),
                "T", String.valueOf(r.score().components().schedule())));
        score.put("usedWeights", r.score().usedWeights());
        score.put("weightsValidated", false);
        score.put("threshold", DEFAULT_THRESHOLD);
        return RecommendationCandidate.rule(RecommendationCandidate.ROADMAP_NODE,
                        "다음 단계: " + UserPlannerTaskRecommender.trim(n.title(), 160), reason, n.key(), ev, unknown,
                        unknown ? "숙련도 측정 기록이 없어 진입 조건을 확인하지 못했습니다. 직전 단계 확인 퀴즈를 권장합니다." : null)
                .withScore(score);
    }

    /** 오늘 이전/당일 = 1, 7일 뒤 0 으로 선형 감소(계획된 날짜와의 거리). */
    static double scheduleFit(LocalDate date, LocalDate today) {
        long ahead = ChronoUnit.DAYS.between(today, date);
        if (ahead <= 0) return 1.0;
        return Math.max(0.0, 1.0 - ahead / 7.0);
    }

    static Set<String> tokens(String s) {
        Set<String> out = new LinkedHashSet<>();
        if (s == null) return out;
        for (String t : s.toLowerCase(Locale.ROOT).replaceAll("\\[[^\\]]*\\]", " ").split("[^\\p{L}\\p{N}]+")) {
            String core = t.replaceAll("(을|를|이|가|은|는|의|에|와|과|로|으로|하기|한다|학습|중심)$", "");
            if (core.length() >= 2) out.add(core);
        }
        return out;
    }

    static double overlap(Set<String> goal, Set<String> title) {
        if (goal.isEmpty() || title.isEmpty()) return 0.0;
        long hit = title.stream().filter(goal::contains).count();
        return (double) hit / title.size();
    }

    private static String pct(Double v) {
        return v == null ? "미측정" : Math.round(v * 100) + "%";
    }
}
