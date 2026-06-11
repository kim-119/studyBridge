package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyQuizSession;
import com.studybridge.api.entity.GroupStudyQuizSessionStatus;
import org.springframework.data.jpa.repository.JpaRepository;
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
}
