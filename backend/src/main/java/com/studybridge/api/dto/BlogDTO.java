package com.studybridge.api.dto;

import lombok.*;
import java.time.LocalDateTime;
import java.util.List;

public class BlogDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private String title;
        private String content;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long blogId;
        private String title;
        private String content;
        private Long authorId;
        private String authorNickname;
        private String authorPhotoUrl;
        private String pdfS3Key;
        private String imageS3Key;
        private String pdfPresignedUrl;
        private String imagePresignedUrl;
        private long likeCount;
        private boolean likedByCurrentUser;
        private List<BlogCommentDTO.Response> comments;
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
    }
}
