package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;

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
    @Column(name = "step_id")
    private Long stepId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "roadmap_id", nullable = false)
    private Roadmap roadmap;

    @Column(name = "step_order", nullable = false)
    private Integer stepOrder;

    @Column(name = "title", nullable = false)
    private String title;

    @Column(name = "description", length = 1000)
    private String description;

    // RoadmapTasks와의 1:N 관계는 필요에 따라 추가할 수 있습니다.
    // @OneToMany(mappedBy = "roadmapStep", cascade = CascadeType.ALL, orphanRemoval = true)
    // private List<RoadmapTask> tasks = new ArrayList<>();
}
