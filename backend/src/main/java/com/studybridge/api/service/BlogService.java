package com.studybridge.api.service;

import com.studybridge.api.dto.BlogCommentDTO;
import com.studybridge.api.dto.BlogDTO;
import com.studybridge.api.entity.Blog;
import com.studybridge.api.entity.BlogComment;
import com.studybridge.api.entity.BlogLike;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.BlogCommentRepository;
import com.studybridge.api.repository.BlogLikeRepository;
import com.studybridge.api.repository.BlogRepository;
import com.studybridge.api.repository.ReportRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.Optional;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class BlogService {

    private final BlogRepository blogRepository;
    private final BlogCommentRepository blogCommentRepository;
    private final BlogLikeRepository blogLikeRepository;
    private final UserRepository userRepository;
    private final ReportRepository reportRepository;
    private final S3Service s3Service;

    // 블로그 생성
    @Transactional
    public BlogDTO.Response createPost(Long userId, String title, String content, MultipartFile image, MultipartFile pdf) throws IOException {
        User author = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        String imageS3Key = null;
        if (image != null && !image.isEmpty()) {
            imageS3Key = s3Service.uploadBlogFile(image, userId);
        }

        String pdfS3Key = null;
        if (pdf != null && !pdf.isEmpty()) {
            pdfS3Key = s3Service.uploadBlogFile(pdf, userId);
        }

        Blog blog = Blog.builder()
                .title(title)
                .content(content)
                .author(author)
                .imageS3Key(imageS3Key)
                .pdfS3Key(pdfS3Key)
                .build();

        Blog savedBlog = blogRepository.save(blog);
        log.info("[블로그 생성 완료] ID: {}, 작성자: {}", savedBlog.getBlogId(), author.getDisplayName());

        return convertToDTO(savedBlog, userId);
    }

    // 블로그 수정
    @Transactional
    public BlogDTO.Response updatePost(Long userId, Long blogId, String title, String content,
                                       MultipartFile image, MultipartFile pdf,
                                       boolean clearImage, boolean clearPdf) throws IOException {
        Blog blog = blogRepository.findById(blogId)
                .orElseThrow(() -> new IllegalArgumentException("게시글을 찾을 수 없습니다."));

        if (!blog.getAuthor().getId().equals(userId)) {
            throw new SecurityException("해당 게시글에 대한 수정 권한이 없습니다.");
        }

        if (title != null && !title.isBlank()) {
            blog.setTitle(title);
        }
        if (content != null && !content.isBlank()) {
            blog.setContent(content);
        }

        // 이미지 파일 업데이트
        if (clearImage) {
            if (blog.getImageS3Key() != null) {
                s3Service.deleteFile(blog.getImageS3Key());
                blog.setImageS3Key(null);
            }
        } else if (image != null && !image.isEmpty()) {
            // 기존 이미지 삭제
            if (blog.getImageS3Key() != null) {
                s3Service.deleteFile(blog.getImageS3Key());
            }
            String key = s3Service.uploadBlogFile(image, userId);
            blog.setImageS3Key(key);
        }

        // PDF 파일 업데이트
        if (clearPdf) {
            if (blog.getPdfS3Key() != null) {
                s3Service.deleteFile(blog.getPdfS3Key());
                blog.setPdfS3Key(null);
            }
        } else if (pdf != null && !pdf.isEmpty()) {
            // 기존 PDF 삭제
            if (blog.getPdfS3Key() != null) {
                s3Service.deleteFile(blog.getPdfS3Key());
            }
            String key = s3Service.uploadBlogFile(pdf, userId);
            blog.setPdfS3Key(key);
        }

        Blog updatedBlog = blogRepository.save(blog);
        log.info("[블로그 수정 완료] ID: {}", updatedBlog.getBlogId());

        return convertToDTO(updatedBlog, userId);
    }

    // 블로그 삭제 (연관 파일도 함께 삭제)
    @Transactional
    public void deletePost(Long userId, Long blogId) {
        Blog blog = blogRepository.findById(blogId)
                .orElseThrow(() -> new IllegalArgumentException("게시글을 찾을 수 없습니다."));

        if (!blog.getAuthor().getId().equals(userId)) {
            throw new SecurityException("해당 게시글에 대한 삭제 권한이 없습니다.");
        }

        deletePostForce(blogId);
    }

    // 블로그 관리자 강제 삭제 (소유권 검증 없음)
    @Transactional
    public void deletePostForce(Long blogId) {
        Blog blog = blogRepository.findById(blogId)
                .orElseThrow(() -> new IllegalArgumentException("게시글을 찾을 수 없습니다."));

        // S3 첨부파일들 정리
        if (blog.getImageS3Key() != null) {
            s3Service.deleteFile(blog.getImageS3Key());
        }
        if (blog.getPdfS3Key() != null) {
            s3Service.deleteFile(blog.getPdfS3Key());
        }

        blogRepository.delete(blog);
        log.info("[블로그 강제 삭제 완료] ID: {}", blogId);
    }

    // 단건 상세 조회
    public BlogDTO.Response getPost(Long userId, Long blogId) {
        Blog blog = blogRepository.findById(blogId)
                .orElseThrow(() -> new IllegalArgumentException("게시글을 찾을 수 없습니다."));

        return convertToDTO(blog, userId);
    }

    // 전체 게시글 조회
    public List<BlogDTO.Response> listPosts(Long userId) {
        return blogRepository.findAllByOrderByCreatedAtDesc().stream()
                .map(blog -> convertToDTO(blog, userId))
                .collect(Collectors.toList());
    }

    // 게시글 검색
    public List<BlogDTO.Response> searchPosts(Long userId, String keyword) {
        log.info("[블로그 검색] 키워드: {}, 요청자 ID: {}", keyword, userId);
        return blogRepository.findByTitleContainingIgnoreCaseOrContentContainingIgnoreCaseOrAuthor_DisplayNameContainingIgnoreCaseOrderByCreatedAtDesc(
                keyword, keyword, keyword).stream()
                .map(blog -> convertToDTO(blog, userId))
                .collect(Collectors.toList());
    }

    // 좋아요 토글
    @Transactional
    public BlogDTO.Response toggleLike(Long userId, Long blogId) {
        Blog blog = blogRepository.findById(blogId)
                .orElseThrow(() -> new IllegalArgumentException("게시글을 찾을 수 없습니다."));
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        Optional<BlogLike> existingLike = blogLikeRepository.findByBlog_BlogIdAndUser_Id(blogId, userId);
        if (existingLike.isPresent()) {
            blogLikeRepository.delete(existingLike.get());
            log.info("[좋아요 취소] 블로그: {}, 사용자: {}", blogId, user.getDisplayName());
        } else {
            BlogLike like = BlogLike.builder()
                    .blog(blog)
                    .user(user)
                    .build();
            blogLikeRepository.save(like);
            log.info("[좋아요 추가] 블로그: {}, 사용자: {}", blogId, user.getDisplayName());
        }

        // 변경된 트랜잭션 반영 후 최신 DTO 반환
        return convertToDTO(blog, userId);
    }

    // 댓글 작성
    @Transactional
    public BlogCommentDTO.Response addComment(Long userId, Long blogId, String content) {
        Blog blog = blogRepository.findById(blogId)
                .orElseThrow(() -> new IllegalArgumentException("게시글을 찾을 수 없습니다."));
        User author = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        BlogComment comment = BlogComment.builder()
                .blog(blog)
                .author(author)
                .content(content)
                .build();

        BlogComment savedComment = blogCommentRepository.save(comment);
        log.info("[댓글 작성 완료] 블로그: {}, 댓글 ID: {}, 작성자: {}", blogId, savedComment.getCommentId(), author.getDisplayName());

        return convertCommentToDTO(savedComment);
    }

    // 댓글 삭제
    @Transactional
    public void deleteComment(Long userId, Long blogId, Long commentId) {
        BlogComment comment = blogCommentRepository.findById(commentId)
                .orElseThrow(() -> new IllegalArgumentException("댓글을 찾을 수 없습니다."));

        if (!comment.getBlog().getBlogId().equals(blogId)) {
            throw new IllegalArgumentException("잘못된 요청입니다.");
        }

        // 댓글 작성자이거나 게시글 작성자 본인인 경우에만 삭제 가능
        boolean isCommentAuthor = comment.getAuthor().getId().equals(userId);
        boolean isBlogAuthor = comment.getBlog().getAuthor().getId().equals(userId);

        if (!isCommentAuthor && !isBlogAuthor) {
            throw new SecurityException("댓글 삭제 권한이 없습니다.");
        }

        reportRepository.deleteByReportedComment_CommentId(commentId);
        blogCommentRepository.delete(comment);
        log.info("[댓글 삭제 완료] 댓글 ID: {}, 요청자 ID: {}", commentId, userId);
    }

    // 댓글 관리자 강제 삭제 (소유권 검증 없음)
    @Transactional
    public void deleteCommentForce(Long commentId) {
        BlogComment comment = blogCommentRepository.findById(commentId)
                .orElseThrow(() -> new IllegalArgumentException("댓글을 찾을 수 없습니다."));

        reportRepository.deleteByReportedComment_CommentId(commentId);
        blogCommentRepository.delete(comment);
        log.info("[댓글 강제 삭제 완료] 댓글 ID: {}", commentId);
    }

    // Entity -> DTO 변환 헬퍼
    private BlogDTO.Response convertToDTO(Blog blog, Long currentUserId) {
        String imagePresignedUrl = null;
        if (blog.getImageS3Key() != null && !blog.getImageS3Key().isBlank()) {
            try {
                imagePresignedUrl = s3Service.getPresignedUrl(blog.getImageS3Key());
            } catch (Exception e) {
                log.warn("블로그 이미지 Presigned URL 생성 실패 blogId={}: {}", blog.getBlogId(), e.getMessage());
            }
        }

        String pdfPresignedUrl = null;
        if (blog.getPdfS3Key() != null && !blog.getPdfS3Key().isBlank()) {
            try {
                pdfPresignedUrl = s3Service.getPresignedUrl(blog.getPdfS3Key());
            } catch (Exception e) {
                log.warn("블로그 PDF Presigned URL 생성 실패 blogId={}: {}", blog.getBlogId(), e.getMessage());
            }
        }

        long likeCount = blogLikeRepository.countByBlog_BlogId(blog.getBlogId());
        boolean likedByCurrentUser = currentUserId != null && blogLikeRepository.existsByBlog_BlogIdAndUser_Id(blog.getBlogId(), currentUserId);

        List<BlogCommentDTO.Response> commentDTOs = blogCommentRepository.findByBlog_BlogIdOrderByCreatedAtAsc(blog.getBlogId()).stream()
                .map(this::convertCommentToDTO)
                .collect(Collectors.toList());

        String authorPhotoUrl = blog.getAuthor().getPhotoUrl();
        if (authorPhotoUrl != null && !authorPhotoUrl.isBlank() && !authorPhotoUrl.startsWith("http")) {
            try {
                authorPhotoUrl = s3Service.getPresignedUrl(authorPhotoUrl);
            } catch (Exception e) {
                log.warn("Failed to generate presigned URL for blog author photo: {}", e.getMessage());
            }
        }

        return BlogDTO.Response.builder()
                .blogId(blog.getBlogId())
                .title(blog.getTitle())
                .content(blog.getContent())
                .authorId(blog.getAuthor().getId())
                .authorNickname(blog.getAuthor().getDisplayName())
                .authorPhotoUrl(authorPhotoUrl)
                .imageS3Key(blog.getImageS3Key())
                .pdfS3Key(blog.getPdfS3Key())
                .imagePresignedUrl(imagePresignedUrl)
                .pdfPresignedUrl(pdfPresignedUrl)
                .likeCount(likeCount)
                .likedByCurrentUser(likedByCurrentUser)
                .comments(commentDTOs)
                .createdAt(blog.getCreatedAt())
                .updatedAt(blog.getUpdatedAt())
                .build();
    }

    private BlogCommentDTO.Response convertCommentToDTO(BlogComment comment) {
        String authorPhotoUrl = comment.getAuthor().getPhotoUrl();
        if (authorPhotoUrl != null && !authorPhotoUrl.isBlank() && !authorPhotoUrl.startsWith("http")) {
            try {
                authorPhotoUrl = s3Service.getPresignedUrl(authorPhotoUrl);
            } catch (Exception e) {
                log.warn("Failed to generate presigned URL for comment author photo: {}", e.getMessage());
            }
        }

        return BlogCommentDTO.Response.builder()
                .commentId(comment.getCommentId())
                .blogId(comment.getBlog().getBlogId())
                .authorId(comment.getAuthor().getId())
                .authorNickname(comment.getAuthor().getDisplayName())
                .authorPhotoUrl(authorPhotoUrl)
                .content(comment.getContent())
                .createdAt(comment.getCreatedAt())
                .updatedAt(comment.getUpdatedAt())
                .build();
    }
}
