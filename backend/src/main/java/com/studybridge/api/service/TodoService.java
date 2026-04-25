package com.studybridge.api.service;

import com.studybridge.api.dto.TodoDTO;
import com.studybridge.api.entity.Todo;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.TodoRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class TodoService {

    private final TodoRepository todoRepository;
    private final UserRepository userRepository;

    // 1. 할일 추가
    @Transactional
    public TodoDTO.Response createTodo(TodoDTO.Request request) {
        User user = userRepository.findById(request.getUserId())
                .orElseThrow(() -> new RuntimeException("사용자를 찾을 수 없습니다."));

        Todo todo = Todo.builder()
                .user(user)
                .text(request.getText())
                .startDate(request.getStartDate())
                .endDate(request.getEndDate())
                .viewType(request.getViewType())
                .completed(request.getCompleted() != null && request.getCompleted())
                .build();

        Todo savedTodo = todoRepository.save(todo);
        return convertToResponse(savedTodo);
    }

    // 2. 사용자별 할 일 목록 조회
    public List<TodoDTO.Response> getTodosByUserId(Long userId) {
        return todoRepository.findByUserId(userId).stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    // 3. 할 일 상태 토글 (완료/미완료)
    @Transactional
    public TodoDTO.Response toggleTodo(Long todoId) {
        Todo todo = todoRepository.findById(todoId)
                .orElseThrow(() -> new RuntimeException("할 일을 찾을 수 없습니다."));

        todo.setCompleted(!todo.getCompleted());
        return convertToResponse(todo);
    }

    // 4. 할 일 삭제
    @Transactional
    public void deleteTodo(Long todoId) {
        todoRepository.deleteById(todoId);
    }

    // DTO 변환해줌
    private TodoDTO.Response convertToResponse(Todo todo) {
        return TodoDTO.Response.builder()
                .id(todo.getId())
                .text(todo.getText())
                .completed(todo.getCompleted())
                .startDate(todo.getStartDate())
                .endDate(todo.getEndDate())
                .viewType(todo.getViewType())
                .createdAt(todo.getCreatedAt())
                .build();
    }
}
