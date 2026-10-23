package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.Folder;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.repository.FolderRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlannerRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 플래너 "자료보관함에 저장"(archivePlanner) 회귀 방어.
 *  - 로드맵 플래너의 materialId 는 출처 PDF 를 가리킨다 → 그 PDF 를 PLANNER 로 덮어쓰지 않고 새 보관 항목을 만든다.
 *  - 이미 있는 이 플래너의 보관 항목(PLANNER)은 재사용(갱신)한다.
 *  - 보관 항목이 플래너 도메인이 아닌 폴더(학습자료 폴더)에 있으면 루트로 옮겨 플래너 탭에 보이게 한다.
 */
class PlannerArchiveTest {

    private static final long USER_ID = 8L;

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
        when(materialRepository.save(any())).thenAnswer(inv -> {
            Material m = inv.getArgument(0);
            if (m.getMaterialId() == null) m.setMaterialId(900L);
            return m;
        });
    }

    private Planner roadmapPlanner(long id, Long materialId) {
        return Planner.builder().id(id).userId(USER_ID).plannerType(PlannerType.ROADMAP).sourceType("ROADMAP_AUTO")
                .title("[로드맵 12주차 3일] 모의 시험").subject("선형회귀").materialId(materialId).sourceMaterialId(materialId).build();
    }

    @Test
    void archiveRoadmapPlanner_createsNewItemAndNeverOverwritesSourcePdf() {
        Planner planner = roadmapPlanner(2383L, 299L);
        Material sourcePdf = Material.builder().materialId(299L).userId(USER_ID).title("선형회귀").materialType(MaterialType.PDF)
                .folderId(29L).originalFileName("선형회귀.pdf").storedFileName("materials/user_8/x/선형회귀.pdf").build();
        when(plannerRepository.findById(2383L)).thenReturn(Optional.of(planner));
        when(materialRepository.findById(299L)).thenReturn(Optional.of(sourcePdf));
        when(materialRepository.findByPlannerIdAndMaterialType(2383L, MaterialType.PLANNER)).thenReturn(List.of());

        service.archivePlanner(USER_ID, 2383L);

        ArgumentCaptor<Material> cap = ArgumentCaptor.forClass(Material.class);
        verify(materialRepository).save(cap.capture());
        Material saved = cap.getValue();
        assertNotSame(sourcePdf, saved);
        assertEquals(MaterialType.PLANNER, saved.getMaterialType());
        assertEquals(2383L, saved.getPlannerId());
        assertNull(saved.getFolderId());                                 // 플래너 탭 루트에 보인다
        assertTrue(saved.getContentJson().contains("\"plannerId\":2383"));
        // 출처 PDF 는 그대로
        assertEquals(MaterialType.PDF, sourcePdf.getMaterialType());
        assertEquals("선형회귀", sourcePdf.getTitle());
        assertEquals("선형회귀.pdf", sourcePdf.getOriginalFileName());
        assertEquals(900L, planner.getMaterialId());                     // 플래너는 새 보관 항목을 가리킨다
    }

    @Test
    void archiveAgain_reusesExistingItemAndMovesItOutOfLearningMaterialFolder() {
        Planner planner = roadmapPlanner(2383L, 299L);
        Material archive = Material.builder().materialId(700L).userId(USER_ID).materialType(MaterialType.PLANNER)
                .plannerId(2383L).folderId(29L).title("옛 제목").build();
        when(plannerRepository.findById(2383L)).thenReturn(Optional.of(planner));
        when(materialRepository.findByPlannerIdAndMaterialType(2383L, MaterialType.PLANNER)).thenReturn(List.of(archive));
        when(folderRepository.findById(29L)).thenReturn(Optional.of(Folder.builder().folderId(29L).userId(USER_ID).name("머신러닝").domain("LEARNING_MATERIAL").build()));

        service.archivePlanner(USER_ID, 2383L);

        verify(materialRepository).save(archive);
        assertEquals("[로드맵 12주차 3일] 모의 시험", archive.getTitle());
        assertNull(archive.getFolderId());                               // 학습자료 폴더 → 루트
        assertEquals(700L, planner.getMaterialId());
    }

    @Test
    void archiveAgain_keepsPlannerDomainFolder() {
        Planner planner = roadmapPlanner(2383L, 700L);
        Material archive = Material.builder().materialId(700L).userId(USER_ID).materialType(MaterialType.PLANNER)
                .plannerId(null).folderId(13L).title("옛 제목").build();  // 연결이 끊긴 보관 항목도 재사용
        when(plannerRepository.findById(2383L)).thenReturn(Optional.of(planner));
        when(materialRepository.findByPlannerIdAndMaterialType(2383L, MaterialType.PLANNER)).thenReturn(List.of());
        when(materialRepository.findById(700L)).thenReturn(Optional.of(archive));
        when(folderRepository.findById(13L)).thenReturn(Optional.of(Folder.builder().folderId(13L).userId(USER_ID).name("백엔드").domain("PLANNER").build()));

        service.archivePlanner(USER_ID, 2383L);

        verify(materialRepository).save(archive);
        assertEquals(13L, archive.getFolderId());
        assertEquals(2383L, archive.getPlannerId());
    }

    @Test
    void archive_generatesPreviewPdfForTheArchiveItem() {
        Planner planner = roadmapPlanner(2383L, null);
        planner.setYear(2026); planner.setMonth(11); planner.setDay(26);
        planner.setContent("[오늘 목표] 선형회귀의 모의 시험을 응용 문제 풀이 중심으로 학습한다.\n\n[할 일]\n1. 모의 시험 오류 원인 추론: 원인을 적는다.");
        when(plannerRepository.findById(2383L)).thenReturn(Optional.of(planner));
        when(materialRepository.findByPlannerIdAndMaterialType(2383L, MaterialType.PLANNER)).thenReturn(List.of());

        service.archivePlanner(USER_ID, 2383L);

        ArgumentCaptor<byte[]> pdf = ArgumentCaptor.forClass(byte[].class);
        verify(s3Service).uploadBytes(pdf.capture(), eq("planners/downloads/user_8/2383.pdf"), eq("application/pdf"));
        assertTrue(pdf.getValue().length > 800);
        assertEquals("planners/downloads/user_8/2383.pdf", planner.getS3Key());
    }

    @Test
    void ensurePreviewPdf_buildsFromSnapshotWhenPlannerIsGone() {
        Material detached = Material.builder().materialId(700L).userId(USER_ID).materialType(MaterialType.PLANNER)
                .title("[로드맵 11주차 7일] 질의응답 및 토론").plannerId(null)
                .contentJson("{\"plannerId\":1,\"title\":\"[로드맵 11주차 7일] 질의응답 및 토론\",\"subject\":\"선형회귀\",\"term\":\"11주차\","
                        + "\"plannerDate\":\"2026-11-23\",\"goalTime\":\"120분\",\"content\":\"[오늘 목표] 질의응답 및 토론을 정리한다.\\n\\n[할 일]\\n1. 질문 목록 정리\","
                        + "\"tmi\":\"핵심 개념: 질의응답, 선형회귀\"}")
                .build();

        service.ensurePreviewPdf(detached);

        verify(s3Service).uploadBytes(any(byte[].class), eq("planners/downloads/user_8/material_700.pdf"), eq("application/pdf"));
        // storedFileName 은 더 이상 쓰지 않는다: PLANNER 불변식 가드가 영속 시 항상 지우므로
        // '이미 생성됨' 표식이 될 수 없다. 미리보기 PDF 의 SSOT 는 s3FileUrl(= S3 object key)이다.
        assertNull(detached.getStoredFileName());
        assertEquals("planners/downloads/user_8/material_700.pdf", detached.getS3FileUrl());
        assertEquals("[로드맵 11주차 7일] 질의응답 및 토론.pdf", detached.getOriginalFileName());
        verify(materialRepository).save(detached);
        // 두 번째 호출은 아무것도 하지 않는다
        service.ensurePreviewPdf(detached);
        verify(s3Service, times(1)).uploadBytes(any(byte[].class), anyString(), anyString());
    }

    @Test
    void ensurePreviewPdf_usesLinkedPlannerAndSkipsWhenPdfExists() {
        Planner planner = roadmapPlanner(2383L, 700L);
        planner.setS3Key("planners/downloads/user_8/2383.pdf");
        Material archive = Material.builder().materialId(700L).userId(USER_ID).materialType(MaterialType.PLANNER).plannerId(2383L).build();
        when(plannerRepository.findById(2383L)).thenReturn(Optional.of(planner));

        service.ensurePreviewPdf(archive);
        verify(s3Service, never()).uploadBytes(any(byte[].class), anyString(), anyString());

        planner.setS3Key(null);
        service.ensurePreviewPdf(archive);
        verify(s3Service).uploadBytes(any(byte[].class), eq("planners/downloads/user_8/2383.pdf"), eq("application/pdf"));
        assertEquals("planners/downloads/user_8/2383.pdf", planner.getS3Key());
    }
}
