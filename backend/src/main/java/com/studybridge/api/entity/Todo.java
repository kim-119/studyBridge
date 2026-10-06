package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import java.time.LocalDateTime;

@Entity
@Table(name = "todos")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Todo {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "todo_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(nullable = false, length = 255)
    private String text; // 할 일 내용

    @Builder.Default
    @Column(nullable = false)
    private Boolean completed = false; // 완료 여부

    @Column(name = "start_date")
    private LocalDateTime startDate; // 시작 일시

    @Column(name = "end_date")
    private LocalDateTime endDate; // 종료 일시

    // ── 출처 추적(주간 일정 = todos 가 source of truth). 수동 입력 Todo 는 모두 null ──
    //  sourceType : REVIEW_NOTE(오답노트 복습 일정) | PLANNER(플래너 일정)
    //  sourceId   : review_notes.review_note_id | planners.planner_id
    //  scheduleDate: 등록 기준 날짜(LocalDate). (user_id, source_type, source_id, schedule_date) 로 중복 등록을 막는다.
    //  ddl-auto=update 로 nullable 컬럼 자동 추가. 부분 unique index 는 RDS 에 수동 생성(uk_todos_source_schedule).
    @Column(name = "source_type", length = 30)
    private String sourceType;

    @Column(name = "source_id")
    private Long sourceId;

    @Column(name = "schedule_date")
    private java.time.LocalDate scheduleDate;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

}
