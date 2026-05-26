package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.DeleteObjectRequest;
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
        if (file.getContentType() == null || !file.getContentType().equals("application/pdf")) {
            throw new IllegalArgumentException("PDF 파일만 업로드 가능합니다.");
        }

        String fileName = "materials/user_" + userId + "/" + UUID.randomUUID() + ".pdf";

        try {
            PutObjectRequest putObjectRequest = PutObjectRequest.builder()
                    .bucket(bucket)
                    .key(fileName)
                    .contentType(file.getContentType())
                    .build();

            s3Client.putObject(putObjectRequest, RequestBody.fromBytes(file.getBytes()));
            log.info("[S3 업로드 완료] 파일이 S3 버킷에 정상 업로드되었습니다: {}", fileName);
            return fileName;
        } catch (Exception e) {
            log.error("[S3 업로드 에러] S3 업로드 중 예외가 발생했습니다: ", e);
            throw new RuntimeException("AWS S3 파일 업로드에 실패했습니다.", e);
        }
    }

    public String getPresignedUrl(String s3Key) {
        if (s3Key == null || s3Key.isEmpty()) {
            return null;
        }

        try {
            GetObjectPresignRequest presignRequest = GetObjectPresignRequest.builder()
                    .signatureDuration(Duration.ofHours(1))
                    .getObjectRequest(builder -> builder.bucket(bucket).key(s3Key))
                    .build();

            PresignedGetObjectRequest presignedRequest = s3Presigner.presignGetObject(presignRequest);
            return presignedRequest.url().toString();
        } catch (Exception e) {
            log.error("[S3 Presign 에러] 임시 URL 발급 중 예외가 발생했습니다: ", e);
            throw new RuntimeException("AWS S3 Presigned URL 생성에 실패했습니다.", e);
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