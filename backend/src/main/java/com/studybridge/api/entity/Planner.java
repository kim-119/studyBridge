package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 공부 플래너 원본 데이터.
 *  - 구조화된 입력값을 보관한다. 생성된 PDF는 S3에 저장하고 자료보관함(Material, type=PLANNER)과 연결한다.
 *  - ddl-auto=update 로 테이블이 자동 생성된다.
 */
@Entity
@Table(name = "planners")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Planner {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "planner_id")
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(nullable = false, length = 200)
    private String title;

    // 표시용 날짜 구성요소 (7번 이미지 플래너 상단)
    private Integer year;
    private Integer month;
    private Integer day;

    @Column(name = "day_of_week", length = 10)
    private String dayOfWeek;     // 요일

    @Column(name = "planner_date")
    private LocalDate plannerDate; // 정렬/조회용 날짜

    @Column(name = "goal_time", length = 50)
    private String goalTime;       // 목표 시간

    @Column(name = "net_study_time", length = 50)
    private String netStudyTime;   // 순공부 시간

    @Column(name = "wake_up_time", length = 50)
    private String wakeUpTime;     // 기상 시간

    @Column(name = "d_day", length = 50)
    private String dDay;           // 디데이

    @Column(length = 200)
    private String subject;        // 과목

    @Column(columnDefinition = "TEXT")
    private String content;        // 내용

    @Column(columnDefinition = "TEXT")
    private String tmi;            // 오늘의 TMI 메모

    // 10분 단위 시간 체크표 (프론트에서 JSON 직렬화하여 저장)
    @Column(name = "time_table_json", columnDefinition = "TEXT")
    private String timeTableJson;

    // 생성된 PDF 연동 정보
    @Column(name = "s3_key", length = 500)
    private String s3Key;

    @Column(name = "material_id")
    private Long materialId;       // 자료보관함(Material) 연결 id

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;
}
