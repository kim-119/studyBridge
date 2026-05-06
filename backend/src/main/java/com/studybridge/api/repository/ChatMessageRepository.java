package com.studybridge.api.repository;

import com.studybridge.api.entity.ChatMessage;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {
    List<ChatMessage> findByAgentIdOrderByCreatedAtAsc(Long agentId);
    void deleteByAgentId(Long agentId);
}
