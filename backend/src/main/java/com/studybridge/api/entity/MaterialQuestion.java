package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "material_questions")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class MaterialQuestion {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long questionId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "material_id", nullable = false)
    private Material material;

    @Column(nullable = false, length = 1000)
    private String userQuestion;

    @Column(columnDefinition = "TEXT")
    private String aiAnswer;

    // 품질 게이트 승인 기록(APPROVED 만, 게이트 OFF 저장분은 null = 미검증). ddl-auto=update 로 nullable 추가.
    @Column(name = "quality_status", length = 24)
    private String qualityStatus;

    @CreationTimestamp
    private LocalDateTime createdAt;
}
