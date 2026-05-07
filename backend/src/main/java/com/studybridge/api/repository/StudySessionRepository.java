package com.studybridge.api.repository;

import com.studybridge.api.entity.StudySession;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface StudySessionRepository extends JpaRepository<StudySession, Long> {

    Optional<StudySession> findByUserIdAndStatus(Long userId, com.studybridge.api.entity.StudySessionStatus status);

    List<StudySession> findByUserIdOrderByStartTimeDesc(Long userId);
}
