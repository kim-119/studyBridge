package com.studybridge.api.service;

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
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 개인 PDF 자료의 그룹 공유(퀴즈 응시·랭킹 참여 범위). 자료 소유자만, 자신이 JOINED 멤버인 그룹에만 공유/해제한다.
 * 그룹 멤버는 공유 목록에서 자료 제목·소유자 닉네임·퀴즈 수만 본다(원문·S3 URL·추출 텍스트 없음).
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class MaterialShareService {

    private final MaterialRepository materialRepository;
    private final MaterialQuizRepository quizRepository;
    private final MaterialGroupShareRepository shareRepository;
    private final GroupStudyRepository groupStudyRepository;
    private final GroupStudyMemberRepository memberRepository;
    private final UserRepository userRepository;

    private Material ownedPdf(Long userId, Long materialId) {
        Material m = materialRepository.findById(materialId)
                .orElseThrow(() -> QuizAccessException.of(HttpStatus.NOT_FOUND, "MATERIAL_NOT_FOUND", "자료를 찾을 수 없습니다."));
        if (userId == null || !userId.equals(m.getUserId())) {
            throw QuizAccessException.of(HttpStatus.FORBIDDEN, "FORBIDDEN", "자료 소유자만 공유를 관리할 수 있습니다.");
        }
        if (m.getMaterialType() != MaterialType.PDF) {
            throw QuizAccessException.of(HttpStatus.BAD_REQUEST, "NOT_SHAREABLE", "PDF 학습 자료만 그룹에 공유할 수 있습니다.");
        }
        return m;
    }

    private boolean joined(Long groupId, Long userId) {
        return memberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId, GroupStudyMemberStatus.JOINED);
    }

    @Transactional
    public Map<String, Object> share(Long userId, Long materialId, Long groupId) {
        if (groupId == null) throw QuizAccessException.of(HttpStatus.BAD_REQUEST, "GROUP_REQUIRED", "공유할 그룹을 선택해 주세요.");
        Material m = ownedPdf(userId, materialId);
        GroupStudy g = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> QuizAccessException.of(HttpStatus.NOT_FOUND, "GROUP_NOT_FOUND", "그룹을 찾을 수 없습니다."));
        if (!joined(groupId, userId)) {
            throw QuizAccessException.of(HttpStatus.FORBIDDEN, "FORBIDDEN", "내가 가입한 그룹에만 공유할 수 있습니다.");
        }
        MaterialGroupShare share = shareRepository.findByMaterialIdAndGroupStudyId(m.getMaterialId(), groupId).orElse(null);
        boolean created = false;
        if (share == null) {
            try {
                share = shareRepository.saveAndFlush(MaterialGroupShare.builder()
                        .materialId(m.getMaterialId()).groupStudyId(groupId).sharedByUserId(userId).build());
                created = true;
            } catch (DataIntegrityViolationException dup) {
                share = shareRepository.findByMaterialIdAndGroupStudyId(m.getMaterialId(), groupId).orElseThrow(() -> dup);
            }
        }
        log.info("[MATERIAL_SHARE] share materialId={} groupId={} by={} created={}", materialId, groupId, userId, created);
        return view(share, g.getTitle(), created);
    }

    @Transactional
    public void unshare(Long userId, Long materialId, Long groupId) {
        Material m = ownedPdf(userId, materialId);
        shareRepository.findByMaterialIdAndGroupStudyId(m.getMaterialId(), groupId).ifPresent(s -> {
            shareRepository.delete(s);
            log.info("[MATERIAL_SHARE] unshare materialId={} groupId={} by={}", materialId, groupId, userId);
        });
    }

    public List<Map<String, Object>> sharesOf(Long userId, Long materialId) {
        Material m = ownedPdf(userId, materialId);
        List<MaterialGroupShare> shares = shareRepository.findByMaterialId(m.getMaterialId());
        Map<Long, String> titles = new LinkedHashMap<>();
        groupStudyRepository.findAllById(shares.stream().map(MaterialGroupShare::getGroupStudyId).toList())
                .forEach(g -> titles.put(g.getId(), g.getTitle()));
        List<Map<String, Object>> out = new ArrayList<>();
        for (MaterialGroupShare s : shares) out.add(view(s, titles.get(s.getGroupStudyId()), false));
        return out;
    }

    /** 그룹 멤버용: 이 그룹에 공유된 자료(공유한 소유자가 아직 JOINED 인 것만). */
    public List<Map<String, Object>> sharedToGroup(Long userId, Long groupId) {
        if (!groupStudyRepository.existsById(groupId)) {
            throw QuizAccessException.of(HttpStatus.NOT_FOUND, "GROUP_NOT_FOUND", "그룹을 찾을 수 없습니다.");
        }
        if (!joined(groupId, userId)) throw QuizAccessException.of(HttpStatus.FORBIDDEN, "FORBIDDEN", "그룹 멤버만 볼 수 있습니다.");
        List<MaterialGroupShare> shares = shareRepository.findByGroupStudyIdOrderByCreatedAtDesc(groupId);
        Map<Long, Material> materials = new LinkedHashMap<>();
        materialRepository.findAllById(shares.stream().map(MaterialGroupShare::getMaterialId).toList())
                .forEach(m -> materials.put(m.getMaterialId(), m));
        Set<Long> owners = new HashSet<>();
        materials.values().forEach(m -> owners.add(m.getUserId()));
        Map<Long, String> nicks = new LinkedHashMap<>();
        userRepository.findAllById(owners).forEach(u -> nicks.put(u.getId(), nickname(u)));
        List<Map<String, Object>> out = new ArrayList<>();
        for (MaterialGroupShare s : shares) {
            Material m = materials.get(s.getMaterialId());
            if (m == null || !joined(groupId, m.getUserId())) continue;
            Map<String, Object> v = new LinkedHashMap<>();
            v.put("materialId", m.getMaterialId());
            v.put("title", m.getTitle());
            v.put("ownerNickname", nicks.getOrDefault(m.getUserId(), "탈퇴한 사용자"));
            v.put("quizCount", quizRepository.findByMaterial_MaterialIdOrderByCreatedAtDesc(m.getMaterialId()).size());
            v.put("sharedAt", s.getCreatedAt());
            v.put("mine", userId.equals(m.getUserId()));
            out.add(v);
        }
        return out;
    }

    private static String nickname(User u) {
        return u.getDisplayName() == null || u.getDisplayName().isBlank() ? "익명" : u.getDisplayName().trim();
    }

    private static Map<String, Object> view(MaterialGroupShare s, String groupTitle, boolean created) {
        Map<String, Object> v = new LinkedHashMap<>();
        v.put("materialId", s.getMaterialId());
        v.put("groupId", s.getGroupStudyId());
        v.put("groupTitle", groupTitle);
        v.put("sharedAt", s.getCreatedAt());
        v.put("created", created);
        return v;
    }
}
