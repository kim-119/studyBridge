package com.studybridge.api.dto;

import com.studybridge.api.entity.MindmapNodeMemo;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDateTime;

/**
 * 마인드맵 노드 메모 DTO. 응답은 항상 { memo: {...}|null } 형태로 통일해 프론트 처리를 단순화한다.
 */
public class MindmapNodeMemoDTO {

    // 저장(PUT) 요청 본문. nodeId 는 path 인코딩 이슈를 피하기 위해 본문으로 받는다.
    @Getter
    @Setter
    @NoArgsConstructor
    public static class SaveRequest {
        private String nodeId;
        private String nodeLabel;
        private String content;
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Memo {
        private Long id;
        private Long materialId;
        private String nodeId;
        private String nodeLabel;
        private String content;
        private LocalDateTime updatedAt;

        public static Memo from(MindmapNodeMemo m) {
            return Memo.builder()
                    .id(m.getNodeMemoId())
                    .materialId(m.getMaterialId())
                    .nodeId(m.getNodeId())
                    .nodeLabel(m.getNodeLabel())
                    .content(m.getContent())
                    .updatedAt(m.getUpdatedAt())
                    .build();
        }
    }

    // 응답 래퍼: { success, memo }. memo 가 없으면 null.
    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Response {
        private boolean success;
        private Memo memo;

        public static Response of(Memo memo) {
            return Response.builder().success(true).memo(memo).build();
        }
    }
}
