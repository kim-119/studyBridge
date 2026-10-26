package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyQuizSessionAnswer;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyQuizSessionAnswerRepository extends JpaRepository<GroupStudyQuizSessionAnswer, Long> {
    Optional<GroupStudyQuizSessionAnswer> findBySessionIdAndUserIdAndQuestionId(Long sessionId, Long userId, Long questionId);

    List<GroupStudyQuizSessionAnswer> findBySessionIdAndQuestionIdOrderBySubmittedAtAsc(Long sessionId, Long questionId);

    List<GroupStudyQuizSessionAnswer> findBySessionIdOrderBySubmittedAtAsc(Long sessionId);

    // 그룹스터디 삭제 시 cascade가 없는 퀴즈 세션 답변을 세션 id 기준으로 일괄 정리.
    @Modifying
    @Query("delete from GroupStudyQuizSessionAnswer a where a.session.id in :sessionIds")
    void deleteBySessionIdIn(@Param("sessionIds") Collection<Long> sessionIds);
}
