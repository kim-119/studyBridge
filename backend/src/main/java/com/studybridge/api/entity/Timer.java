package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "timers", indexes = {
        @Index(name = "ix_timers_user_status", columnList = "user_id, status"),
        @Index(name = "ix_timers_group_start", columnList = "group_study_id, start_time")
})
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Timer {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(nullable = false)
    private LocalDateTime startTime;

    private LocalDateTime endTime;

    private Long durationSeconds;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private TimerStatus status;

    @Column(name = "group_study_id")
    private Long groupStudyId; // 연동된 그룹스터디 ID

    // 마지막 heartbeat(서버 시각). null = heartbeat 를 보내지 않는 구 클라이언트 세션(reaper 의 timeout 대상 아님).
    // 이 시각까지의 공부시간은 이미 group_study_attendances 에 크레딧돼 있다("credited until").
    @Column(name = "last_heartbeat_at")
    private LocalDateTime lastHeartbeatAt;

    @Enumerated(EnumType.STRING)
    @Column(name = "end_reason", length = 30)
    private TimerEndReason endReason;

    @CreationTimestamp
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(nullable = false)
    private LocalDateTime updatedAt;
}
