package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "roadmap_tasks")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class RoadmapTask {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long taskId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "step_id")
    private RoadmapStep step;

    @Column(nullable = false)
    private Integer taskOrder;

    @Column(nullable = false, length = 1000)
    private String content;
}