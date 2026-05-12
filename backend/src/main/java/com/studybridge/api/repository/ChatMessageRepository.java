package com.studybridge.api.repository;

import com.studybridge.api.entity.ChatMessage;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Repository
public interface ChatMessageRepository extends JpaRepository<ChatMessage, Long> {
    List<ChatMessage> findByAgentIdOrderByCreatedAtAsc(Long agentId);
    
    @Modifying
    @Transactional
    @Query("DELETE FROM ChatMessage c WHERE c.agent.id = :agentId")
    void deleteByAgentId(@Param("agentId") Long agentId);
}
