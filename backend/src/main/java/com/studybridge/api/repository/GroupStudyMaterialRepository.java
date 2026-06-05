package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyMaterial;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GroupStudyMaterialRepository extends JpaRepository<GroupStudyMaterial, Long> {
    List<GroupStudyMaterial> findByGroupStudyIdOrderByCreatedAtDesc(Long groupStudyId);
}
