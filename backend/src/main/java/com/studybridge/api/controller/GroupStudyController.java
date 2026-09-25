package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupStudyDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupStudyService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api/groups")
public class GroupStudyController {

    private final GroupStudyService groupStudyService;

    @PostMapping(consumes = org.springframework.http.MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<GroupStudyDTO.Response> createGroup(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @Valid @ModelAttribute GroupStudyDTO.CreateRequest request,
            @RequestParam(value = "image", required = false) org.springframework.web.multipart.MultipartFile image) {
        log.info("Create group request received from userId={}, title={}", userDetails.getId(), request.getTitle());
        GroupStudyDTO.Response response = groupStudyService.createGroupStudy(userDetails.getId(), request, image);
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    @GetMapping
    public ResponseEntity<List<GroupStudyDTO.Response>> getAllGroups() {
        log.info("Request for all group studies list");
        List<GroupStudyDTO.Response> response = groupStudyService.getAllGroupStudies();
        return ResponseEntity.ok(response);
    }

    @GetMapping("/{id}")
    public ResponseEntity<GroupStudyDTO.Response> getGroupDetails(@PathVariable Long id) {
        log.info("Request group study details. groupId={}", id);
        GroupStudyDTO.Response response = groupStudyService.getGroupStudy(id);
        return ResponseEntity.ok(response);
    }

    @PostMapping("/{id}/apply")
    public ResponseEntity<GroupStudyDTO.ApplicationResponse> applyGroup(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @Valid @RequestBody GroupStudyDTO.JoinApplyRequest request) {
        log.info("Apply to join group study. userId={}, groupId={}", userDetails.getId(), id);
        GroupStudyDTO.ApplicationResponse response = groupStudyService.applyToGroupStudy(userDetails.getId(), id,
                request);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/{id}/members")
    public ResponseEntity<List<GroupStudyDTO.MemberResponse>> getMembers(@PathVariable Long id) {
        log.info("Request members of groupId={}", id);
        List<GroupStudyDTO.MemberResponse> response = groupStudyService.getGroupMembers(id);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/{id}/applications")
    public ResponseEntity<List<GroupStudyDTO.ApplicationResponse>> getApplications(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        log.info("Request pending applications. leaderId={}, groupId={}", userDetails.getId(), id);
        List<GroupStudyDTO.ApplicationResponse> response = groupStudyService.getApplications(userDetails.getId(), id);
        return ResponseEntity.ok(response);
    }

    @PostMapping("/applications/{applicationId}/approve")
    public ResponseEntity<GroupStudyDTO.ApplicationResponse> approve(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long applicationId) {
        log.info("Approve group study application. leaderId={}, applicationId={}", userDetails.getId(), applicationId);
        GroupStudyDTO.ApplicationResponse response = groupStudyService.approveApplication(userDetails.getId(),
                applicationId);
        return ResponseEntity.ok(response);
    }

    @PostMapping("/applications/{applicationId}/reject")
    public ResponseEntity<GroupStudyDTO.ApplicationResponse> reject(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long applicationId) {
        log.info("Reject group study application. leaderId={}, applicationId={}", userDetails.getId(), applicationId);
        GroupStudyDTO.ApplicationResponse response = groupStudyService.rejectApplication(userDetails.getId(),
                applicationId);
        return ResponseEntity.ok(response);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteGroup(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        log.info("Request delete group study. leaderId={}, groupId={}", userDetails.getId(), id);
        groupStudyService.deleteGroupStudy(userDetails.getId(), id);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{id}/complete")
    public ResponseEntity<GroupStudyDTO.Response> completeRecruitment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        log.info("Request to complete recruitment and start study. leaderId={}, groupId={}", userDetails.getId(), id);
        GroupStudyDTO.Response response = groupStudyService.startGroupStudy(userDetails.getId(), id);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/search")
    public ResponseEntity<List<GroupStudyDTO.Response>> searchGroups(
            @RequestParam(value = "keyword", required = false) String keyword) {
        log.info("Request to search group studies by keyword: {}", keyword);
        List<GroupStudyDTO.Response> response = groupStudyService.searchGroupStudies(keyword);
        return ResponseEntity.ok(response);
    }

    @PutMapping(value = "/{id}", consumes = org.springframework.http.MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<GroupStudyDTO.Response> updateGroup(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @Valid @ModelAttribute GroupStudyDTO.UpdateRequest request,
            @RequestParam(value = "image", required = false) org.springframework.web.multipart.MultipartFile image,
            @RequestParam(value = "clearImage", required = false, defaultValue = "false") boolean clearImage) {
        log.info("Request to update group study. leaderId={}, groupId={}", userDetails.getId(), id);
        GroupStudyDTO.Response response = groupStudyService.updateGroupStudy(userDetails.getId(), id, request, image, clearImage);
        return ResponseEntity.ok(response);
    }

    @DeleteMapping("/{id}/members/{memberUserId}")
    public ResponseEntity<Void> kickMember(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @PathVariable Long memberUserId) {
        log.info("Request to kick member from group study. leaderId={}, groupId={}, memberUserId={}", userDetails.getId(), id, memberUserId);
        groupStudyService.kickMember(userDetails.getId(), id, memberUserId);
        return ResponseEntity.noContent().build();
    }

    @DeleteMapping("/{id}/leave")
    public ResponseEntity<Void> leaveGroup(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        log.info("Request to leave group study. userId={}, groupId={}", userDetails.getId(), id);
        groupStudyService.leaveGroupStudy(userDetails.getId(), id);
        return ResponseEntity.noContent().build();
    }
}

