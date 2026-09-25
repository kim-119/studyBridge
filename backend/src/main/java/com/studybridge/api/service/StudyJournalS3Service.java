package com.studybridge.api.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.DeleteObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.ServerSideEncryption;

import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Map;

/**
 * 학습일지 전용 S3 입출력.
 *
 * 기존 S3Service/S3Config(S3Client 빈)를 재사용하되, 학습일지 전용 bucket/prefix/SSE는 별도 설정으로 분리한다.
 * - bucket/region/prefix/SSE 모드/KMS 키는 환경변수(STUDY_JOURNAL_S3_*)로 관리. 하드코딩 금지.
 * - bucket 미지정 시 기존 자료 버킷(cloud.aws.s3.bucket)을 사용한다.
 * - Server-side encryption: KMS 키가 있으면 SSE-KMS, 없으면 SSE-S3(AES256).
 * - 자격증명은 코드에 두지 않는다(IAM Role 또는 기존 환경변수 방식 — S3Config가 처리).
 *
 * S3 lifecycle(예: 1년 후 IA, 3년 후 Glacier, 만료)은 코드에서 생성하지 않는다 — 별도 운영 작업 필요.
 */
@Slf4j
@Service
public class StudyJournalS3Service {

    private final S3Client s3Client;
    private final String bucket;
    private final String prefix;
    private final String sseMode;       // KMS | S3 (대소문자 무시)
    private final String kmsKeyId;

    public StudyJournalS3Service(
            S3Client s3Client,
            @Value("${STUDY_JOURNAL_S3_BUCKET:}") String journalBucket,
            @Value("${cloud.aws.s3.bucket:}") String defaultBucket,
            @Value("${STUDY_JOURNAL_S3_PREFIX:study-journals}") String prefix,
            @Value("${STUDY_JOURNAL_S3_SSE_MODE:S3}") String sseMode,
            @Value("${STUDY_JOURNAL_S3_KMS_KEY_ID:}") String kmsKeyId) {
        this.s3Client = s3Client;
        // 전용 버킷 미설정(빈 env 포함) 시 기존 자료 버킷으로 폴백.
        this.bucket = (journalBucket == null || journalBucket.isBlank()) ? defaultBucket : journalBucket;
        // prefix 끝 슬래시 정규화
        this.prefix = (prefix == null || prefix.isBlank()) ? "study-journals" : prefix.replaceAll("/+$", "");
        this.sseMode = (sseMode == null || sseMode.isBlank()) ? "S3" : sseMode;
        this.kmsKeyId = kmsKeyId;
    }

    /** study-journals/user-{userId}/material-{materialId}/yyyy/MM/dd/{uuid}.json */
    public String buildKey(Long userId, Long materialId, String uuid) {
        LocalDate now = LocalDate.now();
        String datePath = now.format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
        return String.format("%s/user-%d/material-%d/%s/%s.json",
                prefix, userId, materialId, datePath, uuid);
    }

    /**
     * 검증 통과한 학습일지 JSON을 SSE 적용하여 S3에 저장한다.
     * object metadata에는 비민감 식별값만 넣는다(원문/비밀값 금지).
     */
    public void putJournalJson(String key, byte[] json, Map<String, String> metadata) {
        PutObjectRequest.Builder req = PutObjectRequest.builder()
                .bucket(bucket)
                .key(key)
                .contentType("application/json")
                .metadata(metadata);

        if (kmsKeyId != null && !kmsKeyId.isBlank()) {
            req.serverSideEncryption(ServerSideEncryption.AWS_KMS).ssekmsKeyId(kmsKeyId);
        } else if ("KMS".equalsIgnoreCase(sseMode)) {
            // KMS 모드인데 키 미지정 → S3 관리형 KMS 키 사용
            req.serverSideEncryption(ServerSideEncryption.AWS_KMS);
        } else {
            req.serverSideEncryption(ServerSideEncryption.AES256); // SSE-S3
        }

        s3Client.putObject(req.build(), RequestBody.fromBytes(json));
    }

    /** 학습일지 원문 JSON 본문을 읽어 문자열로 반환. */
    public String getJournalJson(String key) {
        GetObjectRequest req = GetObjectRequest.builder().bucket(bucket).key(key).build();
        ResponseBytes<GetObjectResponse> bytes = s3Client.getObjectAsBytes(req);
        return new String(bytes.asByteArray(), StandardCharsets.UTF_8);
    }

    /** 보상/삭제. 실패 시 호출측에서 s3Key만 로깅. */
    public void deleteJournal(String key) {
        s3Client.deleteObject(DeleteObjectRequest.builder().bucket(bucket).key(key).build());
    }

    public boolean isConfigured() {
        return bucket != null && !bucket.isBlank();
    }
}
