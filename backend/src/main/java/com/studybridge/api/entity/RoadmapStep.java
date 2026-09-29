package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;

import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "roadmap_steps")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class RoadmapStep {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long stepId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "roadmap_id")
    private Roadmap roadmap;

    @Column(nullable = false)
    private Integer stepOrder;

    @Column(nullable = false)
    private String title;

    // AI가 생성하는 주차 설명은 여러 줄/수백 자가 될 수 있어 기본 varchar(255)로는 저장 실패(500)가 발생할 수 있다.
    @Column(columnDefinition = "TEXT")
    private String description;

    @OneToMany(mappedBy = "step", cascade = CascadeType.ALL, orphanRemoval = true)
    @Builder.Default
    private List<RoadmapTask> tasks = new ArrayList<>();

}