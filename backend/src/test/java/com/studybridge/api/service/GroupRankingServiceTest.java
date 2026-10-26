package com.studybridge.api.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.DefaultTypedTuple;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

/**
 * GroupRankingService 단위 테스트.
 *  - 실제 Redis 없이 RedisTemplate/ZSetOperations 를 mock 하고,
 *    key -> (member -> score) 인메모리 Map 으로 Redis Sorted Set 의 ZINCRBY/ZSCORE/ZREVRANGE 의미를 재현한다.
 *  - score(K,Object) 와 score(K,Object...) 처럼 오버로드된 메서드의 Mockito 매칭 취약성을 피하기 위해
 *    메서드명 기반 default Answer 디스패처로 fake 를 구성한다.
 *  - 테스트컨테이너/임베디드 Redis 를 추가하지 않는다.
 */
class GroupRankingServiceTest {

    private GroupRankingService rankingService;

    /** key -> (member -> score) — Redis ZSet 인메모리 fake */
    private final Map<String, Map<Object, Double>> store = new LinkedHashMap<>();

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        store.clear();

        ZSetOperations<String, Object> zset = mock(ZSetOperations.class, invocation -> {
            String method = invocation.getMethod().getName();
            Object[] args = invocation.getArguments();
            switch (method) {
                case "incrementScore": { // ZINCRBY -> 누적 후 새 점수
                    String key = (String) args[0];
                    Object member = args[1];
                    double delta = ((Number) args[2]).doubleValue();
                    Map<Object, Double> m = store.computeIfAbsent(key, k -> new LinkedHashMap<>());
                    double next = m.getOrDefault(member, 0.0) + delta;
                    m.put(member, next);
                    return next;
                }
                case "score": { // ZSCORE -> 없으면 null
                    String key = (String) args[0];
                    Object member = args[1];
                    Map<Object, Double> m = store.get(key);
                    return m == null ? null : m.get(member);
                }
                case "reverseRangeWithScores": { // ZREVRANGE WITHSCORES -> 점수 내림차순
                    String key = (String) args[0];
                    Map<Object, Double> m = store.get(key);
                    Set<ZSetOperations.TypedTuple<Object>> result = new LinkedHashSet<>();
                    if (m != null) {
                        m.entrySet().stream()
                                .sorted((a, b) -> Double.compare(b.getValue(), a.getValue()))
                                .forEach(e -> result.add(new DefaultTypedTuple<>(e.getKey(), e.getValue())));
                    }
                    return result;
                }
                default:
                    return null;
            }
        });

        RedisTemplate<String, Object> redisTemplate = mock(RedisTemplate.class, invocation -> {
            switch (invocation.getMethod().getName()) {
                case "opsForZSet":
                    return zset;
                case "delete": // DEL
                    return store.remove(invocation.getArguments()[0]) != null;
                default:
                    return null;
            }
        });

        rankingService = new GroupRankingService(redisTemplate);
    }

    @Test
    void addPoints_accumulatesScore() {
        rankingService.addPoints(1L, 100L, 10);
        rankingService.addPoints(1L, 100L, 5);
        rankingService.addPoints(1L, 100L, 7);

        assertEquals(22, rankingService.getPoints(1L, 100L));
    }

    @Test
    void getPoints_returnsZeroWhenMemberAbsent() {
        // 존재하지 않는 group/user
        assertEquals(0, rankingService.getPoints(999L, 888L));

        rankingService.addPoints(1L, 100L, 10);
        assertEquals(0, rankingService.getPoints(1L, 777L)); // 같은 group, 다른 user
        assertEquals(0, rankingService.getPoints(2L, 100L)); // 다른 group, 같은 user
    }

    @Test
    void getRanking_isSortedByScoreDescending() {
        rankingService.addPoints(1L, 1L, 10); // userA
        rankingService.addPoints(1L, 2L, 30); // userB
        rankingService.addPoints(1L, 3L, 20); // userC

        List<GroupRankingService.RankingEntry> ranking = rankingService.getRanking(1L);

        assertEquals(3, ranking.size());
        assertEquals(2L, ranking.get(0).userId());
        assertEquals(30, ranking.get(0).points());
        assertEquals(3L, ranking.get(1).userId());
        assertEquals(20, ranking.get(1).points());
        assertEquals(1L, ranking.get(2).userId());
        assertEquals(10, ranking.get(2).points());

        List<Integer> points = ranking.stream()
                .map(GroupRankingService.RankingEntry::points)
                .collect(Collectors.toList());
        assertEquals(List.of(30, 20, 10), points);
    }

    @Test
    void clearRanking_removesAllEntries() {
        rankingService.addPoints(1L, 1L, 10);
        assertEquals(10, rankingService.getPoints(1L, 1L));

        rankingService.clearRanking(1L);

        assertEquals(0, rankingService.getPoints(1L, 1L));
        assertTrue(rankingService.getRanking(1L).isEmpty());
    }
}
