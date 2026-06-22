package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupChatMessage;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GroupChatMessageRepository extends JpaRepository<GroupChatMessage, Long> {
    List<GroupChatMessage> findTop100ByGroupStudyIdOrderByCreatedAtDesc(Long groupStudyId);
}
