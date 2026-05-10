package com.studybridge.api.controller;

import com.studybridge.api.dto.TodoDTO;
import com.studybridge.api.service.TodoService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@CrossOrigin(origins = "http://localhost:3000")
public class TodoController {

    private final TodoService todoService;

    // 할 일 추가
    @PostMapping("/api/users/{userId}/todos")
    public ResponseEntity<TodoDTO.Response> createTodo(
            @PathVariable Long userId,
            @RequestBody TodoDTO.Request request) {

        request.setUserId(userId);
        return ResponseEntity.ok(todoService.createTodo(request));
    }

    // 사용자별 할 일 목록 조회
    @GetMapping("/api/users/{userId}/todos")
    public ResponseEntity<List<TodoDTO.Response>> getTodos(@PathVariable Long userId) {
        return ResponseEntity.ok(todoService.getTodosByUserId(userId));
    }

    // 할 일 상태 토글
    @PatchMapping("/api/todos/{id}/toggle")
    public ResponseEntity<TodoDTO.Response> toggleTodo(@PathVariable Long id) {
        return ResponseEntity.ok(todoService.toggleTodo(id));
    }

    // 할 일 삭제
    @DeleteMapping("/api/todos/{id}")
    public ResponseEntity<Void> deleteTodo(@PathVariable Long id) {
        todoService.deleteTodo(id);
        return ResponseEntity.noContent().build();
    }
}
