package com.studybridge.api.repository;

import com.studybridge.api.entity.MaterialGroupShare;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;

import java.util.List;
import java.util.Optional;

public interface MaterialGroupShareRepository extends JpaRepository<MaterialGroupShare, Long> {

    List<MaterialGroupShare> findByMaterialId(Long materialId);

    List<MaterialGroupShare> findByGroupStudyIdOrderByCreatedAtDesc(Long groupStudyId);

    Optional<MaterialGroupShare> findByMaterialIdAndGroupStudyId(Long materialId, Long groupStudyId);

    @Modifying
    void deleteByMaterialId(Long materialId);
}
