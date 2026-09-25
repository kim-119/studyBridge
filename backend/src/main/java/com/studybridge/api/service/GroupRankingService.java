package com.studybridge.api.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;

/**
 * 그룹스터디 퀴즈 랭킹 SoT(Source of Truth) — Redis Sorted Set 기반.
 *
 * <p>키: {@code groupstudy:ranking:{groupId}}, member: {@code String.valueOf(userId)}, score: 누적 points.
 * 포인트 적립은 {@link #addPoints(Long, Long, int)} 의 {@code ZINCRBY}(incrementScore) 단일 경로만 사용해
 * 동시 채점 안전성을 Redis 원자 연산에 위임한다. 세션/퀴즈 단위가 아니라 groupId 단위 누적이므로
 * 이전 퀴즈에서 쌓인 랭킹이 다음 퀴즈로 그대로 이어진다(이전 퀴즈 랭킹 보존).</p>
 *
 * <p>Redis 장애가 나도 퀴즈 진행 자체는 깨지지 않도록 모든 호출을 try-catch 로 감싼다.
 * 조회 메서드는 장애 시 0 또는 empty list 를 반환하며, DB fallback 은 하지 않는다.
 * 예외 처리/로깅 패턴은 {@link RedisChatService} 를 따른다.</p>
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class GroupRankingService {

    private final RedisTemplate<String, Object> redisTemplate;

    private static final String KEY_PREFIX = "groupstudy:ranking:%d";

    private String rankingKey(Long groupId) {
        return String.format(KEY_PREFIX, groupId);
    }

    /**
     * userId 의 누적 점수에 delta 를 더한다(원자적 ZINCRBY). 유일한 점수 쓰기 경로.
     * Redis 장애 시에는 로그만 남기고 조용히 넘어가 퀴즈 진행을 막지 않는다(DB fallback 없음).
     */
    public void addPoints(Long groupId, Long userId, int delta) {
        if (groupId == null || userId == null) {
            return;
        }
        String key = rankingKey(groupId);
        try {
            Double newScore = redisTemplate.opsForZSet().incrementScore(key, String.valueOf(userId), delta);
            log.debug("Ranking incremented. groupId={}, userId={}, delta={}, newScore={}", groupId, userId, delta, newScore);
        } catch (Exception e) {
            log.error("Failed to increment ranking in Redis for groupId={}, userId={}", groupId, userId, e);
        }
    }

    /**
     * userId 의 현재 누적 점수. member 가 없으면 0, Redis 장애 시에도 0 을 반환한다.
     * 반환 타입은 프론트 계약(points: int)에 맞춰 int.
     */
    public int getPoints(Long groupId, Long userId) {
        if (groupId == null || userId == null) {
            return 0;
        }
        String key = rankingKey(groupId);
        try {
            Double score = redisTemplate.opsForZSet().score(key, String.valueOf(userId));
            return score != null ? (int) Math.round(score) : 0;
        } catch (Exception e) {
            log.error("Failed to read ranking score from Redis for groupId={}, userId={}", groupId, userId, e);
            return 0;
        }
    }

    /**
     * 그룹의 전체 랭킹(점수 내림차순). Redis 장애 시 empty list.
     */
    public List<RankingEntry> getRanking(Long groupId) {
        if (groupId == null) {
            return Collections.emptyList();
        }
        String key = rankingKey(groupId);
        try {
            Set<ZSetOperations.TypedTuple<Object>> tuples =
                    redisTemplate.opsForZSet().reverseRangeWithScores(key, 0, -1);
            if (tuples == null || tuples.isEmpty()) {
                return Collections.emptyList();
            }
            List<RankingEntry> ranking = new ArrayList<>(tuples.size());
            for (ZSetOperations.TypedTuple<Object> tuple : tuples) {
                Object value = tuple.getValue();
                Double score = tuple.getScore();
                if (value == null) {
                    continue;
                }
                try {
                    Long userId = Long.parseLong(String.valueOf(value));
                    int points = score != null ? (int) Math.round(score) : 0;
                    ranking.add(new RankingEntry(userId, points));
                } catch (NumberFormatException ex) {
                    log.warn("Skipping malformed ranking member for groupId={}: {}", groupId, value);
                }
            }
            return ranking;
        } catch (Exception e) {
            log.error("Failed to read ranking from Redis for groupId={}", groupId, e);
            return Collections.emptyList();
        }
    }

    /**
     * 그룹 랭킹 키 삭제(그룹 삭제 시 정리). 예외는 삼키되 로그를 남겨
     * 그룹 삭제 트랜잭션이 Redis 장애로 실패하지 않게 한다.
     */
    public void clearRanking(Long groupId) {
        if (groupId == null) {
            return;
        }
        String key = rankingKey(groupId);
        try {
            redisTemplate.delete(key);
            log.info("Redis ranking cleared for groupId={}", groupId);
        } catch (Exception e) {
            log.error("Failed to clear Redis ranking for groupId={}", groupId, e);
        }
    }

    /**
     * 랭킹 1건 — userId 와 누적 points. (이전/현재 퀴즈 누적 랭킹 표현용)
     */
    public record RankingEntry(Long userId, int points) {
    }
}
