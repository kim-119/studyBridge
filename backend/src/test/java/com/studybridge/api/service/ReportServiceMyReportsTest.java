package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.entity.Blog;
import com.studybridge.api.entity.BlogComment;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyReport;
import com.studybridge.api.entity.Report;
import com.studybridge.api.entity.ReportReason;
import com.studybridge.api.entity.ReportStatus;
import com.studybridge.api.entity.ReportType;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.BlogCommentRepository;
import com.studybridge.api.repository.BlogRepository;
import com.studybridge.api.repository.GroupStudyReportRepository;
import com.studybridge.api.repository.ReportRepository;
import com.studybridge.api.repository.UserRepository;
import jakarta.persistence.EntityNotFoundException;
import java.time.LocalDateTime;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

/**
 * ReportService.getMyReports: 신고자 id 로만 두 저장소를 조회해 합치고(최신순), 삭제된 게시글/댓글·탈퇴 유저는 대체 라벨로 떨어진다.
 */
class ReportServiceMyReportsTest {

    private static final long ME = 55L;

    private ReportRepository reportRepository;
    private GroupStudyReportRepository groupStudyReportRepository;
    private ReportService service;
    private User me;

    @BeforeEach
    void setUp() {
        reportRepository = Mockito.mock(ReportRepository.class);
        groupStudyReportRepository = Mockito.mock(GroupStudyReportRepository.class);
        service = new ReportService(reportRepository, Mockito.mock(UserRepository.class),
                Mockito.mock(BlogRepository.class), Mockito.mock(BlogCommentRepository.class), groupStudyReportRepository);
        me = User.builder().id(ME).email("me@x").password("p").displayName("SRE오답").build();
    }

    private Report knowledgeReport(long id, ReportType type, LocalDateTime at) {
        Report r = Report.builder().reportId(id).reporter(me).reportType(type)
                .reason(ReportReason.SPAM).details("d" + id).status(ReportStatus.PENDING).build();
        r.setCreatedAt(at);
        return r;
    }

    @Test
    void mergesKnowledgeAndGroupReports_newestFirst_byPrincipalIdOnly() {
        Blog blog = Mockito.mock(Blog.class);
        Mockito.when(blog.getBlogId()).thenReturn(32L);
        Mockito.when(blog.getTitle()).thenReturn("하이");
        Report post = knowledgeReport(1L, ReportType.POST, LocalDateTime.of(2026, 10, 1, 10, 0));
        post.setReportedBlog(blog);

        User reported = User.builder().id(68L).email("other@x").password("p").displayName("상대").build();
        GroupStudy group = Mockito.mock(GroupStudy.class);
        Mockito.when(group.getId()).thenReturn(32L);
        Mockito.when(group.getTitle()).thenReturn("알고리즘 스터디");
        GroupStudyReport gr = GroupStudyReport.builder().id(7L).reporter(me).reportedUser(reported).groupStudy(group)
                .reason("도배 및 스팸 - 반복").build();
        gr.setCreatedAt(LocalDateTime.of(2026, 10, 5, 10, 0));

        Mockito.when(reportRepository.findByReporter_IdOrderByCreatedAtDesc(ME, org.springframework.data.domain.PageRequest.of(0, 20))).thenReturn(List.of(post));
        Mockito.when(groupStudyReportRepository.findByReporter_IdOrderByCreatedAtDesc(ME, org.springframework.data.domain.PageRequest.of(0, 20))).thenReturn(List.of(gr));

        List<ReportDTO.MyReportResponse> out = service.getMyReports(ME, "KNOWLEDGE", 0, 20);

        assertEquals(1, out.size());
        assertEquals("KNOWLEDGE", out.get(0).getSource());
        assertEquals("POST", out.get(0).getTargetType());
        assertEquals(32L, out.get(0).getTargetId());
        List<ReportDTO.MyReportResponse> groups = service.getMyReports(ME, "GROUP", 0, 20);
        assertEquals(1, groups.size());
        assertEquals("GROUP", groups.get(0).getSource());
        assertNull(groups.get(0).getStatus());

        Mockito.verify(reportRepository).findByReporter_IdOrderByCreatedAtDesc(ME, org.springframework.data.domain.PageRequest.of(0, 20));
        Mockito.verify(groupStudyReportRepository).findByReporter_IdOrderByCreatedAtDesc(ME, org.springframework.data.domain.PageRequest.of(0, 20));
        Mockito.verify(reportRepository, Mockito.never()).findAllByOrderByCreatedAtDesc();
    }

