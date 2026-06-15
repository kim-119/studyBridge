package com.studybridge.api.repository;

import com.studybridge.api.entity.SocraticReviewSession;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface SocraticReviewSessionRepository extends JpaRepository<SocraticReviewSession, Long> {
    Optional<SocraticReviewSession> findBySessionId(String sessionId);
}
