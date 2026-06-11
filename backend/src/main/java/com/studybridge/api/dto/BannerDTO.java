package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

public class BannerDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MainBanner {
        private String title;
        private String subtitle;
        private String imageUrl;            // S3 presigned URL (외부 원본 URL 노출 금지)
        private String primaryButtonText;
        private String primaryButtonPath;
        private String secondaryButtonText;
        private String secondaryButtonPath;
        private String tertiaryButtonText;
        private String tertiaryButtonPath;
    }
}
