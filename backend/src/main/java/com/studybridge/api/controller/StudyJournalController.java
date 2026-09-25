package com.studybridge.api.controller;

import com.studybridge.api.dto.StudyJournalDTO;
import com.studybridge.api.exception.StudyJournalRejectedException;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.StudyJournalService;
import com.studybridge.api.service.StudyJournalValidationResult;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 학습일지 API. 자료보관함 PDF 상세 '메모' 탭의 학습일지 기능.
 *
 * 검증 통과(ACCEPT) 입력만 S3에 원문 저장 + DB에 메타데이터 저장.
 * REQUEST_REVISION/BLOCK 입력은 S3/DB 어디에도 저장하지 않고 사유/제안을 반환(HTTP 422).
 */
@RestController
@RequestMapping("/api/materials/{materialId}/study-journals")
@RequiredArgsConstructor
public class StudyJournalController {

    private final StudyJournalService studyJournalService;

    @PostMapping
    public ResponseEntity<?> create(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody StudyJournalDTO.CreateRequest request) {
        try {
            StudyJournalDTO.Response saved =
                    studyJournalService.create(userDetails.getId(), materialId, request.getContent());
            return ResponseEntity.ok(saved);
        } catch (StudyJournalRejectedException ex) {
            StudyJournalValidationResult r = ex.getResult();
            StudyJournalDTO.RejectionResponse rejection = StudyJournalDTO.RejectionResponse.builder()
                    .decision(r.getDecision())
                    .category(r.getCategory())
                    .relationType(r.getRelationType())
                    .relationPath(r.getRelationPath())
                    .reason(r.getReason())
                    .suggestion(r.getSuggestion())
                    .build();
            return ResponseEntity.unprocessableEntity().body(rejection);
        }
    }

    @GetMapping
    public ResponseEntity<List<StudyJournalDTO.Response>> list(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(studyJournalService.list(userDetails.getId(), materialId));
    }

    @GetMapping("/{journalId}")
    public ResponseEntity<StudyJournalDTO.Response> detail(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @PathVariable Long journalId) {
        return ResponseEntity.ok(studyJournalService.detail(userDetails.getId(), materialId, journalId));
    }

    @DeleteMapping("/{journalId}")
    public ResponseEntity<Void> delete(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @PathVariable Long journalId) {
        studyJournalService.delete(userDetails.getId(), materialId, journalId);
        return ResponseEntity.noContent().build();
    }
}
