package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

public class InquiryDTO {

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Request {
        private String type;
        private String title;
        private String content;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ReplyRequest {
        private String reply;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Response {
        private Long id;
        private String type;
        private String title;
        private String content;
        private String reply;
        private String status;
        private String author; // 닉네임 (displayName)
        private String date; // yyyy-MM-dd 형식
    }
}
