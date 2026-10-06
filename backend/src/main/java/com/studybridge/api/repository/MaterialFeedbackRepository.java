package com.studybridge.api.repository;

import com.studybridge.api.entity.MaterialFeedback;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface MaterialFeedbackRepository extends JpaRepository<MaterialFeedback, Long> {
    Optional<MaterialFeedback> findByMaterial_MaterialId(Long materialId);
}
