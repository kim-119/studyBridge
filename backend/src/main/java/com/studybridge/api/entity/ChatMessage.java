package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "chat_messages")
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
    @JoinColumn(name = "agent_id") // nullable = true (유저가 보낸 메시지는 null)
    private Agent agent;

    @Column(columnDefinition = "TEXT", nullable = false)
    private String content; // 메시지 내용

    @Column(nullable = false)
    private String sender; // "USER" 또는 "AI"

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
