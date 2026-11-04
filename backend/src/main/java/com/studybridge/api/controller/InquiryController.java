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

    /** 문의 유형 기본값. 유형 선택이 없는 클라이언트(Android 모바일 마이페이지 — android-features MyPageScreen)는 type 을 보내지 않는다. */
    static final String DEFAULT_TYPE = "이용문의";
    /** 관리자 화면·기존 데이터가 쓰는 유형 값(공백 변형 포함). 그 밖의 값은 "기타". */
    static final java.util.Set<String> KNOWN_TYPES = java.util.Set.of("이용문의", "이용 문의", "버그 및 오류신고", "버그 및 오류 신고", "기타");
    static final int MAX_TITLE = 200;
    static final int MAX_CONTENT = 10000;
    /** 같은 사용자가 같은 유형·제목·내용을 이 시간 안에 다시 보내면 새로 저장하지 않고 앞선 접수를 돌려준다(연속 클릭). */
    static final java.time.Duration DUPLICATE_WINDOW = java.time.Duration.ofSeconds(10);

    static String normalizeType(String raw) {
        String t = raw == null ? "" : raw.strip();
        if (t.isEmpty()) {
            return DEFAULT_TYPE;
        }
        return KNOWN_TYPES.contains(t) ? t : "기타";
    }

    @PostMapping
    public ResponseEntity<InquiryDTO.Response> createInquiry(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody InquiryDTO.Request request) {

        User user = userRepository.findById(userDetails.getId())
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        // 2026-11-04 장애: Android 앱이 type 없이 보내 inquiries.type NOT NULL 위반 → 500. 서버에서 검증·정규화한다.
        String title = request == null || request.getTitle() == null ? "" : request.getTitle().strip();
        String content = request == null || request.getContent() == null ? "" : request.getContent().strip();
        if (title.isEmpty() || content.isEmpty()) {
            throw new IllegalArgumentException("문의 제목과 내용을 입력해 주세요.");
        }
        if (title.length() > MAX_TITLE || content.length() > MAX_CONTENT) {
            throw new IllegalArgumentException("문의 제목은 " + MAX_TITLE + "자, 내용은 " + MAX_CONTENT + "자 이내로 입력해 주세요.");
        }
        String type = normalizeType(request.getType());

        java.util.Optional<Inquiry> last = inquiryRepository.findFirstByAuthorIdOrderByCreatedAtDescIdDesc(user.getId());
        if (last.isPresent() && title.equals(last.get().getTitle()) && content.equals(last.get().getContent())
                && type.equals(last.get().getType()) && last.get().getCreatedAt() != null
                && last.get().getCreatedAt().isAfter(java.time.LocalDateTime.now().minus(DUPLICATE_WINDOW))) {
            return ResponseEntity.ok(convertToResponse(last.get()));
        }

        Inquiry inquiry = Inquiry.builder()
                .type(type)
                .title(title)
                .content(content)
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
