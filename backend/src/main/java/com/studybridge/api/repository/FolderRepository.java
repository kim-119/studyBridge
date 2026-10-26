package com.studybridge.api.repository;

import com.studybridge.api.entity.Folder;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface FolderRepository extends JpaRepository<Folder, Long> {

    // 특정 위치(부모 폴더)의 하위 폴더 목록 (최신순)
    List<Folder> findByUserIdAndParentIdOrderByCreatedAtDesc(Long userId, Long parentId);

    // 루트(홈) 위치의 폴더 목록 (최신순)
    List<Folder> findByUserIdAndParentIdIsNullOrderByCreatedAtDesc(Long userId);

    // ── 도메인(탭) 분리 조회 ──────────────────────────────────────────────
    //  레거시(domain IS NULL) 폴더는 학습자료(LEARNING_MATERIAL)로 폴백 — 파괴적 마이그레이션 없이 호환.
    @Query("select f from Folder f where f.userId = :userId and f.parentId is null "
            + "and (f.domain = :domain or (f.domain is null and :domain = 'LEARNING_MATERIAL')) "
            + "order by f.createdAt desc")
    List<Folder> findRootByUserIdAndDomain(@Param("userId") Long userId, @Param("domain") String domain);

    @Query("select f from Folder f where f.userId = :userId and f.parentId = :parentId "
            + "and (f.domain = :domain or (f.domain is null and :domain = 'LEARNING_MATERIAL')) "
            + "order by f.createdAt desc")
    List<Folder> findChildrenByUserIdAndDomain(@Param("userId") Long userId,
                                               @Param("parentId") Long parentId,
                                               @Param("domain") String domain);

    // 하위 폴더 존재 여부 (삭제 차단 정책)
    long countByParentId(Long parentId);

    // 사용자의 전체 폴더 (이동 대상 선택용)
    List<Folder> findByUserIdOrderByCreatedAtDesc(Long userId);
}
