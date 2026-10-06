package com.studybridge.api.controller;

import com.studybridge.api.dto.AppVersionDTO;
import com.studybridge.api.service.AndroidAppReleaseService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * Android 앱 자체 배포 공개 엔드포인트(인증 없음 — SecurityConfig 에서 GET /api/app/** permitAll).
 *
 *  GET /api/app/version                                   최신 릴리즈 메타데이터(JSON). 릴리즈 없음 → 404 {code:NO_RELEASE}
 *  GET /api/app/downloads/android/StudyBridge-latest.apk  302 → S3 presigned URL (nginx 가 /downloads/android/ 를 여기로 프록시)
 *  GET /api/app/downloads/android/StudyBridge-{v}.apk     302 → 버전 고정 APK presigned URL
 *
 * 모든 응답은 Cache-Control: no-store — 메타데이터/리다이렉트는 캐시하지 않는다(구버전 노출 방지).
 * APK 객체 자체의 캐시 정책은 S3 객체 Cache-Control(버전 고정 immutable / latest no-cache)이 담당한다.
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class AppVersionController {

    static final String CACHE_CONTROL_NO_STORE = "no-store, no-cache, max-age=0";
    static final String VERSION_PATTERN = "\\d+\\.\\d+(?:\\.\\d+)?";

    private final AndroidAppReleaseService releaseService;

    @GetMapping(value = "/api/app/version", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<?> version() {
        Optional<AppVersionDTO> latest = releaseService.getLatest();
        if (latest.isEmpty()) {
            return noRelease();
        }
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, CACHE_CONTROL_NO_STORE)
                .contentType(MediaType.APPLICATION_JSON)
                .body(latest.get());
    }

    @GetMapping("/api/app/downloads/android/StudyBridge-latest.apk")
    public ResponseEntity<?> downloadLatest() {
        return redirectOrNotFound(releaseService.presignLatestApk(), "latest");
    }

    @GetMapping("/api/app/downloads/android/StudyBridge-{versionName:" + VERSION_PATTERN + "}.apk")
    public ResponseEntity<?> downloadVersioned(@PathVariable String versionName) {
        return redirectOrNotFound(releaseService.presignVersionedApk(versionName), versionName);
    }

    private ResponseEntity<?> redirectOrNotFound(Optional<String> presigned, String label) {
        if (presigned.isEmpty()) {
            log.info("[AndroidRelease] APK 없음: {}", label);
            return noRelease();
        }
        return ResponseEntity.status(HttpStatus.FOUND)
                .header(HttpHeaders.CACHE_CONTROL, CACHE_CONTROL_NO_STORE)
                .location(URI.create(presigned.get()))
                .build();
    }

    private ResponseEntity<Map<String, Object>> noRelease() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", 404);
        body.put("code", "NO_RELEASE");
        body.put("message", "배포된 Android 릴리즈가 아직 없습니다.");
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .header(HttpHeaders.CACHE_CONTROL, CACHE_CONTROL_NO_STORE)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body);
    }
}
