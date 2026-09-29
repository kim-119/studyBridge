package com.studybridge.api.repository;

import com.studybridge.api.entity.AgentChatRoom;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AgentChatRoomRepository extends JpaRepository<AgentChatRoom, Long> {
    List<AgentChatRoom> findByUserIdOrderByCreatedAtDesc(Long userId);

    long countByUserId(Long userId);
}
