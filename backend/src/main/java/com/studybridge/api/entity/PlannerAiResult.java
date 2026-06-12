package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 공부 플래너 AI 확장 결과.
 *  - 사용자가 대충 적은 플래너를 GPT가 "학습 실행 관리" 관점으로 확장한 결과를 보관한다.
 *  - JSON 배열 필드는 PostgreSQL TEXT(JSON 문자열)로 저장한다. ddl-auto=update 로 자동 생성.
 *  - 기존 planners 테이블은 변경하지 않고 1:1 보조 테이블로 분리한다.
 */
@Entity
@Table(name = "planner_ai_result")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class PlannerAiResult {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "planner_id", nullable = false, unique = true)
    private Long plannerId;

    @Column(name = "expanded_goal", columnDefinition = "TEXT")
    private String expandedGoal;

    @Column(name = "expanded_todo", columnDefinition = "TEXT")
    private String expandedTodo;       // JSON 배열 문자열

    @Column(name = "estimated_time", length = 100)
    private String estimatedTime;

    @Column(name = "study_strategy", columnDefinition = "TEXT")
    private String studyStrategy;      // JSON 배열 문자열 (학습 순서)

    @Column(name = "risk_points", columnDefinition = "TEXT")
    private String riskPoints;         // JSON 배열 문자열

    @Column(name = "today_checkpoints", columnDefinition = "TEXT")
    private String todayCheckpoints;   // JSON 배열 문자열

    @Column(name = "ai_questions", columnDefinition = "TEXT")
    private String aiQuestions;        // JSON 배열 문자열

    @Column(name = "reflection_prompts", columnDefinition = "TEXT")
    private String reflectionPrompts;  // JSON 배열 문자열

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;
}
