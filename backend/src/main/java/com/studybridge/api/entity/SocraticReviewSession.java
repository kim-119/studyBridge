package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 소크라테스 복습 세션 매핑/결과 캐시. 실제 대화/평가는 ai07이 보유하며, EC2는 소유권 검증과
 * 완료 후 복습일 일정 등록을 위해 sessionId↔userId↔materialId 매핑과 finish 결과만 저장한다.
 * ddl-auto=update 로 테이블 자동 생성.
 */
@Entity
@Table(name = "socratic_review_sessions",
        uniqueConstraints = @UniqueConstraint(name = "uk_socratic_session_id", columnNames = "session_id"))
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class SocraticReviewSession {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "session_id", nullable = false, length = 100)
    private String sessionId; // ai07이 발급한 세션 id

    @Column(name = "material_id", nullable = false)
    private Long materialId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(nullable = false, length = 20)
    private String status; // IN_PROGRESS | COMPLETED

    private String title;

    private Integer recommendReviewInDays;
    private LocalDate recommendedReviewDate;

    @Column(columnDefinition = "TEXT")
    private String summaryForPlanner;

    @Column(columnDefinition = "TEXT")
    private String weakConceptsJson;

    @CreationTimestamp
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;
}
