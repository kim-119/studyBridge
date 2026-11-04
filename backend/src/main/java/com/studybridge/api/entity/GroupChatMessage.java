package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import java.time.LocalDateTime;

@Entity
@Table(name = "group_chat_messages")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupChatMessage {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "message_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "group_study_id", nullable = false)
    private GroupStudy groupStudy;

    @Column(nullable = false)
    private String senderName;
    
    @Column(nullable = false)
    private String senderId;

    @Column(nullable = false)
    private String role;

    @Column(columnDefinition = "TEXT", nullable = false)
    private String content;

    // Spring 품질 게이트 판정(APPROVED 만 기록, AI 행 전용). null = 게이트 OFF 시기/레거시/사용자 행 → 게이트 ON 에서 AI 행은 미검증으로 취급.
    @Column(name = "quality_status", length = 24)
    private String qualityStatus;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
