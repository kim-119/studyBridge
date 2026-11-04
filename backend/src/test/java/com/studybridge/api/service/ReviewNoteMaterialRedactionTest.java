package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.repository.ReviewNoteRepository;
import java.util.Optional;
import org.junit.jupiter.api.Test;

/**
 * Phase D 우회 경로 차단: GET /api/materials/{id}?context=review-note 가 오답노트 자료의 AI 해설 PDF URL·본문 사본을 내주던 문제.
 * 게이트 ON + 원 노트 미승인(또는 못 찾음) → URL·본문 미노출(qualityRedacted). 승인 → 기존과 같음. 게이트 OFF → 기존과 같음.
 */
class ReviewNoteMaterialRedactionTest {

        static final long USER = 31L;
        static final long MID = 901L;

        record Fixture(MaterialService service, S3Service s3, ReviewNoteRepository notes) { }

        static Fixture fixture(boolean gateOn, String noteStatus) {
                com.studybridge.api.repository.MaterialRepository materials = mock(com.studybridge.api.repository.MaterialRepository.class);
                S3Service s3 = mock(S3Service.class);
                when(s3.getPresignedUrl(anyString(), anyString())).thenReturn("https://s3.example/presigned-CANARY7F3A");
                Material m = Material.builder().materialId(MID).userId(USER).materialType(MaterialType.REVIEW_NOTE).title("오답노트: 네트워크")
                                .learningContent("CANARY7F3A AI 해설 사본").s3FileUrl("review-notes/31/901.pdf").originalFileName("note.pdf").build();
                when(materials.findById(MID)).thenReturn(Optional.of(m));
                MaterialService svc = new MaterialService(materials, s3, mock(PdfExtractionService.class),
                                mock(com.studybridge.api.repository.MaterialFeedbackRepository.class),
                                mock(com.studybridge.api.repository.MaterialSummaryRepository.class), mock(com.studybridge.api.repository.FolderRepository.class),
                                mock(com.studybridge.api.repository.PlannerRepository.class), mock(StudyNoteAnalysisService.class), mock(PlannerService.class),
                                mock(MaterialQuizScoreService.class), mock(com.studybridge.api.repository.MaterialGroupShareRepository.class),
                                mock(com.studybridge.api.ai.training.TrainingCandidateCollector.class));
                ReviewNoteRepository notes = mock(ReviewNoteRepository.class);
                when(notes.findFirstByArchiveMaterialIdAndUserId(MID, USER)).thenReturn(noteStatus == null && !gateOn ? Optional.empty()
                                : Optional.of(ReviewNote.builder().userId(USER).archiveMaterialId(MID).qualityStatus(noteStatus).build()));
                svc.setQualityGateSupport(AiQualityGateSettings.forTest(gateOn), notes);
                return new Fixture(svc, s3, notes);
        }

        @Test
        @com.studybridge.api.ai.quality.GateEvidence({"GET /api/materials/{materialId}"})
        void unapprovedReviewNoteMaterialHidesPdfAndBodyWhenGateOn() {
                Fixture f = fixture(true, null);
                MaterialDTO dto = f.service().getMaterial(USER, MID, "review-note");
                assertNull(dto.getS3PresignedUrl(), "미승인 노트 PDF URL 미발급");
                assertNull(dto.getLearningContent(), "AI 해설 본문 사본 미노출");
                assertEquals(Boolean.TRUE, dto.getQualityRedacted());
                assertEquals("오답노트: 네트워크", dto.getTitle(), "제목·식별자는 유지");
                verify(f.s3(), never()).getPresignedUrl(anyString(), anyString());
        }

        @Test
        @com.studybridge.api.ai.quality.GateEvidence({"GET /api/materials/{materialId}"})
        void approvedReviewNoteMaterialIsShownWhenGateOn() {
                Fixture f = fixture(true, "APPROVED");
                MaterialDTO dto = f.service().getMaterial(USER, MID, "review-note");
                assertTrue(dto.getS3PresignedUrl().contains("presigned"));
                assertTrue(dto.getLearningContent().contains("AI 해설"));
                assertNull(dto.getQualityRedacted());
        }

        @Test
        void gateOffKeepsLegacyBehaviour() {
                Fixture f = fixture(false, null);
                MaterialDTO dto = f.service().getMaterial(USER, MID, "review-note");
                assertTrue(dto.getS3PresignedUrl().contains("presigned"));
                assertNull(dto.getQualityRedacted());
                verify(f.notes(), never()).findFirstByArchiveMaterialIdAndUserId(MID, USER);
        }
}
