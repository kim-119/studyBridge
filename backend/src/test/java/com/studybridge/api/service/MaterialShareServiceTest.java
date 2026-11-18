package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialGroupShare;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.QuizAccessException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.MaterialGroupShareRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.UserRepository;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** 공유 관계: 소유자·JOINED 그룹·PDF 만, 멱등, 해제, 그룹 목록은 멤버만 + 소유자가 떠난 공유 제외, 식별 정보 최소. */
class MaterialShareServiceTest {

    static final long OWNER = 55L, MEMBER = 61L, OUTSIDER = 70L, MAT = 900L, LOG = 902L, GROUP = 33L, OTHER_GROUP = 34L;
    final List<MaterialGroupShare> shares = new ArrayList<>();
    final Set<String> joined = new HashSet<>();
    final AtomicLong ids = new AtomicLong(1);
    MaterialShareService service;

    @BeforeEach
    void setUp() {
        Material pdf = new Material();
        pdf.setMaterialId(MAT); pdf.setUserId(OWNER); pdf.setTitle("CNN 노트"); pdf.setMaterialType(MaterialType.PDF);
        Material log = new Material();
        log.setMaterialId(LOG); log.setUserId(OWNER); log.setTitle("일지"); log.setMaterialType(MaterialType.STUDY_LOG);
        MaterialRepository mr = mock(MaterialRepository.class);
        when(mr.findById(MAT)).thenReturn(Optional.of(pdf));
        when(mr.findById(LOG)).thenReturn(Optional.of(log));
        when(mr.findAllById(any())).thenAnswer(i -> ((Collection<?>) i.getArgument(0)).contains(MAT) ? List.of(pdf) : List.of());
        MaterialGroupShareRepository sr = mock(MaterialGroupShareRepository.class);
        when(sr.findByMaterialIdAndGroupStudyId(anyLong(), anyLong())).thenAnswer(i -> shares.stream()
                .filter(s -> s.getMaterialId().equals(i.getArgument(0)) && s.getGroupStudyId().equals(i.getArgument(1))).findFirst());
        when(sr.saveAndFlush(any())).thenAnswer(i -> { MaterialGroupShare s = i.getArgument(0); s.setId(ids.getAndIncrement()); shares.add(s); return s; });
        when(sr.findByMaterialId(anyLong())).thenAnswer(i -> shares.stream().filter(s -> s.getMaterialId().equals(i.getArgument(0))).toList());
        when(sr.findByGroupStudyIdOrderByCreatedAtDesc(anyLong())).thenAnswer(i -> shares.stream().filter(s -> s.getGroupStudyId().equals(i.getArgument(0))).toList());
        org.mockito.Mockito.doAnswer(i -> { shares.remove((MaterialGroupShare) i.getArgument(0)); return null; }).when(sr).delete(any());
        GroupStudyRepository gr = mock(GroupStudyRepository.class);
        GroupStudy g = new GroupStudy();
        g.setId(GROUP); g.setTitle("CNN 스터디");
        when(gr.findById(GROUP)).thenReturn(Optional.of(g));
        when(gr.findById(OTHER_GROUP)).thenReturn(Optional.of(new GroupStudy()));
        when(gr.existsById(GROUP)).thenReturn(true);
        when(gr.findAllById(any())).thenReturn(List.of(g));
        GroupStudyMemberRepository gm = mock(GroupStudyMemberRepository.class);
        when(gm.existsByGroupStudyIdAndUserIdAndStatus(anyLong(), anyLong(), any())).thenAnswer(i ->
                i.getArgument(2) == GroupStudyMemberStatus.JOINED && joined.contains(i.getArgument(0) + ":" + i.getArgument(1)));
        UserRepository ur = mock(UserRepository.class);
        when(ur.findAllById(any())).thenReturn(List.of(User.builder().id(OWNER).email("owner@x").displayName("주인").password("p").build()));
        MaterialQuizRepository qr = mock(MaterialQuizRepository.class);
        when(qr.findByMaterial_MaterialIdOrderByCreatedAtDesc(MAT)).thenReturn(List.of(new com.studybridge.api.entity.MaterialQuiz()));
        service = new MaterialShareService(mr, qr, sr, gr, gm, ur);
        joined.add(GROUP + ":" + OWNER);
        joined.add(GROUP + ":" + MEMBER);
    }

    private static String code(org.junit.jupiter.api.function.Executable ex) {
        RuntimeException e = assertThrows(RuntimeException.class, ex);
        return ((QuizAccessException.Coded) e).getCode();
    }

    @Test
    void ownerSharesToJoinedGroup_idempotent_andMemberSeesIt() {
        assertEquals(true, service.share(OWNER, MAT, GROUP).get("created"));
        assertEquals(false, service.share(OWNER, MAT, GROUP).get("created"), "같은 그룹 재공유는 멱등");
        assertEquals(1, shares.size());
        List<Map<String, Object>> list = service.sharedToGroup(MEMBER, GROUP);
        assertEquals(1, list.size());
        assertEquals("CNN 노트", list.get(0).get("title"));
        assertEquals("주인", list.get(0).get("ownerNickname"));
        assertEquals(1, list.get(0).get("quizCount"));
        assertTrue(list.get(0).keySet().stream().noneMatch(k -> k.contains("userId") || k.contains("email") || k.contains("s3")));
    }

    @Test
    void cannotShare_notOwner_notJoinedGroup_nonPdf_missingGroup() {
        assertEquals("FORBIDDEN", code(() -> service.share(MEMBER, MAT, GROUP)), "소유자만");
        assertEquals("FORBIDDEN", code(() -> service.share(OWNER, MAT, OTHER_GROUP)), "가입하지 않은 그룹 불가");
        assertEquals("NOT_SHAREABLE", code(() -> service.share(OWNER, LOG, GROUP)), "PDF 만");
        assertEquals("GROUP_NOT_FOUND", code(() -> service.share(OWNER, MAT, 404L)));
        assertEquals("GROUP_REQUIRED", code(() -> service.share(OWNER, MAT, null)));
        assertEquals("MATERIAL_NOT_FOUND", code(() -> service.share(OWNER, 404L, GROUP)));
        assertTrue(shares.isEmpty());
    }

    @Test
    void groupListing_membersOnly_andOwnerLeavingHidesShare_unshareRemoves() {
        service.share(OWNER, MAT, GROUP);
        assertEquals("FORBIDDEN", code(() -> service.sharedToGroup(OUTSIDER, GROUP)));
        joined.remove(GROUP + ":" + OWNER);
        assertTrue(service.sharedToGroup(MEMBER, GROUP).isEmpty(), "공유한 소유자가 떠나면 목록에서 빠진다");
        joined.add(GROUP + ":" + OWNER);
        service.unshare(OWNER, MAT, GROUP);
        assertTrue(shares.isEmpty());
        assertEquals("FORBIDDEN", code(() -> service.unshare(MEMBER, MAT, GROUP)));
    }
}
