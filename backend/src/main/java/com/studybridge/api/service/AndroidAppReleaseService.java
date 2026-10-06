package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.AppVersionDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * Android 앱 자체 배포(APK) 메타데이터/다운로드 리졸버.
 *
 * 저장 구조(S3, 비공개 버킷 — 기존 자료 정책과 동일하게 presigned URL 로만 노출):
 *   {prefix}releases/StudyBridge-{versionName}.apk   버전 고정 APK (immutable, 장기 캐시)
 *   {prefix}releases/StudyBridge-{versionName}.json  버전별 매니페스트
 *   {prefix}latest/StudyBridge-latest.apk            최신 APK (no-cache)
 *   {prefix}latest/version.json                      최신 메타데이터 — 릴리즈 절차의 "가장 마지막" 에 갱신된다
 *
 * 메타데이터는 짧은 TTL(기본 30초) 로 메모리 캐시한다. 부재(아직 릴리즈 없음)도 같은 TTL 로 캐시해
 * 공개 엔드포인트가 S3 를 두드리는 빈도를 제한한다. 서버 재배포 없이 S3 파일만 갱신하면 새 버전이 노출된다.
 */
@Slf4j
@Service
public class AndroidAppReleaseService {

    public static final String LATEST_APK_FILE_NAME = "StudyBridge-latest.apk";
    public static final String APK_CONTENT_TYPE = "application/vnd.android.package-archive";
    public static final String DOWNLOAD_PATH = "/downloads/android/";
    /** versionName 허용 형식: 1.0 / 1.0.1 (숫자와 점만 — S3 키/파일명 주입 방지) */
    static final Pattern VERSION_NAME = Pattern.compile("^\\d+\\.\\d+(?:\\.\\d+)?$");

    private final S3Service s3Service;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final String prefix;
    private final String publicBaseUrl;
    private final String expectedPackageName;
    private final long cacheMillis;
    private final Duration presignDuration;

    private volatile CacheEntry cache;

    private record CacheEntry(long expiresAtMillis, Optional<AppVersionDTO> value) {}

    // 생성자가 둘(운영용/테스트용)이라 Spring 이 고를 생성자를 명시한다 — 없으면 "No default constructor found" 로 기동 실패.
    @Autowired
    public AndroidAppReleaseService(S3Service s3Service,
                                    ObjectMapper objectMapper,
                                    @Value("${app.android.release.s3-prefix:android/}") String prefix,
                                    @Value("${app.android.release.public-base-url:https://studybridge.co.kr}") String publicBaseUrl,
                                    @Value("${app.android.release.package-name:kr.co.studybridge.app}") String expectedPackageName,
                                    @Value("${app.android.release.metadata-cache-seconds:30}") long cacheSeconds,
                                    @Value("${app.android.release.presign-minutes:15}") long presignMinutes) {
        this(s3Service, objectMapper, Clock.systemUTC(), prefix, publicBaseUrl, expectedPackageName, cacheSeconds, presignMinutes);
    }

    AndroidAppReleaseService(S3Service s3Service, ObjectMapper objectMapper, Clock clock, String prefix, String publicBaseUrl,
                             String expectedPackageName, long cacheSeconds, long presignMinutes) {
        this.s3Service = s3Service;
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.prefix = normalizePrefix(prefix);
        this.publicBaseUrl = publicBaseUrl == null ? "" : publicBaseUrl.replaceAll("/+$", "");
        this.expectedPackageName = expectedPackageName;
        this.cacheMillis = Math.max(0, cacheSeconds) * 1000L;
        this.presignDuration = Duration.ofMinutes(Math.max(1, presignMinutes));
    }

    private static String normalizePrefix(String p) {
        if (p == null || p.isBlank()) return "";
        String s = p.replaceAll("^/+", "");
        return s.endsWith("/") ? s : s + "/";
    }

    public String latestMetadataKey() { return prefix + "latest/version.json"; }
    public String latestApkKey() { return prefix + "latest/" + LATEST_APK_FILE_NAME; }
    public String versionedApkKey(String versionName) { return prefix + "releases/StudyBridge-" + versionName + ".apk"; }
    public String latestDownloadUrl() { return publicBaseUrl + DOWNLOAD_PATH + LATEST_APK_FILE_NAME; }
    public String versionedDownloadUrl(String versionName) { return publicBaseUrl + DOWNLOAD_PATH + "StudyBridge-" + versionName + ".apk"; }