    @Test
    void deletedTargets_fallBackToSafeLabels() {
        Report deletedPost = knowledgeReport(1L, ReportType.POST, LocalDateTime.of(2026, 10, 3, 0, 0)); // reportedBlog == null
        Report deletedComment = knowledgeReport(2L, ReportType.COMMENT, LocalDateTime.of(2026, 10, 2, 0, 0)); // reportedComment == null
        Report withdrawn = knowledgeReport(3L, ReportType.USER, LocalDateTime.of(2026, 10, 1, 0, 0)); // reportedUser == null

        // 지연 프록시가 EntityNotFound 를 던지는 경우도 대체 라벨.
        Blog ghost = Mockito.mock(Blog.class);
        Mockito.when(ghost.getBlogId()).thenReturn(99L);
        Mockito.when(ghost.getTitle()).thenThrow(new EntityNotFoundException("Unable to find Blog 99"));
        Report ghostPost = knowledgeReport(4L, ReportType.POST, LocalDateTime.of(2026, 9, 30, 0, 0));
        ghostPost.setReportedBlog(ghost);

        BlogComment comment = Mockito.mock(BlogComment.class);
        Mockito.when(comment.getCommentId()).thenReturn(5L);
        Mockito.when(comment.getContent()).thenReturn("가나다라마바사아자차카타파하가나다라마바사아자차카타파하가나다라마바사");
        Report longComment = knowledgeReport(5L, ReportType.COMMENT, LocalDateTime.of(2026, 9, 29, 0, 0));
        longComment.setReportedComment(comment);

        Mockito.when(reportRepository.findByReporter_IdOrderByCreatedAtDesc(ME, org.springframework.data.domain.PageRequest.of(0, 20)))
                .thenReturn(List.of(deletedPost, deletedComment, withdrawn, ghostPost, longComment));
        Mockito.when(groupStudyReportRepository.findByReporter_IdOrderByCreatedAtDesc(ME, org.springframework.data.domain.PageRequest.of(0, 20))).thenReturn(List.of());

        List<ReportDTO.MyReportResponse> out = service.getMyReports(ME, "KNOWLEDGE", 0, 20);

        assertEquals("삭제된 게시글", out.get(0).getTargetSummary());
        assertFalse(out.get(0).isTargetAvailable());
        assertNull(out.get(0).getTargetId());
        assertEquals("삭제된 댓글", out.get(1).getTargetSummary());
        assertEquals("탈퇴한 사용자", out.get(2).getTargetSummary());
        assertEquals("삭제된 게시글", out.get(3).getTargetSummary());
        assertFalse(out.get(3).isTargetAvailable());
        assertEquals(33, out.get(4).getTargetSummary().length()); // 30자 + "..."
        assertTrue(out.get(4).getTargetSummary().endsWith("..."));
        assertTrue(out.get(4).isTargetAvailable());
    }

    @Test
    void emptyWhenNothingReported() {
        Mockito.when(reportRepository.findByReporter_IdOrderByCreatedAtDesc(ME, org.springframework.data.domain.PageRequest.of(0, 20))).thenReturn(List.of());
        Mockito.when(groupStudyReportRepository.findByReporter_IdOrderByCreatedAtDesc(ME, org.springframework.data.domain.PageRequest.of(0, 20))).thenReturn(List.of());
        assertTrue(service.getMyReports(ME, "KNOWLEDGE", 0, 20).isEmpty());
    }
}
