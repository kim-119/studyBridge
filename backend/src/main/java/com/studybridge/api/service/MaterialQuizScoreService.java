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
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 자료 퀴즈(MaterialQuiz) 서버 채점 점수 저장소 — Redis.
 *
 * <p>키: {@code studybridge:quiz:{quizId}:scores} (HASH, field = userId, value = JSON {@link StoredScore}).
 * 기존 컨벤션({@code studybridge:{domain}:{id}:...}, RedisChatService) 을 따르며 groupstudy:ranking 과 겹치지 않는다.
 * 퀴즈 1개 = 키 1개 이므로 퀴즈/자료 삭제 시 {@code DEL} 한 번으로 모든 사용자의 점수가 정리된다(KEYS 스캔 불필요).</p>
 *
 * <p>정책: 재응시 허용 → 같은 (quizId,userId) 는 최신 제출이 덮어쓰고 attempt 만 누적한다. 정답 키는 저장하지 않고
 * 사용자가 고른 optionId 만 저장한다(재조회 시 DB 정답 키로 다시 채점). TTL 은 안전장치(기본 180일, 쓰기마다 갱신).
 * Redis 장애 시 예외를 삼키고 false 를 돌려주어 채점 응답 자체는 막지 않는다(GroupRankingService 와 같은 패턴).</p>
 */
@Slf4j
@Service
public class MaterialQuizScoreService {

    static final String KEY_PREFIX = "studybridge:quiz:%d:scores";

    private final RedisTemplate<String, Object> redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration ttl;

    public MaterialQuizScoreService(RedisTemplate<String, Object> redisTemplate, ObjectMapper objectMapper,
                                    @Value("${ai.quiz.score-ttl-days:180}") long ttlDays) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.ttl = Duration.ofDays(Math.max(1, ttlDays));
    }

    public static String scoreKey(Long quizId) {
        return String.format(KEY_PREFIX, quizId);
    }

    /** Redis 에 저장되는 값. 정답 키 없음. */
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
    }

    /** @return 저장 성공 여부. */
    public boolean save(StoredScore score) {
        if (score == null || score.getQuizId() == null || score.getUserId() == null) return false;
        String key = scoreKey(score.getQuizId());
        try {
            redisTemplate.opsForHash().put(key, String.valueOf(score.getUserId()), objectMapper.writeValueAsString(score));
            redisTemplate.expire(key, ttl);
            return true;
        } catch (Exception e) {
            log.error("[QUIZ_SCORE] redis save failed quizId={} userId={}", score.getQuizId(), score.getUserId(), e);
            return false;
        }
    }

    public StoredScore find(Long quizId, Long userId) {
        if (quizId == null || userId == null) return null;
        try {
            Object v = redisTemplate.opsForHash().get(scoreKey(quizId), String.valueOf(userId));
            if (v == null) return null;
            if (v instanceof StoredScore) return (StoredScore) v;
            String json = v instanceof String ? (String) v : objectMapper.writeValueAsString(v);
            return objectMapper.readValue(json, StoredScore.class);
        } catch (Exception e) {
            log.error("[QUIZ_SCORE] redis read failed quizId={} userId={}", quizId, userId, e);
            return null;
        }
    }

    /** 퀴즈 삭제 시 점수 키 제거(DEL 1회). Redis 장애는 로그만. */
    public void deleteForQuiz(Long quizId) {
        if (quizId == null) return;
        try {
            redisTemplate.delete(scoreKey(quizId));
        } catch (Exception e) {
            log.error("[QUIZ_SCORE] redis delete failed quizId={}", quizId, e);
        }
    }

    public void deleteForQuizzes(Collection<Long> quizIds) {
        if (quizIds == null) return;
        for (Long id : quizIds) deleteForQuiz(id);
    }
}
