package com.studybridge.api.repository;

import com.studybridge.api.entity.RoadmapTask;
import org.springframework.data.jpa.repository.JpaRepository;

public interface RoadmapTaskRepository extends JpaRepository<RoadmapTask, Long> {
    /**
     * 레거시(roadmap_json 없는) 관계형 로드맵의 한 주차 task 전체.
     * 레거시 모델은 RoadmapStep = 주차(stepOrder), RoadmapTask.taskOrder = 그 주차 안의 task 번호(1..N, 운영 데이터는 주당 3개)이며
     * "일차" 개념이 없다. 이전 시그니처는 세 번째 인자(taskOrder)에 day(1..7)를 넣어 4~7일차는 빈 결과, 1~3일차는
     * 엉뚱한 task 1개만 반환했으므로, 주차 단위로 조회해 taskOrder 순으로 돌려준다.
     */
    java.util.List<RoadmapTask> findByStep_Roadmap_RoadmapIdAndStep_StepOrderOrderByTaskOrderAscTaskIdAsc(Long roadmapId, Integer stepOrder);
}
