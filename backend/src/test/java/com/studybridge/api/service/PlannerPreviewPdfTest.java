package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.repository.FolderRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlannerRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.lang.reflect.Method;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 플래너 보관 항목 미리보기 PDF 회귀 방어.
 *
 * <p>증상: PDF 는 S3 에 정상 생성되는데(planners/downloads/user_8/material_337.pdf)
 * DB s3_file_url 이 NULL 이라 상세 응답 s3PresignedUrl 이 null → 뷰어가 못 뜬다.
 * 원인은 Material 의 PLANNER 불변식 가드가 저장 직전에 파일 메타를 전부 지운 것.
 */
class PlannerPreviewPdfTest {

    private static final long USER_ID = 8L;
    private static final long MATERIAL_ID = 337L;

    private PlannerRepository plannerRepository;
    private MaterialRepository materialRepository;
    private FolderRepository folderRepository;
    private S3Service s3Service;
    private PlannerService service;

    @BeforeEach
    void setUp() {
        plannerRepository = mock(PlannerRepository.class);
        materialRepository = mock(MaterialRepository.class);
        folderRepository = mock(FolderRepository.class);
        s3Service = mock(S3Service.class);
        service = new PlannerService(plannerRepository, materialRepository, s3Service, new ObjectMapper(), folderRepository);
        when(plannerRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
        when(materialRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
    }

    /** 영속 콜백은 Mockito 저장소에서 실행되지 않으므로 직접 돌려 DB 저장 결과를 재현한다. */
    private static void runPersistGuard(Material m) throws Exception {
        Method mth = Material.class.getDeclaredMethod("enforceTypeInvariant");
        mth.setAccessible(true);
        mth.invoke(m);
    }

    private Material detachedPlannerArchive() {
        return Material.builder()
                .materialId(MATERIAL_ID).userId(USER_ID).title("공부 플래너")
                .materialType(MaterialType.PLANNER)
                .contentJson("{\"title\":\"공부 플래너\",\"subject\":\"선형회귀\",\"content\":\"1장 복습\"}")
                .build();
    }

    @Test
    void ensurePreviewPdf_uploadsUnderPlannerDownloadsPrefixAndKeepsKeyAfterPersist() throws Exception {
        Material material = detachedPlannerArchive();

        service.ensurePreviewPdf(material);

        ArgumentCaptor<String> key = ArgumentCaptor.forClass(String.class);
        verify(s3Service).uploadBytes(any(byte[].class), key.capture(), eq("application/pdf"));
        assertEquals("planners/downloads/user_8/material_337.pdf", key.getValue());
        assertEquals(key.getValue(), material.getS3FileUrl(), "s3FileUrl 에 object key 가 설정되지 않음");

        // DB 저장 경계(@PrePersist/@PreUpdate)를 통과해도 key 가 살아남아야 한다.
        runPersistGuard(material);
        assertNotNull(material.getS3FileUrl(), "영속 가드가 미리보기 key 를 지웠다(= s3PresignedUrl null 원인)");
        assertEquals("planners/downloads/user_8/material_337.pdf", material.getS3FileUrl());
    }

    @Test
    void ensurePreviewPdf_isIdempotentWhenKeyAlreadyStored() {
        Material material = detachedPlannerArchive();
        material.setS3FileUrl("planners/downloads/user_8/material_337.pdf");

        service.ensurePreviewPdf(material);

        verify(s3Service, never()).uploadBytes(any(), any(), any());
    }

    @Test
    void ensurePreviewPdf_withOriginalPlannerUsesPlannerS3Key() {
        Material material = detachedPlannerArchive();
        material.setPlannerId(2383L);
        Planner planner = Planner.builder().id(2383L).userId(USER_ID).title("공부 플래너").build();
        when(plannerRepository.findById(2383L)).thenReturn(Optional.of(planner));

        service.ensurePreviewPdf(material);

        ArgumentCaptor<String> key = ArgumentCaptor.forClass(String.class);
        verify(s3Service).uploadBytes(any(byte[].class), key.capture(), eq("application/pdf"));
        assertEquals("planners/downloads/user_8/2383.pdf", key.getValue());
        assertEquals(key.getValue(), planner.getS3Key());
    }

    @Test
    void ensurePreviewPdf_ignoresNonPlannerMaterial() {
        Material pdf = Material.builder().materialId(299L).userId(USER_ID).title("선형회귀")
                .materialType(MaterialType.PDF).build();

        service.ensurePreviewPdf(pdf);

        verify(s3Service, never()).uploadBytes(any(), any(), any());
    }
}
