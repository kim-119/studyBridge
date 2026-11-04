package com.studybridge.api.repository;

import com.studybridge.api.entity.AiTrainingConsent;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface AiTrainingConsentRepository extends JpaRepository<AiTrainingConsent, Long> {

    Optional<AiTrainingConsent> findTopByUserIdAndPurposeOrderByCreatedAtDescIdDesc(Long userId, String purpose);

    boolean existsByUserIdAndPurpose(Long userId, String purpose);
}
