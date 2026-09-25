package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
// history 조회(agent_room_id + created_at 정렬)가 매번 전체 스캔이던 문제 → 복합 인덱스(ddl-auto=update 가 생성, RDS 에는 수동 CONCURRENTLY 적용).
@Table(name = "chat_messages", indexes = {
        @jakarta.persistence.Index(name = "idx_chat_messages_room_created", columnList = "agent_room_id, created_at")
})
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ChatMessage {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "message_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "agent_room_id", nullable = false)
    private AgentChatRoom agentChatRoom;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "agent_id")
    private Agent agent;

    @Column(columnDefinition = "TEXT", nullable = false)
    private String content;

    @Column(nullable = false)
    private String sender;

    // 1차/2차/3차 생성 과정(processSteps) JSON 영속화. AI 메시지에만 채워지고 그 외는 null.
    // 새로고침 후에도 '생성과정 보기' 아코디언을 복원하기 위함. (잘림 방지를 위해 TEXT)
    @Column(name = "process_steps_json", columnDefinition = "TEXT")
    private String processStepsJson;

    // ── AI07 SSE 계약 metadata(2026-09-22, 학습메이트 FINAL V2). nullable 가산 컬럼 — ddl-auto=update 가 ALTER 로 추가한다.
    //  · event_id: AI07 eventId(agent_answer) 또는 안전한 composite(turnId:agentId:stage:displayOrder) — 멱등 키.
    //    reload/reconnect/late event/재시도로 같은 답변이 두 번 저장되지 않는다(exists 검사 + unique 제약 백스톱).
    //  · request_id/turn_id: 브라우저 X-Request-ID ↔ Spring ↔ AI07 상관 id.
    //  · stage/status/mode/personality_key/knowledge_level_key: 응답 identity 보존(성공 답변만 저장, 실패는 저장하지 않는다).
    @Column(name = "request_id", length = 64)
    private String requestId;

    @Column(name = "turn_id", length = 64)
    private String turnId;

    @Column(name = "event_id", length = 96, unique = true)
    private String eventId;

    @Column(name = "agent_index")
    private Integer agentIndex;

    @Column(name = "stage", length = 40)
    private String stage;

    @Column(name = "status", length = 20)
    private String status;

    @Column(name = "mode", length = 40)
    private String mode;

    @Column(name = "personality_key", length = 20)
    private String personalityKey;

    @Column(name = "knowledge_level_key", length = 20)
    private String knowledgeLevelKey;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
