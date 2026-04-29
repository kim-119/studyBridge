package com.studybridge.api.repository;

import com.studybridge.api.entity.ChatMessage;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {
    // 특정 에이전트와의 채팅 내역을 시간순으로 조회
    List<ChatMessage> findByAgentIdOrderByCreatedAtAsc(Long agentId);
}
