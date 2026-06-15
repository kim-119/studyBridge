package com.studybridge.api.dto;

import lombok.Builder;
import lombok.Getter;

import java.util.List;

/**
 * 자료보관함 폴더 뷰 한 화면의 응답.
 * - currentFolderId: 현재 위치(루트면 null)
 * - breadcrumb: 루트 다음부터 현재 폴더까지의 조상 경로(현재 폴더 포함). 루트면 빈 배열.
 * - folders: 현재 위치의 하위 폴더
 * - materials: 현재 위치의 자료(REVIEW_NOTE 제외)
 */
@Getter
@Builder
public class ArchiveListDTO {
    private Long currentFolderId;
    private List<FolderDTO> breadcrumb;
    private List<FolderDTO> folders;
    private List<MaterialDTO> materials;
}
