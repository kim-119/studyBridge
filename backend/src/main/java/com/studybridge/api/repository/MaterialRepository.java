package com.studybridge.api.repository;

import com.studybridge.api.entity.Material;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface MaterialRepository extends JpaRepository<Material, Long> {
    List<Material> findByUserIdOrderByUploadedAtDesc(Long userId);

    // 폴더 뷰: 루트(folder_id IS NULL) 위치의 자료
    List<Material> findByUserIdAndFolderIdIsNullOrderByUploadedAtDesc(Long userId);

    // 폴더 뷰: 특정 폴더 안의 자료
    List<Material> findByUserIdAndFolderIdOrderByUploadedAtDesc(Long userId, Long folderId);
}