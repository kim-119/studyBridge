package com.studybridge.api.service;

import com.studybridge.api.dto.FolderDTO;
import com.studybridge.api.entity.Folder;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.repository.FolderRepository;
import com.studybridge.api.repository.MaterialRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class FolderService {

    private final FolderRepository folderRepository;
    private final MaterialRepository materialRepository;

    /** 본인 소유 폴더를 반환. 없거나 타인 소유면 예외. */
    public Folder getOwnedFolder(Long userId, Long folderId) {
        Folder folder = folderRepository.findById(folderId)
                .orElseThrow(() -> new IllegalArgumentException("폴더를 찾을 수 없습니다."));
        if (!folder.getUserId().equals(userId)) {
            throw new SecurityException("해당 폴더에 대한 권한이 없습니다.");
        }
        return folder;
    }

    /** 사용자의 전체 폴더 목록(이동 대상 선택 등). */
    public java.util.List<FolderDTO> listAllFolders(Long userId) {
        return folderRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
                .map(FolderDTO::from)
                .collect(java.util.stream.Collectors.toList());
    }

    @Transactional
    public FolderDTO createFolder(Long userId, String name, Long parentId) {
        String trimmed = name == null ? "" : name.trim();
        if (trimmed.isEmpty()) {
            throw new IllegalArgumentException("폴더 이름을 입력해주세요.");
        }
        if (parentId != null) {
            getOwnedFolder(userId, parentId); // 부모 존재/소유 검증
        }
        Folder folder = Folder.builder()
                .userId(userId)
                .name(trimmed)
                .parentId(parentId)
                .build();
        return FolderDTO.from(folderRepository.save(folder));
    }

    @Transactional
    public FolderDTO renameFolder(Long userId, Long folderId, String name) {
        String trimmed = name == null ? "" : name.trim();
        if (trimmed.isEmpty()) {
            throw new IllegalArgumentException("폴더 이름을 입력해주세요.");
        }
        Folder folder = getOwnedFolder(userId, folderId);
        folder.setName(trimmed);
        return FolderDTO.from(folderRepository.save(folder));
    }

    /** 폴더 이동. 자기 자신/자기 하위로의 이동(순환)은 차단한다. parentId=null 이면 루트로 이동. */
    @Transactional
    public FolderDTO moveFolder(Long userId, Long folderId, Long newParentId) {
        Folder folder = getOwnedFolder(userId, folderId);

        if (newParentId != null) {
            if (newParentId.equals(folderId)) {
                throw new IllegalArgumentException("폴더를 자기 자신으로 이동할 수 없습니다.");
            }
            Folder target = getOwnedFolder(userId, newParentId);
            // target 의 조상 체인을 거슬러 올라가며 folderId 를 만나면 순환 → 차단
            Long cursor = target.getParentId();
            int guard = 0;
            while (cursor != null && guard++ < 1000) {
                if (cursor.equals(folderId)) {
                    throw new IllegalArgumentException("폴더를 자기 하위 폴더로 이동할 수 없습니다.");
                }
                Folder parent = folderRepository.findById(cursor).orElse(null);
                cursor = parent == null ? null : parent.getParentId();
            }
        }

        folder.setParentId(newParentId);
        return FolderDTO.from(folderRepository.save(folder));
    }

    /**
     * 폴더 삭제(A안: 비어 있어야만 삭제 가능).
     * 하위 폴더 또는 자료(REVIEW_NOTE 제외)가 하나라도 있으면 차단한다.
     */
    @Transactional
    public void deleteFolder(Long userId, Long folderId) {
        Folder folder = getOwnedFolder(userId, folderId);

        long subFolders = folderRepository.countByParentId(folderId);
        long childMaterials = materialRepository.findByUserIdAndFolderIdOrderByUploadedAtDesc(userId, folderId).stream()
                .filter(m -> m.getMaterialType() != MaterialType.REVIEW_NOTE)
                .count();

        if (subFolders > 0 || childMaterials > 0) {
            throw new IllegalStateException("폴더 안에 자료가 있어 삭제할 수 없습니다.");
        }
        folderRepository.delete(folder);
    }
}
