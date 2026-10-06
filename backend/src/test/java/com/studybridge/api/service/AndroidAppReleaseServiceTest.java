package com.studybridge.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.AppVersionDTO;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * S3 latest/version.json → /api/app/version 계약 정규화, 부재/손상/패키지 불일치 → empty, TTL 캐시, 버전 키 검증.
 */
class AndroidAppReleaseServiceTest {

    private static final String META = """
            {"platform":"android","packageName":"kr.co.studybridge.app","versionCode":2,"versionName":"1.0.1",
             "downloadUrl":"https://wrong.example/x.apk","releaseDate":"2026-10-06T21:00:00+09:00",
             "releaseNotes":["모바일 안정성 개선","회원가입 오류 수정"],"forceUpdate":false,"minimumSupportedVersionCode":1,
             "sha256":"abc","fileSize":123,"unknownFutureField":"ignored"}
            """;

    private S3Service s3;
    private MutableClock clock;
    private AndroidAppReleaseService service;

    static final class MutableClock extends Clock {
        Instant now = Instant.parse("2026-10-06T12:00:00Z");
        @Override public ZoneOffset getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(java.time.ZoneId zone) { return this; }
        @Override public Instant instant() { return now; }
    }

    @BeforeEach
    void setUp() {
        s3 = mock(S3Service.class);
        clock = new MutableClock();
        service = new AndroidAppReleaseService(s3, new ObjectMapper(), clock, "android/",
                "https://studybridge.co.kr/", "kr.co.studybridge.app", 30, 15);
    }

    @Test
    void keys_follow_release_layout_and_prefix_is_normalized() {
        assertThat(service.latestMetadataKey()).isEqualTo("android/latest/version.json");
        assertThat(service.latestApkKey()).isEqualTo("android/latest/StudyBridge-latest.apk");
        assertThat(service.versionedApkKey("1.0.1")).isEqualTo("android/releases/StudyBridge-1.0.1.apk");
        AndroidAppReleaseService noSlash = new AndroidAppReleaseService(s3, new ObjectMapper(), clock, "/android",
                "https://studybridge.co.kr", "kr.co.studybridge.app", 30, 15);
        assertThat(noSlash.latestMetadataKey()).isEqualTo("android/latest/version.json");
    }

    @Test
    void latest_parses_metadata_and_pins_public_urls() {
        when(s3.downloadBytesIfExists("android/latest/version.json"))
                .thenReturn(Optional.of(META.getBytes(StandardCharsets.UTF_8)));

        Optional<AppVersionDTO> latest = service.getLatest();

        assertThat(latest).isPresent();
        AppVersionDTO dto = latest.get();
        assertThat(dto.getPlatform()).isEqualTo("android");
        assertThat(dto.getPackageName()).isEqualTo("kr.co.studybridge.app");
        assertThat(dto.getVersionCode()).isEqualTo(2);
        assertThat(dto.getVersionName()).isEqualTo("1.0.1");
        // 메타데이터의 downloadUrl 이 아니라 서버 설정의 안정 URL 로 고정된다(trailing slash 정리 포함)
        assertThat(dto.getDownloadUrl()).isEqualTo("https://studybridge.co.kr/downloads/android/StudyBridge-latest.apk");
        assertThat(dto.getVersionedDownloadUrl()).isEqualTo("https://studybridge.co.kr/downloads/android/StudyBridge-1.0.1.apk");
        assertThat(dto.getReleaseNotes()).containsExactly("모바일 안정성 개선", "회원가입 오류 수정");
        assertThat(dto.getForceUpdate()).isFalse();
        assertThat(dto.getMinimumSupportedVersionCode()).isEqualTo(1);
        assertThat(dto.getSha256()).isEqualTo("abc");
        assertThat(dto.getFileSize()).isEqualTo(123L);
    }

