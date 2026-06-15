package com.studybridge.api.repository;

import com.studybridge.api.entity.MaterialStudyNoteAnalysis;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface MaterialStudyNoteAnalysisRepository extends JpaRepository<MaterialStudyNoteAnalysis, Long> {
    Optional<MaterialStudyNoteAnalysis> findByMaterialId(Long materialId);
}
