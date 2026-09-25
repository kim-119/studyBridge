package com.studybridge.api.repository;

import com.studybridge.api.entity.MindmapNodeMemo;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface MindmapNodeMemoRepository extends JpaRepository<MindmapNodeMemo, Long> {

    // (사용자 + 자료 + 노드) 단일 최신 메모 조회.
    Optional<MindmapNodeMemo> findByUserIdAndMaterialIdAndNodeId(Long userId, Long materialId, String nodeId);

    // 자료 1개의 모든 노드 메모(추후 일괄 로드/내보내기용).
    List<MindmapNodeMemo> findByUserIdAndMaterialId(Long userId, Long materialId);

    void deleteByUserIdAndMaterialIdAndNodeId(Long userId, Long materialId, String nodeId);
}
