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

    private String description;

    @OneToMany(mappedBy = "step", cascade = CascadeType.ALL, orphanRemoval = true)
    @Builder.Default
    private List<RoadmapTask> tasks = new ArrayList<>();

    /**
     * 태스크를 추가할 때 연관관계를 동시에 설정해주는 편의 메서드입니다.
     */
    public void addTask(RoadmapTask task) {
        this.tasks.add(task);
        if (task.getStep() != this) {
            task.setStep(this);
        }
    }
}