#ifndef SECRET_SAUCE_TEXTPREP_H
#define SECRET_SAUCE_TEXTPREP_H

/*
 * PDF 추출 텍스트 전처리 엔진.
 * 파일/네트워크/경로 입력 일절 없음. 입력 바이트만 정규화하거나 청크 경계만 계산한다.
 * ASCII 공백/숫자만 특수 처리하고 멀티바이트(UTF-8 >=0x80)는 그대로 통과 → UTF-8 안전.
 * 반환 코드: 0 성공, 음수 실패. 실패 시 Python fallback.
 */

#ifdef __cplusplus
extern "C" {
#endif

/*
 * 공백/탭 축소, 줄 끝 공백 제거, 과도한 빈 줄 축소, 보수적 페이지번호 줄 제거.
 * output_capacity 는 input_len+1 이상이어야 한다(정규화는 길이를 늘리지 않음).
 */
int normalize_text(
    const char *input,
    int input_len,
    char *output,
    int output_capacity,
    int *output_len);

/*
 * 청크 경계(바이트 오프셋) 계산. UTF-8 continuation 바이트에서 자르지 않는다.
 * 가능하면 개행/공백 경계를 선호한다. 실제 슬라이싱/decode 는 Python 이 수행한다.
 * out_starts[t], out_ends[t] : 바이트 오프셋 [start, end)
 */
int compute_chunk_boundaries(
    const char *input,
    int input_len,
    int chunk_size,
    int overlap,
    int *out_starts,
    int *out_ends,
    int max_chunks,
    int *out_chunk_count);

#ifdef __cplusplus
}
#endif

#endif /* SECRET_SAUCE_TEXTPREP_H */
