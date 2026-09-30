package com.studybridge.api.service;

import com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.DefaultTypedTuple;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 그룹스터디 퀴즈 누적 점수 — Redis Sorted Set 캐시 + RDS 정본.
 *
 * <p><b>정본(Source of Truth)은 RDS</b>({@code group_study_quiz_session_answers.points_awarded}, 채점 완료 행의 합)다.
 * Redis 는 실시간 점수판(WebSocket reveal/scoreboard) 가속용 캐시일 뿐이며, 완전히 비워져도
 * {@link #rebuild(Long)} 이 RDS 집계({@code aggregatePointsByUser})로 언제든 같은 값을 재생성한다.</p>
 *
 * <p>키: {@code groupstudy:ranking:{groupId}}(기존 컨벤션 유지), member: {@code String.valueOf(userId)}, score: 누적 점수.
 * 캐시 TTL {@value #TTL_HOURS}시간. 읽기 경로:</p>
 * <ol>
 *   <li>키가 있고 TTL 이 걸려 있으면(캐시 hit) Redis 값을 그대로 사용.</li>
 *   <li>키가 없거나(miss / 유실 / 만료) TTL 없이 남은 레거시 키(과거 ZINCRBY 시대의 drift 가능 데이터)면 RDS 로 재구축 후 사용.</li>
 *   <li>Redis 장애(예외)면 RDS 집계를 직접 반환하고 그룹을 dirty 로 표시 → 다음 읽기에서 재구축을 재시도.</li>
 * </ol>
 *
 * <p>쓰기 경로: 채점 트랜잭션(RDS commit) <b>이후</b>에만 {@link #refreshAfterCommit(Long)} 로 재구축한다.
 * 부분 실패 정합성 — RDS 커밋 성공/Redis 실패: 점수는 RDS 에 남아 있고 dirty + TTL 로 lazy recovery.
 * RDS 롤백: afterCommit 이 실행되지 않으므로 Redis 에 유령 점수가 생기지 않는다.
 * 재구축은 임시 키에 ZADD 후 RENAME 하므로 읽는 쪽이 빈 키를 보지 않는다. 그룹별 인프로세스 락으로
 * 재구축과 refresh 를 직렬화한다(운영 Spring 은 단일 인스턴스).</p>
 *
 * <p>Redis 장애가 나도 퀴즈 진행/그룹 삭제 자체는 깨지지 않도록 모든 Redis 호출을 try-catch 로 감싼다
 * (예외 처리/로깅 패턴은 {@link RedisChatService} 를 따른다).</p>
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class GroupRankingService {

    static final long TTL_HOURS = 24;
    private static final String KEY_PREFIX = "groupstudy:ranking:%d";

    private final RedisTemplate<String, Object> redisTemplate;
    private final GroupStudyQuizSessionAnswerRepository answerRepository;

    /** Redis 쓰기에 실패해 RDS 와 어긋났을 수 있는 그룹 — 다음 읽기에서 재구축한다. */
    private final Set<Long> dirtyGroups = ConcurrentHashMap.newKeySet();
    private final Map<Long, Object> groupLocks = new ConcurrentHashMap<>();

    /** 마지막 조회가 어디서 왔는지(테스트/운영 진단용). */
    public enum Source { REDIS, REBUILT, RDS_FALLBACK }

    private String rankingKey(Long groupId) {
        return String.format(KEY_PREFIX, groupId);
    }

    private Object lockFor(Long groupId) {
        return groupLocks.computeIfAbsent(groupId, k -> new Object());
    }

    // ── 읽기 ──────────────────────────────────────────────────────────────────

    /** 그룹의 사용자별 누적 점수(userId → points). 그룹 단위 Redis 1~2회 호출(N+1 없음). 항상 non-null. */
    public Map<Long, Integer> getPointsMap(Long groupId) {
        return read(groupId).points();
    }

    /** userId 의 현재 누적 점수. 없으면 0. (하위 호환 — 반복 호출 대신 {@link #getPointsMap} 사용 권장) */
    public int getPoints(Long groupId, Long userId) {
        if (groupId == null || userId == null) {
            return 0;
        }
        return getPointsMap(groupId).getOrDefault(userId, 0);
    }

    /** 그룹의 전체 랭킹(점수 내림차순, 동점은 userId 오름차순). */
    public List<RankingEntry> getRanking(Long groupId) {
        if (groupId == null) {
            return Collections.emptyList();
        }
        List<RankingEntry> ranking = new ArrayList<>();
        getPointsMap(groupId).forEach((uid, pts) -> ranking.add(new RankingEntry(uid, pts)));
        ranking.sort(Comparator.comparingInt(RankingEntry::points).reversed().thenComparing(RankingEntry::userId));
        return ranking;
    }

    /** 점수 맵 + 출처. */
    public record PointsSnapshot(Map<Long, Integer> points, Source source) {
    }

    public PointsSnapshot read(Long groupId) {
        if (groupId == null) {
            return new PointsSnapshot(Map.of(), Source.RDS_FALLBACK);
        }
        String key = rankingKey(groupId);
        try {
            if (!dirtyGroups.contains(groupId)) {
                Long ttl = redisTemplate.getExpire(key);
                // -2: 키 없음(miss/유실/만료), -1: TTL 없는 레거시 키(재구축 전 drift 가능) → 둘 다 RDS 로 재구축
                if (ttl != null && ttl > 0) {
                    Set<ZSetOperations.TypedTuple<Object>> tuples = redisTemplate.opsForZSet().reverseRangeWithScores(key, 0, -1);
                    if (tuples != null && !tuples.isEmpty()) {
                        return new PointsSnapshot(parse(groupId, tuples), Source.REDIS);
                    }
                }
            }
            Map<Long, Integer> rebuilt = rebuild(groupId);
            return new PointsSnapshot(rebuilt, Source.REBUILT);
        } catch (Exception e) {
            log.error("Failed to read ranking from Redis for groupId={} — falling back to RDS", groupId, e);
            dirtyGroups.add(groupId);
            return new PointsSnapshot(loadFromRds(groupId), Source.RDS_FALLBACK);
        }
    }

    private Map<Long, Integer> parse(Long groupId, Set<ZSetOperations.TypedTuple<Object>> tuples) {
        Map<Long, Integer> out = new LinkedHashMap<>();
        for (ZSetOperations.TypedTuple<Object> tuple : tuples) {
            Object value = tuple.getValue();
            if (value == null) {
                continue;
            }
            try {
                Long userId = Long.parseLong(String.valueOf(value));
                Double score = tuple.getScore();
                out.put(userId, score != null ? (int) Math.round(score) : 0);
            } catch (NumberFormatException ex) {
                log.warn("Skipping malformed ranking member for groupId={}: {}", groupId, value);
            }
        }
        return out;
    }

    // ── 정본(RDS) ──────────────────────────────────────────────────────────────

    /** RDS 정본 집계: 채점 완료 답안의 points_awarded 합(userId → points). Redis 를 전혀 쓰지 않는다. */
    public Map<Long, Integer> loadFromRds(Long groupId) {
        Map<Long, Integer> out = new LinkedHashMap<>();
        for (Object[] row : answerRepository.aggregatePointsByUser(groupId)) {
            Long userId = ((Number) row[0]).longValue();
            int points = row[1] == null ? 0 : (int) ((Number) row[1]).longValue();
            out.put(userId, points);
        }
        return out;
    }

    // ── 쓰기(재구축) ──────────────────────────────────────────────────────────

    /**
     * RDS 정본으로 Redis 키를 통째로 재구축(임시 키 ZADD → EXPIRE → RENAME, 점수가 없으면 DEL).
     * 반환값은 RDS 집계 결과(Redis 성공 여부와 무관). Redis 실패 시 dirty 유지 + 로그.
     */
    public Map<Long, Integer> rebuild(Long groupId) {
        synchronized (lockFor(groupId)) {
            Map<Long, Integer> scores = loadFromRds(groupId);
            String key = rankingKey(groupId);
            try {
                if (scores.isEmpty()) {
                    redisTemplate.delete(key);
                } else {
                    String tmp = key + ":rebuild";
                    Set<ZSetOperations.TypedTuple<Object>> tuples = new HashSet<>();
                    scores.forEach((uid, pts) -> tuples.add(new DefaultTypedTuple<>(String.valueOf(uid), (double) pts)));
                    redisTemplate.delete(tmp);
                    redisTemplate.opsForZSet().add(tmp, tuples);
                    redisTemplate.expire(tmp, Duration.ofHours(TTL_HOURS));
                    redisTemplate.rename(tmp, key);
                }
                dirtyGroups.remove(groupId);
                log.debug("Ranking rebuilt from RDS. groupId={}, members={}", groupId, scores.size());
            } catch (Exception e) {
                dirtyGroups.add(groupId);
                log.error("Failed to rebuild ranking in Redis for groupId={} (RDS values still authoritative)", groupId, e);
            }
            return scores;
        }
    }

    /**
     * 채점 트랜잭션 커밋 <b>후</b> Redis 캐시를 RDS 로 재구축한다. 트랜잭션 밖에서 호출되면 즉시 실행.
     * 커밋 전에 Redis 를 갱신하지 않으므로 롤백 시 유령 점수가 남지 않는다.
     */
    public void refreshAfterCommit(Long groupId) {
        if (groupId == null) {
            return;
        }
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    rebuild(groupId);
                }
            });
        } else {
            rebuild(groupId);
        }
    }

    /**
     * 그룹 랭킹 키 삭제(그룹 삭제 시 정리). 예외는 삼키되 로그를 남겨 그룹 삭제 트랜잭션이 Redis 장애로 실패하지 않게 한다.
     * 삭제 실패로 남은 고아 키는 TTL 로 자연 소멸하고, 그룹이 없으면 API 가 404 로 먼저 차단되므로 노출되지 않는다.
     */
    public void clearRanking(Long groupId) {
        if (groupId == null) {
            return;
        }
        dirtyGroups.remove(groupId);
        String key = rankingKey(groupId);
        try {
            redisTemplate.delete(key);
            redisTemplate.delete(key + ":rebuild");
            log.info("Redis ranking cleared for groupId={}", groupId);
        } catch (Exception e) {
            log.error("Failed to clear Redis ranking for groupId={}", groupId, e);
        }
    }

    boolean isDirty(Long groupId) {
        return dirtyGroups.contains(groupId);
    }

    /** 랭킹 1건 — userId 와 누적 points. */
    public record RankingEntry(Long userId, int points) {
    }
}
