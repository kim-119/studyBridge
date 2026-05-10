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
    private String text; // 할 일 내용 (캘린더의 title 역할)

    @Builder.Default
    @Column(nullable = false)
    private Boolean completed = false; // 완료 여부

    @Column(name = "start_date")
    private LocalDateTime startDate; // 시작 일시 (캘린더 연동용)

    @Column(name = "end_date")
    private LocalDateTime endDate; // 종료/마감 일시 (캘린더 연동용)

    @Column(name = "view_type")
    private String viewType; // month 또는 week 구분

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

}
