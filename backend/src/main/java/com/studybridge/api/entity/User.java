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
    private Long id; // 사용자 고유 식별자

    @Column(name = "email", nullable = false, unique = true, length = 100)
    private String email; // 아이디(이메일)

    @Column(name = "password", nullable = false)
    private String password; // 비밀번호

    @Column(name = "display_name", nullable = false, length = 50)
    private String displayName; // 닉네임 (표시 이름)

    @Column(name = "photo_url")
    private String photoUrl; // 프로필 이미지

    @Column(name = "major", length = 50)
    private String major; // 전공 (학과)

    @Column(name = "status", length = 20)
    private String status; // 사용자 상태 (신고에 관한)

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt; // 계정 생성일
    
    // 엔티티가 데이터베이스에 저장되기 직전에 기본값 설정 (디폴트 값이라고 생각하면 됨요)
    @PrePersist
    public void prePersist() {
        if (this.status == null) {
            this.status = "ACTIVE";
        }
    }
}
