/*
 * secret_sauce_engine / scheduler
 * 학습 시간 배분 계산 엔진 (숫자 전용, UTF-8/문자열 무관).
 *
 * 점수: score = priority*0.4 + weakness*0.4 + exam_weight*0.2
 *       정수화: score10 = priority*4 + weakness*4 + exam_weight*2  (10배 스케일, 범위 10..50)
 * 최소 학습 단위: 10분. 모든 배정은 10분 블록 단위.
 */
#include "scheduler.h"

#define MIN_UNIT 10
#define MAX_SUBJECTS 20
#define MAX_DAYS 30

/* 안전 한도 */
#define LIM_DAILY_MIN 30
#define LIM_DAILY_MAX 720
#define LIM_RATING_MIN 1
#define LIM_RATING_MAX 5

static int rating_ok(int v) {
    return v >= LIM_RATING_MIN && v <= LIM_RATING_MAX;
}

int optimize_schedule(
    int subject_count,
    int days,
    int daily_minutes,
    const int *priorities,
    const int *weaknesses,
    const int *exam_weights,
    int *out_day_indices,
    int *out_subject_indices,
    int *out_minutes,
    int max_tasks,
    int *out_task_count) {

    /* ── 1. 입력 검증 ───────────────────────────────────────────── */
    if (subject_count < 1 || subject_count > MAX_SUBJECTS) return -1;
    if (days < 1 || days > MAX_DAYS) return -1;
    if (daily_minutes < LIM_DAILY_MIN || daily_minutes > LIM_DAILY_MAX) return -1;
    if (max_tasks < 1) return -1;
    if (!priorities || !weaknesses || !exam_weights) return -2;
    if (!out_day_indices || !out_subject_indices || !out_minutes || !out_task_count) return -2;

    int i, d;
    int score10[MAX_SUBJECTS];
    long sum_score = 0;
    for (i = 0; i < subject_count; i++) {
        if (!rating_ok(priorities[i]) || !rating_ok(weaknesses[i]) || !rating_ok(exam_weights[i]))
            return -1;
        score10[i] = priorities[i] * 4 + weaknesses[i] * 4 + exam_weights[i] * 2;
        if (score10[i] < 0) return -1; /* integer overflow 방지(이론상 불가) */
        sum_score += score10[i];
    }

    /* ── 2. 총 학습 블록(10분 단위) ─────────────────────────────── */
    int daily_cap = daily_minutes / MIN_UNIT;           /* 하루 최대 블록 */
    if (daily_cap < 1) return -1;                       /* division/zero 방어 */
    long total_units = (long)daily_cap * days;          /* 전체 배정 블록 상한 */
    if (total_units <= 0) return -1;

    /* ── 3. 과목별 블록 비례 배분 ───────────────────────────────── */
    int subj_units[MAX_SUBJECTS];
    long assigned = 0;
    if (sum_score <= 0) {
        /* 점수 합 0 → 균등 배분 */
        for (i = 0; i < subject_count; i++) {
            subj_units[i] = (int)(total_units / subject_count);
            assigned += subj_units[i];
        }
    } else {
        for (i = 0; i < subject_count; i++) {
            subj_units[i] = (int)((total_units * score10[i]) / sum_score);
            assigned += subj_units[i];
        }
    }
    /* 남는 블록은 score 높은 과목부터 1개씩 분배 */
    long remainder = total_units - assigned;
    while (remainder > 0) {
        int best = -1;
        for (i = 0; i < subject_count; i++) {
            if (best < 0 || score10[i] > score10[best])
                best = i;
        }
        if (best < 0) break;
        /* 같은 과목에 몰리지 않도록: 가장 높은 점수를 한 번 준 뒤 그 점수를 임시로 낮춰 회전 */
        subj_units[best] += 1;
        score10[best] -= 1; /* 임시 감점으로 다음 라운드에 다른 과목 우선 */
        remainder -= 1;
    }

    /* ── 4. 일자별 분산 배치 (subject별 round-robin, 하루 cap 준수) ── */
    static int grid[MAX_DAYS][MAX_SUBJECTS]; /* 블록 수 (static: 스택 절약, 단일스레드 wrapper) */
    int day_total[MAX_DAYS];
    for (d = 0; d < days; d++) {
        day_total[d] = 0;
        for (i = 0; i < subject_count; i++) grid[d][i] = 0;
    }

    for (i = 0; i < subject_count; i++) {
        int u = subj_units[i];
        if (u < 0) u = 0;
        int start = i % days;          /* 과목마다 시작 요일을 달리해 분산 */
        int cursor = start;
        int guard_full;
        while (u > 0) {
            guard_full = 0;
            /* 한 바퀴 돌며 cap 여유 있는 날에 한 블록씩 */
            for (d = 0; d < days && u > 0; d++) {
                int day = (cursor + d) % days;
                if (day_total[day] < daily_cap) {
                    grid[day][i] += 1;
                    day_total[day] += 1;
                    u -= 1;
                } else {
                    guard_full++;
                }
            }
            if (guard_full >= days) break; /* 모든 날이 가득 → 남은 블록 폐기(초과 방지) */
            cursor = (cursor + 1) % days;  /* 다음 바퀴 시작점 회전 */
        }
    }

    /* ── 5. 출력 task 생성 ──────────────────────────────────────── */
    int tcount = 0;
    for (d = 0; d < days; d++) {
        for (i = 0; i < subject_count; i++) {
            if (grid[d][i] > 0) {
                if (tcount >= max_tasks) return -3; /* 버퍼 초과 */
                out_day_indices[tcount] = d;
                out_subject_indices[tcount] = i;
                out_minutes[tcount] = grid[d][i] * MIN_UNIT;
                tcount++;
            }
        }
    }
    *out_task_count = tcount;
    return 0;
}
