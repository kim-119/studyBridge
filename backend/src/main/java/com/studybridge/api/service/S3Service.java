package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.DeleteObjectRequest;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.GetObjectPresignRequest;
import software.amazon.awssdk.services.s3.presigner.model.PresignedGetObjectRequest;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.time.Duration;
import java.util.UUID;

@Slf4j
@Service
public class S3Service {

    private final S3Client s3Client;
    private final S3Presigner s3Presigner;

    private final String bucket;
    private final String accessKey;
    private final String secretKey;
    
    // 로컬 임시 저장 디렉토리 명칭
    private static final String LOCAL_UPLOAD_DIR = "temp-materials";

    public S3Service(S3Client s3Client, 
                     S3Presigner s3Presigner,
                     @Value("${cloud.aws.s3.bucket:}") String bucket,
                     @Value("${cloud.aws.credentials.access-key:}") String accessKey,
                     @Value("${cloud.aws.credentials.secret-key:}") String secretKey) {
        this.s3Client = s3Client;
        this.s3Presigner = s3Presigner;
        this.bucket = bucket;
        this.accessKey = accessKey;
        this.secretKey = secretKey;
    }

    private boolean isAwsConfigured() {
        return bucket != null && !bucket.trim().isEmpty() 
            && accessKey != null && !accessKey.trim().isEmpty() 
            && secretKey != null && !secretKey.trim().isEmpty();
    }

    public String uploadFile(MultipartFile file, Long userId) throws IOException {
        if (file.getContentType() == null || !file.getContentType().equals("application/pdf")) {
            throw new IllegalArgumentException("PDF 파일만 업로드 가능합니다.");
        }

        String fileName = "materials/user_" + userId + "/" + UUID.randomUUID() + ".pdf";

        if (!isAwsConfigured()) {
            log.warn("[S3 폴백 가동] AWS S3 자격 증명이 제공되지 않아 파일을 로컬 임시 저장소에 백업합니다: {}", fileName);
            saveToLocalFile(file, fileName);
            return fileName;
        }

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
            log.error("[S3 업로드 에러] S3 업로드 중 예상치 못한 예외가 발생하여 로컬로 우회 저장합니다: ", e);
            saveToLocalFile(file, fileName);
            return fileName;
        }
    }
    
    /**
     * S3에서 파일을 삭제합니다.
     * @param s3Key 삭제할 파일의 키
     */
    public void deleteFile(String s3Key) {
        if (s3Key == null || s3Key.isEmpty()) return;

        if (!isAwsConfigured()) {
            log.warn("[S3 폴백 가동] 로컬 임시 저장소에서 파일을 삭제합니다: {}", s3Key);
            deleteLocalFile(s3Key);
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
            log.error("[S3 삭제 에러] S3 파일 삭제 중 예상치 못한 예외가 발생했습니다: ", e);
        }
    }

    public String getPresignedUrl(String s3Key) {
        if (s3Key == null || s3Key.isEmpty()) return null;

        if (!isAwsConfigured()) {
            log.warn("[S3 폴백 가동] AWS S3 자격 증명이 없어 가짜 로컬 경로를 반환합니다: {}", s3Key);
            return "http://localhost:8080/temp-materials/" + s3Key.replace("materials/", "").replace("/", "_");
        }

        try {
            GetObjectPresignRequest presignRequest = GetObjectPresignRequest.builder()
                    .signatureDuration(Duration.ofHours(1))
                    .getObjectRequest(builder -> builder.bucket(bucket).key(s3Key))
                    .build();

            PresignedGetObjectRequest presignedRequest = s3Presigner.presignGetObject(presignRequest);
            return presignedRequest.url().toString();
        } catch (Exception e) {
            log.error("[S3 Presign 에러] 임시 URL 발급 오류로 가짜 로컬 경로를 반환합니다: ", e);
            return "http://localhost:8080/temp-materials/" + s3Key.replace("materials/", "").replace("/", "_");
        }
    }

    private void saveToLocalFile(MultipartFile file, String fileName) throws IOException {
        String cleanFileName = fileName.replace("materials/", "").replace("/", "_");
        File dir = new File(LOCAL_UPLOAD_DIR);
        if (!dir.exists()) {
            dir.mkdirs();
        }
        
        File localFile = new File(dir, cleanFileName);
        try (FileOutputStream fos = new FileOutputStream(localFile)) {
            fos.write(file.getBytes());
        }
        log.info("[로컬 파일 임시 백업 성공] 저장된 물리 경로: {}", localFile.getAbsolutePath());
    }
    
    private void deleteLocalFile(String s3Key) {
        String cleanFileName = s3Key.replace("materials/", "").replace("/", "_");
        File fileToDelete = new File(LOCAL_UPLOAD_DIR, cleanFileName);
        if (fileToDelete.exists()) {
            if (fileToDelete.delete()) {
                log.info("[로컬 파일 삭제 성공] 삭제된 물리 경로: {}", fileToDelete.getAbsolutePath());
            } else {
                log.error("[로컬 파일 삭제 실패] 파일 삭제에 실패했습니다: {}", fileToDelete.getAbsolutePath());
            }
        } else {
            log.warn("[로컬 파일 삭제 시도] 삭제할 파일이 존재하지 않습니다: {}", fileToDelete.getAbsolutePath());
        }
    }
}