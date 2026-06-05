package com.studybridge.api.service;

import com.studybridge.api.dto.RedisChatMessage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.List;

@Service
@RequiredArgsConstructor
@Slf4j
public class RedisChatService {

    private final RedisTemplate<String, Object> redisTemplate;
    private static final String KEY_PREFIX = "studybridge:group:%d:chats";

    private String getRedisKey(Long groupId) {
        return String.format(KEY_PREFIX, groupId);
    }

    /**
     * 특정 그룹 스터디 대화 내역에 새 메시지를 캐싱합니다.
     * 최근 100개까지만 보관하도록 Trimming(슬라이딩 윈도우)을 수행합니다.
     */
    public void saveMessage(Long groupId, RedisChatMessage message) {
        String key = getRedisKey(groupId);
        try {
            redisTemplate.opsForList().rightPush(key, message);
            
            // 크기 확인 후 100개 초과 시 가장 오래된 것(좌측) 제거
            Long size = redisTemplate.opsForList().size(key);
            if (size != null && size > 100) {
                redisTemplate.opsForList().leftPop(key);
            }
            log.info("Message cached to Redis for groupId={}, size={}", groupId, size);
        } catch (Exception e) {
            log.error("Failed to cache message in Redis for groupId={}", groupId, e);
        }
    }

    /**
     * 최근 100개의 대화 이력을 조회합니다 (시간순: 오래된 것 -> 최신 순).
     */
    @SuppressWarnings("unchecked")
    public List<RedisChatMessage> getRecentHistory(Long groupId) {
        String key = getRedisKey(groupId);
        try {
            List<Object> range = redisTemplate.opsForList().range(key, 0, -1);
            if (range == null || range.isEmpty()) {
                return Collections.emptyList();
            }
            // 형변환
            return (List<RedisChatMessage>) (List<?>) range;
        } catch (Exception e) {
            log.error("Failed to retrieve chat history from Redis for groupId={}", groupId, e);
            return Collections.emptyList();
        }
    }

    /**
     * 특정 스터디룸의 Redis 대화 캐시를 초기화합니다.
     */
    public void clearHistory(Long groupId) {
        String key = getRedisKey(groupId);
        try {
            redisTemplate.delete(key);
            log.info("Redis chat cache cleared for groupId={}", groupId);
        } catch (Exception e) {
            log.error("Failed to clear Redis chat cache for groupId={}", groupId, e);
        }
    }
}
