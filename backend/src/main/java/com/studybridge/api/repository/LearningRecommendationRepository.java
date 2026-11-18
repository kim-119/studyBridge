package com.studybridge.api.repository;

import com.studybridge.api.entity.LearningRecommendation;
import com.studybridge.api.entity.LearningRecommendation.Status;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface LearningRecommendationRepository extends JpaRepository<LearningRecommendation, Long> {

    Optional<LearningRecommendation> findByIdAndUserId(Long id, Long userId);

    Optional<LearningRecommendation> findByUserIdAndDedupKey(Long userId, String dedupKey);

    List<LearningRecommendation> findByUserIdAndPlannerIdAndStatusInOrderByIdAsc(Long userId, Long plannerId, Collection<Status> statuses);

    List<LearningRecommendation> findByUserIdAndMaterialIdAndPlannerIdIsNullAndStatusInOrderByIdAsc(Long userId, Long materialId, Collection<Status> statuses);

    List<LearningRecommendation> findByUserId(Long userId);

    /**
     * 조건부 상태 전이(원자적). 반환 1 = 이 요청이 전이시킴, 0 = 이미 다른 상태(중복 클릭/동시 요청).
     * 승인 시 플래너 중복 생성을 막는 1차 방어선.
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("UPDATE LearningRecommendation r SET r.status = :to, r.decidedAt = :at, r.updatedAt = :at " +
            "WHERE r.id = :id AND r.userId = :userId AND r.status = :from")
    int transition(@Param("id") Long id, @Param("userId") Long userId,
                   @Param("from") Status from, @Param("to") Status to, @Param("at") LocalDateTime at);

    /** ACCEPTED → COMPLETED (decidedAt 은 승인 시각으로 유지). 상태는 파라미터로 받는다(중첩 enum 리터럴은 JPQL 경로 해석 불가). */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("UPDATE LearningRecommendation r SET r.status = :to, r.completedAt = :at, r.updatedAt = :at " +
            "WHERE r.id = :id AND r.userId = :userId AND r.status = :from")
    int markCompleted(@Param("id") Long id, @Param("userId") Long userId,
                      @Param("from") Status from, @Param("to") Status to, @Param("at") LocalDateTime at);
}
