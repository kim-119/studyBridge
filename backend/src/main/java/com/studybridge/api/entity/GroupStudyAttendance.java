package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDate;
import java.time.LocalDateTime;

@Entity
@Table(name = "group_study_attendances", uniqueConstraints = {
        @UniqueConstraint(columnNames = { "group_study_id", "user_id", "attendance_date" })
})
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyAttendance {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_attendance_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "group_study_id", nullable = false)
    private GroupStudy groupStudy;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(name = "attendance_date", nullable = false)
    private LocalDate date;

    @Column(nullable = false)
    private LocalDateTime checkInTime;

    private LocalDateTime checkOutTime;

    // 서버가 세션 구간(heartbeat/종료)에서 날짜별로 분할 크레딧한 누적 공부시간(초). 클라이언트 값이 아니다.
    @Builder.Default
    @Column(nullable = false)
    private Long studyDurationSeconds = 0L;

    // 마지막으로 크레딧이 반영된 서버 시각(heartbeat/종료). 비정상 종료 시 "마지막 활동" 근거.
    @Column(name = "last_active_at")
    private LocalDateTime lastActiveAt;

    @Column(nullable = false, length = 20)
    private String status;
}
