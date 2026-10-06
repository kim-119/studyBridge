package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.DeleteObjectRequest;
import software.amazon.awssdk.services.s3.model.HeadObjectRequest;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;
import software.amazon.awssdk.services.s3.model.S3Exception;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.GetObjectPresignRequest;
import software.amazon.awssdk.services.s3.presigner.model.PresignedGetObjectRequest;

import java.io.IOException;
import java.time.Duration;
import java.util.UUID;

@Slf4j
@Service
public class S3Service {

    private final S3Client s3Client;
    private final S3Presigner s3Presigner;
    private final String bucket;

    public S3Service(S3Client s3Client,
                     S3Presigner s3Presigner,
                     @Value("${cloud.aws.s3.bucket}") String bucket) {
        this.s3Client = s3Client;
        this.s3Presigner = s3Presigner;
        this.bucket = bucket;
    }

    public String uploadFile(MultipartFile file, Long userId) throws IOException {
        String contentType = file.getContentType();
        String originalName = file.getOriginalFilename();
        String lowerName = originalName != null ? originalName.toLowerCase() : "";
        boolean supported = "application/pdf".equals(contentType)
                || "application/vnd.openxmlformats-officedocument.wordprocessingml.document".equals(contentType)
                || "text/plain".equals(contentType)
                || lowerName.endsWith(".pdf")
                || lowerName.endsWith(".docx")
                || lowerName.endsWith(".txt");
        if (!supported) {
            throw new IllegalArgumentException("문서 파일만 업로드 가능합니다. (PDF/DOCX/TXT)");
        }

        if (originalName != null) {
            originalName = new java.io.File(originalName).getName();
        }
        if (originalName == null || originalName.isBlank()) {
            originalName = "document";
            if ("application/pdf".equals(contentType)) {
                originalName += ".pdf";
            } else if ("application/vnd.openxmlformats-officedocument.wordprocessingml.document".equals(contentType)) {
                originalName += ".docx";
            } else if ("text/plain".equals(contentType)) {
                originalName += ".txt";
            }
        }
        originalName = originalName.replaceAll("[^a-zA-Z0-9.\\-_\\s가-힣ㄱ-ㅎㅏ-ㅣ]", "_");

        String fileName = "materials/user_" + userId + "/" + UUID.randomUUID() + "/" + originalName;

        try {
            PutObjectRequest putObjectRequest = PutObjectRequest.builder()
                    .bucket(bucket)
                    .key(fileName)
                    .contentType(contentType != null ? contentType : "application/octet-stream")
                    .build();

            s3Client.putObject(putObjectRequest, RequestBody.fromBytes(file.getBytes()));
            log.info("[S3 업로드 완료] 파일이 S3 버킷에 정상 업로드되었습니다: {}", fileName);
            return fileName;
        } catch (Exception e) {
            log.error("[S3 업로드 에러] S3 업로드 중 예외가 발생했습니다: ", e);
            throw new RuntimeException("AWS S3 파일 업로드에 실패했습니다.", e);
        }
    }

    // 대표 이미지(미디어 자산) 허용 MIME — 문서(uploadFile)와 분리. FastAPI 분석 대상 아님.
    private static final java.util.Set<String> COVER_IMAGE_CONTENT_TYPES = java.util.Set.of(
            "image/jpeg",
            "image/png",
            "image/webp"
    );

