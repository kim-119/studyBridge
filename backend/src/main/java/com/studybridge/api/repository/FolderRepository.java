package com.studybridge.api.repository;

import com.studybridge.api.entity.Folder;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface FolderRepository extends JpaRepository<Folder, Long> {

    // 특정 위치(부모 폴더)의 하위 폴더 목록 (최신순)
    List<Folder> findByUserIdAndParentIdOrderByCreatedAtDesc(Long userId, Long parentId);

    // 루트(홈) 위치의 폴더 목록 (최신순)
    List<Folder> findByUserIdAndParentIdIsNullOrderByCreatedAtDesc(Long userId);

    // 하위 폴더 존재 여부 (삭제 차단 정책)
    long countByParentId(Long parentId);

    // 사용자의 전체 폴더 (이동 대상 선택용)
    List<Folder> findByUserIdOrderByCreatedAtDesc(Long userId);
}
