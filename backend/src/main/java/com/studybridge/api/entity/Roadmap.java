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

    // 품질 게이트(Phase D): 분할 평가 전 세그먼트 승인 시에만 APPROVED. 게이트 OFF 저장본·레거시는 null(= 미검증).
    @Column(name = "quality_status", length = 24)
    private String qualityStatus;

    // 승인 당시 매니페스트 fullChecksum(SHA-256 hex) — 진행 상태(days[].completed)를 뺀 AI 본문 기준. 표시 직전 재계산해 일치할 때만 노출.
    @Column(name = "quality_checksum", length = 64)
    private String qualityChecksum;

    @CreationTimestamp
    private LocalDateTime createdAt;

    @OneToMany(mappedBy = "roadmap", cascade = CascadeType.ALL, orphanRemoval = true)
    @Builder.Default
    private List<RoadmapStep> steps = new ArrayList<>();
}