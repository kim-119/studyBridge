package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
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
 *  - 플래너 삭제 시 자료보관함의 PLANNER 항목도 함께 삭제되는가
 *  - PDF/일반 학습자료는 절대 삭제되지 않는가 (타입 가드)
 *  - 다른 사용자 데이터는 건드리지 않는가 (userId 스코프)
 *  - 자료 삭제 실패 시 예외가 전파되어(=@Transactional 롤백) 부분 삭제가 남지 않는가
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

    private PlannerDTO.BulkDeleteRequest bulkReq(List<Long> ids) {
        return PlannerDTO.BulkDeleteRequest.builder()
                .scope("VISIBLE_ROADMAP_AUTO")
                .sourceType("ROADMAP_AUTO")
                .plannerIds(ids)
                .build();
    }

    @Test
    void deleteAllPlanners_shouldDeletePlannerArchiveItems() {
        Planner planner = roadmapPlanner(1L, 100L);
        Material archive = plannerMaterial(100L, 1L);

        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(1L))).thenReturn(List.of(planner));
        when(materialRepository.findByPlannerIdAndMaterialType(1L, MaterialType.PLANNER))
                .thenReturn(Collections.emptyList());
        when(materialRepository.findAllById(any())).thenReturn(List.of(archive));

        PlannerDTO.BulkDeleteResponse res = service.bulkDelete(USER_ID, bulkReq(List.of(1L)));

        assertTrue(res.isSuccess());
        assertEquals(1, res.getDeletedCount());
        verify(materialRepository).delete(archive);          // 연결된 PLANNER 자료 삭제됨
        verify(plannerRepository).delete(planner);           // 플래너 본체 삭제됨
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
    void deleteAllPlanners_shouldRollbackWhenArchiveDeleteFails() {
        Planner planner = roadmapPlanner(1L, 100L);
        Material archive = plannerMaterial(100L, 1L);

        when(plannerRepository.findByUserIdAndIdIn(USER_ID, List.of(1L))).thenReturn(List.of(planner));
        when(materialRepository.findByPlannerIdAndMaterialType(1L, MaterialType.PLANNER))
                .thenReturn(Collections.emptyList());
        when(materialRepository.findAllById(any())).thenReturn(List.of(archive));
        doThrow(new RuntimeException("archive delete failed")).when(materialRepository).delete(archive);

        // 예외가 @Transactional 경계 밖으로 전파 → 런타임에서 전체 롤백된다.
        assertThrows(RuntimeException.class, () -> service.bulkDelete(USER_ID, bulkReq(List.of(1L))));

        // 자료 삭제가 실패한 뒤 플래너 본체 삭제까지 진행되지 않아야 함(부분 삭제 방지).
        verify(plannerRepository, never()).delete(any(Planner.class));
    }
}
