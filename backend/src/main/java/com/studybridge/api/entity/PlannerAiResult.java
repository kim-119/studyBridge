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

    // ---------- 학습 실행 관리 AI 피드백(ai-assist) 결과 ----------
    // 플래너를 "실행 가능한 계획"으로 정리하고 피드백한다. 로드맵/퀴즈/문서질문과 무관.
    // 사용자 원본 메모(planner.tmi)는 절대 덮어쓰지 않고, AI 결과만 여기에 보관한다.
    @Column(name = "ai_summary", columnDefinition = "TEXT")
    private String aiSummary;          // AI 요약

    @Column(name = "refined_goal", columnDefinition = "TEXT")
    private String refinedGoal;        // 정리된 학습 목표

    @Column(name = "task_breakdown", columnDefinition = "TEXT")
    private String taskBreakdown;      // JSON 배열 문자열 (할 일 정리)

    @Column(name = "time_feedback", columnDefinition = "TEXT")
    private String timeFeedback;       // 시간(목표/실제) 피드백 문장

    @Column(name = "ai_feedback", columnDefinition = "TEXT")
    private String aiFeedback;         // JSON {strengths, concerns, recommendations}

    @Column(name = "next_actions", columnDefinition = "TEXT")
    private String nextActions;        // JSON 배열 문자열 (다음 학습 행동)

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;
}
