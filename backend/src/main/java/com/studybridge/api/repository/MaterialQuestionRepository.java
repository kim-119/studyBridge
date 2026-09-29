package com.studybridge.api.repository;

import com.studybridge.api.entity.MaterialQuestion;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface MaterialQuestionRepository extends JpaRepository<MaterialQuestion, Long> {
    List<MaterialQuestion> findByMaterial_MaterialIdOrderByCreatedAtAsc(Long materialId);
}
