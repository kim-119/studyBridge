package com.studybridge.api.repository;

import com.studybridge.api.entity.MaterialQuiz;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface MaterialQuizRepository extends JpaRepository<MaterialQuiz, Long> {
    List<MaterialQuiz> findByMaterial_MaterialIdOrderByCreatedAtDesc(Long materialId);
}
