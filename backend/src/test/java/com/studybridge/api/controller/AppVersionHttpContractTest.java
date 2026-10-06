package com.studybridge.api.controller;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.studybridge.api.dto.AppVersionDTO;
import com.studybridge.api.exception.GlobalExceptionHandler;
import com.studybridge.api.service.AndroidAppReleaseService;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/**
 * HTTP 계약: GET /api/app/version 200(필수 9필드 + no-store) / 404 NO_RELEASE JSON,
 * /api/app/downloads/android/StudyBridge-latest.apk 및 StudyBridge-{v}.apk 302 Location(presigned) / 404.
 * (인증 면제는 SecurityConfig permitAll — 여기서는 컨트롤러 계약만 고정한다.)
 */
class AppVersionHttpContractTest {

    private MockMvc mvc;
    private AndroidAppReleaseService service;

    @BeforeEach
    void setUp() {
        service = mock(AndroidAppReleaseService.class);
        mvc = MockMvcBuilders.standaloneSetup(new AppVersionController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    private static AppVersionDTO sample() {
        return AppVersionDTO.builder()
                .platform("android").packageName("kr.co.studybridge.app")
                .versionCode(2).versionName("1.0.1")
                .downloadUrl("https://studybridge.co.kr/downloads/android/StudyBridge-latest.apk")
                .versionedDownloadUrl("https://studybridge.co.kr/downloads/android/StudyBridge-1.0.1.apk")
                .releaseDate("2026-10-06T21:00:00+09:00")
                .releaseNotes(List.of("모바일 안정성 개선", "회원가입 오류 수정"))
                .forceUpdate(false).minimumSupportedVersionCode(1)
                .sha256("deadbeef").fileSize(19196753L)
                .build();
    }

    @Test
    void version_200_contract_fields_and_no_store() throws Exception {
        when(service.getLatest()).thenReturn(Optional.of(sample()));

        mvc.perform(get("/api/app/version"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(header().string("Cache-Control", "no-store, no-cache, max-age=0"))
                .andExpect(jsonPath("$.platform").value("android"))
                .andExpect(jsonPath("$.packageName").value("kr.co.studybridge.app"))
                .andExpect(jsonPath("$.versionCode").value(2))
                .andExpect(jsonPath("$.versionName").value("1.0.1"))
                .andExpect(jsonPath("$.downloadUrl").value("https://studybridge.co.kr/downloads/android/StudyBridge-latest.apk"))
                .andExpect(jsonPath("$.releaseDate").value("2026-10-06T21:00:00+09:00"))
                .andExpect(jsonPath("$.releaseNotes[0]").value("모바일 안정성 개선"))
                .andExpect(jsonPath("$.releaseNotes[1]").value("회원가입 오류 수정"))
                .andExpect(jsonPath("$.forceUpdate").value(false))
                .andExpect(jsonPath("$.minimumSupportedVersionCode").value(1))
                .andExpect(jsonPath("$.sha256").value("deadbeef"))
                .andExpect(jsonPath("$.fileSize").value(19196753));
    }

    @Test
    void version_404_json_when_no_release() throws Exception {
        when(service.getLatest()).thenReturn(Optional.empty());

        mvc.perform(get("/api/app/version"))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(header().string("Cache-Control", "no-store, no-cache, max-age=0"))
                .andExpect(jsonPath("$.status").value(404))
                .andExpect(jsonPath("$.code").value("NO_RELEASE"));
    }

    @Test
    void latestApk_302_to_presigned_or_404() throws Exception {
        when(service.presignLatestApk()).thenReturn(Optional.of("https://bucket.s3.amazonaws.com/android/latest/StudyBridge-latest.apk?X-Amz-Signature=abc"));
        mvc.perform(get("/api/app/downloads/android/StudyBridge-latest.apk"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "https://bucket.s3.amazonaws.com/android/latest/StudyBridge-latest.apk?X-Amz-Signature=abc"))
                .andExpect(header().string("Cache-Control", "no-store, no-cache, max-age=0"));

        when(service.presignLatestApk()).thenReturn(Optional.empty());
        mvc.perform(get("/api/app/downloads/android/StudyBridge-latest.apk"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("NO_RELEASE"));
    }

    @Test
    void versionedApk_302_404_and_invalid_names_do_not_match() throws Exception {
        when(service.presignVersionedApk("1.0.1")).thenReturn(Optional.of("https://s3/v101"));
        when(service.presignVersionedApk("9.9.9")).thenReturn(Optional.empty());

        mvc.perform(get("/api/app/downloads/android/StudyBridge-1.0.1.apk"))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", "https://s3/v101"));
        mvc.perform(get("/api/app/downloads/android/StudyBridge-9.9.9.apk"))
                .andExpect(status().isNotFound());
        // 형식 외 파일명은 핸들러 자체가 없다(presign 호출 없이 404)
        mvc.perform(get("/api/app/downloads/android/StudyBridge-1.0-beta.apk"))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/app/downloads/android/other.apk"))
                .andExpect(status().isNotFound());
    }
}