    /**
     * 스터디 대표 이미지 업로드 — 문서 검증(uploadFile)과 완전히 분리한다.
     * 허용: image/jpeg, image/png, image/webp (확장자 fallback 포함), 최대 5MB.
     * S3 prefix: study-images/user_{userId}/{uuid}.{ext}. 단순 media asset 으로 분석 파이프라인에 보내지 않는다.
     */
    public String uploadCoverImage(MultipartFile file, Long userId) throws IOException {
        String contentType = file.getContentType();
        String originalName = file.getOriginalFilename();
        String lowerName = originalName != null ? originalName.toLowerCase() : "";
        boolean validMime = contentType != null && COVER_IMAGE_CONTENT_TYPES.contains(contentType);
        boolean validExt = lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg")
                || lowerName.endsWith(".png") || lowerName.endsWith(".webp");
        if (!validMime && !validExt) {
            throw new IllegalArgumentException("대표 이미지는 JPG, PNG, WEBP 파일만 업로드할 수 있습니다.");
        }

        long maxSize = 5L * 1024L * 1024L;
        if (file.getSize() > maxSize) {
            throw new IllegalArgumentException("대표 이미지는 5MB 이하만 업로드할 수 있습니다.");
        }

        // 확장자/콘텐츠 타입 정규화 — MIME 누락 시 확장자로, 둘 다 없으면 jpg 로 보정
        String ext;
        String resolvedContentType;
        if ("image/png".equals(contentType) || lowerName.endsWith(".png")) {
            ext = ".png";
            resolvedContentType = "image/png";
        } else if ("image/webp".equals(contentType) || lowerName.endsWith(".webp")) {
            ext = ".webp";
            resolvedContentType = "image/webp";
        } else {
            ext = ".jpg";
            resolvedContentType = "image/jpeg";
        }

        String key = "study-images/user_" + userId + "/" + UUID.randomUUID() + ext;
        try {
            PutObjectRequest putObjectRequest = PutObjectRequest.builder()
                    .bucket(bucket)
                    .key(key)
                    .contentType(resolvedContentType)
                    .build();

            s3Client.putObject(putObjectRequest, RequestBody.fromBytes(file.getBytes()));
            log.info("[S3 대표 이미지 업로드 완료] 대표 이미지가 정상 업로드되었습니다: {}", key);
            return key;
        } catch (Exception e) {
            log.error("[S3 대표 이미지 업로드 에러] S3 업로드 중 예외가 발생했습니다: ", e);
            throw new RuntimeException("AWS S3 파일 업로드에 실패했습니다.", e);
        }
    }

    public String uploadBlogFile(MultipartFile file, Long userId) throws IOException {
        String contentType = file.getContentType();
        if (contentType == null) {
            throw new IllegalArgumentException("파일 타입을 확인할 수 없습니다.");
        }

        String extension = "";
        if (contentType.equals("application/pdf")) {
            extension = ".pdf";
        } else if (contentType.equals("image/jpeg") || contentType.equals("image/jpg")) {
            extension = ".jpg";
        } else if (contentType.equals("image/png")) {
            extension = ".png";
        } else if (contentType.equals("image/gif")) {
            extension = ".gif";
        } else if (contentType.equals("image/webp")) {
            extension = ".webp";
        } else {
            throw new IllegalArgumentException("지원하지 않는 파일 형식입니다. (PDF 및 이미지 파일만 가능)");
        }

        String fileName = "blogs/user_" + userId + "/" + UUID.randomUUID() + extension;

        try {
            PutObjectRequest putObjectRequest = PutObjectRequest.builder()
                    .bucket(bucket)
                    .key(fileName)
                    .contentType(contentType)
                    .build();

            s3Client.putObject(putObjectRequest, RequestBody.fromBytes(file.getBytes()));
            log.info("[S3 블로그 파일 업로드 완료] 파일이 S3 버킷에 정상 업로드되었습니다: {}", fileName);
            return fileName;
        } catch (Exception e) {
            log.error("[S3 블로그 파일 업로드 에러] S3 업로드 중 예외가 발생했습니다: ", e);
            throw new RuntimeException("AWS S3 파일 업로드에 실패했습니다.", e);
        }
    }

    public String getPresignedUrl(String s3Key) {
        return getPresignedUrl(s3Key, null);
    }

