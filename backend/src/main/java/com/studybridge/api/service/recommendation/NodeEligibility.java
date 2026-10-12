package com.studybridge.api.service.recommendation;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 숙련도 기반 진입 조건 Eligible(v) = ∧_{u ∈ Prereq(v)} (Mastery(u) ≥ τ_u) 를 3값 논리로 계산한다.
 *
 * <ul>
 *   <li>측정된 숙련도가 없으면 그 선수 노드는 UNKNOWN 이다. 학습 완료(체크리스트 완료) 는 숙련도가 아니다 —
 *       완료만으로 Mastery 를 1.0 으로 만들지 않는다.</li>
 *   <li>하나라도 측정값이 τ 미만이면 NOT_ELIGIBLE, 모두 측정되어 τ 이상이면 ELIGIBLE, 그 외(미측정 포함) UNKNOWN.</li>
 *   <li>선수 노드가 없으면 ELIGIBLE(공집합의 논리곱 = 참).</li>
 * </ul>
 */
public final class NodeEligibility {

    public enum Status { ELIGIBLE, NOT_ELIGIBLE, UNKNOWN }

    /** 노드별 상태. mastery 는 0..1 측정값(없으면 null), source 는 측정 근거(예: QUIZ:345). */
    public record NodeState(boolean completed, Double mastery, String masterySource) {
        public static NodeState unmeasured(boolean completed) {
            return new NodeState(completed, null, null);
        }
    }

    public record PrereqCheck(String prereqKey, boolean completed, Double mastery, double threshold, Status status) {}

    public record Result(Status status, double prereqCompletionRatio, Double measuredSatisfaction, List<PrereqCheck> checks) {
        /** 선수 노드가 모두 '완료' 되었는가(숙련도와 별개 — 진도 조건). */
        public boolean allPrereqsCompleted() {
            return checks.stream().allMatch(PrereqCheck::completed);
        }
    }

    private NodeEligibility() {}

    /**
     * @param thresholds 노드별 τ (없으면 defaultThreshold)
     */
    public static Result evaluate(LearningGraph graph, String nodeKey, Map<String, NodeState> states,
                                  Map<String, Double> thresholds, double defaultThreshold) {
        List<PrereqCheck> checks = new ArrayList<>();
        boolean anyBelow = false;
        boolean anyUnknown = false;
        int completed = 0;
        int measured = 0;
        int measuredOk = 0;
        for (String u : graph.prereqs(nodeKey)) {
            NodeState s = states.getOrDefault(u, NodeState.unmeasured(false));
            double tau = thresholds.getOrDefault(u, defaultThreshold);
            Status st;
            if (s.mastery() == null) {
                st = Status.UNKNOWN;
                anyUnknown = true;
            } else if (s.mastery() >= tau) {
                st = Status.ELIGIBLE;
                measured++;
                measuredOk++;
            } else {
                st = Status.NOT_ELIGIBLE;
                anyBelow = true;
                measured++;
            }
            if (s.completed()) completed++;
            checks.add(new PrereqCheck(u, s.completed(), s.mastery(), tau, st));
        }
        int n = checks.size();
        Status status = anyBelow ? Status.NOT_ELIGIBLE : anyUnknown ? Status.UNKNOWN : Status.ELIGIBLE;
        double completionRatio = n == 0 ? 1.0 : (double) completed / n;
        Double satisfaction;
        if (measured > 0) satisfaction = (double) measuredOk / measured;
        else satisfaction = n == 0 ? Double.valueOf(1.0) : null; // 선수 없음 = 공허 참, 미측정 = 모름
        return new Result(status, completionRatio, satisfaction, checks);
    }
}
