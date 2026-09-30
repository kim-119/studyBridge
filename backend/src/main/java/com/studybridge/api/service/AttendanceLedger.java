package com.studybridge.api.service;

import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyAttendance;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyAttendanceRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.Optional;

/**
 * 그룹 출석/공부시간 원장(group_study_attendances) 기록기. 세션(Timer)의 서버 시각 구간만 입력으로 받는다.
 *  · checkIn: 세션 시작(또는 그룹 연결) 시 당일 행 생성(0초). "그날 공부 세션 1회 이상 = 출석".
 *  · credit: [from, to) 구간을 날짜별로 분할해 각 날짜 행에 초를 더한다(heartbeat 마다 진행분, 종료 시 잔여분).
 *    호출 측(TimerService)이 Timer 행 잠금 아래에서 lastHeartbeatAt("credited until") 을 함께 전진시키므로 중복 크레딧이 없다.
 * 세션이 그룹에 연결돼 있지 않거나(개인 타이머) 그룹 멤버가 아니면 아무것도 기록하지 않는다.
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class AttendanceLedger {

    public static final String STATUS_PRESENT = "PRESENT";

    private final GroupStudyAttendanceRepository attendanceRepository;
    private final GroupStudyMemberRepository memberRepository;
    private final GroupStudyRepository groupStudyRepository;
    private final UserRepository userRepository;

    public boolean isGroupMember(Long groupStudyId, Long userId) {
        return groupStudyId != null && memberRepository.existsByGroupStudyIdAndUserIdAndStatus(
                groupStudyId, userId, GroupStudyMemberStatus.JOINED);
    }

    /** 세션 시작 시각의 날짜 행을 보장한다(이미 있으면 유지). */
    public void checkIn(Timer timer, LocalDateTime at) {
        Long groupId = timer.getGroupStudyId();
        Long userId = timer.getUser().getId();
        if (!isGroupMember(groupId, userId)) {
            return;
        }
        ensureRow(groupId, userId, at, at);
    }

    /** [from, to) 를 날짜별로 분할해 크레딧. 반환값은 실제 반영된 초 합계. */
    public long credit(Timer timer, LocalDateTime from, LocalDateTime to) {
        Long groupId = timer.getGroupStudyId();
        Long userId = timer.getUser().getId();
        if (!isGroupMember(groupId, userId)) {
            return 0L;
        }
        long total = 0L;
        for (StudyIntervalSplitter.DaySegment seg : StudyIntervalSplitter.split(from, to)) {
            GroupStudyAttendance row = ensureRow(groupId, userId, seg.start(), seg.end());
            long secs = seg.seconds();
            row.setStudyDurationSeconds((row.getStudyDurationSeconds() == null ? 0L : row.getStudyDurationSeconds()) + secs);
            row.setCheckOutTime(seg.end());
            row.setLastActiveAt(seg.end());
            attendanceRepository.save(row);
            total += secs;
        }
        return total;
    }

    private GroupStudyAttendance ensureRow(Long groupId, Long userId, LocalDateTime segmentStart, LocalDateTime activeAt) {
        Optional<GroupStudyAttendance> existing = attendanceRepository
                .findByGroupStudyIdAndUserIdAndDate(groupId, userId, segmentStart.toLocalDate());
        if (existing.isPresent()) {
            GroupStudyAttendance row = existing.get();
            if (row.getLastActiveAt() == null || row.getLastActiveAt().isBefore(activeAt)) {
                row.setLastActiveAt(activeAt);
            }
            return row;
        }
        GroupStudy group = groupStudyRepository.findById(groupId).orElse(null);
        User user = userRepository.findById(userId).orElse(null);
        if (group == null || user == null) {
            throw new IllegalStateException("출석 기록 대상 그룹/사용자를 찾을 수 없습니다.");
        }
        GroupStudyAttendance row = GroupStudyAttendance.builder()
                .groupStudy(group)
                .user(user)
                .date(segmentStart.toLocalDate())
                .checkInTime(segmentStart)
                .status(STATUS_PRESENT)
                .studyDurationSeconds(0L)
                .lastActiveAt(activeAt)
                .build();
        GroupStudyAttendance saved = attendanceRepository.save(row);
        log.info("Attendance row created. groupId={}, userId={}, date={}", groupId, userId, saved.getDate());
        return saved;
    }
}
