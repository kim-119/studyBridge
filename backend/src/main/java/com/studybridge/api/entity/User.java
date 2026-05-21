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
    private Long id;

    @Column(name = "email", nullable = false, unique = true, length = 100)
    private String email;

    @Column(name = "password", nullable = false)
    private String password;

    @Column(name = "display_name", nullable = false, length = 50)
    private String displayName;

    @Column(name = "photo_url")
    private String photoUrl;

    @Column(name = "major", length = 50)
    private String major;

    @Builder.Default
    @Column(name = "is_subscribed", nullable = false, columnDefinition = "boolean default false")
    private Boolean isSubscribed = false;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

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
