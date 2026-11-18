package com.studybridge.api.service;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * 공부 구간 [from, to) 를 날짜(자정) 경계로 분할한다. 타임존 독립적(LocalDateTime 산술만 사용).
 * 예) 23:50~00:20 → 9/30 10분 + 10/1 20분. 통계와 출석 크레딧이 같은 분할 규칙을 쓴다.
 */
public final class StudyIntervalSplitter {

    public record DaySegment(LocalDate date, LocalDateTime start, LocalDateTime end) {
        public long seconds() {
            return Math.max(0L, Duration.between(start, end).getSeconds());
        }
    }

    private StudyIntervalSplitter() {
    }

    public static List<DaySegment> split(LocalDateTime from, LocalDateTime to) {
        List<DaySegment> out = new ArrayList<>();
        if (from == null || to == null || !to.isAfter(from)) {
            return out;
        }
        LocalDateTime cursor = from;
        while (cursor.isBefore(to)) {
            LocalDateTime nextMidnight = cursor.toLocalDate().plusDays(1).atStartOfDay();
            LocalDateTime segEnd = to.isBefore(nextMidnight) ? to : nextMidnight;
            out.add(new DaySegment(cursor.toLocalDate(), cursor, segEnd));
            cursor = segEnd;
        }
        return out;
    }

    /** [from, to) 를 [windowFrom, windowTo) 로 자른 뒤 분할. 겹치지 않으면 빈 목록. */
    public static List<DaySegment> splitWithin(LocalDateTime from, LocalDateTime to,
                                               LocalDateTime windowFrom, LocalDateTime windowTo) {
        if (from == null || to == null) {
            return List.of();
        }
        LocalDateTime f = from.isBefore(windowFrom) ? windowFrom : from;
        LocalDateTime t = to.isAfter(windowTo) ? windowTo : to;
        return split(f, t);
    }
}
