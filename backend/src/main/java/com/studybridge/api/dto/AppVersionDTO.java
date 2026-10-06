package com.studybridge.api.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * GET /api/app/version 공개 계약(인증 없음, 개인정보 없음).
 *
 * 원천은 S3 {prefix}latest/version.json (ops/android/publish-android-release.py 가 릴리즈 마지막 단계에 기록).
 * 이 클래스는 그 JSON 을 그대로 역직렬화하는 동시에 API 응답 본문이다. 필수 필드:
 *   platform, packageName, versionCode, versionName, downloadUrl, releaseDate, releaseNotes, forceUpdate, minimumSupportedVersionCode
 * 추가 필드(sha256, fileSize, versionedDownloadUrl)는 무결성 검증/장기 캐시 링크용이며 없을 수 있다.
 * 모르는 필드는 무시한다(메타데이터 스키마가 먼저 확장되어도 서버가 깨지지 않도록).
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AppVersionDTO {

    public static final String PLATFORM_ANDROID = "android";

    private String platform;
    private String packageName;
    private Integer versionCode;
    private String versionName;
    /** 항상 동일한 안정 URL(.../downloads/android/StudyBridge-latest.apk). 새 릴리즈가 나와도 바뀌지 않는다. */
    private String downloadUrl;
    /** ISO-8601 offset date-time 문자열(예: 2026-10-06T21:00:00+09:00). 파싱하지 않고 그대로 전달한다. */
    private String releaseDate;
    private List<String> releaseNotes;
    private Boolean forceUpdate;
    private Integer minimumSupportedVersionCode;

    /** 릴리즈 APK SHA-256(hex). 앱/사용자가 다운로드 무결성을 검증할 수 있다. */
    private String sha256;
    private Long fileSize;
    /** 버전 고정 URL(.../downloads/android/StudyBridge-1.0.1.apk). 장기 캐시 가능. */
    private String versionedDownloadUrl;
}
