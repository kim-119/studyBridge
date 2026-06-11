package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyQuizSessionAnswer;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyQuizSessionAnswerRepository extends JpaRepository<GroupStudyQuizSessionAnswer, Long> {
    Optional<GroupStudyQuizSessionAnswer> findBySessionIdAndUserIdAndQuestionId(Long sessionId, Long userId, Long questionId);

    List<GroupStudyQuizSessionAnswer> findBySessionIdAndQuestionIdOrderBySubmittedAtAsc(Long sessionId, Long questionId);

    List<GroupStudyQuizSessionAnswer> findBySessionIdOrderBySubmittedAtAsc(Long sessionId);
}
