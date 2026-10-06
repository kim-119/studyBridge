package com.studybridge.api.repository;

import com.studybridge.api.entity.MaterialMemo;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface MaterialMemoRepository extends JpaRepository<MaterialMemo, Long> {
    Optional<MaterialMemo> findByMaterial_MaterialId(Long materialId);
}
