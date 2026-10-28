package com.studybridge.api.service;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.connection.StringRedisConnection;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.serializer.StringRedisSerializer;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * 자료 퀴즈(MaterialQuiz) 서버 채점 점수 + 퀴즈별 랭킹 저장소 — Redis.
 *
 * <ul>
 *   <li>{@code studybridge:quiz:{quizId}:scores} HASH(field = userId, value = JSON {@link StoredScore}) — 최근 제출(재채점용 선택 답안)과
 *       최고점(bestScore·bestCorrectCount·bestAt)·응시 횟수(attempt). 값은 기존과 같은 RedisTemplate 직렬화(JSON 문자열을 한 번 더 감싼 형태).</li>
 *   <li>{@code studybridge:quiz:{quizId}:ranking} ZSET(member = userId, score = {@link #composite}) — 최고점 내림차순, 동점은 먼저 도달한 사람 우선.</li>
 * </ul>
 *
 * <p>제출 기록은 Lua 스크립트 하나로 원자 처리한다: 응시 횟수 증가 · 최고점 비교/갱신 · ZSET 갱신(ZADD GT) · 두 키 TTL ·
 * 같은 답안의 짧은 시간 내 중복 제출 무시. 낮은 점수 재응시는 최고점·순위를 바꾸지 않는다.</p>
 *
 * <p>ZSET 점수 인코딩: {@code bestScore × 2^42 + (2^42 − 1 − (bestAt − 2020-01-01T00:00Z) ms)}. 최댓값 101·2^42 ≈ 4.4e14 < 2^53 이라 double 로
 * 정확히 표현되고(정밀도 손실 없음), 시간은 UTC epoch ms 라 서버 시간대와 무관하다. 경쟁 순위(1,1,3)는 "점수가 더 높은 사람 수 + 1" =
 * {@code ZCOUNT [(score+1)·2^42, +inf]} + 1 로 정확히 계산한다.</p>
 *
 * <p>Redis 장애: 제출은 예외를 삼켜 persisted=false 로 응답(채점 자체는 막지 않음), 랭킹 조회는 {@link RankingUnavailableException}.
 * 기존 기록(ZSET 이전)은 랭킹 조회 시 HASH 로 ZSET 을 재구성한다(HLEN ≠ ZCARD 일 때만).</p>
 */
@Slf4j
@Service
public class MaterialQuizScoreService {

    static final String KEY_PREFIX = "studybridge:quiz:%d:scores";
    static final String RANKING_KEY_PREFIX = "studybridge:quiz:%d:ranking";

    /** 점수 자리 단위(2^42 ms ≈ 139년). */
    static final long SCORE_UNIT = 1L << 42;
    /** 시간 기준점 2020-01-01T00:00:00Z. */
    static final long EPOCH_MS = 1577836800000L;
    static final int MAX_SCORE = 100;

    /**
     * KEYS[1]=scores HASH, KEYS[2]=ranking ZSET.
     * ARGV: 1 userId, 2 기록 JSON(최근 제출), 3 score, 4 correctCount, 5 이번 제출 composite,
     *       6 이전 최고점 composite(없으면 ""), 7 TTL 초, 8 답안 지문, 9 now epoch ms, 10 중복 판정 창(ms).
     * bestAt 은 기록 JSON 의 submittedAt 값을 그대로 복사한다(ObjectMapper 직렬화 형식 유지).
     * 반환: "attempt|improved|bestScore|duplicate"
     */
    static final String RECORD_LUA = String.join("\n",
            "local raw = redis.call('HGET', KEYS[1], ARGV[1])",
            "local prev = nil",
            "if raw then",
            "  local ok, v = pcall(cjson.decode, raw)",
            "  if ok and type(v) == 'string' then ok, v = pcall(cjson.decode, v) end",
            "  if ok and type(v) == 'table' then prev = v end",
            "end",
            "local attempt, best, bestCorrect, bestAt = 0, -1, nil, nil",
            "if prev then",
            "  attempt = tonumber(prev.attempt) or 0",
            "  if prev.bestScore ~= nil and prev.bestScore ~= cjson.null then",
            "    best = tonumber(prev.bestScore) or -1; bestCorrect = prev.bestCorrectCount; bestAt = prev.bestAt",
            "  elseif prev.score ~= nil and prev.score ~= cjson.null then",
            "    best = tonumber(prev.score) or -1; bestCorrect = prev.correctCount; bestAt = prev.submittedAt",
            "  end",
            "  local lastAt = tonumber(prev.submittedAtEpochMs)",
            "  if prev.answerFingerprint == ARGV[8] and lastAt and (tonumber(ARGV[9]) - lastAt) >= 0",
            "     and (tonumber(ARGV[9]) - lastAt) < tonumber(ARGV[10]) then",
            "    return attempt .. '|0|' .. best .. '|1'",
            "  end",
            "end",
            "local rec = cjson.decode(ARGV[2])",
            "if type(rec.selected) == 'table' and next(rec.selected) == nil then rec.selected = nil end",
            "attempt = attempt + 1",
            "rec.attempt = attempt",
            "local score = tonumber(ARGV[3])",
            "local improved = 0",
            "if score > best then best = score; bestCorrect = tonumber(ARGV[4]); bestAt = rec.submittedAt; improved = 1 end",
            "rec.bestScore = best; rec.bestCorrectCount = bestCorrect; rec.bestAt = bestAt",
            "rec.answerFingerprint = ARGV[8]; rec.submittedAtEpochMs = tonumber(ARGV[9])",
            "redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(cjson.encode(rec)))",
            "if improved == 1 then",
            "  redis.call('ZADD', KEYS[2], 'GT', ARGV[5], ARGV[1])",
            "elseif redis.call('ZSCORE', KEYS[2], ARGV[1]) == false and ARGV[6] ~= '' then",
            "  redis.call('ZADD', KEYS[2], 'GT', ARGV[6], ARGV[1])",
            "end",
            "redis.call('EXPIRE', KEYS[1], ARGV[7])",
            "redis.call('EXPIRE', KEYS[2], ARGV[7])",
            "return attempt .. '|' .. improved .. '|' .. best .. '|0'");

    private static final DefaultRedisScript<String> RECORD_SCRIPT = new DefaultRedisScript<>(RECORD_LUA, String.class);

    private final RedisTemplate<String, Object> redisTemplate;
    private final StringRedisTemplate stringRedisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration ttl;
    private final long duplicateWindowMs;
    private final ZoneId zone;

    public MaterialQuizScoreService(RedisTemplate<String, Object> redisTemplate, StringRedisTemplate stringRedisTemplate,
                                    ObjectMapper objectMapper,
                                    @Value("${ai.quiz.score-ttl-days:180}") long ttlDays,
                                    @Value("${ai.quiz.duplicate-submit-window-ms:3000}") long duplicateWindowMs) {
        this.redisTemplate = redisTemplate;
        this.stringRedisTemplate = stringRedisTemplate;
        this.objectMapper = objectMapper;
        this.ttl = Duration.ofDays(Math.max(1, ttlDays));
        this.duplicateWindowMs = Math.max(0, duplicateWindowMs);
        this.zone = ZoneId.systemDefault();
    }

    public static String scoreKey(Long quizId) {
        return String.format(KEY_PREFIX, quizId);
    }

    public static String rankingKey(Long quizId) {
        return String.format(RANKING_KEY_PREFIX, quizId);
    }

    /** Redis 에 저장되는 값. 정답 키 없음. 최고점 필드는 하위 호환(이전 기록은 null → score 를 최고점으로 본다). */
    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class StoredScore {
        private Long quizId;
        private Long userId;
        private Integer score;
        private Integer correctCount;
        private Integer totalQuestions;
        private Integer answeredCount;
        private Integer attempt;
        private LocalDateTime submittedAt;
        /** questionId → selectedOptionId (사용자 선택만). */
        @Builder.Default
        private Map<String, String> selected = new LinkedHashMap<>();
        private Integer bestScore;
        private Integer bestCorrectCount;
        private LocalDateTime bestAt;
        private String answerFingerprint;
        private Long submittedAtEpochMs;

        public int effectiveBestScore() {
            return bestScore != null ? bestScore : score != null ? score : 0;
        }

        public Integer effectiveBestCorrect() {
            return bestScore != null ? bestCorrectCount : correctCount;
        }

        public LocalDateTime effectiveBestAt() {
            return bestScore != null ? bestAt : submittedAt;
        }
    }

    /** 제출 기록 결과. persisted=false 면 Redis 장애로 저장하지 못한 것(채점 결과는 유효). */
    public record RecordOutcome(boolean persisted, int attempt, boolean improved, int bestScore, boolean duplicate) {}

    /** 퀴즈별 랭킹 원자료(사용자 식별자는 이 계층까지만, API 응답에는 내보내지 않는다). */
    public record RankedUser(long userId, int rank, StoredScore score) {}

    public record RankingSnapshot(long totalParticipants, List<RankedUser> top, RankedUser me) {}

    /** Redis 를 쓸 수 없어 랭킹을 만들 수 없음 → 503 RANKING_UNAVAILABLE. */
    public static class RankingUnavailableException extends RuntimeException {
        public RankingUnavailableException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    // ───────────────────────── 인코딩 ─────────────────────────

    /** ZSET 점수 = 최고점 × 2^42 + 시간 역순(먼저 달성할수록 큼). 정수 < 2^53 이라 double 정확 표현. */
    static long composite(int score, long achievedAtEpochMs) {
        int s = Math.max(0, Math.min(MAX_SCORE, score));
        long elapsed = Math.max(0, Math.min(SCORE_UNIT - 1, achievedAtEpochMs - EPOCH_MS));
        return s * SCORE_UNIT + (SCORE_UNIT - 1 - elapsed);
    }

    static int scoreOf(double composite) {
        return (int) (((long) composite) / SCORE_UNIT);
    }

    static long achievedAtOf(double composite) {
        return EPOCH_MS + (SCORE_UNIT - 1 - (((long) composite) % SCORE_UNIT));
    }

    /** 답안 지문(문항 순서 무관). 같은 답안의 연속 제출(중복 클릭·재전송) 판정용. */
    static String fingerprint(Map<String, String> selected) {
        try {
            String canonical = new TreeMap<>(selected == null ? Map.of() : selected).toString();
            byte[] d = MessageDigest.getInstance("SHA-256").digest(canonical.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(d, 0, 12);
        } catch (Exception e) {
            return "";
        }
    }

    private long epochMs(LocalDateTime t) {
        return t == null ? EPOCH_MS : t.atZone(zone).toInstant().toEpochMilli();
    }

    // ───────────────────────── 쓰기 ─────────────────────────

    /**
     * 제출 1건을 원자 기록한다. score 의 attempt/best 필드는 스크립트가 채운다.
     * Redis 장애는 로그만 남기고 persisted=false(채점 응답은 막지 않는다).
     */
    public RecordOutcome record(StoredScore score, Instant now) {
        if (score == null || score.getQuizId() == null || score.getUserId() == null) {
            return new RecordOutcome(false, 1, false, 0, false);
        }
        int value = score.getScore() == null ? 0 : score.getScore();
        try {
            StoredScore previous = find(score.getQuizId(), score.getUserId());
            String prevComposite = previous == null ? ""
                    : String.valueOf(composite(previous.effectiveBestScore(), epochMs(previous.effectiveBestAt())));
            StoredScore toWrite = StoredScore.builder()
                    .quizId(score.getQuizId()).userId(score.getUserId()).score(value)
                    .correctCount(score.getCorrectCount()).totalQuestions(score.getTotalQuestions())
                    .answeredCount(score.getAnsweredCount()).submittedAt(score.getSubmittedAt())
                    .selected(score.getSelected() == null ? new LinkedHashMap<>() : score.getSelected())
                    .build();
            String fp = fingerprint(score.getSelected());
            String raw = redisTemplate.execute(RECORD_SCRIPT, StringRedisSerializer.UTF_8, StringRedisSerializer.UTF_8,
                    List.of(scoreKey(score.getQuizId()), rankingKey(score.getQuizId())),
                    String.valueOf(score.getUserId()),
                    objectMapper.writeValueAsString(toWrite),
                    String.valueOf(value),
                    String.valueOf(score.getCorrectCount() == null ? 0 : score.getCorrectCount()),
                    String.valueOf(composite(value, now.toEpochMilli())),
                    prevComposite,
                    String.valueOf(ttl.toSeconds()),
                    fp,
                    String.valueOf(now.toEpochMilli()),
                    String.valueOf(duplicateWindowMs));
            String[] parts = raw == null ? new String[0] : raw.split("\\|");
            if (parts.length != 4) throw new IllegalStateException("unexpected script result: " + raw);
            return new RecordOutcome(true, Integer.parseInt(parts[0]), "1".equals(parts[1]),
                    (int) Double.parseDouble(parts[2]), "1".equals(parts[3]));
        } catch (Exception e) {
            log.error("[QUIZ_SCORE] redis record failed quizId={} userId={}", score.getQuizId(), score.getUserId(), e);
            return new RecordOutcome(false, 1, false, value, false);
        }
    }

    /** 하위 호환: 현재 시각으로 기록하고 저장 성공 여부만 돌려준다. */
    public boolean save(StoredScore score) {
        return record(score, Instant.now()).persisted();
    }

    public StoredScore find(Long quizId, Long userId) {
        if (quizId == null || userId == null) return null;
        try {
            return parse(redisTemplate.opsForHash().get(scoreKey(quizId), String.valueOf(userId)));
        } catch (Exception e) {
            log.error("[QUIZ_SCORE] redis read failed quizId={} userId={}", quizId, userId, e);
            return null;
        }
    }

    private StoredScore parse(Object v) throws Exception {
        if (v == null) return null;
        if (v instanceof StoredScore s) return s;
        String json = v instanceof String str ? str : objectMapper.writeValueAsString(v);
        return objectMapper.readValue(json, StoredScore.class);
    }

    /** 퀴즈 삭제 시 점수 HASH + 랭킹 ZSET 제거(DEL 1회). Redis 장애는 로그만. */
    public void deleteForQuiz(Long quizId) {
        if (quizId == null) return;
        try {
            redisTemplate.delete(List.of(scoreKey(quizId), rankingKey(quizId)));
        } catch (Exception e) {
            log.error("[QUIZ_SCORE] redis delete failed quizId={}", quizId, e);
        }
    }

    public void deleteForQuizzes(Collection<Long> quizIds) {
        if (quizIds == null) return;
        for (Long id : quizIds) deleteForQuiz(id);
    }

    // ───────────────────────── 랭킹 읽기 ─────────────────────────

    /**
     * 상위 limit 명 + 요청자. Redis 호출: (ZCARD·HLEN·ZREVRANGE·ZSCORE) 파이프라인 1회 + HMGET 1회 + (요청자가 상위 밖이면) ZCOUNT 1회.
     * 경쟁 순위(1,1,3): 같은 최고점은 같은 rank, 표시 순서는 먼저 달성한 사람 우선.
     */
    public RankingSnapshot ranking(Long quizId, Long meUserId, int limit) {
        String zkey = rankingKey(quizId);
        String hkey = scoreKey(quizId);
        try {
            List<Object> head = pipelineHead(zkey, hkey, limit, meUserId);
            long zcard = toLong(head.get(0));
            long hlen = toLong(head.get(1));
            if (zcard != hlen) {
                reconcile(quizId);
                head = pipelineHead(zkey, hkey, limit, meUserId);
                zcard = toLong(head.get(0));
            }
            @SuppressWarnings("unchecked")
            Set<ZSetOperations.TypedTuple<String>> top = (Set<ZSetOperations.TypedTuple<String>>) head.get(2);
            Double meComposite = head.get(3) instanceof Double d ? d : null;

            List<String> ids = new ArrayList<>();
            List<Double> composites = new ArrayList<>();
            if (top != null) {
                for (ZSetOperations.TypedTuple<String> t : top) {
                    if (t.getValue() == null || t.getScore() == null) continue;
                    ids.add(t.getValue());
                    composites.add(t.getScore());
                }
            }
            String meId = meUserId == null ? null : String.valueOf(meUserId);
            boolean meInTop = meId != null && ids.contains(meId);
            List<Object> fields = new ArrayList<>(ids);
            if (meComposite != null && !meInTop) fields.add(meId);
            List<Object> values = fields.isEmpty() ? List.of() : redisTemplate.opsForHash().multiGet(hkey, fields);

            List<RankedUser> out = new ArrayList<>();
            int rank = 0;
            int prevScore = Integer.MIN_VALUE;
            for (int i = 0; i < ids.size(); i++) {
                int s = scoreOf(composites.get(i));
                if (s != prevScore) { rank = i + 1; prevScore = s; }
                out.add(new RankedUser(Long.parseLong(ids.get(i)), rank, withBest(safeParse(values.get(i)), s, composites.get(i))));
            }
            RankedUser me = null;
            if (meComposite != null) {
                if (meInTop) {
                    me = out.get(ids.indexOf(meId));
                } else {
                    int s = scoreOf(meComposite);
                    Long higher = stringRedisTemplate.opsForZSet().count(zkey, (double) ((s + 1) * SCORE_UNIT), Double.POSITIVE_INFINITY);
                    me = new RankedUser(meUserId, (int) (higher == null ? 0 : higher) + 1,
                            withBest(safeParse(values.get(values.size() - 1)), s, meComposite));
                }
            }
            return new RankingSnapshot(zcard, out, me);
        } catch (RankingUnavailableException e) {
            throw e;
        } catch (Exception e) {
            log.error("[QUIZ_RANKING] redis read failed quizId={}", quizId, e);
            throw new RankingUnavailableException("랭킹 저장소에 연결할 수 없습니다.", e);
        }
    }

    private List<Object> pipelineHead(String zkey, String hkey, int limit, Long meUserId) {
        return stringRedisTemplate.executePipelined((RedisCallback<Object>) connection -> {
            StringRedisConnection c = (StringRedisConnection) connection;
            c.zCard(zkey);
            c.hLen(hkey);
            c.zRevRangeWithScores(zkey, 0, Math.max(0, limit - 1));
            c.zScore(zkey, meUserId == null ? "" : String.valueOf(meUserId));
            return null;
        });
    }

    /** ZSET 값이 정본이 되도록 최고점·달성 시각을 보정(기존 기록은 bestScore 가 없으므로). */
    private StoredScore withBest(StoredScore s, int score, double composite) {
        StoredScore r = s != null ? s : new StoredScore();
        if (r.getBestScore() == null) {
            r.setBestScore(score);
            if (r.getBestCorrectCount() == null) r.setBestCorrectCount(r.getCorrectCount());
        }
        if (r.getBestAt() == null) r.setBestAt(LocalDateTime.ofInstant(Instant.ofEpochMilli(achievedAtOf(composite)), zone));
        return r;
    }

    private StoredScore safeParse(Object v) {
        try {
            return parse(v);
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * HASH(정본 기록) → ZSET 재구성. ZADD GT 라 동시 제출로 더 높은 값이 이미 있으면 유지되고, HASH 에 없는 member 는 제거한다.
     * ZSET TTL 은 HASH 의 남은 TTL 에 맞춘다.
     */
    void reconcile(Long quizId) {
        String hkey = scoreKey(quizId);
        String zkey = rankingKey(quizId);
        Map<Object, Object> all = redisTemplate.opsForHash().entries(hkey);
        Set<String> members = new HashSet<>();
        for (Map.Entry<Object, Object> e : all.entrySet()) {
            StoredScore s = safeParse(e.getValue());
            if (s == null) continue;
            String member = String.valueOf(e.getKey());
            members.add(member);
            long c = composite(s.effectiveBestScore(), epochMs(s.effectiveBestAt()));
            stringRedisTemplate.execute((RedisCallback<Object>) conn ->
                    conn.zSetCommands().zAdd(zkey.getBytes(StandardCharsets.UTF_8), c,
                            member.getBytes(StandardCharsets.UTF_8),
                            org.springframework.data.redis.connection.RedisZSetCommands.ZAddArgs.empty().gt()));
        }
        Set<String> existing = stringRedisTemplate.opsForZSet().range(zkey, 0, -1);
        if (existing != null) {
            for (String m : existing) if (!members.contains(m)) stringRedisTemplate.opsForZSet().remove(zkey, m);
        }
        Long pttl = stringRedisTemplate.getExpire(hkey, java.util.concurrent.TimeUnit.MILLISECONDS);
        if (pttl != null && pttl > 0) stringRedisTemplate.expire(zkey, Duration.ofMillis(pttl));
        log.info("[QUIZ_RANKING] reconciled quizId={} members={}", quizId, members.size());
    }

    private static long toLong(Object o) {
        return o instanceof Number n ? n.longValue() : 0L;
    }
}
