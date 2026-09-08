package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlannerRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 플래너 전체삭제(PlannerService.bulkDelete) 회귀 방어 테스트.
 *  - 플래너 삭제 시 자료보관함의 PLANNER 보관 항목은 삭제되지 않고 독립 자료로 유지되는가(연결 해제·스냅샷·PDF 이관)
 *  - PDF/일반 학습자료는 절대 삭제되지 않는가 (타입 가드)
 *  - 다른 사용자 데이터는 건드리지 않는가 (userId 스코프)
 *  - 보관 항목 갱신 실패 시 예외가 전파되어(=@Transactional 롤백) 부분 삭제가 남지 않는가
 * 순수 단위 테스트(Mockito) — Spring 컨텍스트/DB 없이 서비스 로직만 검증.
 */
class PlannerBulkDeleteCascadeTest {

    private static final long USER_ID = 13L;

    private PlannerRepository plannerRepository;
    private MaterialRepository materialRepository;
    private S3Service s3Service;
    private PlannerService service;

    @BeforeEach
    void setUp() {
        plannerRepository = mock(PlannerRepository.class);
        materialRepository = mock(MaterialRepository.class);
        s3Service = mock(S3Service.class);
        service = new PlannerService(plannerRepository, materialRepository, s3Service, new ObjectMapper());
    }

    private Planner roadmapPlanner(long id, Long materialId) {
        return Planner.builder()
                .id(id).userId(USER_ID)
                .plannerType(PlannerType.ROADMAP)
                .sourceType("ROADMAP_AUTO")
                .materialId(materialId)
                .build();
    }

    private Material plannerMaterial(long materialId, long plannerId) {
        return Material.builder()
                .materialId(materialId).userId(USER_ID)
                .materialType(MaterialType.PLANNER)
                .plannerId(plannerId)
                .build();
    }

    private Planner userPlanner(long id) {
        return Planner.builder()
                .id(id).userId(USER_ID)
                .plannerType(PlannerType.USER)
                .build();
    }

    private PlannerDTO.BulkDeleteRequest bulkReq(List<Long> ids) {
        return PlannerDTO.BulkDeleteRequest.builder()
                .scope("VISIBLE_ROADMAP_AUTO")
                .sourceType("ROADMAP_AUTO")
                .plannerIds(ids)
                .build();
    }

    private PlannerDTO.BulkDeleteRequest bulkReq(String plannerType, List<Long> ids) {
        return PlannerDTO.BulkDeleteRequest.builder()
                .plannerType(plannerType)
                .plannerIds(ids)
                .build();
    }

