package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "agents")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Agent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "agent_id")
    private Long id; // 에이전트 고유 식별자 (PK)

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "agent_room_id", nullable = false)
    private AgentChatRoom agentChatRoom; // 소속된 채팅방 (N:1 관계)

    @Column(nullable = false, length = 30)
    private String name; // AI 에이전트 이름

    @Column(nullable = false, length = 50)
    private String role; // AI 에이전트의 역할 (예: 수학 튜터)

    @Column(nullable = false, length = 1000)
    private String persona; // AI 에이전트의 성격 및 상세 설정

    @Column(length = 100)
    private String tone; // 답변 말투 설정

    @Column(length = 200)
    private String goal; // AI 에이전트의 응답 목표

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 에이전트 설정 생성 일시

    @OneToMany(mappedBy = "agent", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<ChatMessage> chatMessages; // 에이전트가 발신한 메시지 목록 (1:N 관계)
}
