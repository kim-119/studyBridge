package com.studybridge.api.service;

import com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.DefaultTypedTuple;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * GroupRankingService — Redis ZSet 캐시 + RDS 정본 의미 검증.
 *  - 실제 Redis 없이 RedisTemplate/ZSetOperations 를 mock 하고, key -> (member -> score) + TTL 인메모리 Map 으로
 *    ZADD(batch)/ZREVRANGE/EXPIRE/TTL/RENAME/DEL 의미를 재현한다(메서드명 기반 default Answer 디스패처).
 *  - RDS 정본은 answerRepository.aggregatePointsByUser 의 [userId, sum] 행으로 흉내 낸다.
 *  - 테스트컨테이너/임베디드 Redis 를 추가하지 않는다.
 */
class GroupRankingServiceTest {

    private static final long GROUP = 1L;

    private GroupRankingService rankingService;

    /** key -> (member -> score) — Redis ZSet 인메모리 fake */
    private final Map<String, Map<Object, Double>> store = new LinkedHashMap<>();
    /** key -> ttl seconds (없으면 -1 = persist 레거시) */
    private final Map<String, Long> ttl = new LinkedHashMap<>();
    /** Redis 장애 시뮬레이션 */
    private final AtomicBoolean redisDown = new AtomicBoolean(false);
    /** RDS 정본 [userId, points] */
    private final List<Object[]> rds = new ArrayList<>();
    private final AtomicInteger rdsQueries = new AtomicInteger();
    private final AtomicInteger redisReads = new AtomicInteger();

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        store.clear();
        ttl.clear();
        rds.clear();
        redisDown.set(false);
        rdsQueries.set(0);
        redisReads.set(0);

