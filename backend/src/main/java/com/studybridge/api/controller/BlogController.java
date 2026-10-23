package com.studybridge.api.controller;

import com.studybridge.api.dto.BlogCommentDTO;
import com.studybridge.api.dto.BlogDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.BlogService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;

@RestController
@RequestMapping("/api/blogs")
@RequiredArgsConstructor
public class BlogController {

    private final BlogService blogService;

    // 블로그 포스트 생성
    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<BlogDTO.Response> createPost(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam("title") String title,
            @RequestParam("content") String content,
            @RequestParam(value = "image", required = false) MultipartFile image,
            @RequestParam(value = "pdf", required = false) MultipartFile pdf) throws IOException {

        BlogDTO.Response response = blogService.createPost(
                userDetails.getId(),
                title,
                content,
                image,
                pdf
        );
        return ResponseEntity.ok(response);
    }

    // 블로그 포스트 수정
    @PutMapping(value = "/{blogId}", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<BlogDTO.Response> updatePost(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long blogId,
            @RequestParam(value = "title", required = false) String title,
            @RequestParam(value = "content", required = false) String content,
            @RequestParam(value = "image", required = false) MultipartFile image,
            @RequestParam(value = "pdf", required = false) MultipartFile pdf,
            @RequestParam(value = "clearImage", required = false, defaultValue = "false") boolean clearImage,
            @RequestParam(value = "clearPdf", required = false, defaultValue = "false") boolean clearPdf) throws IOException {

        BlogDTO.Response response = blogService.updatePost(
                userDetails.getId(),
                blogId,
                title,
                content,
                image,
                pdf,
                clearImage,
                clearPdf
        );
        return ResponseEntity.ok(response);
    }

    // 블로그 포스트 삭제
    @DeleteMapping("/{blogId}")
    public ResponseEntity<Void> deletePost(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long blogId) {
        blogService.deletePost(userDetails.getId(), blogId);
        return ResponseEntity.ok().build();
    }

    // 블로그 포스트 단건 조회
    @GetMapping("/{blogId}")
    public ResponseEntity<BlogDTO.Response> getPost(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long blogId) {
        BlogDTO.Response response = blogService.getPost(userDetails.getId(), blogId);
        return ResponseEntity.ok(response);
    }

    // 블로그 포스트 목록 조회
    @GetMapping
    public ResponseEntity<List<BlogDTO.Response>> listPosts(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        List<BlogDTO.Response> responses = blogService.listPosts(userDetails.getId());
        return ResponseEntity.ok(responses);
    }

    // 블로그 포스트 검색
    @GetMapping("/search")
    public ResponseEntity<List<BlogDTO.Response>> searchPosts(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam("keyword") String keyword) {
        List<BlogDTO.Response> responses = blogService.searchPosts(userDetails.getId(), keyword);
        return ResponseEntity.ok(responses);
    }

    // 좋아요 토글
    @PostMapping("/{blogId}/like")
    public ResponseEntity<BlogDTO.Response> toggleLike(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long blogId) {
        BlogDTO.Response response = blogService.toggleLike(userDetails.getId(), blogId);
        return ResponseEntity.ok(response);
    }

    // 댓글 작성
    @PostMapping("/{blogId}/comments")
    public ResponseEntity<BlogCommentDTO.Response> addComment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long blogId,
            @RequestBody BlogCommentDTO.Request request) {
        BlogCommentDTO.Response response = blogService.addComment(userDetails.getId(), blogId, request.getContent());
        return ResponseEntity.ok(response);
    }

    // 댓글 삭제
    @DeleteMapping("/{blogId}/comments/{commentId}")
    public ResponseEntity<Void> deleteComment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long blogId,
            @PathVariable Long commentId) {
        blogService.deleteComment(userDetails.getId(), blogId, commentId);
        return ResponseEntity.ok().build();
    }
}