    public static boolean isValidVersionName(String versionName) {
        return versionName != null && VERSION_NAME.matcher(versionName).matches();
    }

    /** 최신 릴리즈 메타데이터. 아직 릴리즈가 없거나(메타데이터 부재) 손상된 경우 empty. */
    public Optional<AppVersionDTO> getLatest() {
        CacheEntry c = cache;
        long now = clock.millis();
        if (c != null && now < c.expiresAtMillis()) {
            return c.value();
        }
        Optional<AppVersionDTO> loaded = loadLatest();
        cache = new CacheEntry(now + cacheMillis, loaded);
        return loaded;
    }

    public void invalidateCache() {
        cache = null;
    }

    private Optional<AppVersionDTO> loadLatest() {
        String key = latestMetadataKey();
        Optional<byte[]> raw;
        try {
            raw = s3Service.downloadBytesIfExists(key);
        } catch (Exception e) {
            log.warn("[AndroidRelease] 메타데이터 조회 실패 key={} : {}", key, e.toString());
            return Optional.empty();
        }
        if (raw.isEmpty()) {
            return Optional.empty();
        }
        try {
            AppVersionDTO dto = objectMapper.readValue(raw.get(), AppVersionDTO.class);
            return normalize(dto);
        } catch (Exception e) {
            log.warn("[AndroidRelease] 메타데이터 파싱 실패 key={} : {}", key, e.toString());
            return Optional.empty();
        }
    }

    /** 필수 필드 검증 + 기본값 보정. versionCode/versionName 이 없으면 릴리즈로 취급하지 않는다. */
    Optional<AppVersionDTO> normalize(AppVersionDTO dto) {
        if (dto == null || dto.getVersionCode() == null || dto.getVersionCode() <= 0
                || !isValidVersionName(dto.getVersionName())) {
            log.warn("[AndroidRelease] 메타데이터 필수 필드 불량: versionCode={}, versionName={}",
                    dto == null ? null : dto.getVersionCode(), dto == null ? null : dto.getVersionName());
            return Optional.empty();
        }
        if (dto.getPackageName() != null && !dto.getPackageName().isBlank()
                && !dto.getPackageName().equals(expectedPackageName)) {
            log.warn("[AndroidRelease] packageName 불일치: metadata={} expected={}", dto.getPackageName(), expectedPackageName);
            return Optional.empty();
        }
        dto.setPlatform(AppVersionDTO.PLATFORM_ANDROID);
        dto.setPackageName(expectedPackageName);
        // 공개 URL 은 서버 설정이 단일 출처다(메타데이터가 다른 호스트를 적어도 운영 도메인으로 고정).
        dto.setDownloadUrl(latestDownloadUrl());
        dto.setVersionedDownloadUrl(versionedDownloadUrl(dto.getVersionName()));
        if (dto.getReleaseNotes() == null) dto.setReleaseNotes(List.of());
        if (dto.getForceUpdate() == null) dto.setForceUpdate(false);
        if (dto.getMinimumSupportedVersionCode() == null || dto.getMinimumSupportedVersionCode() <= 0) {
            dto.setMinimumSupportedVersionCode(1);
        }
        if (dto.getMinimumSupportedVersionCode() > dto.getVersionCode()) {
            dto.setMinimumSupportedVersionCode(dto.getVersionCode());
        }
        return Optional.of(dto);
    }

    /** 최신 APK presigned URL(짧은 TTL). 릴리즈가 없으면 empty. 파일명은 버전 고정명으로 내려 저장 시 구분된다. */
    public Optional<String> presignLatestApk() {
        Optional<AppVersionDTO> latest = getLatest();
        if (latest.isEmpty()) {
            return Optional.empty();
        }
        String fileName = "StudyBridge-" + latest.get().getVersionName() + ".apk";
        return Optional.of(s3Service.getDownloadPresignedUrl(latestApkKey(), fileName, APK_CONTENT_TYPE, presignDuration));
    }

    /** 버전 고정 APK presigned URL. 형식이 틀리거나 객체가 없으면 empty. */
    public Optional<String> presignVersionedApk(String versionName) {
        if (!isValidVersionName(versionName)) {
            return Optional.empty();
        }
        String key = versionedApkKey(versionName);
        if (!s3Service.doesObjectExist(key)) {
            return Optional.empty();
        }
        return Optional.of(s3Service.getDownloadPresignedUrl(key, "StudyBridge-" + versionName + ".apk", APK_CONTENT_TYPE, presignDuration));
    }
}