        ZSetOperations<String, Object> zset = mock(ZSetOperations.class, invocation -> {
            if (redisDown.get()) throw new IllegalStateException("redis down");
            String method = invocation.getMethod().getName();
            Object[] args = invocation.getArguments();
            switch (method) {
                case "add": { // ZADD key Set<TypedTuple>
                    String key = (String) args[0];
                    Map<Object, Double> m = store.computeIfAbsent(key, k -> new LinkedHashMap<>());
                    if (args[1] instanceof Set<?> tuples) {
                        for (Object o : tuples) {
                            ZSetOperations.TypedTuple<Object> t = (ZSetOperations.TypedTuple<Object>) o;
                            m.put(t.getValue(), t.getScore());
                        }
                        return (long) tuples.size();
                    }
                    m.put(args[1], ((Number) args[2]).doubleValue());
                    return Boolean.TRUE;
                }
                case "reverseRangeWithScores": {
                    redisReads.incrementAndGet();
                    Map<Object, Double> m = store.get((String) args[0]);
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
            if (redisDown.get()) throw new IllegalStateException("redis down");
            Object[] args = invocation.getArguments();
            switch (invocation.getMethod().getName()) {
                case "opsForZSet":
                    return zset;
                case "getExpire": { // TTL: -2 없음, -1 persist, >0 남은 초
                    String key = (String) args[0];
                    if (!store.containsKey(key)) return -2L;
                    return ttl.getOrDefault(key, -1L);
                }
                case "expire": {
                    String key = (String) args[0];
                    if (!store.containsKey(key)) return Boolean.FALSE;
                    ttl.put(key, ((java.time.Duration) args[1]).getSeconds());
                    return Boolean.TRUE;
                }
                case "rename": {
                    String from = (String) args[0], to = (String) args[1];
                    store.put(to, store.remove(from));
                    ttl.put(to, ttl.remove(from));
                    return null;
                }
                case "delete": {
                    String key = (String) args[0];
                    ttl.remove(key);
                    return store.remove(key) != null;
                }
                default:
                    return null;
            }
        });

        GroupStudyQuizSessionAnswerRepository answers = mock(GroupStudyQuizSessionAnswerRepository.class);
        when(answers.aggregatePointsByUser(anyLong())).thenAnswer(inv -> {
            rdsQueries.incrementAndGet();
            return GROUP == ((Long) inv.getArgument(0)) ? new ArrayList<>(rds) : List.of();
        });

        rankingService = new GroupRankingService(redisTemplate, answers);
    }

    private void rds(long userId, long points) {
        rds.add(new Object[]{userId, points});
    }

    private String key() {
        return "groupstudy:ranking:" + GROUP;
    }

    // ── miss → RDS 재구축 ──────────────────────────────────────────────────────

    @Test
    void miss_rebuildsFromRdsAndCachesWithTtl() {
        rds(100L, 22L);
        rds(200L, 5L);

        GroupRankingService.PointsSnapshot snap = rankingService.read(GROUP);

        assertEquals(GroupRankingService.Source.REBUILT, snap.source());
        assertEquals(22, snap.points().get(100L));
        assertEquals(5, snap.points().get(200L));
        assertEquals(1, rdsQueries.get());
        assertTrue(store.containsKey(key()), "재구축된 키가 존재해야 한다");
        assertFalse(store.containsKey(key() + ":rebuild"), "임시 키는 RENAME 으로 사라져야 한다");
        assertEquals(GroupRankingService.TTL_HOURS * 3600, ttl.get(key()));
        // Redis 에 저장된 member 는 기존 컨벤션(String userId) 을 유지한다
        assertEquals(22.0, store.get(key()).get("100"));
    }

    // ── hit → RDS 미조회 ──────────────────────────────────────────────────────

    @Test
    void hit_servesFromRedisWithoutRds() {
        rds(100L, 22L);
        rankingService.read(GROUP); // warm
        rdsQueries.set(0);

        GroupRankingService.PointsSnapshot snap = rankingService.read(GROUP);

        assertEquals(GroupRankingService.Source.REDIS, snap.source());
        assertEquals(22, snap.points().get(100L));
        assertEquals(0, rdsQueries.get(), "캐시 hit 이면 RDS 를 치지 않는다");
        assertEquals(22, rankingService.getPoints(GROUP, 100L));
        assertEquals(0, rankingService.getPoints(GROUP, 777L));
        assertEquals(0, rankingService.getPoints(2L, 100L));
    }

    // ── 레거시 키(TTL 없음, ZINCRBY 시대 drift) → RDS 로 교정 ──────────────────

    @Test
    void legacyKeyWithoutTtl_isRepairedFromRds() {
        // 운영에서 실제로 관측된 상태: Redis 에는 user 8=13 만 남고 user 1=54 는 유실됨
        store.put(key(), new LinkedHashMap<>(Map.of("8", 13.0)));
        rds(1L, 54L);
        rds(8L, 13L);

        GroupRankingService.PointsSnapshot snap = rankingService.read(GROUP);

        assertEquals(GroupRankingService.Source.REBUILT, snap.source());
        assertEquals(54, snap.points().get(1L));
        assertEquals(13, snap.points().get(8L));
        assertTrue(ttl.get(key()) > 0, "교정 후에는 TTL 이 걸려야 한다");
    }

    // ── Redis 유실 후 RDS 로 재생성 가능 ────────────────────────────────────────

    @Test
    void redisFlushed_rankingIsRegeneratedIdentically() {
        rds(1L, 54L);
        rds(8L, 13L);
        List<GroupRankingService.RankingEntry> before = rankingService.getRanking(GROUP);

        store.clear(); // FLUSHALL
        ttl.clear();

        List<GroupRankingService.RankingEntry> after = rankingService.getRanking(GROUP);
        assertEquals(before, after);
        assertEquals(1L, after.get(0).userId());
        assertEquals(54, after.get(0).points());
        assertEquals(8L, after.get(1).userId());
    }

    // ── Redis 장애 → RDS fallback + dirty → 복구 후 재구축 ─────────────────────

    @Test
    void redisDown_fallsBackToRdsAndRebuildsAfterRecovery() {
        rds(100L, 30L);
        redisDown.set(true);

        GroupRankingService.PointsSnapshot snap = rankingService.read(GROUP);
        assertEquals(GroupRankingService.Source.RDS_FALLBACK, snap.source());
        assertEquals(30, snap.points().get(100L));
        assertTrue(rankingService.isDirty(GROUP));
        assertEquals(30, rankingService.getPoints(GROUP, 100L), "장애 중에도 점수는 RDS 값으로 응답");

        redisDown.set(false);
        GroupRankingService.PointsSnapshot recovered = rankingService.read(GROUP);
        assertEquals(GroupRankingService.Source.REBUILT, recovered.source());
        assertFalse(rankingService.isDirty(GROUP));
        assertTrue(store.containsKey(key()));
    }

    @Test
    void rebuildFailure_keepsRdsValuesAndMarksDirty() {
        rds(100L, 30L);
        redisDown.set(true);

        Map<Long, Integer> scores = rankingService.rebuild(GROUP);

        assertEquals(30, scores.get(100L), "Redis 실패와 무관하게 RDS 값을 돌려준다");
        assertTrue(rankingService.isDirty(GROUP));
        assertFalse(store.containsKey(key()));
    }

    // ── 커밋 후 refresh(트랜잭션 밖이면 즉시) ───────────────────────────────────

    @Test
    void refreshAfterCommit_outsideTransaction_rebuildsImmediately() {
        rds(100L, 10L);
        rankingService.read(GROUP); // warm: 100 → 10
        rds.clear();                // 채점 커밋 후 RDS 집계: 100 → 17, 200 → 3
        rds(100L, 17L);
        rds(200L, 3L);

        rankingService.refreshAfterCommit(GROUP);

        GroupRankingService.PointsSnapshot snap = rankingService.read(GROUP);
        assertEquals(GroupRankingService.Source.REDIS, snap.source());
        assertEquals(17, snap.points().get(100L));
        assertEquals(3, snap.points().get(200L));
    }

    // ── 점수 없음 → 키 없음(매번 RDS, 캐시 오염 없음) ─────────────────────────

    @Test
    void noScores_returnsEmptyAndLeavesNoKey() {
        GroupRankingService.PointsSnapshot snap = rankingService.read(GROUP);
        assertTrue(snap.points().isEmpty());
        assertFalse(store.containsKey(key()));
        assertTrue(rankingService.getRanking(GROUP).isEmpty());
    }

    // ── 정렬 ──────────────────────────────────────────────────────────────────

    @Test
    void getRanking_isSortedByScoreDescendingThenUserIdAsc() {
        rds(1L, 10L);
        rds(2L, 30L);
        rds(3L, 20L);
        rds(4L, 20L);

        List<GroupRankingService.RankingEntry> ranking = rankingService.getRanking(GROUP);

        assertEquals(List.of(2L, 3L, 4L, 1L), ranking.stream().map(GroupRankingService.RankingEntry::userId).toList());
        assertEquals(List.of(30, 20, 20, 10), ranking.stream().map(GroupRankingService.RankingEntry::points).toList());
    }

    // ── 그룹 삭제 → 키 정리, 이후 조회는 RDS(빈) ──────────────────────────────

    @Test
    void clearRanking_removesKeyAndStaleRankingDoesNotSurvive() {
        rds(1L, 10L);
        rankingService.read(GROUP);
        assertTrue(store.containsKey(key()));

        rankingService.clearRanking(GROUP);
        rds.clear(); // 그룹 삭제로 RDS 답안도 함께 정리됨

        assertFalse(store.containsKey(key()));
        assertEquals(0, rankingService.getPoints(GROUP, 1L));
        assertTrue(rankingService.getRanking(GROUP).isEmpty());
    }

    @Test
    void clearRanking_whenRedisDown_doesNotThrow() {
        redisDown.set(true);
        rankingService.clearRanking(GROUP); // 그룹 삭제 트랜잭션을 깨지 않는다
    }
}
