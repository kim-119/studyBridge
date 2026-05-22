package com.studybridge.api.service;

import com.studybridge.api.dto.AdminDashboardDTO;
import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AdminService {

    private final UserRepository userRepository;
    private final ReportRepository reportRepository;
    private final UserService userService;
    private final ReportService reportService;
    private final AgentRepository agentRepository;
    private final AgentChatRoomRepository agentChatRoomRepository;

    /**
     * 관리자 대시보드 통계 정보를 조회합니다.
     * 
     * @return 대시보드 DTO
     */
    public AdminDashboardDTO getDashboardStatistics() {
        long totalUserCount = userRepository.count();
        long todayNewUserCount = userRepository.countByCreatedAtAfter(LocalDate.now().atStartOfDay());

        // 정지 유저 수 계산 (임시 정지가 만료된 유저는 제외)
        long bannedUserCount = userRepository.findAll().stream()
                .filter(user -> user.isBanned() && 
                        (user.getBannedUntil() == null || user.getBannedUntil().isAfter(java.time.LocalDateTime.now())))
                .count();

        // 전공별 유저 수 분포 통계 생성
        Map<String, Long> majorDistribution = userRepository.findAll().stream()
                .filter(user -> user.getMajor() != null && !user.getMajor().trim().isEmpty())
                .collect(Collectors.groupingBy(User::getMajor, Collectors.counting()));

        return AdminDashboardDTO.builder()
                .totalUserCount(totalUserCount)
                .todayNewUserCount(todayNewUserCount)
                .bannedUserCount(bannedUserCount)
                .majorDistribution(majorDistribution)
                .build();
    }

    /**
     * 관리자가 신고를 승인하고, 해당 대상(스터디 그룹)을 자동으로 삭제합니다.
     * 
     * @param reportId 승인할 신고 ID
     * @return 처리된 신고 응답 DTO
     */
    @Transactional
    public ReportDTO.ReportResponse approveReportAndTakeAction(Long reportId) {
        Report report = reportRepository.findById(reportId)
                .orElseThrow(() -> new IllegalArgumentException("신고를 찾을 수 없습니다."));

        // 기존 ReportService를 사용하여 PENDING 검사 및 APPROVED 상태 변경 진행
        ReportDTO.ReportResponse response = reportService.approveReport(reportId);

        // 신고 대상이 학습 그룹(STUDY_GROUP)인 경우, 해당 그룹을 자동으로 데이터베이스에서 삭제 (Cascading Delete)
        if (report.getTargetType() == ReportTargetType.STUDY_GROUP) {
            AgentChatRoom room = agentChatRoomRepository.findById(report.getTargetId()).orElse(null);
            if (room != null) {
                agentChatRoomRepository.delete(room);
            }
        }

        return response;
    }

    /**
     * 관리자가 유저를 정지/해제하고, 정지 시 해당 유저에 대한 모든 대기 중인 신고를 승인 처리합니다.
     * 
     * @param userId 유저 ID
     * @param request 정지 요청 정보
     * @return 수정된 유저 정보 DTO
     */
    @Transactional
    public UserDTO.Response banUserAndResolveReports(Long userId, UserDTO.UserBanRequest request) {
        UserDTO.Response response = userService.banUser(userId, request);

        // 유저를 정지시킨 경우에만 해당 유저를 타겟으로 한 모든 대기 중인 신고를 승인 처리
        if (request.isBanned()) {
            List<Report> reports = reportRepository.findByStatus(ReportStatus.PENDING);
            for (Report report : reports) {
                if (report.getTargetType() == ReportTargetType.USER && report.getTargetId().equals(userId)) {
                    report.setStatus(ReportStatus.APPROVED);
                }
            }
        }

        return response;
    }

    /**
     * 이메일 또는 닉네임으로 사용자를 검색합니다.
     * 
     * @param keyword 검색 키워드
     * @return 사용자 DTO 리스트
     */
    public List<UserDTO.Response> searchUsers(String keyword) {
        return userRepository.findByEmailContainingIgnoreCaseOrDisplayNameContainingIgnoreCase(keyword, keyword)
                .stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    /**
     * 사용자의 역할(관리자/일반사용자)을 변경합니다.
     * 
     * @param userId 유저 ID
     * @param role 설정할 권한
     * @return 수정된 유저 정보 DTO
     */
    @Transactional
    public UserDTO.Response updateUserRole(Long userId, AdminRole role) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않는 사용자입니다."));
        user.setRole(role);
        return convertToResponse(user);
    }

    /**
     * 특정 사용자가 제기했거나, 특정 사용자를 대상으로 제기된 모든 신고 내역을 조회합니다.
     * 
     * @param userId 유저 ID
     * @return 신고 응답 DTO 리스트
     */
    public List<ReportDTO.ReportResponse> getUserReports(Long userId) {
        return reportRepository.findAll().stream()
                .filter(report -> report.getReporter().getId().equals(userId) ||
                        (report.getTargetType() == ReportTargetType.USER && report.getTargetId().equals(userId)))
                .map(this::convertToReportResponse)
                .collect(Collectors.toList());
    }

    /**
     * 시스템에 존재하는 모든 AI 에이전트 목록을 조회합니다.
     * 
     * @return AI 에이전트 리스트
     */
    public List<Agent> getAllAgents() {
        return agentRepository.findAll();
    }

    /**
     * AI 에이전트를 영구적으로 비활성화/삭제합니다.
     * 
     * @param agentId 에이전트 ID
     */
    @Transactional
    public void deleteAgent(Long agentId) {
        if (!agentRepository.existsById(agentId)) {
            throw new IllegalArgumentException("존재하지 않는 AI 에이전트입니다.");
        }
        agentRepository.deleteById(agentId);
    }

    private UserDTO.Response convertToResponse(User user) {
        boolean actualBanned = user.isBanned() && 
                (user.getBannedUntil() == null || user.getBannedUntil().isAfter(java.time.LocalDateTime.now()));

        return UserDTO.Response.builder()
                .id(user.getId())
                .email(user.getEmail())
                .displayName(user.getDisplayName())
                .major(user.getMajor())
                .photoUrl(user.getPhotoUrl())
                .isSubscribed(user.getIsSubscribed())
                .role(user.getRole())
                .banned(actualBanned)
                .bannedUntil(user.getBannedUntil())
                .build();
    }

    private ReportDTO.ReportResponse convertToReportResponse(Report report) {
        String targetContent = "N/A";
        String targetUrl = null;

        if (report.getTargetType() == ReportTargetType.USER) {
            User user = userRepository.findById(report.getTargetId()).orElse(null);
            if (user != null) {
                targetContent = user.getDisplayName() + " (" + user.getEmail() + ")";
            }
        } else if (report.getTargetType() == ReportTargetType.STUDY_GROUP) {
            AgentChatRoom room = agentChatRoomRepository.findById(report.getTargetId()).orElse(null);
            if (room != null) {
                targetContent = room.getRoomName() + " (개설자: " + room.getUser().getDisplayName() + ")";
            }
        }

        return ReportDTO.ReportResponse.builder()
                .reportId(report.getId())
                .reporterUserId(report.getReporter().getId())
                .reporterEmail(report.getReporter().getEmail())
                .targetType(report.getTargetType())
                .targetId(report.getTargetId())
                .targetContent(targetContent)
                .targetUrl(targetUrl)
                .reason(report.getReason())
                .status(report.getStatus())
                .reportedAt(report.getCreatedAt())
                .build();
    }
}