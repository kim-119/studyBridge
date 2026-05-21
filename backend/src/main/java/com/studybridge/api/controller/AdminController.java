package com.studybridge.api.controller;

import com.studybridge.api.dto.AdminDashboardDTO;
import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.entity.AdminRole;
import com.studybridge.api.entity.ReportStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.service.AdminService;
import com.studybridge.api.service.ReportService;
import com.studybridge.api.service.UserService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Optional;

@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class AdminController {

    private final UserService userService;
    private final AdminService adminService;
    private final ReportService reportService;

    // --- 대시보드 ---
    @GetMapping("/dashboard")
    public ResponseEntity<AdminDashboardDTO> getDashboardStatistics() {
        AdminDashboardDTO dashboardData = adminService.getDashboardStatistics();
        return ResponseEntity.ok(dashboardData);
    }

    // --- 사용자 관리 ---
    @GetMapping("/users")
    public ResponseEntity<List<UserDTO.Response>> getAllUsers() {
        List<UserDTO.Response> users = userService.getAllUsers();
        return ResponseEntity.ok(users);
    }

    @GetMapping("/users/search")
    public ResponseEntity<List<UserDTO.Response>> searchUsers(@RequestParam String keyword) {
        List<UserDTO.Response> users = adminService.searchUsers(keyword);
        return ResponseEntity.ok(users);
    }

    // 유저 정지/해제 (신고 일괄 해결 자동화 연동)
    @PatchMapping("/users/{userId}/ban")
    public ResponseEntity<?> banUser(@PathVariable Long userId, @Valid @RequestBody UserDTO.UserBanRequest request) {
        try {
            UserDTO.Response updatedUser = adminService.banUserAndResolveReports(userId, request);
            return ResponseEntity.ok(updatedUser);
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // 유저 권한 변경 (관리자 <-> 일반 유저)
    @PatchMapping("/users/{userId}/role")
    public ResponseEntity<?> updateUserRole(@PathVariable Long userId, @RequestParam AdminRole role) {
        try {
            UserDTO.Response updatedUser = adminService.updateUserRole(userId, role);
            return ResponseEntity.ok(updatedUser);
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // 특정 유저가 업로드한 모든 학습 자료 목록 조회
    @GetMapping("/users/{userId}/materials")
    public ResponseEntity<List<Material>> getUserMaterials(@PathVariable Long userId) {
        List<Material> materials = adminService.getUserMaterials(userId);
        return ResponseEntity.ok(materials);
    }

    // 특정 유저의 상세 신고 내역 조회 (유저가 신고했거나, 유저 대상의 신고 내역)
    @GetMapping("/users/{userId}/reports")
    public ResponseEntity<List<ReportDTO.ReportResponse>> getUserReports(@PathVariable Long userId) {
        List<ReportDTO.ReportResponse> reports = adminService.getUserReports(userId);
        return ResponseEntity.ok(reports);
    }

    // --- 신고 및 콘텐츠 관리 ---
    @GetMapping("/reports")
    public ResponseEntity<List<ReportDTO.ReportResponse>> getReports(@RequestParam Optional<ReportStatus> status) {
        List<ReportDTO.ReportResponse> reports;
        if (status.isPresent()) {
            reports = reportService.getReportsByStatus(status.get());
        } else {
            reports = reportService.getAllReports();
        }
        return ResponseEntity.ok(reports);
    }

    // 신고 승인 (학습 자료 자동 삭제 자동화 연동)
    @PatchMapping("/reports/{reportId}/approve")
    public ResponseEntity<?> approveReport(@PathVariable Long reportId) {
        try {
            ReportDTO.ReportResponse updatedReport = adminService.approveReportAndTakeAction(reportId);
            return ResponseEntity.ok(updatedReport);
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    @PatchMapping("/reports/{reportId}/reject")
    public ResponseEntity<?> rejectReport(@PathVariable Long reportId) {
        try {
            ReportDTO.ReportResponse updatedReport = reportService.rejectReport(reportId);
            return ResponseEntity.ok(updatedReport);
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // '게시글' 삭제 (Material을 Post로 간주, 연관 신고 승인 자동화 연동)
    @DeleteMapping("/posts/{postId}")
    public ResponseEntity<?> deletePost(@PathVariable Long postId) {
        try {
            adminService.deleteMaterialByAdmin(postId);
            return ResponseEntity.ok("게시글(학습 자료)이 성공적으로 삭제되었습니다.");
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // --- AI 에이전트 모니터링 ---
    @GetMapping("/agents")
    public ResponseEntity<List<Agent>> getAllAgents() {
        List<Agent> agents = adminService.getAllAgents();
        return ResponseEntity.ok(agents);
    }

    @DeleteMapping("/agents/{agentId}")
    public ResponseEntity<?> deleteAgent(@PathVariable Long agentId) {
        try {
            adminService.deleteAgent(agentId);
            return ResponseEntity.ok("AI 에이전트가 성공적으로 삭제/비활성화되었습니다.");
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }
}