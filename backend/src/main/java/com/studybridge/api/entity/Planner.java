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

    /**
     * 플래너 원천(ROADMAP/USER). 직접 생성 경로(수동=USER, 로드맵=ROADMAP)는 명시적으로 채운다.
     * 그 외 자동 생성 경로(REVIEW_AUTO/SOCRATIC_REVIEW 등 sourceType 보유)는 비워두면
     * PlannerService.resolvePlannerType 가 ROADMAP(자동)으로 판정하고 기동 시 backfill 로 보정한다.
     * 운영 DB(RDS)에 이미 데이터가 있으므로 컬럼은 nullable 로 두어 ddl-auto=update 자동 추가 시 장애를 막는다.
     * (Builder 기본값을 두지 않는다 — 두면 sourceType 보유 자동 플래너가 USER 로 잘못 고정된다.)
     */
    @Enumerated(EnumType.STRING)
    @Column(name = "planner_type", length = 20)
    private PlannerType plannerType;

    @Column(name = "roadmap_week")
    private Integer roadmapWeek;
    @Column(name = "roadmap_day")
    private Integer roadmapDay;
    @Column(name = "estimated_minutes")
    private Integer estimatedMinutes;

    // AI 계획 분석(구조화 시맨틱) 캐시. ddl-auto=update 로 nullable 컬럼 자동 추가.
    @Column(name = "plan_analysis_json", columnDefinition = "TEXT")
    private String planAnalysisJson;

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
    private String dDay;           // 마감일/시험일 (라벨 변경, 기존 컬럼 재사용)

    // 대학생 친화 가산 필드 (모두 nullable, ddl-auto=update 로 자동 생성 / 기존 데이터 무영향)
    @Column(name = "study_type", length = 50)
    private String studyType;      // 학습 유형 (강의 복습/과제/시험 준비/팀플/프로젝트/발표 준비/개인 공부)

    @Column(name = "priority", length = 20)
    private String priority;       // 우선순위 (낮음/보통/높음/긴급)

    @Column(name = "term", length = 50)
    private String term;           // 학기/주차 (예: 2026-1학기 · 3주차)

    @Column(length = 200)
    private String subject;        // 과목명

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

    // 로드맵 기반 자동 생성 추적용 (84일 플래너 자동 생성)
    @Column(name = "source_type", length = 30)
    private String sourceType;        // ROADMAP_AUTO 등 (수동 생성이면 null)
    @Column(name = "source_material_id")
    private Long sourceMaterialId;    // 출처 자료 id
    @Column(name = "source_roadmap_id")
    private Long sourceRoadmapId;     // 출처 로드맵 id

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;
}
