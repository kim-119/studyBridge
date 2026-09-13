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

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
