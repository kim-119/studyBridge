package com.studybridge.api.controller;

import com.studybridge.api.dto.TodoDTO;
import com.studybridge.api.service.TodoService;
import com.studybridge.api.security.domain.CustomUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/todos")
public class TodoController {

    private final TodoService todoService;

    // 할 일 추가
    @PostMapping
    public ResponseEntity<TodoDTO.Response> createTodo(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody TodoDTO.Request request) {

        return ResponseEntity.ok(todoService.createTodo(userDetails.getId(), request));
    }

    // 사용자별 할 일 목록 조회
    @GetMapping
    public ResponseEntity<List<TodoDTO.Response>> getTodos(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        return ResponseEntity.ok(todoService.getTodosByUserId(userDetails.getId()));
    }

    // 할 일 상태 토글
    @PatchMapping("/{id}/toggle")
    public ResponseEntity<TodoDTO.Response> toggleTodo(@PathVariable Long id) {
        return ResponseEntity.ok(todoService.toggleTodo(id));
    }

    // 할 일 삭제
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteTodo(@PathVariable Long id) {
        todoService.deleteTodo(id);
        return ResponseEntity.noContent().build();
    }
}