    @Test
    void deleteUserPlanners_shouldDeleteOnlyUserType() {
        Planner planner = userPlanner(5L);
        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(5L))).thenReturn(List.of(planner));
        when(materialRepository.findByPlannerIdAndMaterialType(5L, MaterialType.PLANNER))
                .thenReturn(Collections.emptyList());

        PlannerDTO.BulkDeleteResponse res = service.bulkDelete(USER_ID, bulkReq("USER", List.of(5L)));

        assertTrue(res.isSuccess());
        assertEquals(1, res.getDeletedCount());
        verify(plannerRepository).delete(planner);
    }

    @Test
    void deleteUserPlanners_shouldRejectRoadmapMixedIn() {
        // 사용자 탭(USER) 전체삭제에 로드맵 플래너가 섞이면 전체 거부 → 두 타입 동시 삭제 방지.
        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(5L, 1L)))
                .thenReturn(List.of(userPlanner(5L), roadmapPlanner(1L, 100L)));

        PlannerDTO.BulkDeleteResponse res = service.bulkDelete(USER_ID, bulkReq("USER", new ArrayList<>(List.of(5L, 1L))));

        assertFalse(res.isSuccess());
        assertEquals("INVALID_DELETE_SCOPE", res.getErrorCode());
        verify(plannerRepository, never()).delete(any(Planner.class));
    }

    @Test
    void deleteRoadmapPlanners_shouldRejectUserMixedIn() {
        // 로드맵 탭(ROADMAP) 전체삭제에 사용자 플래너가 섞이면 전체 거부.
        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(1L, 5L)))
                .thenReturn(List.of(roadmapPlanner(1L, 100L), userPlanner(5L)));

        PlannerDTO.BulkDeleteResponse res = service.bulkDelete(USER_ID, bulkReq(new ArrayList<>(List.of(1L, 5L))));

        assertFalse(res.isSuccess());
        assertEquals("INVALID_DELETE_SCOPE", res.getErrorCode());
        verify(plannerRepository, never()).delete(any(Planner.class));
    }

    @Test
    void deleteAllPlanners_shouldKeepPlannerArchiveItemsDetached() {
        Planner planner = roadmapPlanner(1L, 100L);
        planner.setTitle("[로드맵 1주차 1일] 선형회귀");
        planner.setS3Key("planners/downloads/user_13/1.pdf");
        Material archive = plannerMaterial(100L, 1L);   // contentJson 없음 → 삭제 직전 스냅샷으로 채워져야 한다

        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(1L))).thenReturn(List.of(planner));
        when(materialRepository.findById(100L)).thenReturn(java.util.Optional.of(archive));
        when(materialRepository.findByPlannerIdAndMaterialType(1L, MaterialType.PLANNER)).thenReturn(List.of(archive));
        when(materialRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

        PlannerDTO.BulkDeleteResponse res = service.bulkDelete(USER_ID, bulkReq(List.of(1L)));

        assertTrue(res.isSuccess());
        assertEquals(1, res.getDeletedCount());
        verify(materialRepository, never()).delete(any(Material.class));   // 보관 항목은 삭제되지 않는다
        verify(materialRepository, times(1)).save(archive);                 // 합집합이라 한 번만 갱신
        assertNull(archive.getPlannerId());                                  // 존재하지 않는 플래너를 가리키지 않는다
        assertEquals(MaterialType.PLANNER, archive.getMaterialType());
        assertNotNull(archive.getContentJson());
        assertTrue(archive.getContentJson().contains("\"title\":\"[로드맵 1주차 1일] 선형회귀\""), archive.getContentJson());
        // 다운로드 PDF 는 S3 에서 지우지 않고 보관 항목이 넘겨받는다(미리보기 유지, 보관 항목 삭제 시 정리)
        assertEquals("planners/downloads/user_13/1.pdf", archive.getStoredFileName());
        assertEquals("planners/downloads/user_13/1.pdf", archive.getS3FileUrl());
        verify(s3Service, never()).deleteFile(anyString());
        verify(plannerRepository).delete(planner);                           // 플래너 본체만 삭제
    }

    @Test
    void deletePlannerWithoutArchive_shouldRemoveDownloadPdf() {
        Planner planner = roadmapPlanner(1L, null);
        planner.setS3Key("planners/downloads/user_13/1.pdf");
        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(1L))).thenReturn(List.of(planner));
        when(materialRepository.findByPlannerIdAndMaterialType(1L, MaterialType.PLANNER)).thenReturn(Collections.emptyList());

        assertTrue(service.bulkDelete(USER_ID, bulkReq(List.of(1L))).isSuccess());
        verify(s3Service).deleteFile("planners/downloads/user_13/1.pdf");   // 보관 항목이 없으면 다운로드 PDF 는 정리
        verify(materialRepository, never()).save(any(Material.class));
        verify(plannerRepository).delete(planner);
    }

    @Test
    void deleteAllPlanners_shouldNotDeletePdfMaterials() {
        // 자료보관함 항목이 없는(또는 PDF뿐인) 플래너 — 역참조 조회는 PLANNER 타입으로만 한다.
        Planner planner = roadmapPlanner(1L, null);
        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(1L))).thenReturn(List.of(planner));
        when(materialRepository.findByPlannerIdAndMaterialType(1L, MaterialType.PLANNER))
                .thenReturn(Collections.emptyList());

        PlannerDTO.BulkDeleteResponse res = service.bulkDelete(USER_ID, bulkReq(List.of(1L)));

        assertTrue(res.isSuccess());
        // 역참조 조회가 PDF가 아닌 PLANNER 타입으로만 수행됨을 증명(PDF는 애초에 대상에서 제외).
        ArgumentCaptor<MaterialType> typeCaptor = ArgumentCaptor.forClass(MaterialType.class);
        verify(materialRepository).findByPlannerIdAndMaterialType(eq(1L), typeCaptor.capture());
        assertEquals(MaterialType.PLANNER, typeCaptor.getValue());
        // 어떤 자료도 삭제되지 않음(PDF 보호).
        verify(materialRepository, never()).delete(any(Material.class));
        verify(plannerRepository).delete(planner);
    }

    @Test
    void deleteAllPlanners_shouldOnlyDeleteCurrentUserData() {
        // 요청 id 2개 중 1개는 다른 사용자 소유 → userId 스코프 쿼리는 1개만 반환 → 전체 거부.
        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(1L, 2L)))
                .thenReturn(List.of(roadmapPlanner(1L, 100L)));

        PlannerDTO.BulkDeleteResponse res = service.bulkDelete(USER_ID, bulkReq(new ArrayList<>(List.of(1L, 2L))));

        assertFalse(res.isSuccess());
        assertEquals("INVALID_DELETE_SCOPE", res.getErrorCode());
        // 한 건도 삭제되지 않아야 함(다른 사용자 데이터 보호 + 원자성).
        verify(materialRepository, never()).delete(any(Material.class));
        verify(plannerRepository, never()).delete(any(Planner.class));
    }

    @Test
    void deleteAllPlanners_shouldRollbackWhenArchiveDetachFails() {
        Planner planner = roadmapPlanner(1L, 100L);
        Material archive = plannerMaterial(100L, 1L);

        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(1L))).thenReturn(List.of(planner));
        when(materialRepository.findById(100L)).thenReturn(java.util.Optional.of(archive));
        when(materialRepository.findByPlannerIdAndMaterialType(1L, MaterialType.PLANNER)).thenReturn(Collections.emptyList());
        doThrow(new RuntimeException("archive save failed")).when(materialRepository).save(archive);

        // 예외가 @Transactional 경계 밖으로 전파 → 런타임에서 전체 롤백된다.
        assertThrows(RuntimeException.class, () -> service.bulkDelete(USER_ID, bulkReq(List.of(1L))));

        // 보관 항목 갱신이 실패한 뒤 플래너 본체 삭제까지 진행되지 않아야 함(부분 삭제 방지).
        verify(plannerRepository, never()).delete(any(Planner.class));
    }
}
