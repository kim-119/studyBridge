package com.studybridge.api.repository;

import com.studybridge.api.entity.MaterialSummary;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface MaterialSummaryRepository extends JpaRepository<MaterialSummary, Long> {
    Optional<MaterialSummary> findByMaterial_MaterialId(Long materialId);
}
