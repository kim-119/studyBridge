package com.studybridge.api.service.recommendation;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 진입 가능한 후보가 여럿일 때의 순위 모델 Score(v) = w₁R(v) + w₂P(v) + w₃C(v) + w₄T(v), Σwᵢ = 1, wᵢ ≥ 0.
 *
 * <ul>
 *   <li>각 항은 근거 데이터가 있을 때만 값(0..1)을 갖고, 없으면 null 이다. 점수는 <b>값이 있는 항의 가중치만 재정규화</b>해
 *       계산한다 — 데이터가 없는 항을 0 으로 채워 다른 후보를 불리하게 만들지 않는다.</li>
 *   <li>선수학습 충족 여부는 이 점수 전에 {@link NodeEligibility} 로 먼저 거른다(NOT_ELIGIBLE 은 순위 대상이 아니다).</li>
 *   <li>기본 가중치는 휴리스틱 초기값이며 검증된 최적값이 아니다(수용률/완료율 데이터로 보정 필요 — 계약 문서 §평가).</li>
 * </ul>
 */
public final class NodeScorer {

    /** 휴리스틱 기본값(검증되지 않음): 선수충족 > 연속성 > 일정 > 목표관련성. */
    public static final Weights DEFAULT_WEIGHTS = new Weights(0.2, 0.35, 0.25, 0.2);

    public record Weights(double relevance, double prerequisite, double continuity, double schedule) {
        public Weights {
            if (relevance < 0 || prerequisite < 0 || continuity < 0 || schedule < 0) {
                throw new IllegalArgumentException("weights must be >= 0");
            }
            double sum = relevance + prerequisite + continuity + schedule;
            if (Math.abs(sum - 1.0) > 1e-6) throw new IllegalArgumentException("weights must sum to 1 (was " + sum + ")");
        }
    }

    /** R/P/C/T 원값. null = 근거 데이터 없음. */
    public record Components(Double relevance, Double prerequisite, Double continuity, Double schedule) {}

    /** score = null 이면 쓸 수 있는 항이 하나도 없다. usedWeights = 재정규화된 실제 가중치. */
    public record Score(Double score, Map<String, Double> usedWeights, Components components) {}

    private NodeScorer() {}

    public static Score score(Components c, Weights w) {
        Map<String, double[]> parts = new LinkedHashMap<>();
        put(parts, "R", c.relevance(), w.relevance());
        put(parts, "P", c.prerequisite(), w.prerequisite());
        put(parts, "C", c.continuity(), w.continuity());
        put(parts, "T", c.schedule(), w.schedule());
        double wSum = parts.values().stream().mapToDouble(p -> p[1]).sum();
        Map<String, Double> used = new LinkedHashMap<>();
        if (parts.isEmpty() || wSum <= 0) return new Score(null, used, c);
        double total = 0;
        for (Map.Entry<String, double[]> e : parts.entrySet()) {
            double nw = e.getValue()[1] / wSum;
            used.put(e.getKey(), round(nw));
            total += nw * e.getValue()[0];
        }
        return new Score(round(total), used, c);
    }

    private static void put(Map<String, double[]> parts, String key, Double value, double weight) {
        if (value == null || value.isNaN()) return;
        parts.put(key, new double[]{Math.max(0, Math.min(1, value)), weight});
    }

    private static double round(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }
}