    @Test
    void latest_defaults_optional_fields() {
        String minimal = "{\"versionCode\":5,\"versionName\":\"2.0\",\"minimumSupportedVersionCode\":9}";
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.of(minimal.getBytes(StandardCharsets.UTF_8)));

        AppVersionDTO dto = service.getLatest().orElseThrow();

        assertThat(dto.getReleaseNotes()).isEmpty();
        assertThat(dto.getForceUpdate()).isFalse();
        // minimumSupportedVersionCode 가 최신 versionCode 보다 클 수 없다
        assertThat(dto.getMinimumSupportedVersionCode()).isEqualTo(5);
        assertThat(dto.getPackageName()).isEqualTo("kr.co.studybridge.app");
    }

    @Test
    void latest_is_empty_when_missing_corrupt_or_wrong_package() {
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.empty());
        assertThat(service.getLatest()).isEmpty();

        service.invalidateCache();
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.of("{not json".getBytes(StandardCharsets.UTF_8)));
        assertThat(service.getLatest()).isEmpty();

        service.invalidateCache();
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.of(
                "{\"versionCode\":1,\"versionName\":\"1.0\",\"packageName\":\"com.evil.app\"}".getBytes(StandardCharsets.UTF_8)));
        assertThat(service.getLatest()).isEmpty();

        service.invalidateCache();
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.of(
                "{\"versionCode\":1,\"versionName\":\"1.0-beta\"}".getBytes(StandardCharsets.UTF_8)));
        assertThat(service.getLatest()).isEmpty();

        service.invalidateCache();
        when(s3.downloadBytesIfExists(anyString())).thenThrow(new RuntimeException("s3 down"));
        assertThat(service.getLatest()).isEmpty();
    }

    @Test
    void latest_is_cached_for_ttl_including_negative_result() {
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.empty());
        service.getLatest();
        service.getLatest();
        verify(s3, times(1)).downloadBytesIfExists(anyString());

        clock.now = clock.now.plusSeconds(31);
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.of(META.getBytes(StandardCharsets.UTF_8)));
        assertThat(service.getLatest()).isPresent();
        verify(s3, times(2)).downloadBytesIfExists(anyString());
    }

    @Test
    void presignLatest_uses_latest_key_with_versioned_filename_and_apk_content_type() {
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.of(META.getBytes(StandardCharsets.UTF_8)));
        when(s3.getDownloadPresignedUrl(eq("android/latest/StudyBridge-latest.apk"), eq("StudyBridge-1.0.1.apk"),
                eq("application/vnd.android.package-archive"), eq(Duration.ofMinutes(15))))
                .thenReturn("https://s3/presigned");

        assertThat(service.presignLatestApk()).contains("https://s3/presigned");
    }

    @Test
    void presignLatest_is_empty_without_release() {
        when(s3.downloadBytesIfExists(anyString())).thenReturn(Optional.empty());
        assertThat(service.presignLatestApk()).isEmpty();
        verify(s3, never()).getDownloadPresignedUrl(anyString(), anyString(), anyString(), any());
    }

    @Test
    void presignVersioned_validates_version_and_existence() {
        assertThat(service.presignVersionedApk("../latest/x")).isEmpty();
        assertThat(service.presignVersionedApk("1.0-beta")).isEmpty();
        assertThat(service.presignVersionedApk(null)).isEmpty();
        verify(s3, never()).doesObjectExist(anyString());

        when(s3.doesObjectExist("android/releases/StudyBridge-1.0.1.apk")).thenReturn(false);
        assertThat(service.presignVersionedApk("1.0.1")).isEmpty();

        when(s3.doesObjectExist("android/releases/StudyBridge-1.0.1.apk")).thenReturn(true);
        when(s3.getDownloadPresignedUrl(eq("android/releases/StudyBridge-1.0.1.apk"), eq("StudyBridge-1.0.1.apk"),
                eq("application/vnd.android.package-archive"), any())).thenReturn("https://s3/v");
        assertThat(service.presignVersionedApk("1.0.1")).contains("https://s3/v");
    }
}
