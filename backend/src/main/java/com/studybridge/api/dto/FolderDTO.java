package com.studybridge.api.dto;

import com.studybridge.api.entity.Folder;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@Builder
public class FolderDTO {

    private Long folderId;
    private String name;
    private Long parentId;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    public static FolderDTO from(Folder f) {
        return FolderDTO.builder()
                .folderId(f.getFolderId())
                .name(f.getName())
                .parentId(f.getParentId())
                .createdAt(f.getCreatedAt())
                .updatedAt(f.getUpdatedAt())
                .build();
    }

    @Getter
    @NoArgsConstructor
    public static class CreateRequest {
        private String name;
        private Long parentId;
    }

    @Getter
    @NoArgsConstructor
    public static class RenameRequest {
        private String name;
    }

    @Getter
    @NoArgsConstructor
    public static class MoveRequest {
        private Long parentId; // null 이면 루트(홈)로 이동
    }
}
