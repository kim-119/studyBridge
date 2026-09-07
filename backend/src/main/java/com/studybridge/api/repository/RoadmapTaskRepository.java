package com.studybridge.api.repository;

import com.studybridge.api.entity.RoadmapTask;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RoadmapTaskRepository extends JpaRepository<RoadmapTask, Long> {
    java.util.List<RoadmapTask> findByStep_Roadmap_RoadmapIdAndStep_StepOrderAndTaskOrderOrderByTaskId(Long roadmapId, Integer week, Integer day);
}
