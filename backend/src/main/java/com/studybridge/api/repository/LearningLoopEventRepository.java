package com.studybridge.api.repository;

import com.studybridge.api.entity.LearningEventType;
import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.entity.LearningSourceType;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface LearningLoopEventRepository extends JpaRepository<LearningLoopEvent, Long> {

    List<LearningLoopEvent> findByUserIdOrderByCreatedAtDesc(Long userId, Pageable pageable);

    List<LearningLoopEvent> findByUserIdAndMaterialIdOrderByCreatedAtDesc(Long userId, Long materialId, Pageable pageable);

    List<LearningLoopEvent> findByUserIdAndDocumentIdOrderByCreatedAtDesc(Long userId, Long documentId, Pageable pageable);

    List<LearningLoopEvent> findByUserIdAndSourceTypeAndSourceIdOrderByCreatedAtDesc(
            Long userId, LearningSourceType sourceType, Long sourceId, Pageable pageable);

    List<LearningLoopEvent> findByUserIdAndMaterialIdAndEventTypeOrderByCreatedAtDesc(
            Long userId, Long materialId, LearningEventType eventType, Pageable pageable);
}
