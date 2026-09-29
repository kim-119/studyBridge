package com.studybridge.api.controller;

import com.studybridge.api.repository.ChatMessageRepository;
import com.studybridge.api.service.RedisChatService;
import com.studybridge.api.util.LogExecutionTime;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/test/performance")
@RequiredArgsConstructor
public class PerformanceTestController {

    private final RedisChatService redisChatService;
    private final ChatMessageRepository chatMessageRepository;
    private final com.studybridge.api.repository.UserRepository userRepository;
    private final com.studybridge.api.repository.AgentChatRoomRepository agentChatRoomRepository;
    private final org.springframework.data.redis.core.RedisTemplate<String, Object> redisTemplate;

    @GetMapping(value = "/seed", produces = "application/json;charset=UTF-8")
    public ResponseEntity<Map<String, Object>> seedData() {
        // 임의의 유저 1명 찾기
        var user = userRepository.findAll().stream().findFirst()
                .orElseThrow(() -> new RuntimeException("DB에 유저가 한 명도 없습니다!"));

        // 임시 채팅방 생성
        var room = new com.studybridge.api.entity.AgentChatRoom();
        room.setUser(user);
        room.setRoomName("성능 테스트용 더미 방");
        room.setLearningMode("basic");
        agentChatRoomRepository.save(room);

        // 더미 메시지 10000개 삽입 (DB와 Redis 양쪽 모두)
        long roomId = room.getId();

        // DB 저장은 속도를 위해 List에 담아서 한 번에 saveAll
        java.util.List<com.studybridge.api.entity.ChatMessage> dbMessages = new java.util.ArrayList<>();
        for (int i = 0; i < 10000; i++) {
            var dbMsg = new com.studybridge.api.entity.ChatMessage();
            dbMsg.setAgentChatRoom(room);
            dbMsg.setSender(i % 2 == 0 ? "USER" : "AI");
            dbMsg.setContent("이것은 성능 테스트를 위한 " + i + "번째 더미 메시지입니다. 내용이 길어지고 데이터가 많을수록 디스크 I/O를 타는 DB와 인메모리 Redis의 속도 차이가 극명하게 벌어집니다.");
            dbMessages.add(dbMsg);
        }
        chatMessageRepository.saveAll(dbMessages);

        // Redis에도 저장 (PPT를 위해 10000개를 그대로 다 넣습니다)
        for (int i = 0; i < 10000; i++) {
            var redisMsg = com.studybridge.api.dto.RedisChatMessage.builder()
                    .role(i % 2 == 0 ? "USER" : "AI")
                    .agentName(i % 2 == 0 ? "사용자" : "AI 도우미")
                    .answer("이것은 성능 테스트를 위한 " + i + "번째 더미 메시지입니다. 내용이 길어지고 데이터가 많을수록 디스크 I/O를 타는 DB와 인메모리 Redis의 속도 차이가 극명하게 벌어집니다.")
                    .build();
            // 강제로 트리밍 없이 List에 넣기 위해 직접 redisTemplate 사용
            redisTemplate.opsForList().rightPush("studybridge:group:" + roomId + ":chats", redisMsg);
        }

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("message", "✅ 더미 데이터 10,000개 생성 완료!");
        response.put("roomId", roomId);
        response.put("redis_test_url", "https://studybridge.co.kr/api/test/performance/redis/" + roomId);
        response.put("db_test_url", "https://studybridge.co.kr/api/test/performance/db/" + roomId);
        
        return ResponseEntity.ok(response);
    }

    @GetMapping(value = "/redis/{groupId}", produces = "application/json;charset=UTF-8")
    @LogExecutionTime
    public ResponseEntity<Map<String, Object>> Fetch_From_Redis_Cache(@PathVariable Long groupId) {
        long start = System.currentTimeMillis();
        var history = redisChatService.getRecentHistory(groupId);
        long end = System.currentTimeMillis();

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("target", "인메모리 REDIS 캐시 조회");
        response.put("data_count", history.size());
        response.put("latency_ms", (end - start));
        
        return ResponseEntity.ok(response);
    }

    @GetMapping(value = "/db/{roomId}", produces = "application/json;charset=UTF-8")
    @LogExecutionTime
    public ResponseEntity<Map<String, Object>> Fetch_From_PostgreSQL_DB(@PathVariable Long roomId) {
        long start = System.currentTimeMillis();
        var history = chatMessageRepository.findByAgentChatRoomIdOrderByCreatedAtAsc(roomId);
        long end = System.currentTimeMillis();

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("target", "기존 PostgreSQL DB 조회");
        response.put("data_count", history.size());
        response.put("latency_ms", (end - start));
        
        return ResponseEntity.ok(response);
    }
}
