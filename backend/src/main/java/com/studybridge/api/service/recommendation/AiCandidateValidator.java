package com.studybridge.api.service.recommendation;

import com.studybridge.api.service.recommendation.RecommendationCandidate.Evidence;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * AI07 추천 후보의 EC2 최종 검증(AI_RECOMMENDATION_CONTRACT_V1 §검증). AI 는 후보만 만들고, 채택은 EC2 가 한다.
 *
 * <ul>
 *   <li>유형: 기능별 허용 목록 밖이면 INVALID_TYPE.</li>
 *   <li>근거: evidenceIds 가 비었거나 EC2 가 보낸 근거 목록에 없는 ID 를 인용하면 NO_EVIDENCE / UNKNOWN_EVIDENCE(환각).</li>
 *   <li>장 제목: NEXT_CHAPTER 는 확인된 목차의 장 번호·제목과 일치해야 한다. 목차 미확인이면 UNVERIFIED_TOC 로 버린다
 *       (번호만 쓰는 다음 장 후보는 규칙 추천이 이미 verificationRequired 로 낸다). 통과 시 제목은 목차 원문으로 교체한다.</li>
 *   <li>로드맵: nodeKey 가 그래프에 없으면 UNKNOWN_NODE, 진입 가능 집합(frontier) 밖이면 NOT_FRONTIER.</li>
 *   <li>근거 라벨은 AI 문자열이 아니라 EC2 데이터(evidenceIndex)에서 가져온다.</li>
 * </ul>
 */
public final class AiCandidateValidator {

    /** AI07 응답 candidates[] 한 건(파싱 결과). chapterNumber/chapterTitle/nodeKey 는 nullable. */
    public record RawCandidate(String type, String title, String reason, List<String> evidenceIds,
                               Integer chapterNumber, String chapterTitle, String nodeKey) {}

    public record Discard(String type, String title, String reason) {}

    public record Result(List<RecommendationCandidate> accepted, List<Discard> discarded) {}

    public static final String INVALID_TYPE = "INVALID_TYPE";
    public static final String INVALID_TITLE = "INVALID_TITLE";
    public static final String NO_EVIDENCE = "NO_EVIDENCE";
    public static final String UNKNOWN_EVIDENCE = "UNKNOWN_EVIDENCE";
    public static final String UNVERIFIED_TOC = "UNVERIFIED_TOC";
    public static final String UNKNOWN_NODE = "UNKNOWN_NODE";
    public static final String NOT_FRONTIER = "NOT_FRONTIER";

    /** 환각(근거·목차·노드 불일치)으로 집계하는 사유. */
    public static final Set<String> HALLUCINATION_REASONS = Set.of(UNKNOWN_EVIDENCE, UNVERIFIED_TOC, UNKNOWN_NODE);

    private AiCandidateValidator() {}

    /**
     * @param evidenceIndex EC2 가 AI07 에 보낸 근거 ID → 근거(라벨 포함)
     * @param toc           교재 목차(없으면 null)
     * @param frontierKeys  로드맵 진입 가능 노드 key(로드맵이 아니면 null)
     * @param graphKeys     로드맵 전체 노드 key(로드맵이 아니면 null)
     */
    public static Result validate(List<RawCandidate> raw, Collection<String> allowedTypes, Map<String, Evidence> evidenceIndex,
                                  TextbookToc toc, Set<String> frontierKeys, Set<String> graphKeys,
                                  String provider, String model) {
        List<RecommendationCandidate> ok = new ArrayList<>();
        List<Discard> bad = new ArrayList<>();
        for (RawCandidate c : raw == null ? List.<RawCandidate>of() : raw) {
            String type = c.type() == null ? "" : c.type().trim();
            String title = c.title() == null ? "" : c.title().trim();
            if (!allowedTypes.contains(type)) { bad.add(new Discard(type, title, INVALID_TYPE)); continue; }
            if (title.isEmpty() || title.length() > 200) { bad.add(new Discard(type, title, INVALID_TITLE)); continue; }
            List<String> ids = c.evidenceIds() == null ? List.of() : c.evidenceIds();
            if (ids.isEmpty()) { bad.add(new Discard(type, title, NO_EVIDENCE)); continue; }
            if (!evidenceIndex.keySet().containsAll(ids)) { bad.add(new Discard(type, title, UNKNOWN_EVIDENCE)); continue; }

            String targetKey = "ai:" + TextbookToc.norm(title);
            if (RecommendationCandidate.NEXT_CHAPTER.equals(type)) {
                if (c.chapterNumber() == null || toc == null || !toc.verified() || !toc.matchesTitle(c.chapterNumber(), c.chapterTitle())) {
                    bad.add(new Discard(type, title, UNVERIFIED_TOC));
                    continue;
                }
                TextbookToc.Entry e = toc.chapter(c.chapterNumber()).orElseThrow();
                title = e.number() + "장 " + e.title() + " 학습";
                targetKey = "ch" + e.number();
            }
            if (graphKeys != null) {
                if (c.nodeKey() == null || !graphKeys.contains(c.nodeKey())) { bad.add(new Discard(type, title, UNKNOWN_NODE)); continue; }
                if (frontierKeys == null || !frontierKeys.contains(c.nodeKey())) { bad.add(new Discard(type, title, NOT_FRONTIER)); continue; }
                targetKey = c.nodeKey();
            }
            List<Evidence> evidence = ids.stream().map(evidenceIndex::get).toList();
            String reason = c.reason() == null ? null : UserPlannerTaskRecommender.trim(c.reason(), 500);
            ok.add(new RecommendationCandidate(type, title, reason, targetKey, evidence, false, null, null,
                    RecommendationCandidate.AI, provider, model));
        }
        return new Result(ok, bad);
    }
}
