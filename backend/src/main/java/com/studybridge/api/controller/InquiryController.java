package com.studybridge.api.controller;

import com.studybridge.api.dto.InquiryDTO;
import com.studybridge.api.entity.Inquiry;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.InquiryRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.domain.CustomUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/inquiries")
@RequiredArgsConstructor
public class InquiryController {

    private final InquiryRepository inquiryRepository;
    private final UserRepository userRepository;

    @PostMapping
    public ResponseEntity<InquiryDTO.Response> createInquiry(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody InquiryDTO.Request request) {

        User user = userRepository.findById(userDetails.getId())
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        Inquiry inquiry = Inquiry.builder()
                .type(request.getType())
                .title(request.getTitle())
                .content(request.getContent())
                .author(user)
                .status("대기중")
                .build();

        Inquiry saved = inquiryRepository.save(inquiry);
        return ResponseEntity.ok(convertToResponse(saved));
    }

    @GetMapping
    public ResponseEntity<List<InquiryDTO.Response>> getMyInquiries(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        
        List<Inquiry> inquiries = inquiryRepository.findAllByAuthorIdOrderByCreatedAtDesc(userDetails.getId());
        List<InquiryDTO.Response> responses = inquiries.stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
        return ResponseEntity.ok(responses);
    }

    private InquiryDTO.Response convertToResponse(Inquiry inquiry) {
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
        return new InquiryDTO.Response(
                inquiry.getId(),
                inquiry.getType(),
                inquiry.getTitle(),
                inquiry.getContent(),
                inquiry.getReply(),
                inquiry.getStatus(),
                inquiry.getAuthor().getDisplayName(),
                inquiry.getCreatedAt() != null ? inquiry.getCreatedAt().format(formatter) : java.time.LocalDate.now().format(formatter)
        );
    }
}
