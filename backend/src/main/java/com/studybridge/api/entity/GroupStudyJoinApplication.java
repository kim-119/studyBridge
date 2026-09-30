package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "group_study_join_applications")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyJoinApplication {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_join_application_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "group_study_id", nullable = false)
    private GroupStudy groupStudy;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user; // 지원자

    @Column(nullable = false, columnDefinition = "TEXT")
    private String introduction; // 지원 동기 및 각오 한마디

    // 그룹의 가입 질문에 대한 답변(질문 OFF 그룹이면 null). 질문 문구는 그룹 설정에서 조회한다.
    @Column(name = "join_answer", columnDefinition = "TEXT")
    private String joinAnswer;

    // 닉네임 규칙 ON 그룹에서 지원자가 입력한 그룹 내 별칭. 승인 시 GroupStudyMember.nickname 으로 복사된다.
    @Column(name = "nickname", length = 30)
    private String nickname;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private GroupStudyJoinStatus status; // PENDING, APPROVED, REJECTED

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
