#ifndef SECRET_SAUCE_SCHEDULER_H
#define SECRET_SAUCE_SCHEDULER_H

/*
 * 학습 시간 배분 엔진 (숫자 계산 전용).
 * 문자열/JSON/파일/네트워크 일절 다루지 않는다. 이름 매핑은 Python wrapper가 한다.
 *
 * 반환 코드: 0 성공, 음수 실패(검증/런타임). 실패 시 Python fallback.
 */

#ifdef __cplusplus
extern "C" {
#endif

/*
 * subject_count : 과목 수 (1..20)
 * days          : 일수 (1..30)
 * daily_minutes : 하루 학습 분 (30..720)
 * priorities/weaknesses/exam_weights : 길이 subject_count, 각 값 1..5
 * out_day_indices/out_subject_indices/out_minutes : 길이 max_tasks 출력 버퍼
 *   - out_day_indices[t]    : 0-based 일 index
 *   - out_subject_indices[t]: 0-based 과목 index
 *   - out_minutes[t]        : 해당 (일,과목) 배정 분 (10분 단위)
 * out_task_count : 실제 생성된 task 수
 */
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
    int *out_task_count);

#ifdef __cplusplus
}
#endif

#endif /* SECRET_SAUCE_SCHEDULER_H */
