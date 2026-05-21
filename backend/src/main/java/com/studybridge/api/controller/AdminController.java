package com.studybridge.api.controller;

import com.studybridge.api.dto.AdminDashboardDTO;
import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.service.AdminService;
import com.studybridge.api.service.UserService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class AdminController {

    private final UserService userService;
    private final AdminService adminService;

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

    @PutMapping("/users/{userId}")
    public ResponseEntity<?> updateUser(@PathVariable Long userId, @Valid @RequestBody UserDTO.AdminUpdateUserRequest request) {
        try {
            UserDTO.Response updatedUser = userService.updateUserByAdmin(userId, request);
            return ResponseEntity.ok(updatedUser);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // --- 콘텐츠 관리 ---
    @GetMapping("/materials")
    public ResponseEntity<List<MaterialDTO>> getAllMaterials() {
        List<MaterialDTO> materials = adminService.getAllMaterials();
        return ResponseEntity.ok(materials);
    }

    @DeleteMapping("/materials/{materialId}")
    public ResponseEntity<?> deleteMaterial(@PathVariable Long materialId) {
        try {
            adminService.deleteMaterialByAdmin(materialId);
            return ResponseEntity.ok("학습 자료가 성공적으로 삭제되었습니다.");
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }
}