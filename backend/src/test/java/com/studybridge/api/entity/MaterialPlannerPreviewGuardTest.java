package com.studybridge.api.entity;

import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.*;

/**
 * PLANNER 타입 영속 불변식 가드 회귀 방어.
 *
 * <p>배경: 가드가 PLANNER 의 파일 메타를 무조건 지워서, 시스템이 만든 미리보기 PDF
 * (planners/downloads/…)를 저장해도 s3_file_url 이 NULL 이 되고 상세 응답의
 * s3PresignedUrl 이 null → 프론트 PDF 뷰어가 아무것도 못 띄웠다.
 *
 * <p>계약:
 * <ul>
 *   <li>PLANNER + 생성된 미리보기 key → s3FileUrl/originalFileName 보존</li>
 *   <li>PLANNER + 그 외 PDF 메타(오염) → 기존처럼 전부 제거</li>
 *   <li>구조화 자료를 PDF 타입으로 저장하려 하면 여전히 예외</li>
 * </ul>
 */
class MaterialPlannerPreviewGuardTest {

    /** @PrePersist/@PreUpdate 콜백은 private 이므로 리플렉션으로 직접 실행한다. */
    private static void runGuard(Material m) throws Exception {
        Method mth = Material.class.getDeclaredMethod("enforceTypeInvariant");
        mth.setAccessible(true);
        mth.invoke(m);
    }

    private static final String PREVIEW_KEY = "planners/downloads/user_8/material_337.pdf";

    @Test
    void generatedPlannerPreviewKeyIsPreserved() throws Exception {
        Material m = Material.builder()
                .materialId(337L).userId(8L).title("공부 플래너")
                .materialType(MaterialType.PLANNER)
                .contentJson("{\"title\":\"공부 플래너\"}")
                .s3FileUrl(PREVIEW_KEY)
                .originalFileName("공부 플래너.pdf")
                .storedFileName(PREVIEW_KEY)
                .fileSize(12345L)
                .build();

        runGuard(m);

        assertEquals(PREVIEW_KEY, m.getS3FileUrl(), "미리보기 PDF key 가 가드에 지워졌다");
        assertEquals("공부 플래너.pdf", m.getOriginalFileName(), "presign inline 파일명이 지워졌다");
        // 미리보기에 필요 없는 필드는 계속 제거된다(최소 보존).
        assertNull(m.getStoredFileName());
        assertNull(m.getFileSize());
    }

    @Test
    void plannerDownloadKeyFromOriginalPlannerIsPreserved() throws Exception {
        Material m = Material.builder()
                .materialId(338L).userId(8L).title("공부 플래너")
                .materialType(MaterialType.PLANNER)
                .s3FileUrl("planners/downloads/user_8/2383.pdf")
                .originalFileName("공부 플래너.pdf")
                .build();

        runGuard(m);

        assertEquals("planners/downloads/user_8/2383.pdf", m.getS3FileUrl());
    }

    @Test
    void contaminatedPdfMetadataOnPlannerIsStillStripped() throws Exception {
        Material m = Material.builder()
                .materialId(339L).userId(8L).title("선형회귀")
                .materialType(MaterialType.PLANNER)
                .s3FileUrl("materials/user_8/abc/선형회귀.pdf")
                .originalFileName("선형회귀.pdf")
                .storedFileName("materials/user_8/abc/선형회귀.pdf")
                .fileSize(99999L)
                .build();

        runGuard(m);

        assertNull(m.getS3FileUrl(), "일반 PDF 오염이 보존됐다");
        assertNull(m.getOriginalFileName());
        assertNull(m.getStoredFileName());
        assertNull(m.getFileSize());
    }

    @Test
    void structuredMaterialStillCannotBeSavedAsPdfType() {
        Material m = Material.builder()
                .materialId(340L).userId(8L).title("공부 플래너")
                .materialType(MaterialType.PDF)
                .plannerId(2383L)
                .build();

        assertThrows(Exception.class, () -> runGuard(m));
    }

    @Test
    void nonPlannerMaterialIsUntouched() throws Exception {
        Material m = Material.builder()
                .materialId(341L).userId(8L).title("선형회귀")
                .materialType(MaterialType.PDF)
                .s3FileUrl("materials/user_8/abc/선형회귀.pdf")
                .originalFileName("선형회귀.pdf")
                .storedFileName("materials/user_8/abc/선형회귀.pdf")
                .fileSize(99999L)
                .build();

        runGuard(m);

        assertEquals("materials/user_8/abc/선형회귀.pdf", m.getS3FileUrl());
        assertEquals("선형회귀.pdf", m.getOriginalFileName());
        assertEquals(99999L, m.getFileSize());
    }
}
