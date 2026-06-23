package com.studybridge.api.repository;

import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface MaterialRepository extends JpaRepository<Material, Long> {
    List<Material> findByUserIdOrderByUploadedAtDesc(Long userId);

    // 폴더 뷰: 루트(folder_id IS NULL) 위치의 자료
    List<Material> findByUserIdAndFolderIdIsNullOrderByUploadedAtDesc(Long userId);

    // 폴더 뷰: 특정 폴더 안의 자료
    List<Material> findByUserIdAndFolderIdOrderByUploadedAtDesc(Long userId, Long folderId);

    // 플래너 삭제 cascade(역참조 보강): 특정 플래너를 가리키는 PLANNER 자료만 조회한다.
    // materialType 을 PLANNER 로 못박아 PDF/학습일지 등 일반 자료는 절대 대상에 포함되지 않게 한다.
    List<Material> findByPlannerIdAndMaterialType(Long plannerId, MaterialType materialType);
}