package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyQuizSession;
import com.studybridge.api.entity.GroupStudyQuizSessionStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyQuizSessionRepository extends JpaRepository<GroupStudyQuizSession, Long> {
    Optional<GroupStudyQuizSession> findTopByGroupStudyIdAndStatusInOrderByCreatedAtDesc(Long groupStudyId, Collection<GroupStudyQuizSessionStatus> statuses);
    Optional<GroupStudyQuizSession> findTopByGroupStudyIdOrderByCreatedAtDesc(Long groupStudyId);
    List<GroupStudyQuizSession> findByGroupStudyIdAndStatusInOrderByCreatedAtDesc(Long groupStudyId, Collection<GroupStudyQuizSessionStatus> statuses);
    List<GroupStudyQuizSession> findByStatusInOrderByCreatedAtDesc(Collection<GroupStudyQuizSessionStatus> statuses);

    // 그룹스터디 삭제 시 cascade가 없는 퀴즈 세션 정리용. 답변 먼저 지우려면 세션 id가 필요하다.
    @Query("select s.id from GroupStudyQuizSession s where s.groupStudy.id = :groupStudyId")
    List<Long> findIdsByGroupStudyId(@Param("groupStudyId") Long groupStudyId);

    @Modifying
    @Query("delete from GroupStudyQuizSession s where s.groupStudy.id = :groupStudyId")
    void deleteByGroupStudyId(@Param("groupStudyId") Long groupStudyId);
}
