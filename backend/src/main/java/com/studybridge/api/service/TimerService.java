package com.studybridge.api.service;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerEndReason;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.TimerRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.DayOfWeek;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 공부 세션(timers) 서비스 — 서버 시각이 source of truth.
 *
 * <p>상태 머신(현재 도메인은 일시정지 UI 가 없으므로 최소): STARTED → COMPLETED(정상/자동 종료) | CANCELLED(좀비 정리).
 * 종료된 세션은 다시 활성화되지 않는다(새 공부 = 새 세션).</p>
 *
 * <p>내구성 전략(2계층):</p>
 * <ul>
 *   <li>클라이언트 graceful stop: 종료 버튼/방 나가기/pagehide(keepalive) → {@link #endTimer}.</li>
 *   <li>서버 fallback: 30초 heartbeat 가 진행분을 출석 원장에 즉시 크레딧하고 lastHeartbeatAt 을 전진시킨다.
 *       heartbeat 가 {@value #HEARTBEAT_TIMEOUT_SECONDS}초 끊기면 reaper 가 마지막 heartbeat 시각으로 종료 → 손실 ≤ heartbeat 간격.</li>
 * </ul>
 *
 * <p>동시성: 사용자별 활성 세션은 partial unique index(timers.user_id WHERE status='STARTED') + 행 잠금(FOR UPDATE)으로
 * 1개만 보장한다. start/heartbeat/end 는 같은 잠금 아래에서 "credited until"(lastHeartbeatAt)을 전진시키므로 크레딧이 중복되지 않는다.
 * 클라이언트가 보내는 startTime/endTime/durationSeconds 는 신뢰값으로 쓰지 않는다(하위 호환을 위해 필드만 유지).</p>
 */
@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class TimerService {

        /** 권장 heartbeat 간격(클라이언트에 응답으로 알려준다). */
        public static final int HEARTBEAT_INTERVAL_SECONDS = 30;
        /** 이 시간 동안 heartbeat 가 없으면 비정상 종료로 간주(3회 누락). */
        public static final long HEARTBEAT_TIMEOUT_SECONDS = 90;
        /** heartbeat 미지원 세션(구 클라이언트)이 이만큼 남아 있으면 좀비로 CANCELLED 처리(공부시간 미상 → 통계 제외). */
        public static final long STALE_SESSION_HOURS = 24;

        private final TimerRepository timerRepository;
        private final UserRepository userRepository;
        private final AttendanceLedger attendanceLedger;
        private final Clock clock;

        private LocalDateTime now() {
                return LocalDateTime.now(clock).withNano(0);
        }

        // ── 시작 ───────────────────────────────────────────────────────────────────

        /**
         * 세션 시작. 활성 세션이 있으면:
         *  · 같은 컨텍스트(같은 그룹 / 둘 다 개인) → 그 세션을 그대로 반환(멱등, resumed=true)
         *  · 다른 컨텍스트 → 기존 세션을 지금 시각으로 정상 종료(NEW_SESSION)하고 새 세션 시작
         * 그룹 세션은 그룹 멤버만 시작할 수 있다(403).
         */
        @Transactional
        public TimerDTO.Response startTimer(Long userId, TimerDTO.StartRequest request) {
                Long groupStudyId = request == null ? null : request.getGroupStudyId();
                boolean heartbeat = request != null && request.isSupportsHeartbeat();
                return startInternal(userId, groupStudyId, heartbeat);
        }

        /** 그룹스터디 입장 시: 이 그룹의 활성 세션을 보장한다(없으면 시작, 다른 컨텍스트면 교체). */
        @Transactional
        public TimerDTO.Response syncGroupStudyTimer(Long userId, Long groupStudyId, boolean supportsHeartbeat) {
                log.info("Ensuring group study session. userId={}, groupStudyId={}", userId, groupStudyId);
                return startInternal(userId, Objects.requireNonNull(groupStudyId), supportsHeartbeat);
        }

        private TimerDTO.Response startInternal(Long userId, Long groupStudyId, boolean supportsHeartbeat) {
                // 사용자 행 잠금으로 START 를 직렬화한다(동시 START → 두 번째는 첫 세션을 보고 멱등 반환). partial unique index 는 최후 방어선.
                User user = userRepository.findByIdForUpdate(userId)
                                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + userId));
                if (groupStudyId != null && !attendanceLedger.isGroupMember(groupStudyId, userId)) {
                        throw new SecurityException("해당 스터디그룹의 멤버만 그룹 공부 세션을 시작할 수 있습니다.");
                }

                LocalDateTime at = now();
                Optional<Timer> activeOpt = timerRepository.findByUserIdAndStatusForUpdate(userId, TimerStatus.STARTED);
                if (activeOpt.isPresent()) {
                        Timer active = activeOpt.get();
                        if (Objects.equals(active.getGroupStudyId(), groupStudyId)) {
                                if (supportsHeartbeat) {
                                        touch(active, at);
                                }
                                log.info("Active session reused. timerId={}, userId={}, groupStudyId={}", active.getId(), userId, groupStudyId);
                                return toResponseDTO(timerRepository.save(active), true);
                        }
                        endInternal(active, at, TimerEndReason.NEW_SESSION);
                        // 반드시 flush: Hibernate 는 UPDATE 보다 INSERT 를 먼저 내보내므로, 이전 세션의 COMPLETED 전환이 DB 에 먼저 반영되지 않으면
                        // 새 세션 INSERT 가 partial unique index(user_id WHERE status='STARTED') 에 걸린다(2026-09-30 운영 E2E 에서 실증).
                        timerRepository.saveAndFlush(active);
                        log.info("Previous session ended for new context. timerId={}, userId={}, prevGroup={}, newGroup={}",
                                        active.getId(), userId, active.getGroupStudyId(), groupStudyId);
                }

                Timer timer = Timer.builder()
                                .user(user)
                                .startTime(at)
                                .status(TimerStatus.STARTED)
                                .groupStudyId(groupStudyId)
                                .lastHeartbeatAt(supportsHeartbeat ? at : null)
                                .build();
                Timer saved = timerRepository.save(timer);
                if (groupStudyId != null) {
                        attendanceLedger.checkIn(saved, at);
                }
                log.info("Timer started. timerId={}, userId={}, groupStudyId={}, heartbeat={}", saved.getId(), userId, groupStudyId, supportsHeartbeat);
                return toResponseDTO(saved, false);
        }

        // ── 진행(heartbeat) ────────────────────────────────────────────────────────

        /** 활성 세션의 진행분을 크레딧하고 lastHeartbeatAt 을 전진. 활성 세션이 없으면 null(204). */
        @Transactional
        public TimerDTO.Response heartbeat(Long userId) {
                Optional<Timer> activeOpt = timerRepository.findByUserIdAndStatusForUpdate(userId, TimerStatus.STARTED);
                if (activeOpt.isEmpty()) {
                        return null;
                }
                Timer timer = activeOpt.get();
                touch(timer, now());
                return toResponseDTO(timerRepository.save(timer), true);
        }

        private void touch(Timer timer, LocalDateTime at) {
                LocalDateTime creditedUntil = creditedUntil(timer);
                if (at.isAfter(creditedUntil)) {
                        attendanceLedger.credit(timer, creditedUntil, at);
                        timer.setLastHeartbeatAt(at);
                } else if (timer.getLastHeartbeatAt() == null) {
                        timer.setLastHeartbeatAt(creditedUntil);
                }
        }

        private static LocalDateTime creditedUntil(Timer timer) {
                return timer.getLastHeartbeatAt() != null ? timer.getLastHeartbeatAt() : timer.getStartTime();
        }

        // ── 종료 ───────────────────────────────────────────────────────────────────

        /**
         * 세션 종료(멱등). 활성 세션이 없으면 가장 최근 세션을 그대로 돌려준다(두 번째 STOP 은 no-op).
         * 클라이언트 endTime/durationSeconds 는 무시하고 서버 시각으로 계산한다.
         */
        @Transactional
        public TimerDTO.Response endTimer(Long userId, TimerDTO.EndRequest request) {
                Optional<Timer> activeOpt = timerRepository.findByUserIdAndStatusForUpdate(userId, TimerStatus.STARTED);
                if (activeOpt.isEmpty()) {
                        return timerRepository.findFirstByUserIdOrderByStartTimeDesc(userId)
                                        .map(t -> toResponseDTO(t, false))
                                        .orElse(null);
                }
                Timer timer = activeOpt.get();
                endInternal(timer, now(), TimerEndReason.USER_STOP);
                Timer saved = timerRepository.save(timer);
                log.info("Timer ended. timerId={}, userId={}, durationSeconds={}, clientReason={}",
                                saved.getId(), userId, saved.getDurationSeconds(), request == null ? null : request.getReason());
                return toResponseDTO(saved, false);
        }

        private void endInternal(Timer timer, LocalDateTime endAt, TimerEndReason reason) {
                LocalDateTime creditedUntil = creditedUntil(timer);
                LocalDateTime effectiveEnd = endAt.isBefore(creditedUntil) ? creditedUntil : endAt; // 음수 구간 방지
                if (effectiveEnd.isBefore(timer.getStartTime())) {
                        effectiveEnd = timer.getStartTime();
                }
                attendanceLedger.credit(timer, creditedUntil, effectiveEnd);
                timer.setEndTime(effectiveEnd);
                timer.setDurationSeconds(Math.max(0L, Duration.between(timer.getStartTime(), effectiveEnd).getSeconds()));
                timer.setStatus(TimerStatus.COMPLETED);
                timer.setEndReason(reason);
                timer.setLastHeartbeatAt(effectiveEnd);
        }

        // ── reaper(비정상 종료 fallback) ────────────────────────────────────────────

        /** heartbeat 가 끊긴 세션 id 목록(별도 트랜잭션에서 하나씩 종료한다). */
        public List<Long> findHeartbeatTimedOutIds() {
                return timerRepository.findHeartbeatTimedOutIds(now().minusSeconds(HEARTBEAT_TIMEOUT_SECONDS));
        }

        public List<Long> findStaleWithoutHeartbeatIds() {
                return timerRepository.findStaleWithoutHeartbeatIds(now().minusHours(STALE_SESSION_HOURS));
        }

        /** heartbeat timeout 세션을 마지막 heartbeat 시각으로 종료. 이미 종료됐거나 그 사이 heartbeat 가 오면 no-op. */
        @Transactional(propagation = Propagation.REQUIRES_NEW)
        public boolean expireTimedOut(Long timerId) {
                Timer timer = timerRepository.findByIdForUpdate(timerId).orElse(null);
                if (timer == null || timer.getStatus() != TimerStatus.STARTED || timer.getLastHeartbeatAt() == null) {
                        return false;
                }
                LocalDateTime threshold = now().minusSeconds(HEARTBEAT_TIMEOUT_SECONDS);
                if (!timer.getLastHeartbeatAt().isBefore(threshold)) {
                        return false;
                }
                endInternal(timer, timer.getLastHeartbeatAt(), TimerEndReason.HEARTBEAT_TIMEOUT);
                timerRepository.save(timer);
                log.warn("Session expired by heartbeat timeout. timerId={}, userId={}, groupStudyId={}, endedAt={}, durationSeconds={}",
                                timer.getId(), timer.getUser().getId(), timer.getGroupStudyId(), timer.getEndTime(), timer.getDurationSeconds());
                return true;
        }

        /** heartbeat 미지원 좀비 세션을 CANCELLED 로 정리(공부시간은 알 수 없으므로 기록하지 않는다). */
        @Transactional(propagation = Propagation.REQUIRES_NEW)
        public boolean cancelStaleWithoutHeartbeat(Long timerId) {
                Timer timer = timerRepository.findByIdForUpdate(timerId).orElse(null);
                if (timer == null || timer.getStatus() != TimerStatus.STARTED || timer.getLastHeartbeatAt() != null
                                || !timer.getStartTime().isBefore(now().minusHours(STALE_SESSION_HOURS))) {
                        return false;
                }
                timer.setStatus(TimerStatus.CANCELLED);
                timer.setEndReason(TimerEndReason.STALE_NO_HEARTBEAT);
                timerRepository.save(timer);
                log.warn("Stale session without heartbeat cancelled. timerId={}, userId={}, startedAt={}",
                                timer.getId(), timer.getUser().getId(), timer.getStartTime());
                return true;
        }

        // ── 조회(기존) ──────────────────────────────────────────────────────────────

        public TimerDTO.Response getCurrentTimer(Long userId) {
                return timerRepository.findByUserIdAndStatus(userId, TimerStatus.STARTED)
                                .map(t -> toResponseDTO(t, true))
                                .orElse(null);
        }

        public List<TimerDTO.Response> getUserTimers(Long userId) {
                return timerRepository.findByUserIdOrderByStartTimeDesc(userId)
                                .stream()
                                .map(t -> toResponseDTO(t, false))
                                .collect(Collectors.toList());
        }

        public TimerDTO.TodayStudyTimeResponse getTodayStudyTime(Long userId) {
                LocalDateTime startOfDay = LocalDate.now(clock).atStartOfDay();
                LocalDateTime endOfDay = LocalDate.now(clock).atTime(LocalTime.MAX);

                List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                                userId, TimerStatus.COMPLETED, startOfDay, endOfDay);

                Long totalSeconds = completedTimers.stream()
                                .mapToLong(timer -> timer.getDurationSeconds() != null ? timer.getDurationSeconds()
                                                : 0L)
                                .sum();

                return TimerDTO.TodayStudyTimeResponse.builder()
                                .userId(userId)
                                .todaySeconds(totalSeconds)
                                .build();
        }

        public TimerDTO.WeeklyStudyTimeResponse getWeeklyStudyTime(Long userId) {
                LocalDate today = LocalDate.now(clock);
                LocalDate startOfWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
                LocalDate endOfWeek = today.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY));

                LocalDateTime startOfWeekDateTime = startOfWeek.atStartOfDay();
                LocalDateTime endOfWeekDateTime = endOfWeek.atTime(LocalTime.MAX);

                List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                                userId, TimerStatus.COMPLETED, startOfWeekDateTime, endOfWeekDateTime);

                Map<LocalDate, Long> dailySecondsMap = completedTimers.stream()
                                .collect(Collectors.groupingBy(
                                                timer -> timer.getEndTime().toLocalDate(),
                                                Collectors.summingLong(timer -> timer.getDurationSeconds() != null
                                                                ? timer.getDurationSeconds()
                                                                : 0L)));

                Long totalSeconds = completedTimers.stream()
                                .mapToLong(timer -> timer.getDurationSeconds() != null ? timer.getDurationSeconds()
                                                : 0L)
                                .sum();

                Set<LocalDate> attendanceDaysSet = completedTimers.stream()
                                .filter(timer -> timer.getDurationSeconds() != null && timer.getDurationSeconds() > 0)
                                .map(timer -> timer.getEndTime().toLocalDate())
                                .collect(Collectors.toSet());
                Integer attendanceDays = attendanceDaysSet.size();

                Long averageSeconds = (attendanceDays > 0) ? (totalSeconds / attendanceDays) : 0L;

                List<TimerDTO.DailyStudyTime> dailyStudyTimes = new ArrayList<>();
                LocalDate currentDay = startOfWeek;
                while (!currentDay.isAfter(endOfWeek)) {
                        Long seconds = dailySecondsMap.getOrDefault(currentDay, 0L);
                        dailyStudyTimes.add(TimerDTO.DailyStudyTime.builder()
                                        .date(currentDay.toString())
                                        .day(currentDay.getDayOfWeek().toString())
                                        .seconds(seconds)
                                        .build());
                        currentDay = currentDay.plusDays(1);
                }

                return TimerDTO.WeeklyStudyTimeResponse.builder()
                                .userId(userId)
                                .totalSeconds(totalSeconds)
                                .averageSeconds(averageSeconds)
                                .attendanceDays(attendanceDays)
                                .dailyStats(dailyStudyTimes)
                                .build();
        }

        private TimerDTO.Response toResponseDTO(Timer timer, boolean resumed) {
                return TimerDTO.Response.builder()
                                .id(timer.getId())
                                .userId(timer.getUser().getId())
                                .groupStudyId(timer.getGroupStudyId())
                                .startTime(timer.getStartTime())
                                .endTime(timer.getEndTime())
                                .durationSeconds(timer.getDurationSeconds())
                                .status(timer.getStatus())
                                .lastHeartbeatAt(timer.getLastHeartbeatAt())
                                .endReason(timer.getEndReason())
                                .heartbeatIntervalSeconds(HEARTBEAT_INTERVAL_SECONDS)
                                .resumed(resumed)
                                .createdAt(timer.getCreatedAt())
                                .updatedAt(timer.getUpdatedAt())
                                .build();
        }
}
