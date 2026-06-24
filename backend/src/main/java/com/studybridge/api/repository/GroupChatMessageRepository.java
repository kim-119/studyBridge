package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupChatMessage;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GroupChatMessageRepository extends JpaRepository<GroupChatMessage, Long> {
    List<GroupChatMessage> findTop100ByGroupStudyIdOrderByCreatedAtDesc(Long groupStudyId);

    // 그룹스터디 삭제 시 cascade가 없는 채팅 메시지를 일괄 정리(FK 제약으로 그룹 삭제가 막히는 것 방지).
    @Modifying
    @Query("delete from GroupChatMessage m where m.groupStudy.id = :groupStudyId")
    void deleteByGroupStudyId(@Param("groupStudyId") Long groupStudyId);
}
