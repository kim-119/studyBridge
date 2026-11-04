package com.studybridge.api.repository;

import com.studybridge.api.entity.AiTrainingConsent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Optional;

public interface AiTrainingConsentRepository extends JpaRepository<AiTrainingConsent, Long> {

    Optional<AiTrainingConsent> findTopByUserIdAndPurposeOrderByCreatedAtDescIdDesc(Long userId, String purpose);

    boolean existsByUserIdAndPurpose(Long userId, String purpose);

    /**
     * 사용자 단위 동의 변경 직렬화(PostgreSQL 트랜잭션 advisory lock — 커밋/롤백 시 자동 해제).
     * 첫 동의(행 없음)까지 포함해 grant/withdraw 가 겹쳐도 시각 단조성(동의 < 철회 < 재동의)이 깨지지 않게 한다.
     */
    @Query(value = "SELECT 1 FROM (SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))) l", nativeQuery = true)
    Integer lockUserConsent(@Param("key") String key);
}
