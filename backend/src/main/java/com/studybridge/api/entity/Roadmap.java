package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "roadmaps")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Roadmap {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long roadmapId;

    @Column(nullable = false)
    private Long userId;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "material_id")
    private Material material;

    // 로드맵 출처 구분: MATERIAL(자료보관함 PDF) | PLANNER(공부 플래너)
    @Column(name = "source_type", length = 20)
    @Builder.Default
    private String sourceType = "MATERIAL";

    // 플래너 로드맵일 때 연결되는 planner id (MATERIAL 로드맵이면 null)
    @Column(name = "planner_id")
    private Long plannerId;

    @Column(nullable = false)
    private String title;

    private String goal;

    @Column(columnDefinition = "TEXT")
    private String summary;

    // ai07 84일(12주 x 7일) 로드맵 원본 응답 JSON. weeks[].days[] 구조를 통째로 보존한다.
    // 존재하면 신(新) 84일 구조, null이면 레거시(steps/tasks 24개) 로드맵으로 간주한다.
    @Column(name = "roadmap_json", columnDefinition = "TEXT")
    private String roadmapJson;

    @CreationTimestamp
    private LocalDateTime createdAt;

    @OneToMany(mappedBy = "roadmap", cascade = CascadeType.ALL, orphanRemoval = true)
    @Builder.Default
    private List<RoadmapStep> steps = new ArrayList<>();
}