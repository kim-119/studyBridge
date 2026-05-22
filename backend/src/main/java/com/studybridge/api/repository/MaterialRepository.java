package com.studybridge.api.repository;

import com.studybridge.api.entity.Material;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface MaterialRepository extends JpaRepository<Material, Long> {
    List<Material> findByUserIdOrderByUploadedAtDesc(Long userId);
}