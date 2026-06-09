package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "agent_chat_rooms")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AgentChatRoom {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "agent_room_id")
    private Long id; // 채팅방 고유 식별자 (PK)

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user; // 채팅방을 소유한 사용자 (N:1 관계)

    @Column(nullable = false, length = 100)
    private String roomName; // 채팅방 이름

    @Column(name = "learning_mode", length = 20)
    private String learningMode; // 학습 진행 모드 (basic/socratic/debate). null이면 basic으로 간주.

    @OneToMany(mappedBy = "agentChatRoom", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<Agent> agents; // 채팅방에 참여 중인 AI 에이전트 목록 (1:N 관계)

    @OneToMany(mappedBy = "agentChatRoom", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<ChatMessage> chatMessages; // 채팅방 내 메시지 이력 (1:N 관계)

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 채팅방 생성 일시
}