    public String getPresignedUrl(String s3Key, String originalFileName) {
        if (s3Key == null || s3Key.isEmpty()) {
            return null;
        }

        try {
            GetObjectPresignRequest presignRequest = GetObjectPresignRequest.builder()
                    .signatureDuration(Duration.ofHours(1))
                    .getObjectRequest(builder -> {
                        builder.bucket(bucket).key(s3Key);
                        if (originalFileName != null && !originalFileName.isEmpty()) {
                            String encoded = java.net.URLEncoder.encode(originalFileName, java.nio.charset.StandardCharsets.UTF_8)
                                    .replaceAll("\\+", "%20");
                            builder.responseContentDisposition("inline; filename=\"" + encoded + "\"; filename*=UTF-8''" + encoded);
                        }
                    })
                    .build();

            PresignedGetObjectRequest presignedRequest = s3Presigner.presignGetObject(presignRequest);
            return presignedRequest.url().toString();
        } catch (Exception e) {
            log.error("[S3 Presign 에러] 임시 URL 발급 중 예외가 발생했습니다: ", e);
            throw new RuntimeException("AWS S3 Presigned URL 생성에 실패했습니다.", e);
        }
    }

    /**
     * 바이트 배열을 임의의 키/콘텐츠 타입으로 S3에 업로드한다.
     * (MultipartFile 이 아닌 서버 생성물 - 배너 이미지, 플래너 PDF 등에 사용)
     */
    public String uploadBytes(byte[] data, String key, String contentType) {
        try {
            PutObjectRequest putObjectRequest = PutObjectRequest.builder()
                    .bucket(bucket)
                    .key(key)
                    .contentType(contentType)
                    .build();
            s3Client.putObject(putObjectRequest, RequestBody.fromBytes(data));
            log.info("[S3 업로드 완료] 서버 생성 파일 업로드: {} ({} bytes)", key, data.length);
            return key;
        } catch (Exception e) {
            log.error("[S3 업로드 에러] 바이트 업로드 중 예외가 발생했습니다: ", e);
            throw new RuntimeException("AWS S3 업로드에 실패했습니다.", e);
        }
    }

    public byte[] downloadBytes(String key) {
        return s3Client.getObjectAsBytes(software.amazon.awssdk.services.s3.model.GetObjectRequest.builder()
                .bucket(bucket).key(key).build()).asByteArray();
    }

    public String getDownloadPresignedUrl(String key, String fileName) {
        String disposition = org.springframework.http.ContentDisposition.attachment()
                .filename(fileName, java.nio.charset.StandardCharsets.UTF_8).build().toString();
        return s3Presigner.presignGetObject(GetObjectPresignRequest.builder()
                .signatureDuration(Duration.ofMinutes(15))
                .getObjectRequest(b -> b.bucket(bucket).key(key).responseContentType("application/pdf")
                        .responseContentDisposition(disposition)).build()).url().toString();
    }

    /** 객체 존재 여부 확인 (배너 동기화 idempotent 처리용) */
    public boolean doesObjectExist(String key) {
        if (key == null || key.isEmpty()) {
            return false;
        }
        try {
            s3Client.headObject(HeadObjectRequest.builder().bucket(bucket).key(key).build());
            return true;
        } catch (NoSuchKeyException e) {
            return false;
        } catch (S3Exception e) {
            if (e.statusCode() == 404) {
                return false;
            }
            log.warn("[S3 headObject 경고] 객체 존재 확인 실패 key={}, status={}", key, e.statusCode());
            return false;
        }
    }

    public void deleteFile(String s3Key) {
        if (s3Key == null || s3Key.isEmpty()) {
            return;
        }

        try {
            DeleteObjectRequest deleteObjectRequest = DeleteObjectRequest.builder()
                    .bucket(bucket)
                    .key(s3Key)
                    .build();
            s3Client.deleteObject(deleteObjectRequest);
            log.info("[S3 삭제 완료] 파일이 S3 버킷에서 정상 삭제되었습니다: {}", s3Key);
        } catch (Exception e) {
            log.error("[S3 삭제 에러] S3 삭제 중 오류가 발생했습니다: ", e);
            throw new RuntimeException("AWS S3 파일 삭제에 실패했습니다.", e);
        }
    }
}