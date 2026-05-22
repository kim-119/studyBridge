package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "users")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "user_id")
    private Long id; // 사용자 고유 식별자 (PK)

    @Column(name = "email", nullable = false, unique = true, length = 100)
    private String email; // 사용자 이메일 (로그인 ID)

    @Column(name = "password", nullable = false)
    private String password; // 암호화된 비밀번호

    @Column(name = "display_name", nullable = false, length = 50)
    private String displayName; // 서비스 내 표시될 닉네임

    @Column(name = "photo_url")
    private String photoUrl; // 프로필 이미지 경로

    @Column(name = "major", length = 50)
    private String major; // 전공/학과 정보

    @Builder.Default
    @Column(name = "status", length = 20)
    private String status = "ACTIVE"; // 사용자 상태 (예: ACTIVE, INACTIVE, BANNED)

    @Builder.Default
    @Column(name = "is_subscribed", nullable = false, columnDefinition = "boolean default false")
    private Boolean isSubscribed = false;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 계정 생성 일시

    @Enumerated(EnumType.STRING)
    @Column(name = "role", nullable = false)
    @Builder.Default
    private AdminRole role = AdminRole.USER;

    @Column(name = "banned", nullable = false)
    @Builder.Default
    private boolean banned = false;

    @Column(name = "banned_until")
    private LocalDateTime bannedUntil;
}
