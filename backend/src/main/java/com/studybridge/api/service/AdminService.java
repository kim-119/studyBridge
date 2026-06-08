package com.studybridge.api.service;

import com.studybridge.api.dto.AdminDTO;
import com.studybridge.api.dto.GroupStudyReportDTO;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AdminService {

    private final UserRepository userRepository;
    private final BlogService blogService;
    private final GroupStudyReportService groupStudyReportService;
    private final GroupStudyService groupStudyService;

    // 유저 일시 정지 (SUSPEND)
    @Transactional
    public AdminDTO.ModerationResponse suspendUser(Long userId, AdminDTO.UserSuspendRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        if ("ADMIN".equals(user.getRole())) {
            throw new IllegalArgumentException("관리자 계정은 제재할 수 없습니다.");
        }

        // request.getDays()가 0일 경우 '경고(WARNING)' 상태로 처리
        if (request.getDays() == 0) {
            user.setStatus("WARNING");
            user.setSuspensionEndDate(null);
        } else {
            user.setStatus("SUSPENDED");
            user.setSuspensionEndDate(LocalDateTime.now().plusDays(request.getDays()));
        }
        user.setSuspensionReason(request.getReason());
        user.setSuspensionMemo(request.getMemo());
        userRepository.save(user);

        log.info("[관리자 제재] 유저 제재 완료. 대상: {}, 상태: {}, 기간: {}일, 정지만료: {}, 사유: {}", 
                user.getDisplayName(), user.getStatus(), request.getDays(), user.getSuspensionEndDate(), request.getReason());

        String message = request.getDays() == 0 ? "유저 경고 성공" : "유저 일시 정지 성공 (기간: " + request.getDays() + "일)";

        return AdminDTO.ModerationResponse.builder()
                .targetId(userId)
                .targetType("USER")
                .action(request.getDays() == 0 ? "WARNING" : "SUSPEND")
                .message(message)
                .executionTime(LocalDateTime.now())
                .build();
    }

    // 유저 영구 정지 (BAN)
    @Transactional
    public AdminDTO.ModerationResponse banUserPermanently(Long userId, AdminDTO.UserBanRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        if ("ADMIN".equals(user.getRole())) {
            throw new IllegalArgumentException("관리자 계정은 제재할 수 없습니다.");
        }

        user.setStatus("BANNED");
        user.setSuspensionEndDate(null); // 영구 정지이므로 만료일 필요 없음
        user.setSuspensionReason(request.getReason());
        user.setSuspensionMemo(request.getMemo());
        userRepository.save(user);

        log.info("[관리자 제재] 유저 영구정지 완료. 대상: {}, 사유: {}", user.getDisplayName(), request.getReason());

        return AdminDTO.ModerationResponse.builder()
                .targetId(userId)
                .targetType("USER")
                .action("BAN")
                .message("유저 영구 정지 성공")
                .executionTime(LocalDateTime.now())
                .build();
    }

    // 게시물 강제 조지기/삭제 (DELETE)
    @Transactional
    public AdminDTO.ModerationResponse crushPost(Long blogId) {
        blogService.deletePostForce(blogId);

        log.info("[관리자 제재] 게시판 글 강제 삭제 완료. 글 ID: {}", blogId);

        return AdminDTO.ModerationResponse.builder()
                .targetId(blogId)
                .targetType("POST")
                .action("DELETE")
                .message("게시글 강제 삭제 성공")
                .executionTime(LocalDateTime.now())
                .build();
     }
 
     // 댓글 강제 삭제 (DELETE)
     @Transactional
     public AdminDTO.ModerationResponse crushComment(Long commentId) {
         blogService.deleteCommentForce(commentId);
 
         log.info("[관리자 제재] 댓글 강제 삭제 완료. 댓글 ID: {}", commentId);
 
         return AdminDTO.ModerationResponse.builder()
                 .targetId(commentId)
                 .targetType("COMMENT")
                 .action("DELETE")
                 .message("댓글 강제 삭제 성공")
                 .executionTime(LocalDateTime.now())
                 .build();
     }

     // 모든 그룹스터디 신고 내역 조회 (어드민 전용)
     public java.util.List<GroupStudyReportDTO.Response> listAllGroupStudyReports() {
         return groupStudyReportService.listAllGroupStudyReports();
     }

     // 그룹스터디 강제 삭제 (DELETE)
     @Transactional
     public AdminDTO.ModerationResponse crushGroupStudy(Long groupId) {
         groupStudyService.deleteGroupStudyForce(groupId);
         log.info("[관리자 제재] 그룹스터디 강제 삭제 완료. 그룹 ID: {}", groupId);
         return AdminDTO.ModerationResponse.builder()
                 .targetId(groupId)
                 .targetType("GROUP_STUDY")
                 .action("DELETE")
                 .message("그룹스터디 강제 삭제 성공")
                 .executionTime(LocalDateTime.now())
                 .build();
     }
 }
