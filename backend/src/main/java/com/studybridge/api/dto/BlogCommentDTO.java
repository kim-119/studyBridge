package com.studybridge.api.dto;

import lombok.*;
import java.time.LocalDateTime;

public class BlogCommentDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private String content;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long commentId;
        private Long blogId;
        private Long authorId;
        private String authorNickname;
        private String authorPhotoUrl;
        private String content;
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
    }
}
