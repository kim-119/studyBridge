package com.studybridge.api.controller;

import com.studybridge.api.dto.FolderDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.FolderService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/folders")
@RequiredArgsConstructor
public class FolderController {

    private final FolderService folderService;

    // 사용자의 전체 폴더 목록 (이동 대상 선택용)
    @GetMapping
    public ResponseEntity<java.util.List<FolderDTO>> listFolders(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        return ResponseEntity.ok(folderService.listAllFolders(userDetails.getId()));
    }

    // 폴더 생성 (parentId=null 이면 루트)
    @PostMapping
    public ResponseEntity<FolderDTO> createFolder(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody FolderDTO.CreateRequest request) {
        return ResponseEntity.ok(
                folderService.createFolder(userDetails.getId(), request.getName(), request.getParentId(), request.getDomain()));
    }

    // 폴더명 변경
    @PatchMapping("/{folderId}")
    public ResponseEntity<FolderDTO> renameFolder(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long folderId,
            @RequestBody FolderDTO.RenameRequest request) {
        return ResponseEntity.ok(
                folderService.renameFolder(userDetails.getId(), folderId, request.getName()));
    }

    // 폴더 이동 (parentId=null 이면 루트로, 순환 이동 차단)
    @PatchMapping("/{folderId}/move")
    public ResponseEntity<FolderDTO> moveFolder(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long folderId,
            @RequestBody FolderDTO.MoveRequest request) {
        return ResponseEntity.ok(
                folderService.moveFolder(userDetails.getId(), folderId, request.getParentId()));
    }

    // 폴더 삭제 (A안: 비어 있어야 삭제 가능, 아니면 409)
    @DeleteMapping("/{folderId}")
    public ResponseEntity<Void> deleteFolder(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long folderId) {
        folderService.deleteFolder(userDetails.getId(), folderId);
        return ResponseEntity.ok().build();
    }
}
