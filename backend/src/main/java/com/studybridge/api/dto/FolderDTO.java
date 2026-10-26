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
    private String domain; // 문서 도메인(LEARNING_MATERIAL/PLANNER/STUDY_JOURNAL). 프론트 탭 분리/방어용.
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    public static FolderDTO from(Folder f) {
        return FolderDTO.builder()
                .folderId(f.getFolderId())
                .name(f.getName())
                .parentId(f.getParentId())
                .domain(com.studybridge.api.entity.DocumentDomain.normalize(f.getDomain()))
                .createdAt(f.getCreatedAt())
                .updatedAt(f.getUpdatedAt())
                .build();
    }

    @Getter
    @NoArgsConstructor
    public static class CreateRequest {
        private String name;
        private Long parentId;
        private String domain; // 생성 탭의 도메인. 누락 시 서버에서 LEARNING_MATERIAL 폴백(+경고 로그).
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
