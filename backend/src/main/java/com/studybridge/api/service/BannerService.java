package com.studybridge.api.service;

import com.studybridge.api.dto.BannerDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * 메인 배너 설정/이미지 관리.
 *  - 외부 원본 이미지 URL과 MCP 토큰은 서버 설정(application.yml/env)으로만 관리한다.
 *  - 외부 이미지를 서버가 다운로드해서 S3에 저장하고, 프론트에는 S3 presigned URL만 내려준다.
 */
@Slf4j
@Service
public class BannerService implements ApplicationRunner {

    private final S3Service s3Service;

    @Value("${banner.main.title}")
    private String title;
    @Value("${banner.main.subtitle}")
    private String subtitle;
    @Value("${banner.main.primary-button-text}")
    private String primaryButtonText;
    @Value("${banner.main.primary-button-path}")
    private String primaryButtonPath;
    @Value("${banner.main.secondary-button-text}")
    private String secondaryButtonText;
    @Value("${banner.main.secondary-button-path}")
    private String secondaryButtonPath;
    @Value("${banner.main.tertiary-button-text}")
    private String tertiaryButtonText;
    @Value("${banner.main.tertiary-button-path}")
    private String tertiaryButtonPath;
    @Value("${banner.main.source-url}")
    private String sourceUrl;
    @Value("${banner.main.s3-key}")
    private String s3Key;
    @Value("${banner.main.mcp-token:}")
    private String mcpToken;

    public BannerService(S3Service s3Service) {
        this.s3Service = s3Service;
    }

    /** 서버 시작 시 배너 이미지를 S3에 best-effort 동기화 (실패해도 앱은 정상 기동). */
    @Override
    public void run(ApplicationArguments args) {
        try {
            if (!s3Service.doesObjectExist(s3Key)) {
                syncImageToS3();
            } else {
                log.info("[배너] S3 배너 이미지가 이미 존재합니다. key={}", s3Key);
            }
        } catch (Exception e) {
            log.warn("[배너] 시작 시 배너 이미지 S3 동기화 실패(무시하고 기동): {}", e.getMessage());
        }
    }

    /** 외부 원본 이미지를 다운로드해서 S3에 저장. (관리자 재동기화에서도 호출) */
    public String syncImageToS3() {
        try {
            HttpClient client = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(10))
                    .followRedirects(HttpClient.Redirect.NORMAL)
                    .build();

            HttpRequest.Builder reqBuilder = HttpRequest.newBuilder()
                    .uri(URI.create(sourceUrl))
                    .timeout(Duration.ofSeconds(20))
                    .GET();
            // MCP 토큰이 설정된 경우에만 Authorization 헤더로 첨부(서버측에서만 사용).
            if (mcpToken != null && !mcpToken.isBlank()) {
                reqBuilder.header("Authorization", "Bearer " + mcpToken);
            }

            HttpResponse<byte[]> resp = client.send(reqBuilder.build(), HttpResponse.BodyHandlers.ofByteArray());
            if (resp.statusCode() != 200 || resp.body() == null || resp.body().length == 0) {
                throw new IllegalStateException("배너 원본 이미지 다운로드 실패 status=" + resp.statusCode());
            }

            String contentType = resp.headers().firstValue("content-type").orElse("image/png");
            s3Service.uploadBytes(resp.body(), s3Key, contentType);
            log.info("[배너] 배너 이미지 S3 동기화 완료. key={}, {} bytes", s3Key, resp.body().length);
            return s3Key;
        } catch (Exception e) {
            log.error("[배너] 배너 이미지 S3 동기화 중 오류: ", e);
            throw new RuntimeException("배너 이미지 동기화에 실패했습니다.", e);
        }
    }

    public BannerDTO.MainBanner getMainBanner() {
        // 이미지가 아직 없으면 즉석 동기화 시도(best-effort).
        String imageUrl = null;
        try {
            if (!s3Service.doesObjectExist(s3Key)) {
                syncImageToS3();
            }
            imageUrl = s3Service.getPresignedUrl(s3Key);
        } catch (Exception e) {
            log.warn("[배너] 배너 이미지 URL 발급 실패(이미지 없이 응답): {}", e.getMessage());
        }

        return BannerDTO.MainBanner.builder()
                .title(title)
                .subtitle(subtitle)
                .imageUrl(imageUrl)
                .primaryButtonText(primaryButtonText)
                .primaryButtonPath(primaryButtonPath)
                .secondaryButtonText(secondaryButtonText)
                .secondaryButtonPath(secondaryButtonPath)
                .tertiaryButtonText(tertiaryButtonText)
                .tertiaryButtonPath(tertiaryButtonPath)
                .build();
    }
}
