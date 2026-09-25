package com.studybridge.api.service;

import com.studybridge.api.dto.MindmapNodeMemoDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MindmapNodeMemo;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MindmapNodeMemoRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.NoSuchElementException;
import java.util.Objects;
import java.util.Optional;

/**
 * 마인드맵 노드 메모 비즈니스 로직.
 *  · 모든 진입점에서 material 소유권(userId)을 검증한다(타 사용자 메모 접근 차단).
 *  · 빈 내용 저장 = 메모 삭제로 통일(테이블/응답 단순화).
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class MindmapNodeMemoService {

    // content 길이 상한(백엔드 방어). 프론트는 1000 grapheme UX 제한을 두지만,
    // 이모지 등 multi-codepoint grapheme 으로 char 길이가 더 길 수 있어 넉넉히 둔다.
    private static final int MAX_CONTENT_CHARS = 4000;

    private final MindmapNodeMemoRepository memoRepository;
    private final MaterialRepository materialRepository;

    // material 존재 + 소유권 검증. 없으면 404, 타인 자료면 403.
    private void verifyOwnership(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new NoSuchElementException("자료를 찾을 수 없습니다."));
        if (!Objects.equals(material.getUserId(), userId)) {
            throw new SecurityException("해당 자료에 대한 권한이 없습니다.");
        }
    }

    private static String requireNodeId(String nodeId) {
        if (nodeId == null || nodeId.trim().isEmpty()) {
            throw new IllegalArgumentException("nodeId 는 필수입니다.");
        }
        return nodeId.trim();
    }

    public MindmapNodeMemoDTO.Memo get(Long userId, Long materialId, String nodeId) {
        verifyOwnership(userId, materialId);
        String node = requireNodeId(nodeId);
        return memoRepository.findByUserIdAndMaterialIdAndNodeId(userId, materialId, node)
                .map(MindmapNodeMemoDTO.Memo::from)
                .orElse(null);
    }

    @Transactional
    public MindmapNodeMemoDTO.Memo upsert(Long userId, Long materialId, MindmapNodeMemoDTO.SaveRequest request) {
        verifyOwnership(userId, materialId);
        String node = requireNodeId(request.getNodeId());

        String content = request.getContent() == null ? "" : request.getContent();
        if (content.length() > MAX_CONTENT_CHARS) {
            throw new IllegalArgumentException("메모는 최대 " + MAX_CONTENT_CHARS + "자까지 저장할 수 있습니다.");
        }

        Optional<MindmapNodeMemo> existing =
                memoRepository.findByUserIdAndMaterialIdAndNodeId(userId, materialId, node);

        // 빈 내용 저장 = 삭제로 통일.
        if (content.trim().isEmpty()) {
            existing.ifPresent(memoRepository::delete);
            return null;
        }

        String nodeLabel = request.getNodeLabel();
        if (nodeLabel != null && nodeLabel.length() > 500) {
            nodeLabel = nodeLabel.substring(0, 500);
        }

        MindmapNodeMemo memo = existing.orElseGet(() -> MindmapNodeMemo.builder()
                .userId(userId)
                .materialId(materialId)
                .nodeId(node)
                .build());
        memo.setNodeLabel(nodeLabel);
        memo.setContent(content);

        return MindmapNodeMemoDTO.Memo.from(memoRepository.save(memo));
    }

    @Transactional
    public void delete(Long userId, Long materialId, String nodeId) {
        verifyOwnership(userId, materialId);
        String node = requireNodeId(nodeId);
        memoRepository.deleteByUserIdAndMaterialIdAndNodeId(userId, materialId, node);
    }
}
