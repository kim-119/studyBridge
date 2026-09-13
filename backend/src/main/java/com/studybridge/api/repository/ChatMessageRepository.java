package com.studybridge.api.repository;

import com.studybridge.api.entity.ChatMessage;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {
    List<ChatMessage> findByAgentIdOrderByCreatedAtAsc(Long agentId);

    List<ChatMessage> findByAgentChatRoomIdOrderByIdAsc(Long roomId);

    List<ChatMessage> findByAgentChatRoomIdOrderByCreatedAtAsc(Long roomId);
    // 같은 트랜잭션에서 저장된 AI 답변들은 created_at 이 µs 단위로 붙어 있어 id 를 tie-breaker 로 둔다(새로고침 후 순서 고정).
    List<ChatMessage> findByAgentChatRoomIdOrderByCreatedAtAscIdAsc(Long roomId);
    // 재시도 멱등 판정용: 방의 마지막 메시지 1건.
    java.util.Optional<ChatMessage> findTopByAgentChatRoomIdOrderByCreatedAtDescIdDesc(Long roomId);

    List<ChatMessage> findTop10ByAgentChatRoomIdAndSenderOrderByCreatedAtDesc(Long roomId, String sender);

    void deleteByAgentId(Long agentId);
}